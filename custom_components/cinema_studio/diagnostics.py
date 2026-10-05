"""Redacted configuration and compact cached runtime diagnostics."""

from typing import Any

# HA's Mapping overload is unparameterized.
from homeassistant.components.diagnostics import (
    async_redact_data,  # pyright: ignore[reportUnknownVariableType]
)
from homeassistant.core import HomeAssistant

from . import CinemaStudioConfigEntry
from .const import CONF_TOKEN

REDACTED_KEYS = {CONF_TOKEN, "token", "api_token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CinemaStudioConfigEntry
) -> dict[str, Any]:
    """Summarize runtime state without clip titles, paths or credentials."""
    state = entry.runtime_data.coordinator.data
    catalog = state.catalog
    return {
        "entry_data": async_redact_data(dict(entry.data), REDACTED_KEYS),
        "options": async_redact_data(dict(entry.options), REDACTED_KEYS),
        "catalog": {
            "revision": catalog.revision,
            "seasons": len(catalog.seasons),
            "collections": len(catalog.collections),
            "clips": len(catalog.clips),
            "invalid_clips": len(catalog.invalid_clip_ids),
        },
        **entry.runtime_data.manager.diagnostics(),
        "connected": state.connected,
    }
