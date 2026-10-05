"""Background work behind the app lifespan: discovery, catalog events and cleanup.

Everything here that the lifespan starts as a task never raises: failures are logged and
reflected in ``app.state`` so a slow or absent Supervisor can neither block nor abort startup.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import cast

from fastapi import FastAPI

from .config import Paths
from .errors import InvalidError
from .repository import Repository
from .storage import TEST_RENDER_DIR, validate_contained_path
from .supervisor import SupervisorClient, SupervisorError, describe_error

_LOGGER = logging.getLogger(__name__)

APP_PORT = 8099
CATALOG_EVENT = "cinema_studio_catalog_changed"
CATALOG_NOTIFY_DELAY = 1.0
HOUSEKEEPING_INTERVAL = 600.0
SERVER_WAIT_TIMEOUT = 10.0
TEST_RENDER_MAX_AGE = 3600.0
ORIGINAL_RETIRE_MAX_AGE = 3600.0
_RETIRED_MARKER = ".retired"
_VERSION_NAME = re.compile(r"v[0-9a-f]{32}")


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
    """Purge abandoned uploads/imports and retired media; retry failed discovery."""
    while True:
        await _clean_up(app)
        await asyncio.sleep(interval)
        await _resync(app)


def purge_test_renders(paths: Paths, max_age: float = TEST_RENDER_MAX_AGE) -> int:
    """Delete test-on-device copies older than ``max_age`` seconds; returns how many went."""
    directory = paths.renders_dir / TEST_RENDER_DIR
    if directory.is_symlink() or not directory.is_dir():
        return 0
    cutoff = time.time() - max_age
    removed = 0
    for path in directory.iterdir():
        try:
            if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError as exc:
            _LOGGER.warning("Could not remove test render %s: %s", path, exc)
    return removed


def retire_original(paths: Paths, clip_id: str, filename: str) -> None:
    """Mark displaced bytes for delayed housekeeping without moving readers' paths."""
    original = paths.originals_dir / clip_id / filename
    directory = paths.originals_dir / clip_id
    try:
        validate_contained_path(original, paths.originals_dir)
        marker = (
            original.parent / _RETIRED_MARKER
            if original.parent != directory
            else directory / f"{_RETIRED_MARKER}-{original.name}"
        )
        validate_contained_path(marker, paths.originals_dir)
        marker.touch()
    except (OSError, InvalidError) as exc:
        _LOGGER.warning("Could not retire original %s: %s", original, exc)


def purge_retired_originals(
    paths: Paths, repo: Repository, max_age: float = ORIGINAL_RETIRE_MAX_AGE
) -> int:
    """Remove marked, unreferenced source versions after a one-hour reader grace period."""
    root = paths.originals_dir
    validate_contained_path(root, paths.media_dir)
    if not root.is_dir():
        return 0
    referenced = {
        root / clip.id / clip.original.filename
        for clip in repo.list_clips()
        if clip.original is not None
    }
    cutoff = time.time() - max_age
    removed = 0
    for directory in root.iterdir():
        try:
            validate_contained_path(directory, root)
            if not directory.is_dir():
                continue
            for candidate in directory.iterdir():
                validate_contained_path(candidate, root)
                version = _VERSION_NAME.fullmatch(candidate.name) is not None
                if version and candidate.is_dir():
                    marker = candidate / _RETIRED_MARKER
                    in_use = any(path.is_relative_to(candidate) for path in referenced)
                    target = candidate
                elif candidate.name.startswith(f"{_RETIRED_MARKER}-"):
                    marker = candidate
                    target = directory / candidate.name.removeprefix(f"{_RETIRED_MARKER}-")
                    validate_contained_path(target, root)
                    in_use = target in referenced
                else:
                    continue
                validate_contained_path(marker, root)
                if in_use or not marker.is_file() or marker.stat().st_mtime >= cutoff:
                    continue
                if version:
                    shutil.rmtree(target)
                else:
                    target.unlink(missing_ok=True)
                    marker.unlink()
                removed += 1
        except (OSError, InvalidError) as exc:
            _LOGGER.warning("Could not clean retired originals in %s: %s", directory, exc)
    return removed


async def _clean_up(app: FastAPI) -> None:
    try:
        await asyncio.to_thread(purge_retired_originals, app.state.paths, app.state.repo)
    except Exception:
        _LOGGER.exception("Retired original cleanup failed")
    try:
        await asyncio.to_thread(purge_test_renders, app.state.paths)
    except Exception:
        _LOGGER.exception("Test render cleanup failed")
    uploads = getattr(app.state, "uploads", None)
    if uploads is not None:
        try:
            await asyncio.to_thread(uploads.purge_stale)
        except Exception:
            _LOGGER.exception("Upload cleanup failed")
    legacy = getattr(app.state, "legacy", None)
    if legacy is not None:
        try:
            await legacy.cleanup_stale()
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
