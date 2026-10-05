"""Background work behind the app lifespan: discovery, catalog events and cleanup.

Everything here that the lifespan starts as a task never raises: failures are logged and
reflected in ``app.state`` so a slow or absent Supervisor can neither block nor abort startup.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import cast

from fastapi import FastAPI

from .supervisor import SupervisorClient, SupervisorError, describe_error

_LOGGER = logging.getLogger(__name__)

APP_PORT = 8099
CATALOG_EVENT = "cinema_studio_catalog_changed"
CATALOG_NOTIFY_DELAY = 1.0
HOUSEKEEPING_INTERVAL = 600.0
SERVER_WAIT_TIMEOUT = 10.0


async def wait_for_server(
    host: str = "127.0.0.1", port: int = APP_PORT, timeout: float | None = None
) -> bool:
    """Wait until something accepts TCP connections on ``host:port``; False on timeout.

    Uvicorn runs the lifespan startup before it binds its socket, so announcing the App to Home
    Assistant from the lifespan itself would point it at a port nobody listens on yet.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + (SERVER_WAIT_TIMEOUT if timeout is None else timeout)
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), remaining)
        except (OSError, TimeoutError):
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(min(0.2, deadline - loop.time()))
        else:
            writer.close()
            with suppress(OSError, TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), 0.2)
            return True


async def supervisor_startup(app: FastAPI) -> None:
    """Announce the App to Home Assistant once the server accepts connections."""
    if not app.state.supervisor.available:
        return
    try:
        if not await wait_for_server():
            _LOGGER.warning("The HTTP server did not accept connections in time; continuing")
        await publish_discovery(app)
    except Exception:
        _LOGGER.exception("Supervisor startup steps failed")


async def housekeeping(app: FastAPI, interval: float) -> None:
    """Purge abandoned uploads/imports periodically and retry failed discovery."""
    while True:
        await _clean_up(app)
        await asyncio.sleep(interval)
        await _resync(app)


async def _clean_up(app: FastAPI) -> None:
    uploads = getattr(app.state, "uploads", None)
    if uploads is not None:
        try:
            await asyncio.to_thread(uploads.purge_stale)
        except Exception:
            _LOGGER.exception("Upload cleanup failed")
    legacy = getattr(app.state, "legacy", None)
    if legacy is not None:
        try:
            await asyncio.to_thread(legacy.discard_stale)
        except Exception:
            _LOGGER.exception("Legacy import cleanup failed")


async def _resync(app: FastAPI) -> None:
    """Correct what a slow Core or Supervisor boot got wrong at startup."""
    if not app.state.supervisor.available:
        return
    try:
        if app.state.discovery_status["status"] == "failed":
            await publish_discovery(app)
    except Exception:
        _LOGGER.exception("Supervisor refresh failed")


# --- discovery -----------------------------------------------------------------------------


async def publish_discovery(app: FastAPI) -> None:
    """Announce the App and its token to Home Assistant, replacing the previous announcement.

    The outcome lands in ``app.state.discovery_status``; this never raises.
    """
    state = app.state
    async with state.discovery_lock:
        supervisor: SupervisorClient = state.supervisor
        uuid_file: Path = state.paths.data_dir / "discovery_uuid"
        try:
            hostname = (await supervisor.self_info()).get("hostname")
            if not isinstance(hostname, str) or not hostname:
                raise SupervisorError("The Supervisor did not report the App hostname")
            stale = await _delete_previous_discoveries(supervisor, uuid_file)
            uuid = await supervisor.publish_discovery(
                {
                    "host": hostname,
                    "port": APP_PORT,
                    "token": state.tokens.get(),
                    "instance_id": state.instance_id,
                }
            )
        except Exception as exc:
            message = describe_error(exc)
            _LOGGER.warning("Could not publish discovery: %s", message)
            state.discovery_status = {"status": "failed", "message": message}
            return
        state.discovery_status = {"status": "ok", "message": None}
        _remember_discoveries(uuid_file, [*stale, uuid])


async def _delete_previous_discoveries(supervisor: SupervisorClient, uuid_file: Path) -> list[str]:
    """Delete the remembered discoveries; returns the ones that could not be deleted."""
    stale: list[str] = []
    for uuid in _read_discoveries(uuid_file):
        try:
            await supervisor.delete_discovery(uuid)
        except SupervisorError as exc:
            if exc.status == 404:
                continue
            _LOGGER.debug("Previous discovery %s was not removed: %s", uuid, exc)
            stale.append(uuid)
    _remember_discoveries(uuid_file, stale)
    return stale


def _read_discoveries(uuid_file: Path) -> list[str]:
    try:
        saved = uuid_file.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        uuids: object = json.loads(saved)
    except json.JSONDecodeError:
        # Upgrade the original single-uuid file (and interim newline records) on the next write.
        return [line.strip() for line in saved.splitlines() if line.strip()]
    if not isinstance(uuids, list):
        return []
    return [uuid for uuid in cast("list[object]", uuids) if isinstance(uuid, str) and uuid]


def _remember_discoveries(uuid_file: Path, uuids: list[str]) -> None:
    """Persist the discovery uuids to delete next time; bookkeeping errors only warn."""
    try:
        if uuids:
            uuid_file.write_text(json.dumps(list(dict.fromkeys(uuids))) + "\n", encoding="utf-8")
        else:
            uuid_file.unlink(missing_ok=True)
    except OSError as exc:
        _LOGGER.warning("Could not record the discovery uuid: %s", describe_error(exc))


# --- catalog events ------------------------------------------------------------------------


def catalog_sender(supervisor: SupervisorClient) -> Callable[[int], Awaitable[None]]:
    """The notifier callback that tells Home Assistant the catalog moved to a new revision."""

    async def send(revision: int) -> None:
        if not supervisor.available:
            return
        try:
            await supervisor.fire_event(CATALOG_EVENT, {"revision": revision})
        except SupervisorError as exc:
            _LOGGER.warning("Could not announce catalog revision %s: %s", revision, exc)

    return send
