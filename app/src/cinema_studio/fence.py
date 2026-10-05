"""Consumer-file validation and exclusive flock-fenced garbage collection."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import stat
import time
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from .config import Paths
from .errors import InvalidError
from .models import RenderRecord
from .repository import Repository
from .storage import RENDER_NAME, MediaStore, validate_contained_path

_LOGGER = logging.getLogger(__name__)

CONSUMER_FILE = "{consumer_id}.json"


@dataclass(frozen=True)
class ConsumerFile:
    consumer_id: str
    generation: str
    seq: int
    written_at: datetime
    held_revision: int
    held_render_ids: frozenset[str]
    pins: dict[str, datetime]


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("expected timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("expected UTC timestamp")
    return parsed.astimezone(UTC)


def parse_consumer_file(data: Mapping[str, Any]) -> ConsumerFile:
    try:
        consumer_id, generation = data["consumer_id"], data["generation"]
        seq, revision = data["seq"], data["held_revision"]
        held, pins = data["held_render_ids"], data["pins"]
        written_at = _timestamp(data["written_at"])
        if (
            not isinstance(consumer_id, str)
            or not isinstance(generation, str)
            or type(seq) is not int
            or seq < 0
            or type(revision) is not int
            or not isinstance(held, list)
            or not isinstance(pins, list)
        ):
            raise ValueError("invalid consumer fields")
        held_ids: set[str] = set()
        for item in cast(list[object], held):
            if not isinstance(item, str):
                raise ValueError("invalid held render ID")
            held_ids.add(item)
        parsed_pins: dict[str, datetime] = {}
        for item in cast(list[object], pins):
            if not isinstance(item, dict):
                raise ValueError("invalid pin")
            pin = cast(dict[str, object], item)
            render_id = pin["render_id"]
            if not isinstance(render_id, str):
                raise ValueError("invalid pin render ID")
            expiry = _timestamp(pin["expires_at"])
            parsed_pins[render_id] = max(parsed_pins.get(render_id, expiry), expiry)
        return ConsumerFile(
            consumer_id, generation, seq, written_at, revision, frozenset(held_ids), parsed_pins
        )
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("malformed consumer file") from error


class GcFence:
    def __init__(self, paths: Paths) -> None:
        self.paths = paths

    @contextmanager
    def exclusive(self, timeout: float = 30.0) -> Generator[None]:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout
        with self.paths.gc_lock_path.open("a") as lock:
            while True:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as error:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out waiting for GC fence") from error
                    time.sleep(min(0.05, remaining))
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def read_consumers(self) -> tuple[dict[str, ConsumerFile], list[str]]:
        parsed: dict[str, ConsumerFile] = {}
        failed: list[str] = []
        with os.scandir(self.paths.consumers_dir) as entries:
            files = sorted(Path(entry.path) for entry in entries if entry.name.endswith(".json"))
        for path in files:
            try:
                data: object = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("expected object")
                consumer = parse_consumer_file(cast(dict[str, Any], data))
                if consumer.consumer_id != path.stem:
                    raise ValueError("consumer ID does not match filename")
                parsed[consumer.consumer_id] = consumer
            except (ValueError, OSError):
                failed.append(path.stem)
        return parsed, failed


@dataclass(frozen=True)
class GcResult:
    deleted: list[str]
    halted_reason: str | None


class GarbageCollector:
    def __init__(
        self,
        paths: Paths,
        repo: Repository,
        fence: GcFence,
        store: MediaStore,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.paths, self.repo, self.fence, self.store, self.now = paths, repo, fence, store, now

    def _candidate_path(self, record: RenderRecord) -> Path | None:
        path = self.paths.media_dir / record.relative_path
        try:
            match = RENDER_NAME.fullmatch(path.name)
            expected = f"cinema-studio/renders/{record.clip_id}/{path.name}"
            if match is None or match["clip"] != record.clip_id or record.relative_path != expected:
                raise ValueError("noncanonical render path")
            validate_contained_path(path, self.paths.renders_dir)
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("render is not a regular file")
        except (ValueError, InvalidError, OSError):
            _LOGGER.warning("Skipping unsafe render %s: %s", record.id, record.relative_path)
            return None
        return path

    def run(self) -> GcResult:
        if self.store.is_network_fs():
            return GcResult([], "network filesystem")
        with self.fence.exclusive():
            try:
                consumers, failed = self.fence.read_consumers()
            except OSError as error:
                return GcResult([], f"cannot read consumers directory: {error}")
            if failed:
                return GcResult([], "unparseable consumer files: " + ", ".join(failed))
            missing = [cid for cid, _ in self.repo.list_consumers_seen() if cid not in consumers]
            if missing:
                return GcResult([], "missing consumer files: " + ", ".join(missing))
            now = self.now()
            protected: set[str] = set()
            for consumer in consumers.values():
                protected.update(consumer.held_render_ids)
                protected.update(
                    rid
                    for rid, expiry in consumer.pins.items()
                    if expiry + timedelta(minutes=10) > now
                )
            deleted: list[str] = []
            for record in self.repo.list_renders(states={"retired", "unrecognized"}):
                if record.id in protected:
                    continue
                path = self._candidate_path(record)
                if path is None:
                    continue
                if record.state == "retired":
                    if record.retired_at is None:
                        continue
                    age_from = datetime.fromisoformat(record.retired_at)
                else:
                    try:
                        age_from = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                    except FileNotFoundError:
                        continue
                if now - age_from < timedelta(hours=48):
                    continue
                path.unlink(missing_ok=True)
                self.repo.mark_render(record.id, "deleted")
                deleted.append(record.id)
                with suppress(OSError):
                    path.parent.rmdir()
            return GcResult(deleted, None)
