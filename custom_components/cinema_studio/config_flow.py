"""User configuration, Supervisor discovery, and Cinema Studio options."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import StudioAuthError, StudioClient, StudioConnectionError
from .const import (
    CONF_HISTORY_RESET_MODE,
    CONF_HISTORY_RESET_TIME,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SEASON_ENTITY,
    CONF_TOKEN,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


class CinemaStudioConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a single Studio instance."""

    VERSION = 1

    def __init__(self) -> None:
        self._pending: dict[str, Any] = {}
        self._addon_name = "Cinema Studio"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> CinemaStudioOptionsFlow:
        return CinemaStudioOptionsFlow()

    async def _health(self, data: Mapping[str, Any]) -> dict[str, Any]:
        client = StudioClient(
            async_get_clientsession(self.hass),
            data[CONF_HOST],
            data[CONF_PORT],
            data[CONF_TOKEN],
            "config-flow",
        )
        return await client.health()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.source == config_entries.SOURCE_USER and self._async_current_entries(
            include_ignore=False
        ):
            return self.async_abort(reason="single_instance_allowed")
        return await self._async_connection_form("user", user_input)

    async def _async_connection_form(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {
                **user_input,
                CONF_HOST: user_input[CONF_HOST].strip(),
                CONF_TOKEN: user_input[CONF_TOKEN].strip(),
            }
            health: dict[str, Any] | None = None
            try:
                if not user_input[CONF_HOST]:
                    errors[CONF_HOST] = "invalid_host"
                else:
                    health = await self._health(user_input)
            except StudioAuthError:
                errors["base"] = "invalid_auth"
            except (StudioConnectionError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                if health is not None:
                    await self.async_set_unique_id(cast(str, health["instance_id"]))
                    if self.source in (
                        config_entries.SOURCE_REAUTH,
                        config_entries.SOURCE_RECONFIGURE,
                    ):
                        self._abort_if_unique_id_mismatch()
                        entry = (
                            self._get_reauth_entry()
                            if self.source == config_entries.SOURCE_REAUTH
                            else self._get_reconfigure_entry()
                        )
                        return self.async_update_reload_and_abort(entry, data_updates=user_input)
                    self._abort_if_unique_id_configured(updates=user_input)
                    if self._async_current_entries(include_ignore=False):
                        return self.async_abort(reason="single_instance_allowed")
                    return self.async_create_entry(title="Cinema Studio", data=user_input)
        defaults = user_input or self._pending
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                    vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=65535)
                    ),
                    vol.Required(CONF_TOKEN): str,
                }
            ),
            errors=errors,
        )

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        config = discovery_info.config
        if (
            not isinstance(config.get("instance_id"), str)
            or not config["instance_id"].strip()
            or not isinstance(config.get(CONF_HOST), str)
            or not config[CONF_HOST].strip()
            or not isinstance(config.get(CONF_TOKEN), str)
            or not config[CONF_TOKEN].strip()
            or type(config.get(CONF_PORT)) is not int
            or not 1 <= config[CONF_PORT] <= 65535
        ):
            return self.async_abort(reason="invalid_discovery_info")
        await self.async_set_unique_id(config["instance_id"])
        data = {key: config[key] for key in (CONF_HOST, CONF_PORT, CONF_TOKEN)}
        if entry := self.hass.config_entries.async_entry_for_domain_unique_id(
            DOMAIN, config["instance_id"]
        ):
            return self.async_update_reload_and_abort(
                entry,
                data_updates=data,
                reason="already_configured",
                reload_even_if_entry_is_unchanged=entry.state is ConfigEntryState.SETUP_RETRY,
            )
        if self._async_current_entries(include_ignore=False):
            return self.async_abort(reason="single_instance_allowed")
        self._pending = data
        self._addon_name = discovery_info.name
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                health = await self._health(self._pending)
            except StudioAuthError:
                return self.async_abort(reason="invalid_auth")
            except (StudioConnectionError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                if health["instance_id"] != self.unique_id:
                    return self.async_abort(reason="cannot_connect")
                self._abort_if_unique_id_configured(updates=self._pending)
                if self._async_current_entries(include_ignore=False):
                    return self.async_abort(reason="single_instance_allowed")
                return self.async_create_entry(title="Cinema Studio", data=self._pending)
        return self.async_show_form(
            step_id="hassio_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"addon": self._addon_name},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._pending = dict(entry_data)
        return await self.async_step_user()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._pending = dict(self._get_reconfigure_entry().data)
        return await self._async_connection_form("reconfigure", user_input)


class CinemaStudioOptionsFlow(config_entries.OptionsFlow):
    """Configure season selection, polling, and history reset behavior."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SEASON_ENTITY,
                        description={"suggested_value": options.get(CONF_SEASON_ENTITY)},
                    ): selector.EntitySelector(  # pyright: ignore[reportUnknownMemberType]
                        selector.EntitySelectorConfig(
                            domain=["sensor", "input_select", "select", "input_text"]
                        )
                    ),  # pyright: ignore[reportUnknownMemberType]
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                    vol.Required(
                        CONF_HISTORY_RESET_MODE,
                        default=options.get(CONF_HISTORY_RESET_MODE, "on_exhaustion"),
                    ): vol.In(["on_exhaustion", "daily"]),
                    vol.Required(
                        CONF_HISTORY_RESET_TIME,
                        default=options.get(CONF_HISTORY_RESET_TIME, "00:00:00"),
                    ): selector.TimeSelector(),  # pyright: ignore[reportUnknownMemberType]
                }
            ),
        )
