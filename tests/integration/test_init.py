"""Entry lifecycle, catalog refresh, and persisted offline recovery."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.cinema_studio import CinemaStudioRuntime
from custom_components.cinema_studio.const import DOMAIN, EVENT_CATALOG_CHANGED, STORAGE_VERSION

pytestmark = pytest.mark.integration
BASE = "http://studio:8099/api/v1"
HEALTH = {"status": "ok", "version": "1.2.3", "api_version": 1, "instance_id": "studio-id"}


@pytest.fixture
def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "studio", "port": 8099, "token": "secret"},
        unique_id="studio-id",
        options={"scan_interval": 45},
    )
    entry.add_to_hass(hass)
    return entry


def snapshot(hass_storage, entry, catalog_payload, etag='"rev-7"'):
    hass_storage[f"{DOMAIN}.{entry.entry_id}.catalog"] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}.catalog",
        "data": {"etag": etag, "catalog": catalog_payload},
    }


def online(aioclient_mock, catalog_payload):
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/catalog", json=catalog_payload, headers={"ETag": '"rev-7"'})


async def test_online_setup_and_unload(hass, entry, aioclient_mock, hass_storage, catalog_payload):
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, CinemaStudioRuntime)
    state = entry.runtime_data.coordinator.data
    assert state.catalog.revision == 4
    assert state.connected
    assert state.last_sync is not None
    assert state.app_version == "1.2.3"
    assert entry.runtime_data.manager is not None
    assert entry.runtime_data.coordinator.update_interval == timedelta(seconds=45)
    assert hass_storage[f"{DOMAIN}.{entry.entry_id}.catalog"]["data"] == {
        "etag": '"rev-7"',
        "catalog": catalog_payload,
    }
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    count = aioclient_mock.call_count
    hass.bus.async_fire(EVENT_CATALOG_CHANGED)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == count


async def test_offline_snapshot(hass, entry, aioclient_mock, hass_storage, catalog_payload):
    snapshot(hass_storage, entry, catalog_payload)
    aioclient_mock.get(f"{BASE}/health", exc=TimeoutError())
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    state = entry.runtime_data.coordinator.data
    assert state.catalog.revision == 4
    assert not state.connected
    assert state.last_sync is None
    assert state.app_version is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_offline_without_snapshot(hass, entry, aioclient_mock):
    aioclient_mock.get(f"{BASE}/health", exc=TimeoutError())
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_catalog_event(hass, entry, aioclient_mock, hass_storage, catalog_payload):
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    changed = {**catalog_payload, "revision": 5}
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/catalog", json=changed, headers={"ETag": '"rev-5"'})
    count = aioclient_mock.call_count
    hass.bus.async_fire(EVENT_CATALOG_CHANGED, {"revision": 5})
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == count + 2
    assert entry.runtime_data.coordinator.data.catalog.revision == 5
    assert hass_storage[f"{DOMAIN}.{entry.entry_id}.catalog"]["data"] == {
        "etag": '"rev-5"',
        "catalog": changed,
    }
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_304_keeps_catalog(hass, entry, aioclient_mock, catalog_payload):
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    coordinator = entry.runtime_data.coordinator
    original = coordinator.data.catalog
    last_sync = coordinator.data.last_sync
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/catalog", status=304)
    next_sync = last_sync + timedelta(seconds=10)
    with patch(
        "custom_components.cinema_studio.coordinator.dt_util.utcnow", return_value=next_sync
    ):
        await coordinator.async_refresh()
    assert coordinator.data.catalog is original
    assert coordinator.data.connected
    assert coordinator.data.last_sync == next_sync
    assert aioclient_mock.mock_calls[-1][3]["If-None-Match"] == '"rev-7"'
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_snapshot_304(hass, entry, aioclient_mock, hass_storage, catalog_payload):
    snapshot(hass_storage, entry, catalog_payload)
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/catalog", status=304)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.coordinator.data.catalog.revision == 4
    assert entry.runtime_data.coordinator.data.connected
    assert aioclient_mock.mock_calls[-1][3]["If-None-Match"] == '"rev-7"'
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_online_then_offline(hass, entry, aioclient_mock, catalog_payload):
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    coordinator = entry.runtime_data.coordinator
    original = coordinator.data
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", exc=TimeoutError())
    await coordinator.async_refresh()
    assert not coordinator.data.connected
    assert coordinator.data.catalog is original.catalog
    assert coordinator.data.last_sync == original.last_sync
    assert coordinator.data.app_version == original.app_version
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_auth_never_uses_snapshot(hass, entry, aioclient_mock, hass_storage, catalog_payload):
    snapshot(hass_storage, entry, catalog_payload)
    aioclient_mock.get(f"{BASE}/health", status=401)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_coordinator_auth_error(hass, entry, aioclient_mock, catalog_payload):
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/catalog", status=403)
    with pytest.raises(ConfigEntryAuthFailed):
        await entry.runtime_data.coordinator._async_update_data()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_corrupt_snapshot_recovers(
    hass, entry, aioclient_mock, hass_storage, catalog_payload
):
    snapshot(hass_storage, entry, {"revision": "bad"})
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.coordinator.data.connected
    assert "If-None-Match" not in aioclient_mock.mock_calls[-1][3]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_reload(hass, entry, aioclient_mock, catalog_payload):
    # Option changes rebuild the runtime and its entity subscriptions.
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    with patch.object(hass.config_entries, "async_reload", return_value=True) as reload:
        hass.config_entries.async_update_entry(entry, options={"scan_interval": 60})
        await hass.async_block_till_done()
        reload.assert_awaited_once_with(entry.entry_id)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_invalid_catalog_preserves_snapshot(
    hass, entry, aioclient_mock, hass_storage, catalog_payload
):
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    coordinator = entry.runtime_data.coordinator
    original = coordinator.data
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/catalog", json={"revision": 5}, headers={"ETag": '"rev-5"'})
    await coordinator.async_refresh()
    assert not coordinator.data.connected
    assert coordinator.data.catalog is original.catalog
    assert coordinator.data.last_sync == original.last_sync
    assert hass_storage[f"{DOMAIN}.{entry.entry_id}.catalog"]["data"] == {
        "etag": '"rev-7"',
        "catalog": catalog_payload,
    }
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/catalog", status=304)
    await coordinator.async_refresh()
    assert coordinator.data.connected
    assert aioclient_mock.mock_calls[-1][3]["If-None-Match"] == '"rev-7"'
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_304_without_catalog_retries(hass, entry, aioclient_mock):
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/catalog", status=304)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_corrupt_snapshot_offline_retries(hass, entry, aioclient_mock, hass_storage):
    snapshot(hass_storage, entry, {"revision": 4})
    aioclient_mock.get(f"{BASE}/health", exc=TimeoutError())
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_refresh_starts_reauth(hass, entry, aioclient_mock, catalog_payload):
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", status=401)
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert any(
        flow["context"]["source"] == SOURCE_REAUTH and flow["context"]["entry_id"] == entry.entry_id
        for flow in hass.config_entries.flow.async_progress()
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_remove_snapshot(hass, entry, aioclient_mock, hass_storage, catalog_payload):
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    key = f"{DOMAIN}.{entry.entry_id}.catalog"
    assert key in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


async def test_polling_without_entities(hass, entry, aioclient_mock, catalog_payload):
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    count = aioclient_mock.call_count
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=46))
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == count + 2
    assert await hass.config_entries.async_unload(entry.entry_id)
    count = aioclient_mock.call_count
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=100))
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == count


@pytest.mark.parametrize("source", ["reauth", "reconfigure"])
async def test_credential_update_reloads_once(hass, entry, aioclient_mock, catalog_payload, source):
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": source, "entry_id": entry.entry_id},
        data=dict(entry.data) if source == "reauth" else None,
    )
    with patch.object(hass.config_entries, "async_reload", return_value=True) as reload:
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {**entry.data, "token": "rotated"}
        )
        await hass.async_block_till_done()
        reload.assert_awaited_once_with(entry.entry_id)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_auth_failed_entry_revived_by_discovery(hass, entry, aioclient_mock, catalog_payload):
    from homeassistant.config_entries import SOURCE_HASSIO
    from homeassistant.helpers.service_info.hassio import HassioServiceInfo

    aioclient_mock.get(f"{BASE}/health", status=401)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    await hass.async_block_till_done()
    aioclient_mock.clear_requests()
    online(aioclient_mock, catalog_payload)
    info = HassioServiceInfo(
        config={**entry.data, "token": "valid", "instance_id": "studio-id"},
        name="Cinema Studio",
        slug="cinema_studio",
        uuid="1234",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=info
    )
    assert result["reason"] == "already_configured"
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data["token"] == "valid"
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer valid"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_discovery_unchanged_does_not_reload(hass, entry, aioclient_mock, catalog_payload):
    from homeassistant.config_entries import SOURCE_HASSIO
    from homeassistant.helpers.service_info.hassio import HassioServiceInfo

    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    info = HassioServiceInfo(
        config={**entry.data, "instance_id": "studio-id"},
        name="Cinema Studio",
        slug="cinema_studio",
        uuid="1234",
    )
    with patch.object(hass.config_entries, "async_reload", return_value=True) as reload:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_HASSIO}, data=info
        )
        await hass.async_block_till_done()
        assert result["reason"] == "already_configured"
        reload.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_retry_entry_revived_by_unchanged_discovery(
    hass, entry, aioclient_mock, catalog_payload
):
    from homeassistant.config_entries import SOURCE_HASSIO
    from homeassistant.helpers.service_info.hassio import HassioServiceInfo

    aioclient_mock.get(f"{BASE}/health", exc=TimeoutError())
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    aioclient_mock.clear_requests()
    online(aioclient_mock, catalog_payload)
    info = HassioServiceInfo(
        config={**entry.data, "instance_id": "studio-id"},
        name="Cinema Studio",
        slug="cinema_studio",
        uuid="1234",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=info
    )
    assert result["reason"] == "already_configured"
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_install_is_awaited_before_coordinator_data_changes(
    hass, entry, aioclient_mock, catalog_payload
):
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    coordinator = entry.runtime_data.coordinator
    original = coordinator.data
    events = []
    manager = entry.runtime_data.manager

    async def install(catalog, raw, persist):
        events.append(("install", coordinator.data is original, catalog.revision))
        await persist(raw)
        events.append(("persisted", coordinator.data is original))

    manager.async_install_snapshot = install
    changed = {**catalog_payload, "revision": 5}
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/catalog", json=changed, headers={"ETag": '"rev-5"'})
    await coordinator.async_refresh()
    assert events == [("install", True, 5), ("persisted", True)]
    assert coordinator.data.catalog.revision == 5
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_install_failure_keeps_previous_data(hass, entry, aioclient_mock, catalog_payload):
    online(aioclient_mock, catalog_payload)
    assert await hass.config_entries.async_setup(entry.entry_id)
    coordinator = entry.runtime_data.coordinator
    original = coordinator.data

    async def fail_install(catalog, raw, persist):
        raise RuntimeError("manager adoption failed")

    coordinator.manager.async_install_snapshot = fail_install
    changed = {**catalog_payload, "revision": 5}
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/catalog", json=changed, headers={"ETag": '"rev-5"'})
    await coordinator.async_refresh()
    assert coordinator.data is original
    assert await hass.config_entries.async_unload(entry.entry_id)
