"""Real probe, hashing, original filmstrip and poster tests."""

import hashlib
import json

import pytest

from cinema_studio.media import (
    MediaError,
    file_sha256,
    legacy_fingerprint,
    make_filmstrip,
    make_poster,
    measure_loudness,
)
from cinema_studio.probe import probe

pytestmark = pytest.mark.studio


async def test_probe_and_hash(make_video):
    source = make_video(seconds=2)
    info = await probe(source)
    assert info.valid and info.duration == pytest.approx(2, abs=0.05)
    assert (info.width, info.height, info.fps) == (320, 180, 24)
    assert info.has_audio and info.video_codec == "h264"
    assert info.video_duration == pytest.approx(2, abs=0.05)
    assert info.audio_duration == pytest.approx(2, abs=0.05)
    digest = await file_sha256(source)
    assert digest == hashlib.sha256(source.read_bytes()).hexdigest()
    assert legacy_fingerprint(digest, source.stat().st_size) == f"{digest}:{source.stat().st_size}"
    lufs, peak = await measure_loudness(source, start=0.2, end=1.8)
    assert lufs is not None and peak is not None and lufs < -20


async def test_thumbnails_original_timeline(make_video, tmp_path):
    src = make_video(seconds=10)
    dst = tmp_path / "original"
    metadata = await make_filmstrip(src, dst, duration=10)
    assert metadata == {"interval": 1.0, "count": 10, "width": 160, "height": 90}
    assert json.loads((dst / "filmstrip.json").read_text()) == metadata
    assert all(
        (dst / f"{index:04d}.jpg").read_bytes().startswith(b"\xff\xd8") for index in range(10)
    )
    poster = tmp_path / "poster.jpg"
    await make_poster(src, poster, 1)
    assert poster.read_bytes().startswith(b"\xff\xd8")
    assert (await probe(poster)).width == 640


async def test_bad_media(tmp_path):
    src = tmp_path / "bad.mp4"
    src.write_text("not video")
    with pytest.raises(MediaError):
        await probe(src)


async def test_silent_audio_loudness(make_video, tmp_path):
    from cinema_studio.media import run_process

    src = make_video(seconds=1)
    silent = tmp_path / "silent.mp4"
    await run_process(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", "volume=0", str(silent)]
    )
    assert await measure_loudness(silent) == (None, None)


def test_stream_duration_and_rate_fallbacks():
    from cinema_studio.probe import _rate, _stream_duration

    assert _rate("30000/1001") == 30000 / 1001
    assert _rate("0/0") is None
    assert _rate("nan") is None
    assert _stream_duration({"duration_ts": 600, "time_base": "1/24"}) == 25
    assert _stream_duration({"duration": "nan"}) is None


async def test_subprocess_timeout_and_cancel_reap_children(monkeypatch):
    import asyncio
    import sys

    from cinema_studio.media import run_process

    real = asyncio.create_subprocess_exec
    children = []

    async def record(*args, **kwargs):
        process = await real(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", record)
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(MediaError, match="timed out"):
        await run_process(argv, timeout=0.05)
    assert children[0].returncode is not None
    task = asyncio.create_task(run_process(argv))
    while len(children) < 2:
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert children[1].returncode is not None


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"format":{},"streams":[]}',
        b'{"format":{"duration":"nan"},"streams":[{"codec_type":"video","width":320,"height":180}]}',
    ],
)
async def test_probe_rejects_malformed_metadata(tmp_path, monkeypatch, payload):
    import importlib

    module = importlib.import_module("cinema_studio.probe")

    async def fake(_argv):
        return payload, b""

    monkeypatch.setattr(module, "run_process", fake)
    with pytest.raises(MediaError, match="metadata"):
        await probe(tmp_path / "unused.mp4")


async def test_poster_out_of_range_does_not_publish_stale_file(make_video, tmp_path):
    src = make_video(seconds=1)
    dst = tmp_path / "poster.jpg"
    await make_poster(src, dst, 0.2)
    before = dst.read_bytes()
    with pytest.raises(MediaError):
        await make_poster(src, dst, 10)
    assert dst.read_bytes() == before
    assert sorted(tmp_path.glob("*.jpg")) == [dst]


async def test_poster_rejects_non_jpeg_and_preserves_previous(tmp_path, monkeypatch):
    from pathlib import Path

    import cinema_studio.media as media

    dst = tmp_path / "poster.jpg"
    dst.write_bytes(b"previous poster")

    async def invalid_output(argv):
        Path(argv[-1]).write_bytes(b"not a jpeg")
        return b"", b""

    monkeypatch.setattr(media, "run_process", invalid_output)
    with pytest.raises(MediaError, match="JPEG"):
        await make_poster(tmp_path / "src.mp4", dst, 0)
    assert dst.read_bytes() == b"previous poster"
    assert sorted(tmp_path.glob("*.jpg")) == [dst]
