"""Consumer writes serialize with each other and exclude garbage collection."""

import fcntl
import json
import multiprocessing
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from custom_components.cinema_studio.fence import ConsumerFence, FenceCorrupt, FenceTimeout

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 5, tzinfo=UTC)


def write(fence: ConsumerFence, **kwargs):
    return fence.write(
        held_revision=4,
        held_render_ids=kwargs.pop("held_render_ids", ["r1"]),
        new_pins=kwargs.pop("new_pins", {}),
        persisted_pins=kwargs.pop("persisted_pins", {}),
        now=NOW,
        **kwargs,
    )


def test_write_and_merge(tmp_path: Path) -> None:
    fence = ConsumerFence(tmp_path, "entry", "old")
    expiry = NOW + timedelta(hours=6)
    write(
        fence,
        new_pins={
            "old": expiry,
            "grace": NOW - timedelta(minutes=5),
            "expired": NOW - timedelta(minutes=11),
            "boundary": NOW - timedelta(minutes=10),
        },
    )
    fence = ConsumerFence(tmp_path, "entry", "new")
    result = write(
        fence, held_render_ids=["r2"], new_pins={"old": NOW}, persisted_pins={"persisted": expiry}
    )
    assert result.written
    assert result.pins == {
        "old": expiry,
        "grace": NOW - timedelta(minutes=5),
        "boundary": NOW - timedelta(minutes=10),
        "persisted": expiry,
    }
    data = json.loads((tmp_path / "cinema-studio/consumers/entry.json").read_text())
    assert set(data) == {
        "consumer_id",
        "generation",
        "seq",
        "written_at",
        "held_revision",
        "held_render_ids",
        "pins",
    }
    assert data["consumer_id"] == "entry"
    assert data["generation"] == "new"
    assert data["seq"] == 2
    assert data["held_revision"] == 4
    assert data["held_render_ids"] == ["r2"]
    assert data["written_at"] == "2026-10-05T00:00:00Z"
    assert {p["render_id"] for p in data["pins"]} == set(result.pins)
    assert all(
        set(p) == {"render_id", "expires_at"} and p["expires_at"].endswith("Z")
        for p in data["pins"]
    )


@pytest.mark.parametrize("contents", [b"not json", b"{}", b"[]", b"\xff"])
def test_corrupt_untouched(tmp_path: Path, contents: bytes) -> None:
    path = tmp_path / "cinema-studio/consumers/entry.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(contents)
    with pytest.raises(FenceCorrupt):
        write(ConsumerFence(tmp_path, "entry", "gen"))
    assert path.read_bytes() == contents


def test_before_write(tmp_path: Path) -> None:
    fence = ConsumerFence(tmp_path, "entry", "gen")
    path = tmp_path / "cinema-studio/consumers/entry.json"
    result = write(fence, before_write=lambda: False)
    assert not result.written and result.pins == {}
    assert not path.exists()
    expiry = NOW - timedelta(minutes=11)
    write(fence, new_pins={"existing": NOW + timedelta(hours=1)})
    data = json.loads(path.read_text())
    data["pins"].append({"render_id": "expired", "expires_at": expiry.isoformat()})
    path.write_text(json.dumps(data))
    original = path.read_bytes()
    result = write(fence, new_pins={"new": NOW}, before_write=lambda: False)
    assert not result.written
    assert result.pins == {"existing": NOW + timedelta(hours=1), "expired": expiry}
    assert path.read_bytes() == original


def hold_gc(path: str, ready) -> None:
    with open(path, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ready.set()
        time.sleep(1)


def test_gc_timeout_and_success(tmp_path: Path) -> None:
    root = tmp_path / "cinema-studio"
    root.mkdir()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(target=hold_gc, args=(str(root / ".gc.lock"), ready))
    process.start()
    try:
        assert ready.wait(5)
        fence = ConsumerFence(tmp_path, "entry", "gen")
        with pytest.raises(FenceTimeout):
            write(fence, timeout=0.2)
        assert write(fence, timeout=3).written
    finally:
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join()
    assert process.exitcode == 0


def test_concurrent_writers(tmp_path: Path) -> None:
    barrier = Barrier(2)

    def worker(pin: str) -> None:
        barrier.wait()
        write(ConsumerFence(tmp_path, "entry", pin), new_pins={pin: NOW + timedelta(hours=6)})

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, ["one", "two"]))
    data = json.loads((tmp_path / "cinema-studio/consumers/entry.json").read_text())
    assert data["seq"] == 2
    assert {pin["render_id"] for pin in data["pins"]} == {"one", "two"}


def test_callback_holds_both_locks(tmp_path: Path) -> None:
    fence = ConsumerFence(tmp_path, "entry", "gen")

    def check() -> bool:
        for path in (
            tmp_path / "cinema-studio/consumers/entry.lock",
            tmp_path / "cinema-studio/.gc.lock",
        ):
            with path.open("a") as lock, pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True

    assert write(fence, before_write=check).written


def test_consumer_lock_timeout_releases(tmp_path: Path) -> None:
    directory = tmp_path / "cinema-studio/consumers"
    directory.mkdir(parents=True)
    fence = ConsumerFence(tmp_path, "entry", "gen")
    with (directory / "entry.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(FenceTimeout):
            write(fence, timeout=0.05)
    assert write(fence).written
