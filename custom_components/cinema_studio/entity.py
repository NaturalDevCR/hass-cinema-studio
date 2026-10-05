"""Shared cached entity lifecycle and Cinema Studio device metadata."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import BaseCoordinatorEntity

from . import CinemaStudioConfigEntry
from .const import DOMAIN
from .coordinator import CinemaStudioCoordinator


class CinemaStudioEntity(BaseCoordinatorEntity[CinemaStudioCoordinator]):
    """Expose cached data, including while Studio is disconnected."""

    _attr_has_entity_name = True

    def __init__(self, entry: CinemaStudioConfigEntry, suffix: str) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self.entry = entry
        self.manager = entry.runtime_data.manager
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Cinema Studio",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=self.coordinator.data.app_version,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._update_state()
        self.async_on_remove(self.manager.async_add_listener(self.async_refresh_state))

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh the shared device version as well as entity state."""
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.entry.entry_id)})
        version = self.coordinator.data.app_version
        if device is not None and device.sw_version != version:
            registry.async_update_device(device.id, sw_version=version)
        self.async_refresh_state()

    @callback
    def async_refresh_state(self) -> None:
        """Refresh HA attribute caches before writing a new state."""
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _update_state(self) -> None:
        """Populate platform-specific state attributes from the runtime."""
        raise NotImplementedError

    async def async_update(self) -> None:
        if self.enabled:
            await self.coordinator.async_request_refresh()
