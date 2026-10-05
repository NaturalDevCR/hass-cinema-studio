"""Offline selection with durable history and garbage collection fences."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime, time, timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .activation import ActivationState, evaluate_activation
from .api import StudioClient, StudioConnectionError, StudioRequestError
from .catalog import EMPTY_CATALOG, Catalog, CollectionDef
from .const import (
    CONF_HISTORY_RESET_MODE,
    CONF_HISTORY_RESET_TIME,
    CONF_SEASON_ENTITY,
    DOMAIN,
    EVENT_SELECTED,
    PIN_TTL,
    STORAGE_VERSION,
)
from .fence import (
    ConsumerFence,
    FenceCorrupt,
    FenceTimeout,
    FenceWriteResult,
    _iso,  # pyright: ignore[reportPrivateUsage]
)
from .history import HistoryState, order_candidates
from .seasons import UnknownSeasonError, resolve_effective_season
from .verify import verify_all, verify_render

if TYPE_CHECKING:
    from . import CinemaStudioConfigEntry
    from .coordinator import CinemaStudioCoordinator

_LOGGER = logging.getLogger(__name__)


class LegacyRunner(Protocol):
    async def async_run(self, history_only: bool) -> Any: ...


def _error(key: str) -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key=key)


class CinemaStudioManager:
    """Serialize catalog adoption, verification, selection, and persistence."""

    legacy: LegacyRunner

    def __init__(
        self,
        hass: HomeAssistant,
        entry: CinemaStudioConfigEntry,
        coordinator: CinemaStudioCoordinator,
        *,
        client: StudioClient,
        rng: random.Random | None = None,
        now: Callable[[], datetime] = dt_util.utcnow,
    ) -> None:
        self.hass, self.entry, self.coordinator = hass, entry, coordinator
        self._client = client
        self._rng, self._now = rng or random.Random(), now
        self._lock = asyncio.Lock()
        self._flush_lock = asyncio.Lock()
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.state"
        )
        self._media_root = Path(hass.config.media_dirs.get("local", "/media"))
        self._fence = ConsumerFence(self._media_root, entry.entry_id, uuid4().hex)
        self._catalog = EMPTY_CATALOG
        self._held: frozenset[str] = frozenset()
        self._verified: dict[str, bool] = {}
        self._pins: dict[str, datetime] = {}
        self._history = HistoryState()
        self._activation = ActivationState(None, None)
        self._selection_queue: list[dict[str, Any]] = []
        self._last: dict[str, dict[str, Any]] = {}
        self._ready = False
        self._listeners_registered = False
        self.override_season: str | None = None

    @property
    def ready(self) -> bool:
        return self._ready

    def _reset_time(self) -> time:
        return time.fromisoformat(self.entry.options.get(CONF_HISTORY_RESET_TIME, "00:00:00"))

    def _state(self) -> dict[str, Any]:
        return {
            "history": self._history.to_dict(),
            "pins": {key: _iso(value) for key, value in self._pins.items()},
            "activation": asdict(self._activation),
            "selection_queue": [dict(event) for event in self._selection_queue],
        }

    async def _write_fence(
        self,
        revision: int,
        held: frozenset[str],
        *,
        new_pins: dict[str, datetime] | None = None,
        before_write: Callable[[], bool] | None = None,
    ) -> FenceWriteResult:
        return await self.hass.async_add_executor_job(
            partial(
                self._fence.write,
                held_revision=revision,
                held_render_ids=held,
                new_pins=new_pins or {},
                persisted_pins=self._pins,
                now=self._now(),
                before_write=before_write,
            )
        )

    def _corrupt(self) -> None:
        self._ready = False
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            "consumer_corrupt",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="consumer_corrupt",
        )

    async def async_setup(self) -> None:
        async with self._lock:
            self._ready = False
            data = await self._store.async_load() or {}
            self._history = HistoryState(data.get("history"))
            self._pins = {
                key: datetime.fromisoformat(value) for key, value in data.get("pins", {}).items()
            }
            activation = data.get("activation", {})
            self._activation = ActivationState(
                activation.get("last_effective_season"), activation.get("last_effective_collection")
            )
            self._selection_queue = data.get("selection_queue", [])
            if self._cap_queue():
                await self._store.async_save(self._state())
            from .coordinator import CinemaStudioState

            state = cast(CinemaStudioState | None, self.coordinator.data)
            if state is not None:
                self._catalog = state.catalog
            self._held = self._catalog.render_ids()
            try:
                result = await self._write_fence(self._catalog.revision, self._held)
                self._pins = result.pins
                self._verified = await self.hass.async_add_executor_job(
                    verify_all, self._media_root, [clip.render for clip in self._catalog.clips]
                )
            except FenceCorrupt as err:
                self._corrupt()
                raise ConfigEntryNotReady("Consumer file is corrupt") from err
            except (FenceTimeout, OSError) as err:
                raise ConfigEntryNotReady("Consumer fence is unavailable") from err
            self._ready = True
            ir.async_delete_issue(self.hass, DOMAIN, "consumer_corrupt")
        if not self._listeners_registered:

            async def changed(event: object) -> None:
                await self.async_evaluate_activation()

            self.entry.async_on_unload(
                async_track_time_change(self.hass, changed, hour=0, minute=0, second=0)
            )
            entity = self.entry.options.get(CONF_SEASON_ENTITY)
            if entity:
                self.entry.async_on_unload(
                    async_track_state_change_event(self.hass, [entity], changed)
                )

            async def reverify(event: datetime) -> None:
                await self.async_reverify()

            self.entry.async_on_unload(
                async_track_time_interval(self.hass, reverify, timedelta(minutes=5))
            )
            self._listeners_registered = True
        self.hass.async_create_task(self.async_flush_selections())

    async def async_install_snapshot(
        self,
        catalog: Catalog,
        raw: dict[str, Any],
        persist: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        async with self._lock:
            held = self._held | catalog.render_ids()
            try:
                await self._write_fence(self._catalog.revision, held)
            except FenceCorrupt:
                self._corrupt()
                raise
            self._held = held
            verified = await self.hass.async_add_executor_job(
                verify_all, self._media_root, [clip.render for clip in catalog.clips]
            )
            await persist(raw)
            self._catalog, self._verified = catalog, verified
            self._ready = True
            ir.async_delete_issue(self.hass, DOMAIN, "consumer_corrupt")
            try:
                result = await self._write_fence(catalog.revision, catalog.render_ids())
                self._held, self._pins = catalog.render_ids(), result.pins
            except Exception as err:
                if isinstance(err, FenceCorrupt):
                    self._corrupt()
                _LOGGER.warning(
                    "Final snapshot fence failed; retaining safe superset", exc_info=True
                )

    def _resolve(self, season_ref: str | None) -> tuple[str, str]:
        entity_id = self.entry.options.get(CONF_SEASON_ENTITY)
        state = self.hass.states.get(entity_id) if entity_id else None
        try:
            return resolve_effective_season(
                self._catalog,
                dt_util.as_local(self._now()).date(),
                action_season=season_ref,
                override=self.override_season,
                entity_state=state.state if state else None,
            )
        except UnknownSeasonError as err:
            raise _error("unknown_season") from err

    def _candidates(self, collection: CollectionDef | None) -> list[str]:
        if collection is None or not collection.enabled:
            return []
        return order_candidates(
            [
                clip
                for clip in self._catalog.clips
                if clip.enabled and self._verified.get(clip.render.id)
            ],
            collection,
        )

    def _collection(self, season: str) -> tuple[CollectionDef | None, list[str], bool]:
        definition = self._catalog.find_season(season)
        collection = self._catalog.find_collection(definition.collection_id) if definition else None
        candidates = self._candidates(collection)
        if candidates:
            return collection, candidates, False
        regular = self._catalog.find_season("regular")
        collection = self._catalog.find_collection(regular.collection_id) if regular else None
        return collection, self._candidates(collection), True

    def _activate(self, season: str, collection: CollectionDef, fallback: bool) -> bool:
        self._activation, reset = evaluate_activation(
            self._activation, season_id=season, collection_id=collection.id, fallback=fallback
        )
        if reset is not None:
            self._history.reset(reset, dt_util.as_local(self._now()), reset_time=self._reset_time())
        return reset is not None

    async def async_evaluate_activation(self) -> None:
        async with self._lock:
            if not self.ready:
                return
            season, _ = self._resolve(None)
            collection, candidates, fallback = self._collection(season)
            if collection is not None and candidates:
                self._activate(season, collection, fallback)
                await self._store.async_save(self._state())

    async def async_set_override(self, season_id: str | None) -> None:
        async with self._lock:
            if season_id is not None and self._catalog.find_season(season_id) is None:
                raise _error("unknown_season")
            self.override_season = season_id
        await self.async_evaluate_activation()

    async def async_select(
        self,
        *,
        collection_ref: str | None,
        season_ref: str | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        async with self._lock:
            if not self.ready:
                raise _error("not_ready")
            season, source = self._resolve(season_ref)
            requested = season
            if collection_ref is not None:
                collection = self._catalog.find_collection(collection_ref)
                if collection is None:
                    raise _error("unknown_collection")
                candidates, fallback = self._candidates(collection), False
            else:
                collection, candidates, fallback = self._collection(season)
                if fallback:
                    season = "regular"
            if collection is None or not candidates:
                raise _error("no_playable_clip")
            previous_history, previous_activation = self._history.to_dict(), self._activation
            activation_reset = False
            if not dry_run and season_ref is None and collection_ref is None:
                activation_reset = self._activate(requested, collection, fallback)
            try:
                while candidates:
                    clip_id, _, history_reset, record = self._history.pick(
                        collection.id,
                        candidates,
                        collection.playback_mode,
                        self._rng,
                        now=dt_util.as_local(self._now()),
                        reset_mode=self.entry.options.get(CONF_HISTORY_RESET_MODE, "on_exhaustion"),
                        reset_time=self._reset_time(),
                    )
                    if clip_id is None or record is None:
                        break
                    clip = next(clip for clip in self._catalog.clips if clip.id == clip_id)
                    render, timestamp = clip.render, self._now()
                    try:
                        result = await self._write_fence(
                            self._catalog.revision,
                            self._held,
                            new_pins={} if dry_run else {render.id: timestamp + PIN_TTL},
                            before_write=partial(verify_render, self._media_root, render),
                        )
                    except OSError as err:
                        _LOGGER.warning("Selection fence failed", exc_info=True)
                        raise _error("not_ready") from err
                    if not result.written:
                        self._verified[render.id] = False
                        candidates.remove(clip_id)
                        continue
                    timing = render.timing
                    response: dict[str, Any] = {
                        "contract_version": 1,
                        "instance_id": self._catalog.instance_id,
                        "catalog_revision": self._catalog.revision,
                        "selection_id": uuid4().hex,
                        "selected_at": _iso(timestamp),
                        "collection_id": collection.id,
                        "season": season,
                        "requested_season": requested,
                        "season_source": source,
                        "season_fallback": fallback,
                        "playback_mode": collection.playback_mode,
                        "history_reset": history_reset,
                        "activation_reset": activation_reset,
                        "clip_id": clip.id,
                        "title": clip.title,
                        "source_name": clip.source_name,
                        "render_id": render.id,
                        "render_n": render.n,
                        "relative_output_path": render.relative_path,
                        "media_content_id": "media-source://media_source/local/"
                        + render.relative_path,
                        "media_content_type": "video",
                        "duration_seconds": timing.duration,
                        "duration": timing.duration,
                        "content_duration": timing.content_duration,
                        "lead_in_duration": timing.lead_in,
                        "tail_out_duration": timing.tail_out,
                        "content_start_offset": timing.content_start,
                        "content_end_offset": timing.content_end,
                        "timing_source": render.timing_source,
                        "timing_verified": True,
                        "file_verified": True,
                        "render_pending": clip.render_pending,
                        "output_is_stale": clip.render_pending,
                        "size": render.size,
                        "sha256": render.sha256,
                        "profile_fingerprint": render.profile_fingerprint,
                    }
                    if not dry_run:
                        self._pins = result.pins
                        self._history.commit(collection.id, record)
                        event = {
                            key: response[key]
                            for key in (
                                "selection_id",
                                "clip_id",
                                "render_id",
                                "catalog_revision",
                                "selected_at",
                            )
                        }
                        previous_queue = list(self._selection_queue)
                        self._selection_queue.append(event)
                        self._cap_queue()
                        try:
                            await self._store.async_save(self._state())
                        except Exception:
                            self._selection_queue = previous_queue
                            raise
                        self._last[collection.id] = dict(response)
                        self.hass.async_create_task(self.async_flush_selections())
                        self.hass.bus.async_fire(EVENT_SELECTED, dict(response))
                    return dict(response)
                raise _error("no_playable_clip")
            except FenceTimeout as err:
                self._history, self._activation = (
                    HistoryState(previous_history),
                    previous_activation,
                )
                raise _error("not_ready") from err
            except FenceCorrupt as err:
                self._corrupt()
                self._history, self._activation = (
                    HistoryState(previous_history),
                    previous_activation,
                )
                raise _error("not_ready") from err
            except Exception:
                self._history, self._activation = (
                    HistoryState(previous_history),
                    previous_activation,
                )
                raise

    async def async_reset(self, collection_ref: str | None) -> list[str]:
        async with self._lock:
            if not self.ready:
                raise _error("not_ready")
            collection = self._catalog.find_collection(collection_ref) if collection_ref else None
            if collection_ref is not None and collection is None:
                raise _error("unknown_collection")
            cleared = self._history.reset(
                collection.id if collection else None,
                dt_util.as_local(self._now()),
                reset_time=self._reset_time(),
            )
            await self._store.async_save(self._state())
            return cleared

    def last_selection(self, collection_id: str) -> dict[str, Any] | None:
        response = self._last.get(collection_id)
        return dict(response) if response else None

    def _cap_queue(self) -> bool:
        excess = len(self._selection_queue) - 2000
        if excess <= 0:
            return False
        del self._selection_queue[:excess]
        _LOGGER.warning("Selection queue limit exceeded; dropping %s oldest events", excess)
        return True

    async def async_reverify(self) -> None:
        """Recover transient verification failures without a new catalog revision."""
        async with self._lock:
            try:
                result = await self._write_fence(self._catalog.revision, self._held)
                verified = await self.hass.async_add_executor_job(
                    verify_all, self._media_root, [clip.render for clip in self._catalog.clips]
                )
            except FenceCorrupt:
                self._corrupt()
                return
            except (FenceTimeout, OSError):
                self._ready = False
                _LOGGER.warning("Render re-verification fence failed", exc_info=True)
                return
            self._verified, self._pins = verified, result.pins
            self._ready = True
            ir.async_delete_issue(self.hass, DOMAIN, "consumer_corrupt")

    async def async_flush_selections(self) -> None:
        async with self._flush_lock:
            while True:
                async with self._lock:
                    events = [dict(event) for event in self._selection_queue[:500]]
                if not events:
                    return
                try:
                    await self._client.post_selections(events)
                except StudioRequestError as err:
                    _LOGGER.warning(
                        "Selection events rejected (HTTP %s); dropping batch", err.status
                    )
                except (StudioConnectionError, ConnectionError):
                    return
                async with self._lock:
                    previous = self._selection_queue
                    sent = {event["selection_id"] for event in events}
                    self._selection_queue = [
                        event for event in previous if event["selection_id"] not in sent
                    ]
                    try:
                        await self._store.async_save(self._state())
                    except Exception:
                        self._selection_queue = previous
                        _LOGGER.debug(
                            "Selection queue save failed; retaining events", exc_info=True
                        )
                        return
