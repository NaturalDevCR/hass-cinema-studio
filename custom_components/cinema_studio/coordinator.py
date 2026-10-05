"""Poll Studio and retain its last adopted catalog for offline use."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import StudioAuthError, StudioClient, StudioConnectionError
from .catalog import Catalog, parse_catalog
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .manager import CinemaStudioManager

_LOGGER = logging.getLogger(__name__)


@dataclass
class CinemaStudioState:
    catalog: Catalog
    connected: bool
    last_sync: datetime | None
    app_version: str | None


class CinemaStudioCoordinator(DataUpdateCoordinator[CinemaStudioState]):
    """Own catalog cache, ETag, connectivity, and refresh lifecycle."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: StudioClient,
        snapshot_store: Store[dict[str, Any]],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self._client = client
        self._snapshot = snapshot_store
        self._etag: str | None = None
        self.manager: CinemaStudioManager | None = None

    async def async_load_snapshot(self) -> bool:
        """Load a validated raw catalog, without claiming a live connection."""
        stored = await self._snapshot.async_load()
        if stored is None:
            return False
        raw: Any = stored.get("catalog")
        etag: Any = stored.get("etag")
        if not isinstance(raw, dict) or (etag is not None and not isinstance(etag, str)):
            return False
        try:
            catalog = parse_catalog(cast(dict[str, Any], raw))
        except ValueError:
            _LOGGER.debug("Ignoring invalid catalog snapshot")
            return False
        self._etag = etag
        self.data = CinemaStudioState(catalog, connected=False, last_sync=None, app_version=None)
        return True

    async def _async_update_data(self) -> CinemaStudioState:
        previous = cast(CinemaStudioState | None, self.data)
        try:
            health = await self._client.health()
            response = await self._client.catalog(self._etag)
            if response.data is None:
                if previous is None:
                    raise StudioConnectionError("Studio returned 304 without a cached catalog")
                catalog = previous.catalog
            else:
                try:
                    catalog = parse_catalog(response.data)
                except ValueError as err:
                    await _create_invalid_catalog_issue(self.hass, err)
                    raise
                if self.manager is None:
                    raise StudioConnectionError("Catalog manager is not ready")
                await self.manager.async_install_snapshot(
                    catalog,
                    {"etag": response.etag, "catalog": response.data},
                    persist=lambda raw: self._snapshot.async_save(raw),
                )
            self._etag = response.etag
            return CinemaStudioState(catalog, True, dt_util.utcnow(), health["version"])
        except StudioAuthError as err:
            raise ConfigEntryAuthFailed("Studio rejected the API token") from err
        except (StudioConnectionError, ValueError) as err:
            if previous is not None:
                return CinemaStudioState(
                    previous.catalog, False, previous.last_sync, previous.app_version
                )
            raise UpdateFailed("No catalog available from Studio") from err


async def _create_invalid_catalog_issue(hass: HomeAssistant, error: ValueError) -> None:
    """Record malformed catalogs for repair when the issue registry is available."""
    try:
        from homeassistant.helpers import issue_registry as ir

        ir.async_create_issue(
            hass,
            DOMAIN,
            "invalid_catalog",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="invalid_catalog",
            translation_placeholders={"error": str(error)},
        )
    except (ImportError, AttributeError):
        _LOGGER.warning("Studio returned an invalid catalog: %s", error)
