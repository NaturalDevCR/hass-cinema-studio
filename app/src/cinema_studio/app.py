"""FastAPI application factory and lifespan."""

from __future__ import annotations

import asyncio
import importlib
import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager, suppress
from functools import partial
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from . import __version__, api_v1, lifecycle
from .auth import TokenStore, require_ingress
from .config import Paths
from .db import Database
from .errors import ConflictError, InvalidError, NotFoundError
from .fence import GarbageCollector, GcFence, GcResult
from .ffmpeg import FfmpegCommandBuilder
from .jobs import JobQueue, render_timeout
from .legacy import LegacyImporter
from .models import ProcessingProfileUpdate, utcnow_iso
from .notifier import CatalogNotifier
from .profiles import validate_settings
from .render import RenderEngine
from .repository import Repository
from .storage import MediaStore, recover
from .supervisor import SupervisorClient
from .uploads import UploadStore

_LOGGER = logging.getLogger(__name__)

# The Ingress UI routers, added by later tasks. Each module exposes a module-level ``router``.
# They are imported by name and skipped while the module does not exist yet; once they all exist
# this list is replaced by plain imports.
_UI_ROUTER_MODULES = ("api_ui_organize", "api_ui_clips")
_NO_SUPERVISOR = "The Supervisor API is not available"
_VALIDATION_LOCATIONS = {"body", "query", "path", "header", "cookie"}

type _ErrorHandler = Callable[[Request, Exception], Awaitable[Response]]


def create_app(
    paths: Paths,
    *,
    supervisor: SupervisorClient | None = None,
    start_background: bool = True,
) -> FastAPI:
    """Build the Studio app.

    The database, token and instance id are prepared here; nothing under the media root is
    touched. With ``start_background`` the lifespan also prepares the media tree, recovers from
    a crash, and runs the render worker, Supervisor integration and periodic cleanup.
    """
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    # The interactive docs would expose the API surface on a LAN-reachable port, so they stay off.
    app = FastAPI(
        title="Cinema Studio",
        version=__version__,
        lifespan=_make_lifespan(start_background),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    db = Database(paths.database_path)
    try:
        # Called after each commit, possibly from worker threads; the notifier exists only while
        # the lifespan runs, so look it up per call instead of capturing it.
        repo = Repository(
            db,
            on_catalog_change=lambda revision: _catalog_changed(app, revision),
            validate_settings=validate_settings,
        )
        _fill_seed_profile_settings(repo)
        store = MediaStore(paths)
        fence = GcFence(paths)
        gc = _RecordingCollector(
            paths, repo, fence, store, on_result=lambda result: _record_gc(app, result)
        )
        engine = RenderEngine(FfmpegCommandBuilder(), timeout_for=render_timeout)
        state = app.state
        state.discovery_lock = asyncio.Lock()
        state.paths = paths
        state.db = db
        state.repo = repo
        state.store = store
        state.engine = engine
        state.fence = fence
        state.gc = gc
        state.gc_last = None  # (GcResult, finished_at) of the latest collection, for the UI
        state.jobs = JobQueue(repo, store, engine, paths, gc)
        state.uploads = UploadStore(paths, lambda: repo.get_settings().max_upload_mb * 1024 * 1024)
        state.tokens = TokenStore(paths.data_dir / "api_token")
        state.supervisor = supervisor if supervisor is not None else SupervisorClient(None)
        state.notifier = None
        state.legacy = LegacyImporter(paths, repo, store, state.jobs)
        state.instance_id = _load_instance_id(paths.data_dir / "instance_id")
        state.discovery_status = {
            "status": "unavailable",
            "message": None if state.supervisor.available else _NO_SUPERVISOR,
        }
        _install_error_handlers(app)
        app.include_router(api_v1.router)
        _include_optional_routers(app)
        _install_ui_shell(app)
    except BaseException:
        db.close()
        raise
    return app


class _RecordingCollector(GarbageCollector):
    """The garbage collector, reporting every finished run (hourly or manual) to the app."""

    def __init__(
        self,
        paths: Paths,
        repo: Repository,
        fence: GcFence,
        store: MediaStore,
        *,
        on_result: Callable[[GcResult], None],
    ) -> None:
        super().__init__(paths, repo, fence, store)
        self._on_result = on_result

    def run(self) -> GcResult:
        result = super().run()
        self._on_result(result)
        return result


def _record_gc(app: FastAPI, result: GcResult) -> None:
    app.state.gc_last = (result, utcnow_iso())


def _fill_seed_profile_settings(repo: Repository) -> None:
    """Give profiles stored with empty settings (the seed) the profile defaults.

    The database seeds the processing profile without settings because the schema layer does not
    know the profile model; the validator expands ``{}`` to the full default profile.
    """
    for record in repo.list_processing_profiles():
        if not record.settings:
            repo.update_processing_profile(record.id, ProcessingProfileUpdate(settings={}))


def _catalog_changed(app: FastAPI, revision: int) -> None:
    notifier: CatalogNotifier | None = app.state.notifier
    if notifier is not None:
        notifier.mark_changed(revision)


def _load_instance_id(path: Path) -> str:
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if existing:
        return existing
    instance_id = uuid.uuid4().hex
    path.write_text(instance_id, encoding="utf-8")
    return instance_id


# --- lifespan ------------------------------------------------------------------------------


def _make_lifespan(
    start_background: bool,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # Callbacks run last-in first-out; each is guarded, so one failure cannot skip the rest.
        async with AsyncExitStack() as stack:
            stack.callback(_close_database, app)
            if start_background:
                await _start_background_services(app, stack)
            yield

    return lifespan


async def _start_background_services(app: FastAPI, stack: AsyncExitStack) -> None:
    """Prepare the media tree, recover, and start the worker, notifier and Supervisor tasks.

    Shutdown order: Supervisor tasks, render worker (which also stops the hourly garbage
    collection), notifier, Supervisor client, database.
    """
    state = app.state
    supervisor: SupervisorClient = state.supervisor
    _on_exit(stack, "close the Supervisor client", supervisor.aclose)

    notifier = CatalogNotifier(
        lifecycle.catalog_sender(supervisor), delay=lifecycle.CATALOG_NOTIFY_DELAY
    )
    state.notifier = notifier

    async def close_notifier() -> None:
        state.notifier = None
        await notifier.close()

    _on_exit(stack, "close the catalog notifier", close_notifier)

    state.store.ensure_dirs()
    counts = await asyncio.to_thread(recover, state.store, state.repo)
    _LOGGER.debug("Startup recovery: %s", counts)

    _on_exit(stack, "stop the render worker", state.jobs.stop)
    await state.jobs.start()

    # The Supervisor steps must neither delay startup nor announce an unbound port, so they run
    # beside the server instead of inside the lifespan.
    _run_task(stack, "supervisor-startup", lifecycle.supervisor_startup(app))
    _run_task(stack, "housekeeping", lifecycle.housekeeping(app, lifecycle.HOUSEKEEPING_INTERVAL))


def _run_task(stack: AsyncExitStack, name: str, work: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(work, name=f"cinema-studio-{name}")
    _on_exit(stack, f"stop the {name} task", partial(_cancel, task))


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def _on_exit(stack: AsyncExitStack, what: str, callback: Callable[[], Awaitable[None]]) -> None:
    async def guarded() -> None:
        try:
            await callback()
        except Exception:
            _LOGGER.exception("Could not %s", what)

    stack.push_async_callback(guarded)


def _close_database(app: FastAPI) -> None:
    try:
        app.state.db.close()
    except Exception:
        _LOGGER.exception("Could not close the database")


# --- errors --------------------------------------------------------------------------------


def _install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, _status_handler(404))
    app.add_exception_handler(ConflictError, _status_handler(409))
    app.add_exception_handler(InvalidError, _status_handler(422))
    app.add_exception_handler(RequestValidationError, _validation_handler)


def _status_handler(status_code: int) -> _ErrorHandler:
    async def handler(_request: Request, exc: Exception) -> Response:
        return JSONResponse({"detail": str(exc)}, status_code=status_code)

    return handler


async def _validation_handler(_request: Request, exc: Exception) -> Response:
    """Answer 422 with the contract's ``{"detail": "<string>"}`` instead of FastAPI's list."""
    errors: Sequence[Any] = ()
    if isinstance(exc, RequestValidationError):
        errors = exc.errors()
    parts = [f"{_field(error['loc'])}: {_message(error['msg'])}" for error in errors]
    return JSONResponse({"detail": "; ".join(parts) or "Invalid request"}, status_code=422)


def _field(loc: tuple[int | str, ...]) -> str:
    """``("body", "events", 0, "clip_id")`` becomes ``events.0.clip_id``."""
    parts = list(loc[1:] if loc and loc[0] in _VALIDATION_LOCATIONS else loc)
    if not parts or isinstance(parts[0], int):
        return "body"
    return ".".join(str(part) for part in parts)


def _message(message: str) -> str:
    return message.removeprefix("Value error, ")


# --- routers and UI shell ------------------------------------------------------------------


def _include_optional_routers(app: FastAPI) -> None:
    """Add the Ingress UI routers that exist; each is guarded by ``require_ingress``."""
    package = __package__ or "cinema_studio"
    included: list[str] = []
    for name in _UI_ROUTER_MODULES:
        qualified = f"{package}.{name}"
        try:
            module = importlib.import_module(qualified)
        except ModuleNotFoundError as exc:
            if exc.name != qualified:
                raise  # the router exists but one of its own imports is broken
            continue
        app.include_router(module.router, dependencies=[Depends(require_ingress)])
        included.append(name)
    _LOGGER.debug("UI routers included: %s", ", ".join(included) or "none")


def _install_ui_shell(app: FastAPI) -> None:
    @app.get("/", dependencies=[Depends(require_ingress)], include_in_schema=False)
    async def index(request: Request) -> Response:
        page: Path = request.app.state.paths.static_dir / "index.html"
        if not page.is_file():
            return PlainTextResponse("UI not built", status_code=503)
        return FileResponse(page, headers={"Cache-Control": "no-cache"})

    @app.get(
        "/assets/{asset_path:path}",
        dependencies=[Depends(require_ingress)],
        include_in_schema=False,
    )
    async def asset(asset_path: str, request: Request) -> Response:
        root = (request.app.state.paths.static_dir / "assets").resolve()
        try:
            target = (root / asset_path).resolve()
        except (OSError, ValueError):
            raise HTTPException(status_code=404, detail="Not Found") from None
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(target)
