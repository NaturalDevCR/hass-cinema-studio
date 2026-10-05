"""The Cinema Studio integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .api import StudioClient
from .const import CONF_HOST, CONF_PORT, CONF_TOKEN, DOMAIN, EVENT_CATALOG_CHANGED, STORAGE_VERSION
from .coordinator import CinemaStudioCoordinator
from .manager import CinemaStudioManager
from .services import async_register_services

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SELECT, Platform.BINARY_SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]


@dataclass
class CinemaStudioRuntime:
    client: StudioClient
    coordinator: CinemaStudioCoordinator
    manager: CinemaStudioManager


type CinemaStudioConfigEntry = ConfigEntry[CinemaStudioRuntime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CinemaStudioConfigEntry) -> bool:
    client = StudioClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_TOKEN],
        entry.entry_id,
    )
    snapshot = Store[dict[str, Any]](hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.catalog")
    coordinator = CinemaStudioCoordinator(hass, entry, client, snapshot)
    had_snapshot = await coordinator.async_load_snapshot()
    manager = CinemaStudioManager(hass, entry, coordinator, client=client)
    coordinator.manager = manager
    await manager.async_setup()
    await coordinator.async_refresh()
    if isinstance(coordinator.last_exception, ConfigEntryAuthFailed):
        raise coordinator.last_exception
    if not coordinator.last_update_success and not had_snapshot:
        raise ConfigEntryNotReady("Studio is offline and no catalog snapshot is available")
    entry.runtime_data = CinemaStudioRuntime(client, coordinator, manager)

    async def refresh_manager() -> None:
        await manager.async_reverify()
        await manager.async_flush_selections()

    def updated() -> None:
        entry.async_create_background_task(hass, refresh_manager(), "Cinema Studio manager refresh")

    entry.async_on_unload(coordinator.async_add_listener(updated))

    async def async_catalog_changed(event: Event) -> None:
        await coordinator.async_request_refresh()

    entry.async_on_unload(hass.bus.async_listen(EVENT_CATALOG_CHANGED, async_catalog_changed))

    async def async_options_updated(hass: HomeAssistant, entry: CinemaStudioConfigEntry) -> None:
        if entry.options != setup_options:
            await hass.config_entries.async_reload(entry.entry_id)

    setup_options = entry.options
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CinemaStudioConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: CinemaStudioConfigEntry) -> None:
    await Store[dict[str, Any]](
        hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.catalog"
    ).async_remove()
    await Store[dict[str, Any]](
        hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.state"
    ).async_remove()

    # The integration permits one entry; these repair IDs belong to that entry.
    for issue_id in ("consumer_corrupt", "invalid_catalog"):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
