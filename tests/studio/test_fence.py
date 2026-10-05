"""Consumer parsing and process-shared garbage collection fence."""

import fcntl
import json
import multiprocessing
import os
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from cinema_studio.db import Database
from cinema_studio.fence import GarbageCollector, GcFence, parse_consumer_file
from cinema_studio.repository import Repository
from cinema_studio.storage import MediaStore
from tests.studio.test_repository import make_clip, make_render

pytestmark = pytest.mark.studio
NOW = datetime.now(UTC)


def consumer(held=(), pins=()):
    return dict(
        consumer_id="entry",
        generation="generation",
        seq=1,
        written_at=NOW.isoformat(),
        held_revision=2,
        held_render_ids=list(held),
        pins=list(pins),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("consumer_id", None),
        ("generation", 1),
        ("seq", True),
        ("seq", -1),
        ("held_revision", False),
        ("written_at", "2026-01-01"),
        ("written_at", "2026-01-01T00:00:00+01:00"),
        ("held_render_ids", [1]),
        ("pins", [{}]),
        ("pins", {}),
    ],
)
def test_malformed(field, value):
    data = consumer()
    data[field] = value
    with pytest.raises(ValueError):
        parse_consumer_file(data)


def test_duplicate_pins():
    late = NOW + timedelta(hours=1)
    parsed = parse_consumer_file(
        consumer(
            pins=[
                dict(render_id="render", expires_at=late.isoformat()),
                dict(render_id="render", expires_at=NOW.isoformat()),
            ]
        )
    )
    assert parsed.pins == {"render": late}


@pytest.mark.parametrize(
    "age,held,pin,kind,deleted",
    [
        (49, False, None, "retired", True),
        (49, True, None, "retired", False),
        (49, False, 60, "retired", False),
        (49, False, -5, "retired", False),
        (49, False, -11, "retired", True),
        (47, False, None, "retired", False),
        (49, False, None, "unrecognized", True),
        (48, False, -10, "retired", True),
    ],
)
def test_gc(paths, monkeypatch, age, held, pin, kind, deleted):
    store = MediaStore(paths)
    store.ensure_dirs()
    monkeypatch.setattr(store, "is_network_fs", lambda: False)
    with closing(Database(paths.database_path)) as db:
        repo = Repository(db)
        clip = make_clip(repo)
        record = make_render(clip, retired_at=(NOW - timedelta(hours=age)).isoformat())
        path = paths.media_dir / record.relative_path
        path.parent.mkdir(parents=True)
        path.write_bytes(b"video")
        if kind == "retired":
            repo.publish_render(record)
            repo.mark_render(record.id, "retired")
            db.connection.execute(
                "UPDATE renders SET retired_at = ? WHERE id = ?",
                ((NOW - timedelta(hours=age)).isoformat(), record.id),
            )
        else:
            repo.add_unrecognized_render(
                render_id=record.id,
                clip_id=clip,
                relative_path=record.relative_path,
                size=5,
                mtime_iso=NOW.isoformat(),
            )
            timestamp = (NOW - timedelta(hours=age)).timestamp()
            os.utime(path, (timestamp, timestamp))
        pins = (
            []
            if pin is None
            else [dict(render_id=record.id, expires_at=(NOW + timedelta(minutes=pin)).isoformat())]
        )
        (paths.consumers_dir / "entry.json").write_text(
            json.dumps(consumer(held=[record.id] if held else [], pins=pins))
        )
        result = GarbageCollector(paths, repo, GcFence(paths), store, now=lambda: NOW).run()
        assert result.halted_reason is None
        assert result.deleted == ([record.id] if deleted else [])
        assert path.exists() != deleted
        assert repo.get_render(record.id).state == ("deleted" if deleted else kind)
        if deleted:
            assert not path.parent.exists()


@pytest.mark.parametrize("reason", ["corrupt", "missing", "network", "mismatch"])
def test_halts(paths, monkeypatch, reason):
    store = MediaStore(paths)
    store.ensure_dirs()
    monkeypatch.setattr(store, "is_network_fs", lambda: reason == "network")
    with closing(Database(paths.database_path)) as db:
        repo = Repository(db)
        record = make_render(make_clip(repo))
        path = paths.media_dir / record.relative_path
        path.parent.mkdir(parents=True)
        path.write_bytes(b"keep")
        repo.add_unrecognized_render(
            render_id=record.id,
            clip_id=record.clip_id,
            relative_path=record.relative_path,
            size=4,
            mtime_iso=NOW.isoformat(),
        )
        timestamp = (NOW - timedelta(hours=49)).timestamp()
        os.utime(path, (timestamp, timestamp))
        if reason == "corrupt":
            (paths.consumers_dir / "entry.json").write_text("{")
        elif reason == "mismatch":
            (paths.consumers_dir / "wrong.json").write_text(json.dumps(consumer()))
        elif reason == "missing":
            repo.touch_consumer("entry", 1)
        result = GarbageCollector(paths, repo, GcFence(paths), store).run()
        assert result.halted_reason and not result.deleted
        assert path.read_bytes() == b"keep"


def shared_lock(path, ready):
    with open(path, "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        ready.set()
        time.sleep(1)


def test_process_lock(paths):
    MediaStore(paths).ensure_dirs()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(target=shared_lock, args=(str(paths.gc_lock_path), ready))
    process.start()
    try:
        assert ready.wait(5)
        fence = GcFence(paths)
        with pytest.raises(TimeoutError), fence.exclusive(timeout=0.2):
            pass
        started = time.monotonic()
        with fence.exclusive(timeout=3):
            assert time.monotonic() - started >= 0.5
    finally:
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join()
    assert process.exitcode == 0
