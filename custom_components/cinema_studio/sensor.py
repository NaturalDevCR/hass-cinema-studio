"""Active season, per-collection last clip and the catalog summary."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CinemaStudioConfigEntry
from .catalog import CollectionDef
from .const import DOMAIN
from .entity import CinemaStudioEntity

COLLECTION_ID_PREFIX = "collection_"


async def async_setup_entry(
    hass: HomeAssistant, entry: CinemaStudioConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Keep collection entities aligned with the catalog."""
    coordinator = entry.runtime_data.coordinator
    collections: dict[str, CinemaStudioCollectionSensor] = {}
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_{COLLECTION_ID_PREFIX}"

    @callback
    def sync_collections() -> None:
        current = {item.id: item for item in coordinator.data.catalog.collections}
        for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
            if (
                registered.domain == "sensor"
                and registered.platform == DOMAIN
                and registered.unique_id.startswith(prefix)
                and registered.unique_id[len(prefix) :] not in current
            ):
                registry.async_remove(registered.entity_id)
        for collection_id in collections.keys() - current.keys():
            del collections[collection_id]
        added: list[CinemaStudioCollectionSensor] = []
        for collection_id, collection in current.items():
            if collection_id not in collections:
                sensor = CinemaStudioCollectionSensor(entry, collection)
                collections[collection_id] = sensor
                added.append(sensor)
        if added:
            async_add_entities(added)

    async_add_entities([CinemaStudioActiveSeasonSensor(entry), CinemaStudioCatalogSensor(entry)])
    sync_collections()
    entry.async_on_unload(coordinator.async_add_listener(sync_collections))


class CinemaStudioActiveSeasonSensor(CinemaStudioEntity, SensorEntity):
    """The active season and how it was chosen."""

    _attr_translation_key = "active_season"

    def __init__(self, entry: CinemaStudioConfigEntry) -> None:
        super().__init__(entry, "active_season")
        self._update_state()

    @callback
    def _update_state(self) -> None:
        season_id, source = self.manager.active_season()
        season = self.coordinator.data.catalog.find_season(season_id)
        self._attr_native_value = season_id
        self._attr_extra_state_attributes = {
            "name": season.name if season else season_id,
            "source": source,
            "collection_id": season.collection_id if season else None,
            "last_effective_season": self.manager.last_effective_season,
            "color": season.color if season else None,
        }


class CinemaStudioCollectionSensor(CinemaStudioEntity, SensorEntity):
    """The collection's last selected clip, with its current playable clip count."""

    def __init__(self, entry: CinemaStudioConfigEntry, collection: CollectionDef) -> None:
        super().__init__(entry, f"{COLLECTION_ID_PREFIX}{collection.id}")
        self.collection = collection
        self._update_state()

    @callback
    def _update_state(self) -> None:
        collection = self.coordinator.data.catalog.find_collection(self.collection.id)
        if collection is not None:
            self.collection = collection
        self._attr_name = f"{self.collection.name} last"
        self._attr_icon = self.collection.icon or "mdi:movie-open"
        last = self.manager.last_selection(self.collection.id) or {}
        title = last.get("title")
        self._attr_native_value = str(title) if title is not None else None
        self._attr_extra_state_attributes = {
            "collection_id": self.collection.id,
            **{
                key: last.get(key)
                for key in (
                    "clip_id",
                    "render_id",
                    "media_content_id",
                    "duration",
                    "season",
                    "selected_at",
                )
            },
            "available": self.manager.playable_count(self.collection.id),
        }


class CinemaStudioCatalogSensor(CinemaStudioEntity, SensorEntity):
    """The catalog revision, with clip verification counts."""

    _attr_translation_key = "catalog"

    def __init__(self, entry: CinemaStudioConfigEntry) -> None:
        super().__init__(entry, "catalog")
        self._update_state()

    @callback
    def _update_state(self) -> None:
        self._attr_native_value = self.manager.catalog_revision
        self._attr_extra_state_attributes = {
            **self.manager.clip_counts(),
            "pins": len(self.manager.active_pins()),
        }
