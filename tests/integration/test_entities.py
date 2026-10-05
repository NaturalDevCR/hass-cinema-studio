"""Season, override, collection, catalog and connectivity entities."""

import copy
from datetime import date
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)

from custom_components.cinema_studio.const import DOMAIN, STORAGE_VERSION
from tests.integration.studio_support import (
    OCTOBER,
    clip_for,
    mock_offline,
    mock_studio,
    new_entry,
    setup,
    write_renders,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("july")]


async def refresh(hass, entry):
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


def lookup(hass, entry, platform, suffix):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{suffix}")


def entity_id(hass, entry, platform, suffix):
    found = lookup(hass, entry, platform, suffix)
    assert found is not None, f"{platform} {suffix} is not registered"
    return found


async def select_option(hass, select_entity, option):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": select_entity, "option": option}, blocking=True
    )


async def select_clip(hass, **data: Any):
    return await hass.services.async_call(
        DOMAIN, "select_next_clip", data, blocking=True, return_response=True
    )


async def test_entities_and_device(hass, loaded_entry):
    entities = er.async_entries_for_config_entry(er.async_get(hass), loaded_entry.entry_id)
    assert {
        (item.domain, item.unique_id.removeprefix(f"{loaded_entry.entry_id}_")) for item in entities
    } == {
        ("sensor", "active_season"),
        ("select", "season_override"),
        ("sensor", "catalog"),
        ("binary_sensor", "studio_connected"),
        ("sensor", "collection_regular"),
        ("sensor", "collection_spooky"),
    }
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, loaded_entry.entry_id)})
    assert device is not None
    assert device.name == "Cinema Studio"
    assert device.entry_type is DeviceEntryType.SERVICE
    assert device.sw_version == "1.0"
    assert {item.device_id for item in entities} == {device.id}
    assert {item.entity_id for item in entities} == {
        "sensor.cinema_studio_active_season",
        "select.cinema_studio_season_override",
        "sensor.cinema_studio_catalog",
        "binary_sensor.cinema_studio_studio_connected",
        "sensor.cinema_studio_regular_last",
        "sensor.cinema_studio_spooky_last",
    }
    names = {
        "sensor.cinema_studio_active_season": "Cinema Studio Active season",
        "select.cinema_studio_season_override": "Cinema Studio Season override",
        "sensor.cinema_studio_catalog": "Cinema Studio Catalog",
        "binary_sensor.cinema_studio_studio_connected": "Cinema Studio Studio connected",
        "sensor.cinema_studio_regular_last": "Cinema Studio Regular last",
        "sensor.cinema_studio_spooky_last": "Cinema Studio Spooky last",
    }
    for eid, name in names.items():
        assert hass.states.get(eid).name == name


async def test_active_season_sensor_follows_override_select(hass, loaded_entry):
    manager = loaded_entry.runtime_data.manager
    sensor = "sensor.cinema_studio_active_season"
    override = "select.cinema_studio_season_override"
    state = hass.states.get(sensor)
    assert state.state == "regular"
    assert {k: v for k, v in state.attributes.items() if k in _SEASON_ATTRS} == {
        "name": "Regular",
        "source": "default",
        "collection_id": "regular",
        "last_effective_season": None,
        "color": "#64748b",
    }
    assert hass.states.get(override).state == "Auto"
    assert hass.states.get(override).attributes["options"] == ["Auto", "Regular", "Halloween"]

    with patch.object(
        manager, "async_evaluate_activation", wraps=manager.async_evaluate_activation
    ) as evaluate:
        await select_option(hass, override, "Halloween")
    evaluate.assert_awaited_once()
    state = hass.states.get(sensor)
    assert state.state == "halloween"
    assert state.attributes["name"] == "Halloween"
    assert state.attributes["source"] == "override"
    assert state.attributes["collection_id"] == "spooky"
    assert state.attributes["last_effective_season"] == "halloween"
    assert state.attributes["color"] == "#f97316"
    assert hass.states.get(override).state == "Halloween"
    assert manager.override_season == "halloween"

    await select_option(hass, override, "Auto")
    assert hass.states.get(override).state == "Auto"
    assert manager.override_season is None
    assert hass.states.get(sensor).state == "regular"
    assert hass.states.get(sensor).attributes["source"] == "default"


_SEASON_ATTRS = {"name", "source", "collection_id", "last_effective_season", "color"}


async def test_active_season_updates_on_coordinator_refresh(
    hass, loaded_entry, aioclient_mock, payload, freezer
):
    sensor = "sensor.cinema_studio_active_season"
    assert hass.states.get(sensor).state == "regular"
    freezer.move_to(OCTOBER)
    assert hass.states.get(sensor).state == "regular"  # nothing re-evaluated it yet
    changed = {**payload, "revision": 8}
    mock_studio(aioclient_mock, changed)
    await refresh(hass, loaded_entry)
    state = hass.states.get(sensor)
    assert state.state == "halloween"
    assert state.attributes["source"] == "calendar"


async def test_active_season_refreshes_at_local_midnight(hass, loaded_entry, freezer):
    sensor = "sensor.cinema_studio_active_season"
    assert hass.states.get(sensor).state == "regular"
    midnight = dt_util.start_of_local_day(date(2026, 10, 2))
    freezer.move_to(midnight)
    async_fire_time_changed(hass, midnight)
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get(sensor)
    assert state.state == "halloween"
    assert state.attributes["last_effective_season"] == "halloween"


async def test_active_season_tracks_season_entity(hass, aioclient_mock, payload, media_root):
    write_renders(media_root, payload)
    entry = new_entry(hass, {"season_entity": "input_select.season"})
    mock_studio(aioclient_mock, payload)
    await setup(hass, entry)
    sensor = "sensor.cinema_studio_active_season"
    assert hass.states.get(sensor).attributes["source"] == "default"

    hass.states.async_set("input_select.season", "Halloween")
    await hass.async_block_till_done()
    state = hass.states.get(sensor)
    assert state.state == "halloween"
    assert state.attributes["source"] == "entity"

    hass.states.async_set("input_select.season", "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "regular"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_override_restored_from_last_state(hass, aioclient_mock, payload, media_root):
    write_renders(media_root, payload)
    mock_restore_cache(hass, [State("select.cinema_studio_season_override", "Halloween")])
    entry = new_entry(hass)
    mock_studio(aioclient_mock, payload)
    await setup(hass, entry)
    assert entry.runtime_data.manager.override_season == "halloween"
    assert hass.states.get("select.cinema_studio_season_override").state == "Halloween"
    assert hass.states.get("sensor.cinema_studio_active_season").state == "halloween"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("restored", ["Auto", "Deleted season", STATE_UNKNOWN, STATE_UNAVAILABLE])
async def test_override_not_restored_for_unusable_state(
    hass, aioclient_mock, payload, media_root, restored
):
    write_renders(media_root, payload)
    mock_restore_cache(hass, [State("select.cinema_studio_season_override", restored)])
    entry = new_entry(hass)
    mock_studio(aioclient_mock, payload)
    await setup(hass, entry)
    assert entry.runtime_data.manager.override_season is None
    assert hass.states.get("select.cinema_studio_season_override").state == "Auto"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_override_select_options_follow_catalog(hass, loaded_entry, aioclient_mock, payload):
    override = "select.cinema_studio_season_override"
    sensor = "sensor.cinema_studio_active_season"
    await select_option(hass, override, "Halloween")

    renamed = copy.deepcopy(payload)
    renamed["revision"] = 8
    renamed["seasons"][1]["name"] = "Spooky season"
    mock_studio(aioclient_mock, renamed)
    await refresh(hass, loaded_entry)
    state = hass.states.get(override)
    assert state.state == "Spooky season"  # stored by id, shown by name
    assert state.attributes["options"] == ["Auto", "Regular", "Spooky season"]
    assert hass.states.get(sensor).attributes["name"] == "Spooky season"

    gone = copy.deepcopy(payload)
    gone["revision"] = 9
    gone["seasons"] = gone["seasons"][:1]
    mock_studio(aioclient_mock, gone)
    await refresh(hass, loaded_entry)
    state = hass.states.get(override)
    assert state.state == "Auto"  # the override points at a deleted season
    assert state.attributes["options"] == ["Auto", "Regular"]
    assert hass.states.get(sensor).state == "regular"


async def test_override_select_maps_names_to_ids(hass, loaded_entry, aioclient_mock, payload):
    # A season whose id equals another season's name must not hijack the selection.
    tricky = copy.deepcopy(payload)
    tricky["revision"] = 9
    tricky["seasons"].append({**tricky["seasons"][1], "id": "halloween_name", "name": "halloween"})
    mock_studio(aioclient_mock, tricky)
    await refresh(hass, loaded_entry)
    override = "select.cinema_studio_season_override"
    await select_option(hass, override, "halloween")
    assert loaded_entry.runtime_data.manager.override_season == "halloween_name"
    await select_option(hass, override, "Halloween")
    assert loaded_entry.runtime_data.manager.override_season == "halloween"


def _with_duplicate_season_names(payload):
    twin = copy.deepcopy(payload)
    twin["revision"] = 9
    twin["seasons"].append({**twin["seasons"][1], "id": "halloween_two", "priority": 5})
    return twin


async def test_duplicate_season_names_are_disambiguated(
    hass, loaded_entry, aioclient_mock, payload
):
    mock_studio(aioclient_mock, _with_duplicate_season_names(payload))
    await refresh(hass, loaded_entry)
    override = "select.cinema_studio_season_override"
    assert hass.states.get(override).attributes["options"] == [
        "Auto",
        "Regular",
        "Halloween (halloween)",
        "Halloween (halloween_two)",
    ]
    await select_option(hass, override, "Halloween (halloween_two)")
    assert loaded_entry.runtime_data.manager.override_season == "halloween_two"
    assert hass.states.get(override).state == "Halloween (halloween_two)"
    await select_option(hass, override, "Halloween (halloween)")
    assert loaded_entry.runtime_data.manager.override_season == "halloween"


async def test_override_restores_season_id_with_duplicate_names(
    hass, aioclient_mock, payload, media_root
):
    twin = _with_duplicate_season_names(payload)
    write_renders(media_root, twin)
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("select.cinema_studio_season_override", "Halloween (halloween_two)"),
                {"season_id": "halloween_two"},
            )
        ],
    )
    entry = new_entry(hass)
    mock_studio(aioclient_mock, twin)
    await setup(hass, entry)
    assert entry.runtime_data.manager.override_season == "halloween_two"
    assert hass.states.get("select.cinema_studio_season_override").state == (
        "Halloween (halloween_two)"
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_override_extra_data_round_trips_season_id(hass, loaded_entry):
    select = hass.data["entity_components"]["select"].get_entity(
        "select.cinema_studio_season_override"
    )
    await select_option(hass, "select.cinema_studio_season_override", "Halloween")
    assert select.extra_restore_state_data.as_dict() == {"season_id": "halloween"}
    await select_option(hass, "select.cinema_studio_season_override", "Auto")
    assert select.extra_restore_state_data.as_dict() == {"season_id": None}


async def test_override_not_restored_from_ambiguous_name(hass, aioclient_mock, payload, media_root):
    twin = _with_duplicate_season_names(payload)
    write_renders(media_root, twin)
    mock_restore_cache(hass, [State("select.cinema_studio_season_override", "Halloween")])
    entry = new_entry(hass)
    mock_studio(aioclient_mock, twin)
    await setup(hass, entry)
    assert entry.runtime_data.manager.override_season is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_override_restored_from_unique_name_without_extra_data(
    hass, aioclient_mock, payload, media_root
):
    write_renders(media_root, payload)
    mock_restore_cache_with_extra_data(
        hass,
        [(State("select.cinema_studio_season_override", "Halloween"), {"season_id": "gone"})],
    )
    entry = new_entry(hass)
    mock_studio(aioclient_mock, payload)
    await setup(hass, entry)
    assert entry.runtime_data.manager.override_season == "halloween"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_collection_sensor_before_any_selection(hass, loaded_entry):
    state = hass.states.get("sensor.cinema_studio_regular_last")
    assert state.state == STATE_UNKNOWN
    assert state.attributes["icon"] == "mdi:movie"
    assert state.attributes["collection_id"] == "regular"
    assert state.attributes["available"] == 2  # a, b: c unverified, e disabled, x invalid
    for key in ("clip_id", "render_id", "media_content_id", "duration", "season", "selected_at"):
        assert state.attributes[key] is None
    spooky = hass.states.get("sensor.cinema_studio_spooky_last")
    assert spooky.attributes["icon"] == "mdi:ghost"
    assert spooky.attributes["available"] == 1


async def test_collection_sensor_updates_after_selection(hass, loaded_entry):
    result = await select_clip(hass, collection_id="regular")
    state = hass.states.get("sensor.cinema_studio_regular_last")
    assert state.state == result["title"]
    assert {
        key: state.attributes[key]
        for key in (
            "collection_id",
            "clip_id",
            "render_id",
            "media_content_id",
            "duration",
            "season",
            "selected_at",
            "available",
        )
    } == {
        "collection_id": "regular",
        "clip_id": result["clip_id"],
        "render_id": result["render_id"],
        "media_content_id": result["media_content_id"],
        "duration": 8.0,
        "season": "regular",
        "selected_at": result["selected_at"],
        "available": 2,
    }
    assert state.attributes["selected_at"].endswith("Z")
    assert hass.states.get("sensor.cinema_studio_spooky_last").state == STATE_UNKNOWN
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_dry_run_leaves_collection_sensor_untouched(hass, loaded_entry):
    await select_clip(hass, collection_id="regular", dry_run=True)
    assert hass.states.get("sensor.cinema_studio_regular_last").state == STATE_UNKNOWN


async def test_collection_availability_follows_verification(hass, loaded_entry, media_root):
    regular = "sensor.cinema_studio_regular_last"
    assert hass.states.get(regular).attributes["available"] == 2
    (media_root / "cinema-studio/renders/clip-b/clip-b.mp4").unlink()
    await loaded_entry.runtime_data.manager.async_reverify()
    assert hass.states.get(regular).attributes["available"] == 1
    assert hass.states.get("sensor.cinema_studio_catalog").attributes["unverified"] == 2


async def test_collection_entities_added_and_removed(
    hass, loaded_entry, aioclient_mock, payload, media_root
):
    registry = er.async_get(hass)
    spooky = entity_id(hass, loaded_entry, "sensor", "collection_spooky")
    assert lookup(hass, loaded_entry, "sensor", "collection_kids") is None

    changed = copy.deepcopy(payload)
    changed["revision"] = 8
    changed["seasons"] = changed["seasons"][:1]
    changed["collections"] = [
        changed["collections"][0],
        {**changed["collections"][1], "id": "kids", "name": "Kids", "icon": "mdi:teddy-bear"},
    ]
    changed["clips"] = [c for c in changed["clips"] if c["collection_id"] != "spooky"]
    changed["clips"].append(clip_for(changed["clips"][0], "clip-k", "kids", 4))
    write_renders(media_root, changed)
    mock_studio(aioclient_mock, changed)
    await refresh(hass, loaded_entry)

    kids = entity_id(hass, loaded_entry, "sensor", "collection_kids")
    assert kids == "sensor.cinema_studio_kids_last"
    state = hass.states.get(kids)
    assert state.state == STATE_UNKNOWN
    assert state.name == "Cinema Studio Kids last"
    assert state.attributes["icon"] == "mdi:teddy-bear"
    assert state.attributes["available"] == 1
    assert registry.async_get(kids).device_id is not None
    assert lookup(hass, loaded_entry, "sensor", "collection_spooky") is None
    assert registry.async_get(spooky) is None
    assert hass.states.get(spooky) is None
    assert lookup(hass, loaded_entry, "sensor", "collection_regular") is not None


async def test_collection_rename_updates_friendly_name(hass, loaded_entry, aioclient_mock, payload):
    renamed = copy.deepcopy(payload)
    renamed["revision"] = 8
    renamed["collections"][1].update({"name": "Terror", "icon": "mdi:skull"})
    mock_studio(aioclient_mock, renamed)
    await refresh(hass, loaded_entry)
    state = hass.states.get("sensor.cinema_studio_spooky_last")
    assert state.name == "Cinema Studio Terror last"
    assert state.attributes["icon"] == "mdi:skull"
    # Identity follows the stable collection id, not the (renamable) name.
    registered = er.async_get(hass).async_get("sensor.cinema_studio_spooky_last")
    assert registered is not None
    assert registered.unique_id == f"{loaded_entry.entry_id}_collection_spooky"


async def test_collection_sensor_icon_fallback(hass, loaded_entry, aioclient_mock, payload):
    bare = copy.deepcopy(payload)
    bare["revision"] = 8
    bare["collections"][1]["icon"] = ""
    mock_studio(aioclient_mock, bare)
    await refresh(hass, loaded_entry)
    state = hass.states.get("sensor.cinema_studio_spooky_last")
    assert state.attributes["icon"] == "mdi:movie-open"


async def test_stale_collection_entities_removed_at_setup(
    hass, aioclient_mock, payload, media_root
):
    write_renders(media_root, payload)
    entry = new_entry(hass)
    registry = er.async_get(hass)
    stale = registry.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_collection_gone", config_entry=entry
    )
    mock_studio(aioclient_mock, payload)
    await setup(hass, entry)
    assert registry.async_get(stale.entity_id) is None
    assert lookup(hass, entry, "sensor", "collection_regular") is not None
    assert lookup(hass, entry, "sensor", "active_season") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_catalog_sensor(hass, loaded_entry, aioclient_mock, payload):
    sensor = "sensor.cinema_studio_catalog"
    state = hass.states.get(sensor)
    assert state.state == "7"
    assert {k: state.attributes[k] for k in ("clips", "playable", "unverified", "invalid")} == {
        "clips": 5,
        "playable": 3,  # a, b, d
        "unverified": 1,  # c has no file; disabled e still verifies
        "invalid": 1,  # x
    }
    assert state.attributes["pins"] == 0
    await select_clip(hass, collection_id="regular")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(sensor).attributes["pins"] == 1

    changed = {**payload, "revision": 8}
    mock_studio(aioclient_mock, changed)
    await refresh(hass, loaded_entry)
    assert hass.states.get(sensor).state == "8"


async def test_connectivity_sensor(hass, loaded_entry, aioclient_mock, payload):
    connected = "binary_sensor.cinema_studio_studio_connected"
    registry_entry = er.async_get(hass).async_get(connected)
    assert registry_entry.entity_category is EntityCategory.DIAGNOSTIC
    state = hass.states.get(connected)
    assert state.state == STATE_ON
    assert state.attributes["device_class"] == "connectivity"
    last_sync = loaded_entry.runtime_data.coordinator.data.last_sync.isoformat().replace(
        "+00:00", "Z"
    )
    assert state.attributes["catalog_revision"] == 7
    assert state.attributes["app_version"] == "1.0"
    assert state.attributes["last_sync"] == last_sync

    mock_offline(aioclient_mock)
    await refresh(hass, loaded_entry)
    state = hass.states.get(connected)
    assert state.state == STATE_OFF
    assert state.attributes["catalog_revision"] == 7
    assert state.attributes["last_sync"] == last_sync
    assert state.attributes["app_version"] == "1.0"
    # The cached catalog keeps the selection entities usable while Studio is offline.
    assert hass.states.get("sensor.cinema_studio_regular_last").state != STATE_UNAVAILABLE
    assert (await select_clip(hass, collection_id="spooky"))["clip_id"] == "clip-d"
    await hass.async_block_till_done(wait_background_tasks=True)

    mock_studio(aioclient_mock, payload)
    await refresh(hass, loaded_entry)
    assert hass.states.get(connected).state == STATE_ON


async def test_device_version_updates_after_reconnect(
    hass, aioclient_mock, hass_storage, payload, media_root
):
    write_renders(media_root, payload)
    entry = new_entry(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}.catalog"] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}.catalog",
        "data": {"etag": None, "catalog": payload},
    }
    mock_offline(aioclient_mock)
    await setup(hass, entry)
    assert hass.states.get("binary_sensor.cinema_studio_studio_connected").state == STATE_OFF
    devices = dr.async_get(hass)
    device = devices.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.sw_version is None

    mock_studio(aioclient_mock, payload, version="2.0.1")
    await refresh(hass, entry)
    device = devices.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device.sw_version == "2.0.1"
    assert hass.states.get("binary_sensor.cinema_studio_studio_connected").state == STATE_ON
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unload_detaches_listeners(hass, loaded_entry):
    manager = loaded_entry.runtime_data.manager
    assert manager._listeners
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    assert manager._listeners == []
    entities = er.async_entries_for_config_entry(er.async_get(hass), loaded_entry.entry_id)
    assert len(entities) == 6
    assert {hass.states.get(item.entity_id).state for item in entities} == {STATE_UNAVAILABLE}


async def test_listener_remover_is_idempotent(hass, loaded_entry):
    manager = loaded_entry.runtime_data.manager
    calls = []
    remove = manager.async_add_listener(lambda: calls.append(1))
    remove()
    remove()  # a second removal is ignored
    manager._notify_listeners()
    assert calls == []


async def test_failed_activation_does_not_notify_listeners(hass, loaded_entry):
    manager = loaded_entry.runtime_data.manager
    calls = []
    remove = manager.async_add_listener(lambda: calls.append(1))
    with (
        patch.object(manager._store, "async_save", side_effect=OSError("disk full")),
        pytest.raises(OSError),
    ):
        await manager.async_evaluate_activation()
    assert calls == []
    await manager.async_evaluate_activation()
    assert calls == [1]
    remove()
