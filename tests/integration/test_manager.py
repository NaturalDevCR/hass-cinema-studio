"""Durable offline selection and fenced catalog transitions."""

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cinema_studio.catalog import parse_catalog
from custom_components.cinema_studio.const import DOMAIN
from custom_components.cinema_studio.manager import CinemaStudioManager

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


@pytest.fixture
async def manager(hass, media_root, catalog_payload):
    catalog_payload["collections"][0]["playback_mode"] = "sequential"
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.data.catalog = parse_catalog(catalog_payload)
    coordinator._client.post_selections = AsyncMock(side_effect=ConnectionError("offline"))
    result = CinemaStudioManager(hass, entry, coordinator, now=lambda: NOW)
    await result.async_setup()
    return result


async def select(manager, **kwargs):
    return await manager.async_select(collection_ref=None, season_ref=None, dry_run=False, **kwargs)


async def test_offline_persist_pin_and_round(manager, media_root):
    response = await select(manager)
    assert response["clip_id"] == "clip-a"
    assert not response["history_reset"]
    data = json.loads(next((media_root / "cinema-studio/consumers").glob("*.json")).read_text())
    assert datetime.fromisoformat(data["pins"][0]["expires_at"]) == NOW + timedelta(hours=6)
    stored = await manager._store.async_load()
    assert stored["history"]["collections"]["regular"]["played_clip_ids"] == ["clip-a"]
    assert stored["selection_queue"][0]["selection_id"] == response["selection_id"]
    assert (await select(manager))["history_reset"]


async def test_dry_run(manager, media_root):
    before = manager._state()
    response = await manager.async_select(collection_ref=None, season_ref=None, dry_run=True)
    assert response["file_verified"]
    assert manager._state() == before
    data = json.loads(next((media_root / "cinema-studio/consumers").glob("*.json")).read_text())
    assert data["pins"] == []
    assert await manager._store.async_load() is None


async def test_file_changes_after_setup(manager, media_root, catalog_payload):
    second = copy.deepcopy(catalog_payload["clips"][0])
    second.update(id="clip-b", sort_key="Z")
    second["render"].update(
        id="r2",
        relative_path="cinema-studio/renders/clip-b/b.mp4",
        media_path="cinema-studio/renders/clip-b/b.mp4",
    )
    path = media_root / second["render"]["relative_path"]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"12345")
    catalog_payload["clips"].append(second)
    await manager.async_install_snapshot(parse_catalog(catalog_payload), {}, AsyncMock())
    (media_root / catalog_payload["clips"][0]["render"]["relative_path"]).write_bytes(b"x")
    assert (await select(manager))["clip_id"] == "clip-b"
    path.unlink()
    with pytest.raises(ServiceValidationError) as err:
        await select(manager)
    assert err.value.translation_key == "no_playable_clip"


async def test_snapshot_serialized_failure(manager, catalog_payload, media_root):
    raw = copy.deepcopy(catalog_payload)
    raw["revision"] = 5
    raw["clips"][0]["render"]["id"] = "r2"
    entered, release = asyncio.Event(), asyncio.Event()

    async def persist(_):
        entered.set()
        await release.wait()
        raise RuntimeError("disk failure")

    install = asyncio.create_task(manager.async_install_snapshot(parse_catalog(raw), raw, persist))
    await entered.wait()
    selection = asyncio.create_task(select(manager))
    await asyncio.sleep(0)
    assert not selection.done()
    data = json.loads(next((media_root / "cinema-studio/consumers").glob("*.json")).read_text())
    assert set(data["held_render_ids"]) == {"r1", "r2"}
    release.set()
    with pytest.raises(RuntimeError):
        await install
    assert (await selection)["catalog_revision"] == 4


async def test_corrupt_consumer(manager, media_root):
    next((media_root / "cinema-studio/consumers").glob("*.json")).write_text("broken")
    await manager.async_setup()
    assert not manager.ready
    assert ir.async_get(manager.hass).async_get_issue(DOMAIN, "consumer_corrupt") is not None
    with pytest.raises(ServiceValidationError) as err:
        await select(manager)
    assert err.value.translation_key == "not_ready"


async def test_queue_retry(manager):
    await select(manager)
    await manager.hass.async_block_till_done()
    assert len(manager._selection_queue) == 1
    manager.coordinator._client.post_selections = AsyncMock()
    await manager.async_flush_selections()
    assert not manager._selection_queue
    assert (await manager._store.async_load())["selection_queue"] == []


async def test_save_failure_returns_no_selection(manager):
    with (
        patch.object(manager._store, "async_save", side_effect=OSError("disk full")),
        pytest.raises(OSError),
    ):
        await select(manager)
    assert manager.last_selection("regular") is None


async def test_activation_restart_action_and_fallback(manager, catalog_payload):
    await select(manager)
    raw = copy.deepcopy(catalog_payload)
    raw["seasons"].append(
        {
            **raw["seasons"][0],
            "id": "holiday",
            "name": "Holiday",
            "start": "10-01",
            "end": "10-31",
            "priority": 10,
        }
    )
    await manager.async_install_snapshot(parse_catalog(raw), raw, AsyncMock())
    before = manager._activation
    action = await manager.async_select(collection_ref=None, season_ref="holiday", dry_run=False)
    assert not action["activation_reset"]
    assert manager._activation == before
    response = await select(manager)
    assert response["activation_reset"]
    assert not (await select(manager))["activation_reset"]
    manager.coordinator.data.catalog = parse_catalog(raw)
    restarted = CinemaStudioManager(
        manager.hass, manager.entry, manager.coordinator, now=lambda: NOW
    )
    await restarted.async_setup()
    assert not (await select(restarted))["activation_reset"]
    raw["seasons"][-1]["collection_id"] = "empty"
    await restarted.async_install_snapshot(parse_catalog(raw), raw, AsyncMock())
    response = await select(restarted)
    assert response["season_fallback"]
    assert response["season"] == "regular"
    assert response["requested_season"] == "holiday"


async def test_gc_lock_other_process(manager, media_root):
    import subprocess
    import sys

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            'import fcntl,sys; f=open(sys.argv[1], "a"); '
            'fcntl.flock(f, fcntl.LOCK_EX); print("locked", flush=True); sys.stdin.read()',
            str(media_root / "cinema-studio/.gc.lock"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert await asyncio.to_thread(process.stdout.readline) == "locked\n"
        original = manager._fence.write
        from functools import partial

        with (
            patch.object(manager._fence, "write", partial(original, timeout=0.05)),
            pytest.raises(ServiceValidationError) as err,
        ):
            await select(manager)
        assert err.value.translation_key == "not_ready"
    finally:
        process.communicate("release")


async def test_initial_unverified(manager, media_root):
    (media_root / manager._catalog.clips[0].render.relative_path).unlink()
    await manager.async_setup()
    with pytest.raises(ServiceValidationError) as err:
        await select(manager)
    assert err.value.translation_key == "no_playable_clip"


@pytest.mark.parametrize(
    "field,key", [("collection_ref", "unknown_collection"), ("season_ref", "unknown_season")]
)
async def test_unknown_references(manager, field, key):
    args = {"collection_ref": None, "season_ref": None, "dry_run": False, field: "missing"}
    with pytest.raises(ServiceValidationError) as err:
        await manager.async_select(**args)
    assert err.value.translation_key == key


async def test_sequential_two_clips(manager, catalog_payload, media_root):
    raw = copy.deepcopy(catalog_payload)
    clip = copy.deepcopy(raw["clips"][0])
    clip.update(id="clip-b", sort_key="Z")
    clip["render"].update(
        id="r2",
        relative_path="cinema-studio/renders/clip-b/b.mp4",
        media_path="cinema-studio/renders/clip-b/b.mp4",
    )
    path = media_root / clip["render"]["relative_path"]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"12345")
    raw["clips"].append(clip)
    await manager.async_install_snapshot(parse_catalog(raw), raw, AsyncMock())
    responses = [await select(manager) for _ in range(3)]
    assert [response["clip_id"] for response in responses] == ["clip-a", "clip-b", "clip-a"]
    assert [response["history_reset"] for response in responses] == [False, False, True]


async def test_final_fence_failure_retains_superset(manager, catalog_payload, media_root):
    raw = copy.deepcopy(catalog_payload)
    raw["revision"] = 5
    raw["clips"][0]["render"]["id"] = "r2"
    original = manager._write_fence
    calls = 0

    async def write(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("final write failed")
        return await original(*args, **kwargs)

    with patch.object(manager, "_write_fence", write):
        await manager.async_install_snapshot(parse_catalog(raw), raw, AsyncMock())
    data = json.loads(next((media_root / "cinema-studio/consumers").glob("*.json")).read_text())
    assert set(data["held_render_ids"]) == {"r1", "r2"}
    assert (await select(manager))["render_id"] == "r2"
    data = json.loads(next((media_root / "cinema-studio/consumers").glob("*.json")).read_text())
    assert set(data["held_render_ids"]) == {"r1", "r2"}
