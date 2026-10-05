"""Blocking, durable consumer writes fenced against App garbage collection."""

from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

PIN_GRACE = timedelta(minutes=10)


class FenceTimeout(Exception):
    """A consumer or GC lock could not be acquired within the deadline."""


class FenceCorrupt(Exception):
    """An existing consumer file cannot safely be read."""


@dataclass(frozen=True)
class FenceWriteResult:
    written: bool
    pins: dict[str, datetime]


@dataclass
class ConsumerState:
    consumer_id: str
    generation: str
    seq: int
    held_revision: int
    held_render_ids: set[str]
    pins: dict[str, datetime]


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return cast(dict[str, object], value)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("expected timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("expected UTC timestamp")
    return parsed.astimezone(UTC)


def _read(path: Path) -> ConsumerState | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except UnicodeError as err:
        raise FenceCorrupt(f"Invalid consumer file: {path}") from err
    try:
        data = _object(json.loads(raw))
        consumer_id, generation = data["consumer_id"], data["generation"]
        seq, revision = data["seq"], data["held_revision"]
        held, pins = data["held_render_ids"], data["pins"]
        _timestamp(data["written_at"])
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
            pin = _object(item)
            render_id = pin["render_id"]
            if not isinstance(render_id, str):
                raise ValueError("invalid pin render ID")
            expiry = _timestamp(pin["expires_at"])
            parsed_pins[render_id] = max(parsed_pins.get(render_id, expiry), expiry)
        return ConsumerState(consumer_id, generation, seq, revision, held_ids, parsed_pins)
    except (ValueError, KeyError, TypeError, OverflowError) as err:
        raise FenceCorrupt(f"Invalid consumer file: {path}") from err


def _lock(fd: int, mode: int, deadline: float) -> None:
    while True:
        try:
            fcntl.flock(fd, mode | fcntl.LOCK_NB)
            return
        except BlockingIOError as err:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FenceTimeout("Timed out waiting for consumer fence") from err
            time.sleep(min(0.05, remaining))


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class ConsumerFence:
    def __init__(self, media_root: Path, consumer_id: str, generation: str) -> None:
        self.root = media_root / "cinema-studio"
        self.consumer_id = consumer_id
        self.generation = generation

    def write(
        self,
        *,
        held_revision: int,
        held_render_ids: Iterable[str],
        new_pins: Mapping[str, datetime],
        persisted_pins: Mapping[str, datetime],
        now: datetime,
        timeout: float = 5.0,
        before_write: Callable[[], bool] | None = None,
    ) -> FenceWriteResult:
        directory = self.root / "consumers"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.consumer_id}.json"
        deadline = time.monotonic() + timeout
        with (directory / f"{self.consumer_id}.lock").open("a") as consumer_lock:
            _lock(consumer_lock.fileno(), fcntl.LOCK_EX, deadline)
            try:
                with (self.root / ".gc.lock").open("a") as gc_lock:
                    _lock(gc_lock.fileno(), fcntl.LOCK_SH, deadline)
                    try:
                        return self._write_locked(
                            path,
                            held_revision,
                            held_render_ids,
                            new_pins,
                            persisted_pins,
                            now,
                            before_write,
                        )
                    finally:
                        fcntl.flock(gc_lock.fileno(), fcntl.LOCK_UN)
            finally:
                fcntl.flock(consumer_lock.fileno(), fcntl.LOCK_UN)

    def _write_locked(
        self,
        path: Path,
        held_revision: int,
        held_render_ids: Iterable[str],
        new_pins: Mapping[str, datetime],
        persisted_pins: Mapping[str, datetime],
        now: datetime,
        before_write: Callable[[], bool] | None,
    ) -> FenceWriteResult:
        existing = _read(path)
        pins = dict(existing.pins) if existing else {}
        if before_write is not None and not before_write():
            return FenceWriteResult(False, pins)
        for source in (persisted_pins, new_pins):
            for render_id, expiry in source.items():
                pins[render_id] = max(pins.get(render_id, expiry), expiry)
        pins = {key: expiry for key, expiry in pins.items() if expiry + PIN_GRACE >= now}
        data = {
            "consumer_id": self.consumer_id,
            "generation": self.generation,
            "seq": existing.seq + 1 if existing else 1,
            "written_at": _iso(now),
            "held_revision": held_revision,
            "held_render_ids": sorted(set(held_render_ids)),
            "pins": [
                {"render_id": key, "expires_at": _iso(expiry)}
                for key, expiry in sorted(pins.items())
            ],
        }
        temporary = path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(data, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return FenceWriteResult(True, pins)
