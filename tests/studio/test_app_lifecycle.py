"""Background services started by the app lifespan: startup, discovery, events, cleanup."""

import asyncio
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import cinema_studio.lifecycle as lifecycle
from cinema_studio.app import create_app
from cinema_studio.config import Paths
from cinema_studio.models import CollectionCreate, Recipe
from cinema_studio.supervisor import SupervisorClient

pytestmark = pytest.mark.studio

HOSTNAME = "local-cinema-studio"
REAL_WAIT_FOR_SERVER = lifecycle.wait_for_server
EVENT = ("POST", "/core/api/events/cinema_studio_catalog_changed")

Routes = dict[tuple[str, str], httpx.Response | Exception]


@dataclass
class FakeSupervisor:
    """A Supervisor stand-in that records requests and answers from a mutable route table."""

    routes: Routes = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)

    def __post_init__(self) -> None:
        defaults: Routes = {
            ("GET", "/addons/self/info"): httpx.Response(
                200, json={"data": {"hostname": HOSTNAME}}
            ),
            ("POST", "/discovery"): httpx.Response(200, json={"data": {"uuid": "uuid-new"}}),
            EVENT: httpx.Response(200, json={"message": "fired"}),
        }
        self.routes = {**defaults, **self.routes}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        result = self.routes.get((request.method, request.url.path))
        if result is None:
            return httpx.Response(404, json={"result": "error", "message": "not routed"})
        if isinstance(result, Exception):
            raise result
        return result

    def client(self) -> SupervisorClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handle))
        return SupervisorClient("sup-token", client=http)

    def calls(self) -> list[tuple[str, str]]:
        return [(r.method, r.url.path) for r in self.requests]

    def body(self, method: str, path: str) -> object:
        request = next(r for r in self.requests if (r.method, r.url.path) == (method, path))
        return json.loads(request.content)


@pytest.fixture(autouse=True)
def instant_server_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real network: the server-listening wait returns at once."""

    async def listening(*args: object, **kwargs: object) -> bool:
        return True

    monkeypatch.setattr(lifecycle, "wait_for_server", listening)


@pytest.fixture
def made(paths: Paths) -> Iterator[list[FastAPI]]:
    apps: list[FastAPI] = []
    yield apps
    for app in apps:
        app.state.db.close()


def build(
    made: list[FastAPI],
    paths: Paths,
    supervisor: SupervisorClient | None = None,
    *,
    start_background: bool = True,
) -> FastAPI:
    app = create_app(paths, supervisor=supervisor, start_background=start_background)
    made.append(app)
    return app


def wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def discovery_status(app: FastAPI) -> str:
    return app.state.discovery_status["status"]


def remembered_uuids(paths: Paths) -> list[str]:
    path = paths.data_dir / "discovery_uuid"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def new_clip(app: FastAPI, title: str = "Movie") -> None:
    app.state.repo.create_clip(
        clip_id=None,
        collection_id="regular",
        title=title,
        source_name="m.mp4",
        recipe=Recipe(),
        original=None,
        sort_key=title.casefold(),
    )


# --- startup ---------------------------------------------------------------------------------


def test_lifespan_prepares_the_media_tree_and_starts_the_worker(paths: Paths, made: list[FastAPI]):
    app = build(made, paths)
    assert not paths.root.exists()
    with TestClient(app):
        for directory in (
            paths.originals_dir,
            paths.renders_dir,
            paths.assets_dir,
            paths.consumers_dir,
            paths.work_dir,
        ):
            assert directory.is_dir()
        assert app.state.jobs._worker is not None  # pyright: ignore[reportPrivateUsage]
    assert app.state.jobs._worker is None  # pyright: ignore[reportPrivateUsage]


def test_lifespan_recovers_renders_a_crash_left_behind(paths: Paths, made: list[FastAPI]):
    app = build(made, paths)
    new_clip(app)
    clip = app.state.repo.list_clips()[0]
    app.state.repo.set_status(clip.id, "rendering")
    with TestClient(app):
        recovered = app.state.repo.get_clip(clip.id)
        assert recovered.status == "failed"
        assert recovered.error == "interrupted"


def test_lifespan_starts_and_stops_the_job_queue_in_order(
    paths: Paths, made: list[FastAPI], monkeypatch: pytest.MonkeyPatch
):
    app = build(made, paths)
    events: list[str] = []
    start, stop = app.state.jobs.start, app.state.jobs.stop

    async def started() -> None:
        events.append("start")
        await start()

    async def stopped() -> None:
        events.append("stop")
        await stop()

    monkeypatch.setattr(app.state.jobs, "start", started)
    monkeypatch.setattr(app.state.jobs, "stop", stopped)
    with TestClient(app):
        assert events == ["start"]
    assert events == ["start", "stop"]


def test_without_background_work_the_lifespan_starts_nothing(
    paths: Paths, made: list[FastAPI], monkeypatch: pytest.MonkeyPatch
):
    fake = FakeSupervisor()
    app = build(made, paths, fake.client(), start_background=False)
    started: list[str] = []

    async def start() -> None:
        started.append("start")

    monkeypatch.setattr(app.state.jobs, "start", start)
    with TestClient(app):
        time.sleep(0.1)
        assert app.state.notifier is None
        assert app.state.discovery_status["status"] == "unavailable"
    assert started == []
    assert fake.requests == []
    assert not paths.root.exists()


def test_shutdown_closes_the_supervisor_notifier_and_database(paths: Paths, made: list[FastAPI]):
    http = httpx.AsyncClient(transport=httpx.MockTransport(FakeSupervisor().handle))
    app = build(made, paths, SupervisorClient("tok", client=http))
    with TestClient(app):
        assert not http.is_closed
        assert app.state.notifier is not None
    assert http.is_closed
    assert app.state.notifier is None
    with pytest.raises(Exception, match="closed"):
        app.state.db.connection.execute("SELECT 1")


def test_a_failing_shutdown_step_does_not_skip_the_others(
    paths: Paths,
    made: list[FastAPI],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    http = httpx.AsyncClient(transport=httpx.MockTransport(FakeSupervisor().handle))
    app = build(made, paths, SupervisorClient("tok", client=http))

    async def broken_stop() -> None:
        raise RuntimeError("worker is stuck")

    monkeypatch.setattr(app.state.jobs, "stop", broken_stop)
    with caplog.at_level(logging.ERROR, logger="cinema_studio.app"), TestClient(app):
        pass
    assert "Could not stop the render worker" in caplog.text
    assert http.is_closed
    assert app.state.notifier is None
    with pytest.raises(Exception, match="closed"):
        app.state.db.connection.execute("SELECT 1")


# --- discovery -------------------------------------------------------------------------------


def test_lifespan_publishes_discovery_and_replaces_the_previous_one(
    paths: Paths, made: list[FastAPI]
):
    (paths.data_dir / "discovery_uuid").write_text("uuid-old", encoding="utf-8")
    fake = FakeSupervisor(routes={("DELETE", "/discovery/uuid-old"): httpx.Response(200, json={})})
    app = build(made, paths, fake.client())
    with TestClient(app):
        assert wait_for(lambda: discovery_status(app) == "ok")
        assert app.state.discovery_status == {"status": "ok", "message": None}
    calls = fake.calls()
    assert calls.index(("DELETE", "/discovery/uuid-old")) < calls.index(("POST", "/discovery"))
    assert fake.body("POST", "/discovery") == {
        "service": "cinema_studio",
        "config": {
            "host": HOSTNAME,
            "port": 8099,
            "token": app.state.tokens.get(),
            "instance_id": app.state.instance_id,
        },
    }
    assert remembered_uuids(paths) == ["uuid-new"]


def test_first_start_publishes_without_deleting(paths: Paths, made: list[FastAPI]):
    fake = FakeSupervisor()
    app = build(made, paths, fake.client())
    with TestClient(app):
        assert wait_for(lambda: discovery_status(app) == "ok")
    assert all(method != "DELETE" for method, _ in fake.calls())
    assert remembered_uuids(paths) == ["uuid-new"]


def test_a_discovery_that_cannot_be_deleted_is_retried_on_the_next_start(
    paths: Paths, made: list[FastAPI]
):
    (paths.data_dir / "discovery_uuid").write_text("uuid-old", encoding="utf-8")
    refused = httpx.Response(500, json={"message": "supervisor busy"})
    first = FakeSupervisor(routes={("DELETE", "/discovery/uuid-old"): refused})
    app = build(made, paths, first.client())
    with TestClient(app):
        assert wait_for(lambda: discovery_status(app) == "ok")
    assert remembered_uuids(paths) == ["uuid-old", "uuid-new"]

    second = FakeSupervisor(
        routes={
            ("DELETE", "/discovery/uuid-old"): httpx.Response(200, json={}),
            ("DELETE", "/discovery/uuid-new"): httpx.Response(200, json={}),
            ("POST", "/discovery"): httpx.Response(200, json={"data": {"uuid": "uuid-3"}}),
        }
    )
    again = build(made, paths, second.client())
    with TestClient(again):
        assert wait_for(lambda: discovery_status(again) == "ok")
    assert ("DELETE", "/discovery/uuid-old") in second.calls()
    assert ("DELETE", "/discovery/uuid-new") in second.calls()
    assert remembered_uuids(paths) == ["uuid-3"]


def test_a_discovery_the_supervisor_no_longer_knows_is_forgotten(paths: Paths, made: list[FastAPI]):
    (paths.data_dir / "discovery_uuid").write_text("uuid-old", encoding="utf-8")
    gone = httpx.Response(404, json={"result": "error", "message": "Gone"})
    fake = FakeSupervisor(routes={("DELETE", "/discovery/uuid-old"): gone})
    app = build(made, paths, fake.client())
    with TestClient(app):
        assert wait_for(lambda: discovery_status(app) == "ok")
    assert remembered_uuids(paths) == ["uuid-new"]


def test_discovery_failure_is_reported_and_the_app_keeps_running(paths: Paths, made: list[FastAPI]):
    fake = FakeSupervisor(
        routes={("POST", "/discovery"): httpx.Response(400, json={"message": "service refused"})}
    )
    app = build(made, paths, fake.client())
    with TestClient(app) as client:
        assert wait_for(lambda: discovery_status(app) == "failed")
        assert "service refused" in str(app.state.discovery_status["message"])
        health = client.get(
            "/api/v1/health",
            headers={
                "Authorization": f"Bearer {app.state.tokens.get()}",
                "X-Cinema-Consumer": "entry-1",
            },
        )
        assert health.status_code == 200
    assert remembered_uuids(paths) == []


def test_unreachable_supervisor_does_not_stop_startup(paths: Paths, made: list[FastAPI]):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    app = build(made, paths, SupervisorClient("tok", client=http))
    with TestClient(app):
        assert wait_for(lambda: discovery_status(app) == "failed")


def test_a_discovery_message_without_text_names_the_error_type(paths: Paths, made: list[FastAPI]):
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    app = build(made, paths, SupervisorClient("tok", client=http))
    with TestClient(app):
        assert wait_for(lambda: discovery_status(app) == "failed")
        assert "ReadTimeout" in str(app.state.discovery_status["message"])


def test_a_bookkeeping_failure_does_not_fail_discovery(
    paths: Paths, made: list[FastAPI], caplog: pytest.LogCaptureFixture
):
    (paths.data_dir / "discovery_uuid").mkdir()  # cannot be read or written as a file
    app = build(made, paths, FakeSupervisor().client())
    with caplog.at_level(logging.WARNING, logger="cinema_studio.lifecycle"), TestClient(app):
        assert wait_for(lambda: discovery_status(app) == "ok")
        assert wait_for(lambda: "Could not record the discovery uuid" in caplog.text)


async def test_publish_discovery_can_be_repeated_after_a_token_rotation(
    paths: Paths, made: list[FastAPI]
):
    fake = FakeSupervisor(routes={("DELETE", "/discovery/uuid-new"): httpx.Response(200, json={})})
    app = build(made, paths, fake.client(), start_background=False)
    await lifecycle.publish_discovery(app)
    app.state.tokens.rotate()
    await lifecycle.publish_discovery(app)
    assert fake.calls().count(("POST", "/discovery")) == 2
    posted = [
        json.loads(r.content)
        for r in fake.requests
        if (r.method, r.url.path) == ("POST", "/discovery")
    ]
    assert posted[1]["config"]["token"] == app.state.tokens.get()
    assert posted[0]["config"]["token"] != posted[1]["config"]["token"]


def test_without_a_supervisor_nothing_is_published(paths: Paths, made: list[FastAPI]):
    app = build(made, paths)
    with TestClient(app):
        time.sleep(0.1)
        assert app.state.discovery_status == {
            "status": "unavailable",
            "message": "The Supervisor API is not available",
        }


def test_the_supervisor_steps_wait_for_the_server_and_never_block_startup(
    paths: Paths, made: list[FastAPI], monkeypatch: pytest.MonkeyPatch
):
    gate = threading.Event()

    async def listening(*args: object, **kwargs: object) -> bool:
        while not gate.is_set():
            await asyncio.sleep(0.01)
        return True

    monkeypatch.setattr(lifecycle, "wait_for_server", listening)
    fake = FakeSupervisor()
    app = build(made, paths, fake.client())
    with TestClient(app):
        # Startup returned while the server is not accepting connections yet: nothing announced.
        time.sleep(0.15)
        assert fake.requests == []
        assert discovery_status(app) == "unavailable"
        gate.set()
        assert wait_for(lambda: discovery_status(app) == "ok")
    assert ("POST", "/discovery") in fake.calls()


def test_shutdown_cancels_steps_that_are_still_waiting(
    paths: Paths, made: list[FastAPI], monkeypatch: pytest.MonkeyPatch
):
    async def never(*args: object, **kwargs: object) -> bool:
        await asyncio.sleep(3600)
        return True

    monkeypatch.setattr(lifecycle, "wait_for_server", never)
    fake = FakeSupervisor()
    app = build(made, paths, fake.client())
    started = time.monotonic()
    with TestClient(app):
        pass
    assert time.monotonic() - started < 5
    assert fake.requests == []


def test_a_server_that_never_answers_does_not_prevent_discovery(
    paths: Paths, made: list[FastAPI], monkeypatch: pytest.MonkeyPatch
):
    async def timed_out(*args: object, **kwargs: object) -> bool:
        return False

    monkeypatch.setattr(lifecycle, "wait_for_server", timed_out)
    app = build(made, paths, FakeSupervisor().client())
    with TestClient(app):
        assert wait_for(lambda: discovery_status(app) == "ok")


@pytest.mark.usefixtures("socket_enabled")
async def test_wait_for_server_returns_once_something_listens():
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        assert await REAL_WAIT_FOR_SERVER("127.0.0.1", port, timeout=2) is True
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.usefixtures("socket_enabled")
async def test_wait_for_server_times_out_when_nothing_listens():
    probe_socket = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = probe_socket.sockets[0].getsockname()[1]
    probe_socket.close()
    await probe_socket.wait_closed()
    started = time.monotonic()
    assert await REAL_WAIT_FOR_SERVER("127.0.0.1", port, timeout=0.4) is False
    assert time.monotonic() - started < 3


async def test_wait_for_server_bounds_a_stalled_connect(monkeypatch: pytest.MonkeyPatch):
    cancelled = asyncio.Event()

    async def stalled(host: str, port: int) -> None:
        try:
            await asyncio.sleep(3600)
        finally:
            cancelled.set()

    monkeypatch.setattr(lifecycle.asyncio, "open_connection", stalled)
    async with asyncio.timeout(1):
        assert await REAL_WAIT_FOR_SERVER(timeout=0.05) is False
    assert cancelled.is_set()


# --- catalog change events -------------------------------------------------------------------


@pytest.fixture
def fast_notifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle, "CATALOG_NOTIFY_DELAY", 0.05)


def test_catalog_changes_fire_a_debounced_home_assistant_event(
    paths: Paths, made: list[FastAPI], fast_notifier: None
):
    fake = FakeSupervisor()
    app = build(made, paths, fake.client())
    with TestClient(app):
        assert app.state.notifier is not None
        app.state.repo.create_collection(CollectionCreate(name="Horror"))
        revision = app.state.repo.catalog_revision()
        assert revision > 0
        assert wait_for(lambda: EVENT in fake.calls())
        assert fake.body(*EVENT) == {"revision": revision}
    assert app.state.notifier is None


def test_event_failures_are_swallowed(paths: Paths, made: list[FastAPI], fast_notifier: None):
    fake = FakeSupervisor(routes={EVENT: httpx.Response(500, json={"message": "core is down"})})
    app = build(made, paths, fake.client())
    with TestClient(app) as client:
        app.state.repo.create_collection(CollectionCreate(name="Horror"))
        assert wait_for(lambda: EVENT in fake.calls())
        app.state.repo.create_collection(CollectionCreate(name="Comedy"))
        assert wait_for(lambda: fake.calls().count(EVENT) == 2)
        health = client.get(
            "/api/v1/health",
            headers={
                "Authorization": f"Bearer {app.state.tokens.get()}",
                "X-Cinema-Consumer": "entry-1",
            },
        )
        assert health.is_success


async def test_the_catalog_sender_is_a_no_op_for_an_unavailable_supervisor():
    fake = FakeSupervisor()
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    await lifecycle.catalog_sender(SupervisorClient(None, client=http))(5)
    assert fake.requests == []


def test_secrets_never_reach_the_logs(
    paths: Paths, made: list[FastAPI], caplog: pytest.LogCaptureFixture
):
    fake = FakeSupervisor(routes={("POST", "/discovery"): httpx.Response(500, text="no")})
    app = build(made, paths, fake.client())
    with caplog.at_level(logging.DEBUG), TestClient(app):
        assert wait_for(lambda: discovery_status(app) == "failed")
    assert app.state.tokens.get() not in caplog.text
    assert "sup-token" not in caplog.text


# --- housekeeping ----------------------------------------------------------------------------


def test_housekeeping_purges_stale_uploads_and_survives_errors(
    paths: Paths, made: list[FastAPI], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(lifecycle, "HOUSEKEEPING_INTERVAL", 0.02)
    app = build(made, paths)
    calls: list[int] = []
    threads: list[bool] = []

    class Uploads:
        def purge_stale(self) -> None:
            calls.append(len(calls))
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                threads.append(True)  # ran in a worker thread, not on the event loop
            if len(calls) == 1:
                raise RuntimeError("disk hiccup")

    app.state.uploads = Uploads()
    with TestClient(app):
        assert wait_for(lambda: len(calls) >= 3)
    assert all(threads)


def test_a_failed_discovery_is_retried_by_the_periodic_refresh(
    paths: Paths, made: list[FastAPI], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(lifecycle, "HOUSEKEEPING_INTERVAL", 0.05)
    fake = FakeSupervisor(
        routes={("POST", "/discovery"): httpx.Response(503, json={"message": "starting"})}
    )
    app = build(made, paths, fake.client())
    with TestClient(app):
        assert wait_for(lambda: discovery_status(app) == "failed")
        fake.routes[("POST", "/discovery")] = httpx.Response(200, json={"data": {"uuid": "late"}})
        assert wait_for(lambda: discovery_status(app) == "ok")
    assert remembered_uuids(paths) == ["late"]


def test_a_healthy_discovery_is_not_republished_by_the_refresh(
    paths: Paths, made: list[FastAPI], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(lifecycle, "HOUSEKEEPING_INTERVAL", 0.05)
    fake = FakeSupervisor()
    app = build(made, paths, fake.client())
    with TestClient(app):
        assert wait_for(lambda: discovery_status(app) == "ok")
        time.sleep(0.3)
    assert fake.calls().count(("POST", "/discovery")) == 1


async def test_housekeeping_loop_stops_when_cancelled(paths: Paths, made: list[FastAPI]):
    app = build(made, paths, start_background=False)
    task = asyncio.create_task(lifecycle.housekeeping(app, 0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_housekeeping_discards_legacy_without_uploads(paths: Paths, made: list[FastAPI]):
    app = build(made, paths, start_background=False)
    run = paths.work_dir / "import" / "abandoned"
    run.mkdir(parents=True)
    # A valid manifest is unnecessary for an abandoned, incomplete staging directory.
    old = time.time() - 7200
    os.utime(run, (old, old))
    await lifecycle._clean_up(app)
    assert not run.exists()
