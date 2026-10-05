"""Bounded, out-of-order chunk uploads assembled into a single part file."""

from __future__ import annotations

import re
import secrets
import shutil
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from .config import Paths
from .errors import InvalidError, NotFoundError

SUPPORTED_EXTENSIONS = frozenset({".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".ts"})
CHUNK_SIZE = 4194304
MAX_UPLOAD_SESSIONS = 20
IDLE_SESSION_TIMEOUT = timedelta(minutes=15)


class UnsupportedUploadError(InvalidError):
    """The input extension is unsupported (HTTP 415)."""


class UploadTooLargeError(InvalidError):
    """The upload or chunk exceeds its permitted size (HTTP 413)."""


def safe_filename(filename: str, *, preserve_extension_case: bool = False) -> str:
    """Keep the basename and extension while removing unsafe and unhelpful characters."""
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    basename = "".join(char for char in basename if not unicodedata.category(char).startswith("C"))
    basename = re.sub(r"\s+", " ", basename).strip()
    stem, separator, extension = basename.rpartition(".")
    suffix = f".{extension}" if separator else ""
    if suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedUploadError("Unsupported video extension.")
    if not preserve_extension_case:
        suffix = suffix.lower()
    stem = stem.strip(" .") or "clip"
    return stem[: 120 - len(suffix)].rstrip() + suffix


@dataclass
class _Upload:
    filename: str
    safe_name: str
    size: int
    part: Path
    # Each range begins at index * CHUNK_SIZE; replacing an index replaces its byte count.
    received: dict[int, int] = field(default_factory=dict[int, int])
    lock: threading.Lock = field(default_factory=threading.Lock)


class UploadStore:
    def __init__(self, paths: Paths, max_bytes: Callable[[], int]) -> None:
        self._directory = paths.uploads_dir
        self._directory.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._uploads: dict[str, _Upload] = {}
        self._sessions_lock = threading.Lock()

    def create(self, filename: str, size: int) -> str:
        name = safe_filename(filename)
        if size <= 0:
            raise InvalidError("Upload size must be positive.")
        if size > self._max_bytes():
            raise UploadTooLargeError("Upload exceeds the maximum size.")
        with self._sessions_lock:
            at_capacity = len(self._uploads) >= MAX_UPLOAD_SESSIONS
        if at_capacity:
            self._evict_idle_sessions()
        with self._sessions_lock:
            if len(self._uploads) >= MAX_UPLOAD_SESSIONS:
                raise InvalidError("Too many concurrent upload sessions (maximum 20).")
            upload_id = secrets.token_hex(16)
            part = self._directory / f"{upload_id}.part"
            try:
                with part.open("xb") as output:
                    output.truncate(size)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
            self._uploads[upload_id] = _Upload(filename, name, size, part)
            return upload_id

    def _evict_idle_sessions(self) -> None:
        cutoff = time.time() - IDLE_SESSION_TIMEOUT.total_seconds()
        with self._sessions_lock:
            candidates = list(self._uploads.items())
        for upload_id, upload in candidates:
            with upload.lock:
                with self._sessions_lock:
                    if self._uploads.get(upload_id) is not upload:
                        continue
                    try:
                        is_idle = upload.part.stat().st_mtime < cutoff
                    except FileNotFoundError:
                        is_idle = True
                    if not is_idle:
                        continue
                    del self._uploads[upload_id]
                upload.part.unlink(missing_ok=True)

    def _get(self, upload_id: str) -> _Upload:
        with self._sessions_lock:
            upload = self._uploads.get(upload_id)
        if upload is None:
            raise NotFoundError("Unknown upload id.")
        return upload

    def chunk_limit(self, upload_id: str, index: int) -> int:
        """Look up the session before accepting a body and bound this index's bytes."""
        upload = self._get(upload_id)
        if index < 0:
            raise InvalidError("Chunk index must be nonnegative.")
        remaining = upload.size - index * CHUNK_SIZE
        if remaining <= 0:
            raise UploadTooLargeError("Chunk exceeds the declared upload size.")
        return min(CHUNK_SIZE, remaining)

    def write_chunk(self, upload_id: str, index: int, data: bytes) -> int:
        limit = self.chunk_limit(upload_id, index)
        if len(data) > limit:
            raise UploadTooLargeError("Chunk exceeds the maximum or declared upload size.")
        if not data:
            raise InvalidError("Chunk must not be empty.")
        upload = self._get(upload_id)
        with upload.lock:
            # A finish or purge may have removed the session while this writer waited.
            self._get(upload_id)
            with upload.part.open("r+b") as output:
                output.seek(index * CHUNK_SIZE)
                output.write(data)
            upload.received[index] = len(data)
            return sum(upload.received.values())

    @staticmethod
    def _check_complete(upload: _Upload) -> None:
        count = (upload.size + CHUNK_SIZE - 1) // CHUNK_SIZE
        if len(upload.received) != count or sum(upload.received.values()) != upload.size:
            raise InvalidError("Upload is incomplete.")
        if any(index not in upload.received for index in range(count)):
            raise InvalidError("Upload is incomplete.")

    def ready_filename(self, upload_id: str) -> str:
        """Validate completeness before creating a clip."""
        upload = self._get(upload_id)
        with upload.lock:
            self._get(upload_id)
            self._check_complete(upload)
            return upload.filename

    def finish(self, upload_id: str, dest_dir: Path) -> Path:
        upload = self._get(upload_id)
        with upload.lock:
            self._get(upload_id)
            self._check_complete(upload)
            dest_dir.mkdir(parents=True, exist_ok=True)
            destination = dest_dir / upload.safe_name
            # The part lives under /data and the destination under /media: possibly another
            # filesystem, where a plain rename fails.
            shutil.move(upload.part, destination)
            with self._sessions_lock:
                del self._uploads[upload_id]
            return destination

    def purge_stale(self, older_than: timedelta = timedelta(hours=6)) -> None:
        cutoff = time.time() - older_than.total_seconds()
        for part in self._directory.glob("*.part"):
            with self._sessions_lock:
                upload = self._uploads.get(part.stem)
            lock = upload.lock if upload is not None else threading.Lock()
            with lock:
                try:
                    if part.stat().st_mtime >= cutoff:
                        continue
                    part.unlink()
                except FileNotFoundError:
                    continue
                with self._sessions_lock:
                    self._uploads.pop(part.stem, None)
