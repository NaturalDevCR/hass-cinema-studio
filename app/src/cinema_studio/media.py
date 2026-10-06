"""Asynchronous media operations; subprocess arguments never pass through a shell."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import signal
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import cast


class MediaError(Exception):
    """A media tool failed or returned unusable data."""


def _exit_summary(executable: str, returncode: int | None) -> str:
    """Name how a media process ended; a SIGKILL nobody sent is most often the OOM killer."""
    if returncode is not None and returncode < 0:
        try:
            name = signal.Signals(-returncode).name
        except ValueError:
            name = f"signal {-returncode}"
        if returncode == -signal.SIGKILL:
            return f"{executable} was killed by {name} (possibly out of memory)"
        return f"{executable} was killed by {name}"
    return f"{executable} exited with code {returncode}"


def _prefer_oom_kill(pid: int) -> None:
    """Under memory pressure the kernel should kill this media process, not Home Assistant.

    Raising a child's own OOM score needs no privileges; it is best effort everywhere else.
    """
    with suppress(OSError):
        Path(f"/proc/{pid}/oom_score_adj").write_text("1000")


async def run_process(
    argv: list[str],
    *,
    timeout: float = 30,
    on_line: Callable[[str], None] | None = None,
) -> tuple[bytes, bytes]:
    """Drain both pipes concurrently and reap the child on timeout or cancellation."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise MediaError(str(exc)[-1000:]) from exc
    assert process.stdout is not None and process.stderr is not None
    _prefer_oom_kill(process.pid)

    async def stdout_reader() -> bytes:
        assert process.stdout is not None
        if on_line is None:
            return await process.stdout.read()
        while line := await process.stdout.readline():
            on_line(line.decode(errors="replace").strip())
        return b""

    stderr_buffer = b""

    async def stderr_reader() -> bytes:
        nonlocal stderr_buffer
        assert process.stderr is not None
        while chunk := await process.stderr.read(8192):
            stderr_buffer = (stderr_buffer + chunk)[-16384:]
        return stderr_buffer

    stdout_task = asyncio.create_task(stdout_reader())
    stderr_task = asyncio.create_task(stderr_reader())
    try:
        async with asyncio.timeout(timeout):
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
            await process.wait()
    except BaseException as exc:
        if process.returncode is None:
            process.kill()
        await process.wait()
        stdout_task.cancel()
        stderr_task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        if isinstance(exc, TimeoutError):
            raise MediaError(
                "media process timed out\n" + stderr_buffer.decode(errors="replace")[-1000:]
            ) from exc
        raise
    if process.returncode != 0:
        raise MediaError(
            f"{_exit_summary(Path(argv[0]).name, process.returncode)}\n"
            + stderr.decode(errors="replace")[-1000:]
        )
    return stdout, stderr


async def file_sha256(path: Path) -> str:
    """Hash bounded chunks off the event loop."""

    def calculate() -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    try:
        return await asyncio.to_thread(calculate)
    except OSError as exc:
        raise MediaError(str(exc)[-1000:]) from exc


def legacy_fingerprint(sha256_hex: str, size: int) -> str:
    return f"{sha256_hex}:{size}"


def loudness_json(stderr: bytes) -> dict[str, float | None]:
    matches = re.findall(r'\{\s*"input_i".*?\}', stderr.decode(errors="replace"), re.DOTALL)
    if not matches:
        raise MediaError("ffmpeg returned no loudness measurements")
    try:
        payload = cast("dict[str, object]", json.loads(matches[-1]))
        result: dict[str, float | None] = {}
        for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
            value = payload[key]
            if not isinstance(value, (str, int, float)):
                raise ValueError("invalid loudness value")
            number = float(value)
            result[key] = number if math.isfinite(number) else None
        return result
    except (ValueError, KeyError, TypeError) as exc:
        raise MediaError("ffmpeg returned malformed loudness measurements") from exc


async def analyze_loudness(
    path: Path,
    filter_text: str,
    *,
    start: float | None = None,
    end: float | None = None,
    timeout: float = 300,
    executable: str = "ffmpeg",
) -> dict[str, float | None]:
    argv = [executable, "-hide_banner", "-nostdin"]
    if start is not None:
        argv += ["-ss", f"{start:.6f}"]
    argv += ["-i", str(path)]
    if end is not None:
        argv += ["-t", f"{end - (start or 0):.6f}"]
    argv += ["-vn", "-af", filter_text + ":print_format=json", "-f", "null", "-"]
    _, stderr = await run_process(argv, timeout=timeout)
    return loudness_json(stderr)


async def measure_loudness(
    path: Path,
    *,
    start: float | None = None,
    end: float | None = None,
) -> tuple[float | None, float | None]:
    data = await analyze_loudness(path, "loudnorm=I=-18:TP=-1.5:LRA=11", start=start, end=end)
    return data["input_i"], data["input_tp"]


async def make_poster(src: Path, dst: Path, at: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(prefix=f".{dst.stem}-", suffix=".jpg", dir=dst.parent)
    os.close(descriptor)
    temporary = Path(filename)
    try:
        await run_process(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-ss",
                str(at),
                "-i",
                str(src),
                "-frames:v",
                "1",
                "-vf",
                "scale=640:-2",
                "-update",
                "1",
                str(temporary),
            ]
        )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise MediaError("ffmpeg produced no poster")
        with temporary.open("rb") as handle:
            if handle.read(3) != b"\xff\xd8\xff":
                raise MediaError("ffmpeg produced an invalid JPEG poster")
        from .probe import probe

        info = await probe(temporary)
        if info.video_codec != "mjpeg":
            raise MediaError("ffmpeg produced an invalid JPEG poster")
        temporary.replace(dst)
    finally:
        temporary.unlink(missing_ok=True)


async def make_filmstrip(src: Path, dst_dir: Path, *, duration: float) -> dict[str, int | float]:
    """Sample the caller's original source timeline, never its rendered margins."""
    if not math.isfinite(duration) or duration <= 0:
        raise MediaError("filmstrip duration must be positive and finite")
    dst_dir.mkdir(parents=True, exist_ok=True)
    interval = max(1.0, duration / 60)
    for stale in dst_dir.glob("[0-9][0-9][0-9][0-9].jpg"):
        stale.unlink()
    (dst_dir / "filmstrip.json").unlink(missing_ok=True)
    await run_process(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(src),
            "-t",
            str(duration),
            "-vf",
            f"fps=1/{interval}:start_time=0,scale=160:-2",
            "-start_number",
            "0",
            str(dst_dir / "%04d.jpg"),
        ],
        timeout=300,
    )
    frames = sorted(dst_dir.glob("[0-9][0-9][0-9][0-9].jpg"))
    if not frames:
        raise MediaError("ffmpeg produced no filmstrip frames")
    # Probe a JPEG to report its actual even-rounded dimensions.
    from .probe import probe

    info = await probe(frames[0])
    metadata: dict[str, int | float] = {
        "interval": interval,
        "count": len(frames),
        "width": info.width or 160,
        "height": info.height or 0,
    }
    (dst_dir / "filmstrip.json").write_text(json.dumps(metadata), encoding="utf-8")
    return metadata
