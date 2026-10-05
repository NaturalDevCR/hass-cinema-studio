"""Persistent season override selector."""

from collections import Counter
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from . import CinemaStudioConfigEntry
from .entity import CinemaStudioEntity

AUTO = "Auto"


async def async_setup_entry(
    hass: HomeAssistant, entry: CinemaStudioConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([CinemaStudioSeasonOverrideSelect(entry)])


@dataclass
class SeasonOverrideExtraData(ExtraStoredData):
    """The overriding season's id, kept apart from its (renamable, repeatable) display name."""

    season_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"season_id": self.season_id}


# HA's own entity mixins declare these attributes differently.
class CinemaStudioSeasonOverrideSelect(  # pyright: ignore[reportIncompatibleVariableOverride]
    CinemaStudioEntity, RestoreEntity, SelectEntity
):
    """Choose automatic resolution or a catalog season."""

    _attr_translation_key = "season_override"

    def __init__(self, entry: CinemaStudioConfigEntry) -> None:
        super().__init__(entry, "season_override")
        self._update_state()

    @property
    def extra_restore_state_data(self) -> SeasonOverrideExtraData:
        return SeasonOverrideExtraData(self.manager.override_season)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        season_id = await self._restored_season_id()
        if season_id is not None:
            await self.manager.async_set_override(season_id)

    async def _restored_season_id(self) -> str | None:
        seasons = self.coordinator.data.catalog.seasons
        extra = await self.async_get_last_extra_data()
        stored = extra.as_dict().get("season_id") if extra is not None else None
        if isinstance(stored, str) and any(season.id == stored for season in seasons):
            return stored
        last = await self.async_get_last_state()
        if last is None or last.state in (AUTO, STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        # Without a usable stored id, fall back to the label: unambiguous labels only.
        return self._season_id(last.state)

    def _labels(self) -> dict[str, str]:
        """Option label by season id: the name, or "Name (id)" when names repeat."""
        seasons = self.coordinator.data.catalog.seasons
        counts = Counter(season.name for season in seasons)
        return {
            season.id: season.name if counts[season.name] == 1 else f"{season.name} ({season.id})"
            for season in seasons
        }

    def _season_id(self, label: str) -> str | None:
        # Options are labels; resolve to the id so a season whose id equals another
        # season's name can never be picked by mistake.
        return next((sid for sid, text in self._labels().items() if text == label), None)

    @callback
    def _update_state(self) -> None:
        labels = self._labels()
        self._attr_options = [AUTO, *labels.values()]
        override = self.manager.override_season
        self._attr_current_option = labels.get(override, AUTO) if override else AUTO

    async def async_select_option(self, option: str) -> None:
        await self.manager.async_set_override(None if option == AUTO else self._season_id(option))
