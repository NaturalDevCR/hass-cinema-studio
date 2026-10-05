"""Studio connection status, independent of cached catalog availability."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CinemaStudioConfigEntry
from .entity import CinemaStudioEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: CinemaStudioConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([CinemaStudioConnectedBinarySensor(entry)])


class CinemaStudioConnectedBinarySensor(CinemaStudioEntity, BinarySensorEntity):
    """Report whether the last Studio refresh succeeded."""

    _attr_translation_key = "studio_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: CinemaStudioConfigEntry) -> None:
        super().__init__(entry, "studio_connected")
        self._update_state()

    @callback
    def _update_state(self) -> None:
        state = self.coordinator.data
        self._attr_is_on = state.connected
        self._attr_extra_state_attributes = {
            "catalog_revision": state.catalog.revision,
            "last_sync": state.last_sync.isoformat().replace("+00:00", "Z")
            if state.last_sync
            else None,
            "app_version": state.app_version,
        }
