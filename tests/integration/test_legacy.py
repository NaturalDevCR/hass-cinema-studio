"""Legacy Worker migration contract."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cinema_studio.api import StudioClient
from custom_components.cinema_studio.catalog import parse_catalog
from custom_components.cinema_studio.manager import CinemaStudioManager

pytestmark = pytest.mark.integration


@pytest.fixture
async def migration(hass, catalog_payload, aioclient_mock):
    entry = MockConfigEntry(domain="cinema_studio", data={})
    entry.add_to_hass(hass)
    client = StudioClient(
        async_get_clientsession(hass), "studio", 8099, "studio-token", entry.entry_id
    )
    coordinator = MagicMock()
    coordinator.data.catalog = parse_catalog(catalog_payload)
    coordinator.async_request_refresh = AsyncMock()
    manager = CinemaStudioManager(hass, entry, coordinator, client=client)
    await manager.async_setup()
    return manager


def worker(hass, mock, *, health=None, status=None):
    entry = MockConfigEntry(
        domain="cinema_collections",
        data={"endpoint": "http://worker:8099", "token": "secret-legacy"},
        options={"history_reset_time": "03:00"},
    )
    entry.add_to_hass(hass)
    mock.get(
        "http://worker:8099/api/v1/status",
        json=status or {"queue_depth": 0, "current_job": None},
    )
    mock.get(
        "http://worker:8099/api/v1/health",
        json={"worker_version": "1.8.0"} if health is None else health,
    )
    for path, items in {
        "collections": [
            {
                "id": "regular",
                "name": "Regular",
                "playback_mode": "random",
                "ordered_clip_ids": [],
                "processing_profile_id": "compat",
                "enabled": True,
            },
            {
                "id": "halloween",
                "name": "Halloween",
                "playback_mode": "random",
                "ordered_clip_ids": [],
                "processing_profile_id": "compat",
                "enabled": True,
            },
        ],
        "profiles": [{"id": "compat", "name": "Compat", "settings": {}}],
        "jobs": [{"id": "done", "state": "done"}],
    }.items():
        mock.get(
            f"http://worker:8099/api/v1/{path}?page=1&page_size=100",
            json={"items": items, "total": len(items)},
        )
    mock.get("http://worker:8099/api/v1/assets", json=["logo.png"])
    return entry


async def test_missing(migration):
    with pytest.raises(ServiceValidationError, match="legacy_not_found"):
        await migration.legacy.async_run(False)


@pytest.mark.parametrize(
    "health,status_version,expected",
    [
        ({"worker_version": "1.8.0"}, "older", "1.8.0"),
        ({}, "1.7.0", "1.7.0"),
        ({}, None, "unknown"),
    ],
)
async def test_full(hass, migration, aioclient_mock, caplog, health, status_version, expected):
    worker(
        hass,
        aioclient_mock,
        health=health,
        status={"queue_depth": 0, "current_job": None, "version": status_version},
    )
    for name, start, end in [
        ("halloween", "2026-10-31", "2026-10-31"),
        ("christmas", "2026-12-01", "2027-01-06"),
    ]:
        hass.states.async_set(f"input_datetime.party_{name}_inicio", start)
        hass.states.async_set(f"input_datetime.party_{name}_fin", end)
    url = "http://worker:8099/api/v1/clips?page=1&page_size=100"

    async def clips_response(method, url, data):
        timestamp = "new" if any(r[0] == "POST" for r in aioclient_mock.mock_calls) else "old"
        return aioclient_mock.request(
            "GET", url, json={"items": [{"id": "clip-a", "updated_at": timestamp}], "total": 1}
        )

    aioclient_mock.get(url, side_effect=clips_response)
    studio = "http://studio:8099/api/v1/import/legacy"

    async def studio_response(method, url, data):
        body = (
            {"run_id": "run", "staged": ["clip-a"], "rejected": []}
            if data["phase"] == "stage"
            else {
                "run_id": "run",
                "catalog_revision": 4,
                "imported": ["clip-a"],
                "queued_for_render": [],
                "needs_source": [],
                "skipped": [],
                "missing_assets": [],
            }
        )
        return aioclient_mock.request("POST", url, json=body)

    aioclient_mock.post(studio, side_effect=studio_response)
    with patch(
        "custom_components.cinema_studio.legacy.persistent_notification.async_create"
    ) as notify:
        report = await migration.legacy.async_run(False)
    posts = [r for r in aioclient_mock.mock_calls if r[0] == "POST"]
    manifest = posts[0][2]["manifest"]
    assert manifest["worker"]["version"] == expected
    assert manifest["roots"] == {
        "source": "/media/cinema-collections/source",
        "compiled": "/media/cinema-collections/compiled",
    }
    assert [(s["id"], s["start"], s["end"], s["collection_id"]) for s in manifest["seasons"]] == [
        ("regular", None, None, "regular"),
        ("halloween", "10-31", "10-31", "halloween"),
        ("christmas", "12-01", "01-06", "regular"),
    ]
    assert posts[1][2] == {
        "phase": "commit",
        "run_id": "run",
        "clips": [{"id": "clip-a", "updated_at": "new"}],
    }
    assert all(
        r[3]["Authorization"] == "Bearer secret-legacy"
        for r in aioclient_mock.mock_calls
        if "worker" in str(r[1])
    )
    assert "secret-legacy" not in json.dumps(report) + caplog.text
    migration.coordinator.async_request_refresh.assert_awaited_once()
    notify.assert_called_once()


async def test_history_only(hass, migration, aioclient_mock):
    entry = worker(hass, aioclient_mock)
    record = {
        "period_start": "2026-10-05",
        "round_number": 7,
        "played_clip_ids": ["unknown"],
        "last_selected_clip_id": None,
        "last_reset_at": None,
        "reset_pending": False,
    }
    await Store(hass, 1, f"cinema_collections.{entry.entry_id}.playback_history").async_save(
        {"collections": {"regular": record, "removed": record}}
    )
    with patch("custom_components.cinema_studio.legacy.persistent_notification.async_create"):
        assert await migration.legacy.async_run(True) == {"history": 1}
    stored = await migration._store.async_load()
    assert stored["history"]["collections"]["regular"]["played_clip_ids"] == []
    assert stored["history"]["collections"]["regular"]["round_number"] == 7
    assert stored["activation"] == {
        "last_effective_season": "regular",
        "last_effective_collection": "regular",
    }
    assert migration.entry.options["history_reset_time"] == "03:00"
    assert not any(r[0] == "POST" for r in aioclient_mock.mock_calls)
    with patch.object(migration._client, "post_selections", AsyncMock()):
        response = await migration.async_select(collection_ref=None, season_ref=None, dry_run=False)
        assert not response["activation_reset"]
        assert not response["history_reset"]
        await hass.async_block_till_done(wait_background_tasks=True)


async def test_paginated_history_and_read_only_source(hass, migration, aioclient_mock):
    entry = MockConfigEntry(
        domain="cinema_collections",
        data={"endpoint": "http://worker:8099", "token": "secret-legacy"},
    )
    entry.add_to_hass(hass)
    for page, collection in [(1, "regular"), (2, "halloween")]:
        aioclient_mock.get(
            f"http://worker:8099/api/v1/collections?page={page}&page_size=100",
            json={"items": [{"id": collection}], "total": 2},
        )
    record = {
        "period_start": "2026-10-05",
        "round_number": 3,
        "played_clip_ids": ["clip-a", "unknown"],
        "last_selected_clip_id": "clip-a",
        "last_reset_at": "2026-10-05T00:00:00Z",
        "reset_pending": True,
    }
    source = Store(hass, 1, f"cinema_collections.{entry.entry_id}.playback_history")
    original = {"collections": {"regular": record}}
    await source.async_save(original)
    with patch("custom_components.cinema_studio.legacy.persistent_notification.async_create"):
        assert await migration.legacy.async_run(True) == {"history": 1}
    assert await source.async_load() == original
    imported = (await migration._store.async_load())["history"]["collections"]["regular"]
    assert imported == {**record, "played_clip_ids": ["clip-a"]}
    assert len(aioclient_mock.mock_calls) == 2


async def test_history_save_failure_rolls_back(migration):
    before = migration._state()
    with (
        patch.object(migration._store, "async_save", side_effect=OSError("disk full")),
        pytest.raises(OSError, match="disk full"),
    ):
        await migration.async_import_history({"collections": {}}, {"regular"})
    assert migration._state() == before


@pytest.mark.parametrize("timeout", [False, True])
async def test_catalog_adoption_wait(hass, migration, aioclient_mock, catalog_payload, timeout):
    worker(hass, aioclient_mock)
    aioclient_mock.get(
        "http://worker:8099/api/v1/clips?page=1&page_size=100", json={"items": [], "total": 0}
    )
    staged = AsyncMock(return_value={"run_id": "run"})
    committed = AsyncMock(
        return_value={
            "run_id": "run",
            "catalog_revision": 5,
            "imported": [],
            "queued_for_render": [],
            "needs_source": [],
            "skipped": [],
            "missing_assets": [],
        }
    )
    calls = 0

    async def refresh():
        nonlocal calls
        calls += 1
        if timeout:
            raise TimeoutError
        if calls == 2:
            catalog_payload["revision"] = 5
            await migration.async_install_snapshot(parse_catalog(catalog_payload), {}, AsyncMock())

    migration.coordinator.async_request_refresh.side_effect = refresh
    with (
        patch.object(migration._client, "legacy_stage", staged),
        patch.object(migration._client, "legacy_commit", committed),
        patch("custom_components.cinema_studio.legacy.asyncio.sleep", AsyncMock()),
        patch(
            "custom_components.cinema_studio.legacy.persistent_notification.async_create"
        ) as notify,
    ):
        if timeout:
            with pytest.raises(ServiceValidationError, match="legacy_catalog_timeout"):
                await migration.legacy.async_run(False)
            assert await migration._store.async_load() is None
            notify.assert_not_called()
        else:
            report = await migration.legacy.async_run(False)
            assert report["catalog_revision"] == migration.catalog_revision == 5
            assert calls == 2
