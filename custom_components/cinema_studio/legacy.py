"""Read-only Worker migration; credentials stay inside Home Assistant."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import TYPE_CHECKING, Any, cast

import aiohttp
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import StudioClient, StudioConnectionError
from .const import CONF_HISTORY_RESET_MODE, CONF_HISTORY_RESET_TIME

if TYPE_CHECKING:
    from .manager import CinemaStudioManager

LEGACY_DOMAIN = "cinema_collections"


class LegacyImport:
    """Stage immutable inputs, reconcile fresh clips, then import history."""

    def __init__(
        self, hass: HomeAssistant, manager: CinemaStudioManager, client: StudioClient
    ) -> None:
        self.hass, self.manager, self.client = hass, manager, client
        self._lock = asyncio.Lock()

    async def async_run(self, history_only: bool) -> dict[str, Any]:
        async with self._lock:
            entries = self.hass.config_entries.async_entries(LEGACY_DOMAIN)
            if not entries:
                raise ServiceValidationError("legacy_not_found")
            if len(entries) != 1:
                raise ServiceValidationError("legacy_multiple_entries")
            entry = entries[0]
            base = str(entry.data["endpoint"]).rstrip("/") + "/api/v1"
            headers = {"Authorization": f"Bearer {entry.data['token']}"}
            session = async_get_clientsession(self.hass)

            async def get(path: str) -> Any:
                try:
                    async with session.request(
                        "GET",
                        base + path,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                        allow_redirects=False,
                    ) as response:
                        if response.status != 200:
                            raise StudioConnectionError(
                                f"Legacy Worker returned HTTP {response.status}"
                            )
                        return await response.json()
                except (aiohttp.ClientError, TimeoutError, ValueError):
                    raise StudioConnectionError("Unable to read legacy Worker") from None

            async def records(path: str) -> list[dict[str, Any]]:
                result: list[dict[str, Any]] = []
                page = 1
                while True:
                    payload = cast(dict[str, Any], await get(f"/{path}?page={page}&page_size=100"))
                    items = cast(list[dict[str, Any]], payload["items"])
                    result.extend(items)
                    if len(result) >= payload["total"]:
                        return result
                    if not items:
                        raise StudioConnectionError("Legacy Worker returned incomplete pagination")
                    page += 1

            collections = await records("collections")
            report: dict[str, Any] = {}
            if not history_only:
                status = cast(dict[str, Any], await get("/status"))
                health = cast(dict[str, Any], await get("/health"))
                version = next(
                    (
                        value
                        for value in (
                            health.get("worker_version"),
                            status.get("version"),
                            status.get("worker_version"),
                        )
                        if isinstance(value, str) and value
                    ),
                    "unknown",
                )
                clips = await records("clips")
                profiles = await records("profiles")
                assets = await get("/assets")
                jobs = await records("jobs")
                active = [job["id"] for job in jobs if job["state"] in ("queued", "running")]
                current = status.get("current_job")
                if current and current["id"] not in active:
                    active.append(current["id"])
                roots = {
                    "source": "/media/cinema-collections/source",
                    "compiled": "/media/cinema-collections/compiled",
                }
                for key in roots:
                    value = status.get("roots", {}).get(key)
                    if isinstance(value, str):
                        roots[key] = value
                manifest = {
                    "worker": {
                        "version": version,
                        "queue_depth": status["queue_depth"],
                        "active_job_ids": active,
                    },
                    "roots": roots,
                    "collections": [
                        {
                            key: collection[key]
                            for key in (
                                "id",
                                "name",
                                "playback_mode",
                                "ordered_clip_ids",
                                "processing_profile_id",
                                "enabled",
                            )
                        }
                        for collection in collections
                    ],
                    "profiles": [
                        {key: profile[key] for key in ("id", "name", "settings")}
                        for profile in profiles
                    ],
                    "assets": assets,
                    "seasons": self._seasons({collection["id"] for collection in collections}),
                    "clips": clips,
                }
                staged = await self.client.legacy_stage({"phase": "stage", "manifest": manifest})
                report = await self.client.legacy_commit(
                    {"phase": "commit", "run_id": staged["run_id"], "clips": await records("clips")}
                )
                try:
                    async with asyncio.timeout(60):
                        await self.manager.coordinator.async_request_refresh()
                        while self.manager.catalog_revision < report["catalog_revision"]:
                            await asyncio.sleep(1)
                            await self.manager.coordinator.async_request_refresh()
                except TimeoutError:
                    raise ServiceValidationError("legacy_catalog_timeout") from None

            options = dict(self.manager.entry.options)
            for key, default in (
                (CONF_HISTORY_RESET_MODE, "on_exhaustion"),
                (CONF_HISTORY_RESET_TIME, "00:00"),
            ):
                value = entry.options.get(key, default)
                if value != default:
                    options[key] = value
            data = await Store[dict[str, Any]](
                self.hass, 1, f"{LEGACY_DOMAIN}.{entry.entry_id}.playback_history"
            ).async_load()
            count = await self.manager.async_import_history(
                data or {}, {collection["id"] for collection in collections}
            )
            result = (
                {"history": count} if history_only else {**report, "history_collections": count}
            )
            message = f"Imported history for {count} collections."
            if not history_only:
                message += " " + ", ".join(
                    f"{key}: {len(report[key])}"
                    for key in (
                        "imported",
                        "queued_for_render",
                        "needs_source",
                        "skipped",
                        "missing_assets",
                    )
                )
            persistent_notification.async_create(
                self.hass,
                message,
                title="Cinema Studio legacy import",
                notification_id="cinema_studio_legacy_import",
            )
            # Updating options schedules a reload; persisted state must be ready first.
            if options != dict(self.manager.entry.options):
                self.hass.config_entries.async_update_entry(self.manager.entry, options=options)
            return result

    def _seasons(self, collections: set[str]) -> list[dict[str, Any]]:
        seasons: list[dict[str, Any]] = [
            {
                "id": "regular",
                "name": "Regular",
                "start": None,
                "end": None,
                "priority": 0,
                "collection_id": "regular",
            }
        ]
        for name, priority in (("halloween", 10), ("christmas", 20)):
            start = self.hass.states.get(f"input_datetime.party_{name}_inicio")
            end = self.hass.states.get(f"input_datetime.party_{name}_fin")
            if start is None or end is None:
                continue
            try:
                first, last = date.fromisoformat(start.state), date.fromisoformat(end.state)
            except ValueError:
                continue
            seasons.append(
                {
                    "id": name,
                    "name": name.title(),
                    "start": first.strftime("%m-%d"),
                    "end": last.strftime("%m-%d"),
                    "priority": priority,
                    "collection_id": name if name in collections else "regular",
                }
            )
        return seasons
