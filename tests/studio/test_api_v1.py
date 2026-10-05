"""Integration API v1, error mapping and the UI shell served by the app factory."""

from __future__ import annotations

import dataclasses
import logging
import sys
import types
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

import cinema_studio.app as app_module
from cinema_studio import __version__
from cinema_studio.app import create_app
from cinema_studio.auth import INGRESS_PEER
from cinema_studio.config import Paths
from cinema_studio.errors import ConflictError, InvalidError, NotFoundError
from cinema_studio.models import (
    OriginalInfo,
    ProcessingProfileCreate,
    ProcessingProfileUpdate,
    Recipe,
    RenderRecord,
)
from cinema_studio.profiles import ProcessingProfile
from cinema_studio.repository import Repository

pytestmark = pytest.mark.studio

CONTRACT = Path(__file__).resolve().parents[2] / "contract" / "openapi-v1.yaml"
CONSUMER = "entry-1"


@pytest.fixture
def app(paths: Paths) -> Iterator[FastAPI]:
    application = create_app(paths, start_background=False)
    yield application
    application.state.db.close()


@pytest.fixture
def repo(app: FastAPI) -> Repository:
    return app.state.repo


@pytest.fixture
def auth(app: FastAPI) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {app.state.tokens.get()}",
        "X-Cinema-Consumer": CONSUMER,
    }


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def ingress(app: FastAPI) -> TestClient:
    return TestClient(app, client=(INGRESS_PEER, 50000))


def publish_clip(repo: Repository, title: str = "Movie") -> str:
    clip = repo.create_clip(
        clip_id=None,
        collection_id="regular",
        title=title,
        source_name="movie.mp4",
        recipe=Recipe(),
        original=OriginalInfo(
            filename="movie.mp4",
            size=1000,
            sha256="ab" * 32,
            duration=60.0,
            width=1920,
            height=1080,
            fps=24.0,
            has_audio=True,
            video_codec="h264",
        ),
        sort_key=title.casefold(),
    )
    render_id = uuid.uuid4().hex
    repo.publish_render(
        RenderRecord.model_validate(
            {
                "id": render_id,
                "clip_id": clip.id,
                "n": 1,
                "relative_path": f"cinema-studio/renders/{clip.id}/{clip.id}-r1-{render_id}.mp4",
                "size": 5000,
                "sha256": "cd" * 32,
                "duration": 154.133,
                "content_start": 2.0,
                "content_end": 152.125,
                "lead_in": 2.0,
                "tail_out": 2.008,
                "content_duration": 150.125,
                "timing_source": "measured",
                "integrated_lufs": -18.0,
                "true_peak": -1.6,
                "recipe_hash": "r" * 8,
                "profile_fingerprint": "p" * 8,
            }
        )
    )
    return clip.id


def consumers(app: FastAPI) -> dict[str, int | None]:
    rows = app.state.db.connection.execute(
        "SELECT consumer_id, held_revision FROM consumers_seen"
    ).fetchall()
    return {row["consumer_id"]: row["held_revision"] for row in rows}


# --- authentication and the consumer header --------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/catalog"),
        ("POST", "/api/v1/selections"),
        ("POST", "/api/v1/import/legacy"),
    ],
)
def test_v1_requires_a_bearer_token(client: TestClient, method: str, path: str):
    headers = {"X-Cinema-Consumer": CONSUMER}
    missing = client.request(method, path, json={"events": []}, headers=headers)
    assert missing.status_code == 401
    assert isinstance(missing.json()["detail"], str)
    wrong = client.request(
        method, path, json={"events": []}, headers={**headers, "Authorization": "Bearer wrong"}
    )
    assert wrong.status_code == 401
    # Authentication wins over the missing consumer header.
    assert client.request(method, path, json={"events": []}).status_code == 401


def test_auth_runs_before_the_body_is_parsed(client: TestClient, auth: dict[str, str]):
    json_type = {"Content-Type": "application/json"}
    for body in ("{nope", '{"events": 5}', ""):
        assert client.post("/api/v1/selections", content=body, headers=json_type).status_code == 401
    bad = client.post("/api/v1/selections", content="{nope", headers={**json_type, **auth})
    assert bad.status_code == 422
    assert isinstance(bad.json()["detail"], str)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/catalog"),
        ("POST", "/api/v1/selections"),
        ("POST", "/api/v1/import/legacy"),
    ],
)
def test_every_route_requires_the_consumer_header(
    app: FastAPI, client: TestClient, auth: dict[str, str], method: str, path: str
):
    headers = {"Authorization": auth["Authorization"]}
    response = client.request(method, path, json={"events": []}, headers=headers)
    assert response.status_code == 422
    assert "X-Cinema-Consumer".lower() in response.json()["detail"].lower()
    assert consumers(app) == {}


def test_a_blank_or_unsafe_consumer_id_is_rejected(client: TestClient, auth: dict[str, str]):
    for value in ("", "../etc", "a b", "x" * 200):
        response = client.get("/api/v1/health", headers={**auth, "X-Cinema-Consumer": value})
        assert response.status_code == 422, value


def test_every_route_records_the_consumer(app: FastAPI, client: TestClient, auth: dict[str, str]):
    assert client.get("/api/v1/health", headers=auth).status_code == 200
    assert consumers(app) == {CONSUMER: None}
    other = {**auth, "X-Cinema-Consumer": "entry-2"}
    assert client.post("/api/v1/selections", json={"events": []}, headers=other).status_code == 204
    assert set(consumers(app)) == {CONSUMER, "entry-2"}


# --- health ----------------------------------------------------------------------------------


def test_health_reports_identity(app: FastAPI, client: TestClient, auth: dict[str, str]):
    response = client.get("/api/v1/health", headers=auth)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "api_version": 1,
        "instance_id": app.state.instance_id,
    }


def test_instance_id_is_stable_across_restarts(paths: Paths):
    first = create_app(paths, start_background=False)
    identifier = first.state.instance_id
    first.state.db.close()
    second = create_app(paths, start_background=False)
    try:
        assert second.state.instance_id == identifier
        assert (paths.data_dir / "instance_id").read_text(encoding="utf-8").strip() == identifier
    finally:
        second.state.db.close()


# --- catalog ---------------------------------------------------------------------------------


def catalog_schema() -> Draft202012Validator:
    document: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return Draft202012Validator(
        {"$ref": "#/components/schemas/Catalog", "components": document["components"]}
    )


def test_catalog_validates_against_the_contract(
    client: TestClient, auth: dict[str, str], repo: Repository
):
    clip_id = publish_clip(repo)
    response = client.get("/api/v1/catalog", headers=auth)
    assert response.status_code == 200
    document = response.json()
    catalog_schema().validate(document)
    assert document["contract_version"] == 1
    assert [clip["id"] for clip in document["clips"]] == [clip_id]
    assert document["clips"][0]["render"]["relative_path"].startswith("cinema-studio/renders/")


def test_empty_catalog_validates_against_the_contract(client: TestClient, auth: dict[str, str]):
    document = client.get("/api/v1/catalog", headers=auth).json()
    catalog_schema().validate(document)
    assert document["clips"] == []
    assert [season["id"] for season in document["seasons"]] == ["regular"]


def test_catalog_carries_an_etag_for_its_revision(
    app: FastAPI, client: TestClient, auth: dict[str, str], repo: Repository
):
    publish_clip(repo)
    response = client.get("/api/v1/catalog", headers=auth)
    assert response.headers["ETag"] == f'"rev-{response.json()["revision"]}"'
    assert response.json()["instance_id"] == app.state.instance_id


def test_catalog_omits_clips_without_a_render(
    client: TestClient, auth: dict[str, str], repo: Repository
):
    repo.create_clip(
        clip_id=None,
        collection_id="regular",
        title="Pending",
        source_name="p.mp4",
        recipe=Recipe(),
        original=None,
        sort_key="pending",
    )
    assert client.get("/api/v1/catalog", headers=auth).json()["clips"] == []


def test_catalog_answers_304_for_a_current_etag(
    client: TestClient, auth: dict[str, str], repo: Repository
):
    publish_clip(repo)
    etag = client.get("/api/v1/catalog", headers=auth).headers["ETag"]
    for header in (etag, f"W/{etag}", f'"other", {etag}', "*"):
        response = client.get("/api/v1/catalog", headers={**auth, "If-None-Match": header})
        assert response.status_code == 304, header
        assert response.headers["ETag"] == etag
        assert response.content == b""


def test_catalog_serves_a_new_body_once_the_revision_moves(
    client: TestClient, auth: dict[str, str], repo: Repository
):
    publish_clip(repo, "One")
    etag = client.get("/api/v1/catalog", headers=auth).headers["ETag"]
    publish_clip(repo, "Two")
    response = client.get("/api/v1/catalog", headers={**auth, "If-None-Match": etag})
    assert response.status_code == 200
    assert response.headers["ETag"] != etag
    assert len(response.json()["clips"]) == 2


def test_catalog_records_the_held_revision(
    app: FastAPI, client: TestClient, auth: dict[str, str], repo: Repository
):
    publish_clip(repo)
    held = repo.catalog_revision()
    publish_clip(repo, "Newer")
    assert client.get("/api/v1/catalog", headers=auth).status_code == 200
    assert consumers(app) == {CONSUMER: None}
    client.get("/api/v1/catalog", headers={**auth, "If-None-Match": f'"rev-{held}"'})
    assert consumers(app) == {CONSUMER: held}
    current = repo.catalog_revision()
    response = client.get(
        "/api/v1/catalog", headers={**auth, "If-None-Match": f'W/"rev-{current}"'}
    )
    assert response.status_code == 304
    assert consumers(app) == {CONSUMER: current}


def test_a_request_without_a_validator_keeps_the_known_held_revision(
    app: FastAPI, client: TestClient, auth: dict[str, str], repo: Repository
):
    revision = repo.catalog_revision()
    client.get("/api/v1/catalog", headers={**auth, "If-None-Match": f'"rev-{revision}"'})
    client.get("/api/v1/health", headers=auth)
    assert consumers(app) == {CONSUMER: revision}


def test_every_route_reads_the_held_revision_from_if_none_match(
    app: FastAPI, client: TestClient, auth: dict[str, str], repo: Repository
):
    publish_clip(repo)
    revision = repo.catalog_revision()
    client.get("/api/v1/health", headers={**auth, "If-None-Match": f'"rev-{revision}"'})
    assert consumers(app) == {CONSUMER: revision}


def test_future_wildcard_and_odd_validators_hold_nothing(
    app: FastAPI, client: TestClient, auth: dict[str, str], repo: Repository
):
    future = repo.catalog_revision() + 5
    headers = [
        "*",
        f'"rev-{future}"',
        '"something-else"',
        '"rev-99999999999999999999999"',
        '"rev--1"',
        '"rev-1x"',
        "rev-1",
        '"rev-²"'.encode(),
    ]
    for header in headers:
        response = client.get("/api/v1/catalog", headers={**auth, "If-None-Match": header})
        assert response.status_code in (200, 304)
    assert consumers(app) == {CONSUMER: None}


# --- selections ------------------------------------------------------------------------------


def selection(clip_id: str, render_id: str, selected_at: str = "2026-03-01T10:00:00Z"):
    return {
        "selection_id": uuid.uuid4().hex,
        "clip_id": clip_id,
        "render_id": render_id,
        "catalog_revision": 1,
        "selected_at": selected_at,
    }


def test_selections_update_the_counters(client: TestClient, auth: dict[str, str], repo: Repository):
    clip_id = publish_clip(repo)
    render_id = repo.get_clip(clip_id).render.id  # type: ignore[union-attr]
    events = [
        selection(clip_id, render_id, "2026-03-01T10:00:00Z"),
        selection(clip_id, render_id, "2026-03-02T10:00:00Z"),
    ]
    response = client.post("/api/v1/selections", json={"events": events}, headers=auth)
    assert response.status_code == 204
    assert response.content == b""
    clip = repo.get_clip(clip_id)
    assert clip.selection_count == 2
    assert clip.last_selected_at == "2026-03-02T10:00:00Z"


def test_selections_accept_an_empty_batch_and_unknown_clips(
    client: TestClient, auth: dict[str, str], repo: Repository
):
    assert client.post("/api/v1/selections", json={"events": []}, headers=auth).status_code == 204
    revision = repo.catalog_revision()
    unknown = [selection("missing", "r")]
    assert (
        client.post("/api/v1/selections", json={"events": unknown}, headers=auth).status_code == 204
    )
    assert repo.catalog_revision() == revision


def test_selections_reject_more_than_500_events(client: TestClient, auth: dict[str, str]):
    events = [selection("c", "r") for _ in range(501)]
    response = client.post("/api/v1/selections", json={"events": events}, headers=auth)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_validation_errors_list_every_field(client: TestClient, auth: dict[str, str]):
    response = client.post(
        "/api/v1/selections", json={"events": [{"clip_id": 5, "selected_at": "x"}]}, headers=auth
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "events.0.selection_id" in detail
    assert "events.0.clip_id" in detail


def test_malformed_bodies_get_a_string_detail(client: TestClient, auth: dict[str, str]):
    for body in ("{nope", "[]", '{"events": "x"}', ""):
        response = client.post(
            "/api/v1/selections",
            content=body,
            headers={**auth, "Content-Type": "application/json"},
        )
        assert response.status_code == 422, body
        assert isinstance(response.json()["detail"], str)


# --- legacy import --------------------------------------------------------------------------


def test_legacy_import_validates_stage_manifest(
    app: FastAPI, client: TestClient, auth: dict[str, str]
):
    assert app.state.legacy is not None
    response = client.post("/api/v1/import/legacy", json={"phase": "stage"}, headers=auth)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


# --- error mapping ---------------------------------------------------------------------------


def test_domain_errors_map_to_http_statuses(app: FastAPI):
    router = APIRouter()

    @router.get("/boom/{kind}")
    async def boom(kind: str) -> None:
        raise {"missing": NotFoundError, "clash": ConflictError, "bad": InvalidError}[kind](
            f"{kind} happened"
        )

    app.include_router(router)
    client = TestClient(app)
    expected = {"missing": 404, "clash": 409, "bad": 422}
    for kind, status in expected.items():
        response = client.get(f"/boom/{kind}")
        assert response.status_code == status
        assert response.json() == {"detail": f"{kind} happened"}


def test_query_validation_errors_are_app_wide_strings(app: FastAPI):
    router = APIRouter()

    @router.get("/count")
    async def count(limit: int) -> int:
        return limit

    app.include_router(router)
    response = TestClient(app).get("/count", params={"limit": "x"})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("limit:")


def test_unknown_routes_keep_the_error_shape(client: TestClient):
    response = client.get("/nope")
    assert response.status_code == 404
    assert isinstance(response.json()["detail"], str)


def test_interactive_docs_are_not_exposed(ingress: TestClient):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert ingress.get(path).status_code == 404


# --- UI shell --------------------------------------------------------------------------------


def test_ui_root_requires_the_ingress_peer(client: TestClient):
    denied = client.get("/")
    assert denied.status_code == 403
    assert isinstance(denied.json()["detail"], str)
    assert client.get("/assets/app.js").status_code == 403


def test_forwarded_headers_cannot_pose_as_the_ingress_peer(client: TestClient):
    response = client.get("/", headers={"X-Forwarded-For": INGRESS_PEER})
    assert response.status_code == 403


def test_ui_root_without_a_build_is_503_text(ingress: TestClient):
    response = ingress.get("/")
    assert response.status_code == 503
    assert response.text == "UI not built"


def build_ui(paths: Paths) -> None:
    (paths.static_dir / "assets").mkdir(parents=True)
    (paths.static_dir / "index.html").write_text("<!doctype html><title>Cinema</title>")
    (paths.static_dir / "assets" / "app.js").write_text("console.log(1)")
    (paths.static_dir / "secret.txt").write_text("outside")


def test_ui_root_serves_the_built_index(ingress: TestClient, paths: Paths):
    build_ui(paths)
    response = ingress.get("/")
    assert response.status_code == 200
    assert "Cinema" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_ui_assets_are_served_behind_ingress(client: TestClient, ingress: TestClient, paths: Paths):
    build_ui(paths)
    assert ingress.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/assets/app.js").status_code == 403
    assert ingress.get("/assets/missing.js").status_code == 404


def test_ui_assets_cannot_escape_the_assets_directory(ingress: TestClient, paths: Paths):
    build_ui(paths)
    for path in ("/assets/../secret.txt", "/assets/%2e%2e/secret.txt", "/assets/..%2fsecret.txt"):
        assert ingress.get(path).status_code in (400, 404), path
    (paths.static_dir / "assets" / "link").symlink_to(paths.static_dir / "secret.txt")
    assert ingress.get("/assets/link").status_code == 404


def test_dev_mode_opens_the_ui_to_any_peer(paths: Paths):
    app = create_app(dataclasses.replace(paths, dev_mode=True), start_background=False)
    try:
        assert TestClient(app).get("/").status_code == 503
    finally:
        app.state.db.close()


# --- app factory -----------------------------------------------------------------------------


def test_create_app_prepares_state_without_background_work(app: FastAPI, paths: Paths):
    state = app.state
    for name in (
        "paths",
        "repo",
        "store",
        "engine",
        "jobs",
        "gc",
        "fence",
        "tokens",
        "supervisor",
        "notifier",
        "instance_id",
        "discovery_status",
        "legacy",
    ):
        assert hasattr(state, name), name
    assert state.paths is paths
    assert state.notifier is None
    assert state.legacy is not None
    assert not state.supervisor.available
    assert state.discovery_status["status"] == "unavailable"
    assert (paths.data_dir / "api_token").is_file()
    # No media work happens before the lifespan starts.
    assert not paths.root.exists()


def test_the_seed_processing_profile_gets_the_default_settings(app: FastAPI, repo: Repository):
    profile = repo.get_processing_profile("compatibility-4k-loudness")
    assert profile.settings == ProcessingProfile().model_dump(mode="json")


def test_a_customised_seed_profile_is_left_alone(paths: Paths):
    first = create_app(paths, start_background=False)
    first.state.repo.update_processing_profile(
        "compatibility-4k-loudness",
        ProcessingProfileUpdate(settings={"video": {"width": 640, "height": 360}}),
    )
    stored = first.state.repo.get_processing_profile("compatibility-4k-loudness").settings
    first.state.db.close()
    second = create_app(paths, start_background=False)
    try:
        assert (
            second.state.repo.get_processing_profile("compatibility-4k-loudness").settings == stored
        )
    finally:
        second.state.db.close()


def test_repository_validates_profile_settings(app: FastAPI, repo: Repository):
    with pytest.raises(InvalidError):
        repo.create_processing_profile(
            ProcessingProfileCreate(name="Bad", settings={"video": {"width": -1}})
        )


def test_catalog_changes_reach_the_notifier(app: FastAPI, repo: Repository):
    seen: list[int] = []

    class Spy:
        def mark_changed(self, revision: int) -> None:
            seen.append(revision)

    app.state.notifier = Spy()
    publish_clip(repo)
    assert seen == [repo.catalog_revision()]
    app.state.notifier = None
    publish_clip(repo, "Silent")  # no notifier: must not fail


def fake_router_module(monkeypatch: pytest.MonkeyPatch, name: str, path: str) -> None:
    router = APIRouter()

    @router.get(path)
    async def handler() -> dict[str, str]:
        return {"from": name}

    module = types.ModuleType(f"cinema_studio.{name}")
    module.__dict__["router"] = router
    monkeypatch.setitem(sys.modules, module.__name__, module)


def test_optional_ui_routers_are_included_behind_ingress(
    paths: Paths, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    fake_router_module(monkeypatch, "api_ui_organize", "/api/ui/organize-probe")
    fake_router_module(monkeypatch, "api_ui_clips", "/api/ui/clips-probe")
    with caplog.at_level(logging.DEBUG, logger="cinema_studio.app"):
        app = create_app(paths, start_background=False)
    try:
        ingress = TestClient(app, client=(INGRESS_PEER, 50000))
        assert ingress.get("/api/ui/organize-probe").json() == {"from": "api_ui_organize"}
        assert ingress.get("/api/ui/clips-probe").json() == {"from": "api_ui_clips"}
        assert TestClient(app).get("/api/ui/organize-probe").status_code == 403
    finally:
        app.state.db.close()
    assert "UI routers included: api_ui_organize, api_ui_clips" in caplog.text


def test_optional_ui_routers_are_skipped_when_the_module_is_absent(
    paths: Paths, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # A None entry makes the import fail exactly as a missing module would.
    monkeypatch.setitem(sys.modules, "cinema_studio.api_ui_organize", None)
    monkeypatch.setitem(sys.modules, "cinema_studio.api_ui_clips", None)
    with caplog.at_level(logging.DEBUG, logger="cinema_studio.app"):
        app = create_app(paths, start_background=False)
    app.state.db.close()
    assert "UI routers included: none" in caplog.text


def test_a_broken_ui_router_module_is_not_hidden(paths: Paths, monkeypatch: pytest.MonkeyPatch):
    def broken(name: str) -> types.ModuleType:
        raise ModuleNotFoundError("No module named 'numpy'", name="numpy")

    monkeypatch.setattr(app_module.importlib, "import_module", broken)
    with pytest.raises(ModuleNotFoundError, match="numpy"):
        create_app(paths, start_background=False)
