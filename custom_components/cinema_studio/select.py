"""Persistent season override selector."""

from homeassistant.components.select import SelectEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import CinemaStudioConfigEntry
from .entity import CinemaStudioEntity

AUTO = "Auto"


async def async_setup_entry(
    hass: HomeAssistant, entry: CinemaStudioConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([CinemaStudioSeasonOverrideSelect(entry)])


# HA's own entity mixins declare these attributes differently.
class CinemaStudioSeasonOverrideSelect(  # pyright: ignore[reportIncompatibleVariableOverride]
    CinemaStudioEntity, RestoreEntity, SelectEntity
):
    """Choose automatic resolution or a named catalog season."""

    _attr_translation_key = "season_override"

    def __init__(self, entry: CinemaStudioConfigEntry) -> None:
        super().__init__(entry, "season_override")
        self._update_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state in (AUTO, STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        season_id = self._season_id(last.state)
        if season_id is not None:
            await self.manager.async_set_override(season_id)

    def _season_id(self, name: str) -> str | None:
        # Options are season names; resolve to the id so a season whose id equals another
        # season's name can never be picked by mistake.
        return next((s.id for s in self.coordinator.data.catalog.seasons if s.name == name), None)

    @callback
    def _update_state(self) -> None:
        self._attr_options = [
            AUTO,
            *(season.name for season in self.coordinator.data.catalog.seasons),
        ]
        override = self.manager.override_season
        season = self.coordinator.data.catalog.find_season(override) if override else None
        self._attr_current_option = season.name if season is not None else AUTO

    async def async_select_option(self, option: str) -> None:
        await self.manager.async_set_override(None if option == AUTO else self._season_id(option))
