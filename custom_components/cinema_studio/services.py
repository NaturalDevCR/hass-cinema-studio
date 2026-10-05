"""Home Assistant actions resolved against the current loaded runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

if TYPE_CHECKING:
    from . import CinemaStudioConfigEntry


def _entry(hass: HomeAssistant) -> CinemaStudioConfigEntry:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return cast("CinemaStudioConfigEntry", entry)
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_ready")


async def async_register_services(hass: HomeAssistant) -> None:
    """Register actions once, including the Task 15 legacy delegation boundary."""

    async def select(call: ServiceCall) -> ServiceResponse:
        result = await _entry(hass).runtime_data.manager.async_select(
            collection_ref=call.data.get("collection_id"),
            season_ref=call.data.get("season"),
            dry_run=call.data["dry_run"],
        )
        return result if call.return_response else None

    async def reset(call: ServiceCall) -> None:
        await _entry(hass).runtime_data.manager.async_reset(call.data.get("collection_id"))

    async def refresh(call: ServiceCall) -> None:
        await _entry(hass).runtime_data.coordinator.async_request_refresh()

    async def legacy(call: ServiceCall) -> None:
        manager = _entry(hass).runtime_data.manager
        if not hasattr(manager, "legacy"):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_ready")
        await manager.legacy.async_run(call.data["history_only"])

    registrations = (
        (
            "select_next_clip",
            select,
            vol.Schema(
                {
                    vol.Optional("collection_id"): cv.string,
                    vol.Optional("season"): cv.string,
                    vol.Optional("dry_run", default=False): cv.boolean,
                }
            ),
            SupportsResponse.OPTIONAL,
        ),
        (
            "reset_history",
            reset,
            vol.Schema({vol.Optional("collection_id"): cv.string}),
            SupportsResponse.NONE,
        ),
        ("refresh", refresh, vol.Schema({}), SupportsResponse.NONE),
        (
            "import_legacy",
            legacy,
            vol.Schema({vol.Optional("history_only", default=False): cv.boolean}),
            SupportsResponse.NONE,
        ),
    )
    for name, handler, schema, response in registrations:
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(
                DOMAIN, name, handler, schema=schema, supports_response=response
            )
