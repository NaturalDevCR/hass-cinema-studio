"""Chunk assembly, limits, safe filenames and stale upload cleanup."""

from __future__ import annotations

import errno
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest

from cinema_studio.errors import InvalidError, NotFoundError
from cinema_studio.uploads import CHUNK_SIZE, UploadStore

pytestmark = pytest.mark.studio


def test_out_of_order_chunks_and_retry(paths, tmp_path):
    store = UploadStore(paths, lambda: 3 * CHUNK_SIZE)
    data = b"a" * CHUNK_SIZE + b"b" * CHUNK_SIZE + b"end"
    upload = store.create("clip.MP4", len(data))
    assert store.write_chunk(upload, 2, data[2 * CHUNK_SIZE :]) == 3
    assert store.write_chunk(upload, 0, data[:CHUNK_SIZE]) == CHUNK_SIZE + 3
    assert store.write_chunk(upload, 0, data[:CHUNK_SIZE]) == CHUNK_SIZE + 3
    with pytest.raises(InvalidError):
        store.finish(upload, tmp_path / "dest")
    assert store.write_chunk(upload, 1, data[CHUNK_SIZE : 2 * CHUNK_SIZE]) == len(data)
    output = store.finish(upload, tmp_path / "dest")
    assert output.name == "clip.mp4" and output.read_bytes() == data
    assert not list(paths.uploads_dir.iterdir())
    with pytest.raises(NotFoundError):
        store.write_chunk(upload, 0, b"x")


@pytest.mark.parametrize("filename", ["bad.exe", "no-extension", "song.mp3"])
def test_unsupported(paths, filename):
    with pytest.raises(InvalidError):
        UploadStore(paths, lambda: 10).create(filename, 1)


def test_limits_and_received_ranges(paths, tmp_path):
    limit = [CHUNK_SIZE + 2]
    store = UploadStore(paths, lambda: limit[0])
    for size in (0, -1, limit[0] + 1):
        with pytest.raises(InvalidError):
            store.create("clip.mp4", size)
    upload = store.create("clip.mp4", limit[0])
    for index, data in [(0, b"x" * (CHUNK_SIZE + 1)), (1, b"xxx"), (2, b"x"), (-1, b"x")]:
        with pytest.raises(InvalidError):
            store.write_chunk(upload, index, data)
    assert store.write_chunk(upload, 0, b"x" * CHUNK_SIZE) == CHUNK_SIZE
    assert store.write_chunk(upload, 0, b"x") == 1
    assert store.write_chunk(upload, 1, b"xx") == 3
    with pytest.raises(InvalidError):
        store.finish(upload, tmp_path / "dest")
    limit[0] = 1
    with pytest.raises(InvalidError):
        store.create("clip.mp4", 2)
    with pytest.raises(NotFoundError):
        store.finish("unknown", tmp_path)


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("..\\folder\\door  bell\x00.MP4", "door bell.mp4"),
        ("../../.MP4", "clip.mp4"),
        ("x" * 200 + ".MKV", "x" * 116 + ".mkv"),
    ],
)
def test_safe_filename(paths, tmp_path, filename, expected):
    store = UploadStore(paths, lambda: 10)
    upload = store.create(filename, 1)
    store.write_chunk(upload, 0, b"x")
    assert store.finish(upload, tmp_path / "dest").name == expected


def test_purge_stale_including_orphaned_parts(paths):
    store = UploadStore(paths, lambda: 10)
    stale = store.create("old.mp4", 1)
    old_part = next(paths.uploads_dir.iterdir())
    old = time.time() - 7 * 3600
    os.utime(old_part, (old, old))
    fresh = store.create("new.mp4", 1)
    orphan = paths.uploads_dir / "orphan.part"
    orphan.write_bytes(b"x")
    os.utime(orphan, (old, old))
    store.purge_stale(timedelta(hours=6))
    with pytest.raises(NotFoundError):
        store.write_chunk(stale, 0, b"x")
    assert store.write_chunk(fresh, 0, b"x") == 1
    assert not orphan.exists()


@pytest.mark.parametrize("extension", [".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".ts"])
def test_all_supported_extensions(paths, extension):
    store = UploadStore(paths, lambda: 1)
    assert store.create("video" + extension.upper(), 1)


def test_concurrent_same_index_serializes_file_and_accounting(paths, tmp_path, monkeypatch):
    store = UploadStore(paths, lambda: 10)
    upload = store.create("clip.mp4", 3)
    entered, release, second_opened = threading.Event(), threading.Event(), threading.Event()
    original_open = Path.open

    class PausedFile:
        def __init__(self, output):
            self.output = output

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.output.close()

        def seek(self, offset):
            return self.output.seek(offset)

        def write(self, data):
            written = self.output.write(data)
            self.output.flush()
            if data == b"abc":
                entered.set()
                assert release.wait(5)
            return written

    def paused_open(path, mode="r", *args, **kwargs):
        output = original_open(path, mode, *args, **kwargs)
        if mode == "r+b":
            if entered.is_set():
                second_opened.set()
            return PausedFile(output)
        return output

    monkeypatch.setattr(Path, "open", paused_open)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(store.write_chunk, upload, 0, b"abc")
        try:
            assert entered.wait(2)
            second = pool.submit(store.write_chunk, upload, 0, b"xyz")
            assert not second_opened.wait(0.1)
        finally:
            release.set()
        assert first.result() == second.result() == 3
    assert store.finish(upload, tmp_path / "dest").read_bytes() == b"xyz"


def test_concurrent_retries_converge(paths, tmp_path):
    data = b"a" * CHUNK_SIZE + b"end"
    store = UploadStore(paths, lambda: len(data))
    upload = store.create("clip.mp4", len(data))
    with ThreadPoolExecutor(max_workers=8) as pool:
        writes = [
            pool.submit(
                store.write_chunk, upload, i % 2, data[:CHUNK_SIZE] if i % 2 == 0 else b"end"
            )
            for i in range(32)
        ]
        for write in writes:
            assert write.result() <= len(data)
    assert store.write_chunk(upload, 1, b"end") == len(data)
    assert store.finish(upload, tmp_path / "dest").read_bytes() == data


def test_session_cap_freed_by_finish_and_purge(paths, tmp_path):
    store = UploadStore(paths, lambda: 1)
    uploads = [store.create("clip.mp4", 1) for _ in range(20)]
    with pytest.raises(InvalidError, match="sessions"):
        store.create("clip.mp4", 1)
    store.write_chunk(uploads[0], 0, b"x")
    store.finish(uploads[0], tmp_path / "dest")
    store.create("replacement.mp4", 1)
    store.purge_stale(timedelta(seconds=-1))
    assert store.create("after-purge.mp4", 1)


def test_session_cap_evicts_sessions_idle_more_than_15_minutes(paths):
    store = UploadStore(paths, lambda: 1)
    uploads = [store.create("clip.mp4", 1) for _ in range(20)]
    old = time.time() - 16 * 60
    for upload in uploads[:3]:
        os.utime(paths.uploads_dir / f"{upload}.part", (old, old))
    replacement = store.create("replacement.mp4", 1)
    assert replacement not in uploads
    for upload in uploads[:3]:
        with pytest.raises(NotFoundError):
            store.write_chunk(upload, 0, b"x")
    for upload in uploads[3:]:
        assert store.write_chunk(upload, 0, b"x") == 1


def test_finish_falls_back_to_copy_across_filesystems(paths, tmp_path, monkeypatch):
    store = UploadStore(paths, lambda: 10)
    upload = store.create("clip.mp4", 3)
    store.write_chunk(upload, 0, b"abc")

    def cross_device(*args, **kwargs):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "rename", cross_device)
    output = store.finish(upload, tmp_path / "dest")
    assert output.read_bytes() == b"abc"
    assert not list(paths.uploads_dir.iterdir())
