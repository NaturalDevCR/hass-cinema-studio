"""Ingress clips workflow with real ffmpeg and a recorded Supervisor."""

from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import sqlite3
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from cinema_studio import api_ui_clips, uploads
from cinema_studio.app import create_app
from cinema_studio.auth import INGRESS_PEER
from cinema_studio.config import Paths
from cinema_studio.models import (
    CollectionCreate,
    NormalizationProfileCreate,
    OriginalInfo,
    ProcessingProfileCreate,
    ProcessingProfileUpdate,
    Recipe,
    RenderRecord,
    Settings,
    TestTarget,
)
from cinema_studio.repository import Repository
from cinema_studio.supervisor import SupervisorClient, SupervisorError

pytestmark = pytest.mark.studio

DEFAULT = "compatibility-4k-loudness"
CHUNK = 16 * 1024
TARGET = {"id": "den", "label": "Den TV", "entity_id": "media_player.den"}
MEDIA_SOURCE = "media-source://media_source/local/"

type Client = httpx.AsyncClient
type Video = Callable[..., Path]


class FakeSupervisor:
    available = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.error: SupervisorError | None = None

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append((domain, service, data))


async def _client(app: FastAPI) -> AsyncIterator[Client]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(INGRESS_PEER, 50000)),
        base_url="http://studio",
    ) as client:
        yield client


@pytest.fixture
def app(paths: Paths, small_profile_settings: dict[str, object]) -> FastAPI:
    application = create_app(paths, start_background=False)
    application.state.store.ensure_dirs()
    application.state.repo.update_processing_profile(
        DEFAULT, ProcessingProfileUpdate(settings=small_profile_settings)
    )
    return application


@pytest.fixture
async def live(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Client]:
    """The app with its job worker running; small chunks so uploads span several of them."""
    monkeypatch.setattr(uploads, "CHUNK_SIZE", CHUNK)
    monkeypatch.setattr(api_ui_clips, "CHUNK_SIZE", CHUNK)
    await app.state.jobs.start()
    try:
        async for client in _client(app):
            yield client
    finally:
        await app.state.jobs.stop()
        app.state.db.close()


@pytest.fixture
async def idle(app: FastAPI) -> AsyncIterator[Client]:
    """The app without a job worker: enqueued jobs stay queued."""
    try:
        async for client in _client(app):
            yield client
    finally:
        app.state.db.close()


@pytest.fixture
def repo(app: FastAPI) -> Repository:
    repository: Repository = app.state.repo
    return repository


def original_info(duration: float = 60.0, width: int = 1920, height: int = 1080) -> OriginalInfo:
    return OriginalInfo(
        filename="movie.mp4",
        size=1000,
        sha256="ab" * 32,
        duration=duration,
        width=width,
        height=height,
        fps=24.0,
        has_audio=True,
        video_codec="h264",
    )


def fake_clip(
    repo: Repository, paths: Paths, *, title: str = "Movie", collection_id: str = "regular"
) -> str:
    """A clip with an unprobed-free fake original and a published render file of fake bytes."""
    clip = repo.create_clip(
        clip_id=None,
        collection_id=collection_id,
        title=title,
        source_name="movie.mp4",
        recipe=Recipe(),
        original=original_info(),
        sort_key=title.casefold(),
    )
    render_id = uuid.uuid4().hex
    relative = f"cinema-studio/renders/{clip.id}/{clip.id}-r1-{render_id}.mp4"
    file = paths.media_dir / relative
    file.parent.mkdir(parents=True)
    file.write_bytes(b"rendered-bytes")
    repo.publish_render(
        RenderRecord.model_validate(
            {
                "id": render_id,
                "clip_id": clip.id,
                "n": 1,
                "relative_path": relative,
                "size": 14,
                "sha256": "cd" * 32,
                "duration": 64.0,
                "content_start": 2.0,
                "content_end": 62.0,
                "lead_in": 2.0,
                "tail_out": 2.0,
                "content_duration": 60.0,
                "timing_source": "measured",
                "integrated_lufs": -18.0,
                "true_peak": -1.6,
                "recipe_hash": "r" * 8,
                "profile_fingerprint": "p" * 8,
            }
        )
    )
    return clip.id


async def start_upload(client: Client, source: Path) -> str:
    data = source.read_bytes()
    response = await client.post(
        "/api/ui/uploads", json={"filename": source.name, "size": len(data)}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["chunk_size"] == CHUNK
    count = (len(data) + CHUNK - 1) // CHUNK
    assert count > 1
    for index in reversed(range(count)):
        chunk = data[index * CHUNK : (index + 1) * CHUNK]
        put = await client.put(f"/api/ui/uploads/{body['upload_id']}/chunks/{index}", content=chunk)
        assert put.status_code == 200
    return str(body["upload_id"])


async def upload_clip(client: Client, source: Path, **body: object) -> httpx.Response:
    upload_id = await start_upload(client, source)
    return await client.post(
        f"/api/ui/uploads/{upload_id}/complete", json={"collection_id": "regular", **body}
    )


async def ready_clip(
    live: Client, app: FastAPI, make_video: Video, **kwargs: object
) -> dict[str, Any]:
    response = await upload_clip(live, make_video(name="shot.mp4", seconds=4, **kwargs))
    assert response.status_code == 200, response.text
    await app.state.jobs.wait_idle()
    clip: dict[str, Any] = (await live.get(f"/api/ui/clips/{response.json()['id']}")).json()
    assert clip["status"] == "ready", clip["error"]
    return clip


# --- uploads ---------------------------------------------------------------------------------


async def test_upload_lifecycle_to_a_ready_clip(
    live: Client, app: FastAPI, repo: Repository, paths: Paths, make_video: Video
):
    repo.update_settings(Settings(default_lead_in=1.5, default_tail_out=2.5))
    source = make_video(name="My-Holiday_clip.mp4", seconds=4)
    response = await upload_clip(live, source)
    assert response.status_code == 200
    created = response.json()
    assert created["title"] == "My Holiday clip"
    assert created["source_name"] == "My-Holiday_clip.mp4"
    assert created["collection_id"] == "regular"
    assert created["status"] == "processing" and created["original"] is None
    assert (created["recipe"]["lead_in"], created["recipe"]["tail_out"]) == (1.5, 2.5)
    stored = paths.originals_dir / created["id"] / "My-Holiday_clip.mp4"
    assert stored.read_bytes() == source.read_bytes()
    assert not list(paths.uploads_dir.iterdir())
    assert not list(paths.work_dir.glob("upload-*"))

    await app.state.jobs.wait_idle()
    clip = (await live.get(f"/api/ui/clips/{created['id']}")).json()
    assert clip["status"] == "ready" and clip["error"] is None
    assert clip["original"]["width"] == 320 and clip["original"]["duration"] == pytest.approx(
        4, abs=0.1
    )
    assert clip["render"]["lead_in"] == 1.5 and clip["render"]["tail_out"] == 2.5
    assert clip["has_thumbs"] is True
    assert (await live.get("/api/ui/clips")).json() == [clip]
    poster = await live.get(f"/api/ui/clips/{clip['id']}/poster.jpg")
    assert poster.status_code == 200 and poster.headers["content-type"] == "image/jpeg"
    strip = (await live.get(f"/api/ui/clips/{clip['id']}/filmstrip.json")).json()
    assert strip["count"] >= 1
    kinds = {(job["kind"], job["status"]) for job in (await live.get("/api/ui/jobs")).json()}
    assert {("probe", "done"), ("render", "done"), ("thumbs", "done")} <= kinds


async def test_explicit_title_is_used(live: Client, app: FastAPI, make_video: Video):
    response = await upload_clip(live, make_video(seconds=1), title="  The Title ")
    assert response.json()["title"] == "The Title"
    await app.state.jobs.wait_idle()


async def test_upload_creation_errors(live: Client, repo: Repository):
    for payload, status in [
        ({"filename": "bad.exe", "size": 1}, 415),
        ({"filename": "audio.mp3", "size": 1}, 415),
        ({"filename": "clip.mp4", "size": 4097 * 1024 * 1024}, 413),
        ({"filename": "clip.mp4", "size": 0}, 422),
    ]:
        response = await live.post("/api/ui/uploads", json=payload)
        assert response.status_code == status, payload
        assert isinstance(response.json()["detail"], str)
    repo.update_settings(Settings(max_upload_mb=1))
    over = await live.post(
        "/api/ui/uploads", json={"filename": "clip.mp4", "size": 2 * 1024 * 1024}
    )
    assert over.status_code == 413


async def test_chunk_and_complete_errors_and_retry(
    live: Client, repo: Repository, make_video: Video
):
    body = (await live.post("/api/ui/uploads", json={"filename": "clip.mp4", "size": 3})).json()
    endpoint = f"/api/ui/uploads/{body['upload_id']}"
    assert (await live.put(endpoint + "/chunks/0", content=b"1234")).status_code == 413
    assert (await live.put(endpoint + "/chunks/-1", content=b"x")).status_code == 422
    assert (await live.put("/api/ui/uploads/unknown/chunks/0", content=b"x")).status_code == 404
    incomplete = await live.post(endpoint + "/complete", json={"collection_id": "regular"})
    assert incomplete.status_code == 422
    unknown = await live.post("/api/ui/uploads/unknown/complete", json={"collection_id": "regular"})
    assert unknown.status_code == 404
    assert repo.list_clips() == []

    upload_id = await start_upload(live, make_video(seconds=1))
    bad = await live.post(f"/api/ui/uploads/{upload_id}/complete", json={"collection_id": "nope"})
    assert bad.status_code == 422 and repo.list_clips() == []
    good = await live.post(
        f"/api/ui/uploads/{upload_id}/complete", json={"collection_id": "regular"}
    )
    assert good.status_code == 200 and len(repo.list_clips()) == 1


async def test_unreadable_upload_fails_the_probe_not_the_upload(
    live: Client, app: FastAPI, repo: Repository, tmp_path: Path
):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video" * 5000)
    response = await upload_clip(live, junk)
    assert response.status_code == 200
    await app.state.jobs.wait_idle()
    clip = repo.get_clip(response.json()["id"])
    assert clip.status == "failed" and clip.error


# --- recipes ---------------------------------------------------------------------------------

RULES: list[tuple[dict[str, Any], int]] = [
    ({"trim_end": 60.06}, 422),  # past the end by more than 0.05 s
    ({"trim_start": 10, "trim_end": 10}, 422),  # start must be before end
    ({"trim_start": 20, "trim_end": 10}, 422),
    ({"trim_start": 61}, 422),  # start past the end
    ({"crop": {"x": 1900, "y": 0, "w": 100, "h": 100}}, 422),  # outside the frame
    ({"crop": {"x": 0, "y": 1000, "w": 100, "h": 100}}, 422),
    ({"crop": {"x": 0, "y": 0, "w": 63, "h": 100}}, 422),  # smaller than 64x64
    ({"crop": {"x": 0, "y": 0, "w": 100, "h": 63}}, 422),
    ({"trim_start": 10, "trim_end": 20, "fade_in": 6, "fade_out": 5}, 422),  # fades > length
    ({"fade_in": -1}, 422),
    ({"fade_out": -0.1}, 422),
    ({"lead_in": 10.5}, 422),
    ({"tail_out": 10.5}, 422),
    ({"lead_in": -1}, 422),
    ({"tail_out": -1}, 422),
    ({"gain_db": 24.5}, 422),
    ({"gain_db": -24.5}, 422),
    ({"profile_id": "missing"}, 422),
]


@pytest.mark.parametrize(("change", "status"), RULES)
async def test_recipe_validation_rules(
    idle: Client, repo: Repository, paths: Paths, change: dict[str, Any], status: int
):
    clip_id = fake_clip(repo, paths)
    before = repo.get_clip(clip_id)
    for method, url in [("put", "recipe"), ("post", "preview")]:
        response = await idle.request(method, f"/api/ui/clips/{clip_id}/{url}", json=change)
        assert response.status_code == status, response.text
        assert isinstance(response.json()["detail"], str)
    after = repo.get_clip(clip_id)
    assert after.recipe == before.recipe and after.render_pending is False


async def test_recipe_boundaries_are_accepted(idle: Client, repo: Repository, paths: Paths):
    repo.create_normalization_profile(
        NormalizationProfileCreate(id="calm", name="Calm", target_lufs=-20, true_peak=-1.5, lra=7)
    )
    clip_id = fake_clip(repo, paths)
    recipe = {
        "trim_start": 5,
        "trim_end": 60.05,
        "crop": {"x": 1856, "y": 1016, "w": 64, "h": 64},
        "fade_in": 27.5,
        "fade_out": 27.5,
        "gain_db": -24,
        "profile_id": "calm",
        "lead_in": 10,
        "tail_out": 0,
    }
    response = await idle.put(f"/api/ui/clips/{clip_id}/recipe", json=recipe)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["clip"]["recipe"] == {**recipe}
    assert body["clip"]["render_pending"] is True
    assert body["job"]["kind"] == "render" and body["job"]["clip_id"] == clip_id
    assert [(j["kind"], j["status"]) for j in (await idle.get("/api/ui/jobs")).json()] == [
        ("render", "queued")
    ]
    cleared = await idle.put(f"/api/ui/clips/{clip_id}/recipe", json={"profile_id": None})
    assert cleared.status_code == 200 and cleared.json()["clip"]["recipe"]["profile_id"] is None


async def test_recipe_needs_a_probed_original(idle: Client, repo: Repository):
    clip = repo.create_clip(
        clip_id=None,
        collection_id="regular",
        title="Fresh",
        source_name="fresh.mp4",
        recipe=Recipe(),
        original=None,
        sort_key="fresh",
    )
    for method, url in [("put", "recipe"), ("post", "preview")]:
        response = await idle.request(method, f"/api/ui/clips/{clip.id}/{url}", json={})
        assert response.status_code == 422
    assert (await idle.put("/api/ui/clips/unknown/recipe", json={})).status_code == 404


async def test_rerender_queues_a_render(idle: Client, repo: Repository, paths: Paths):
    clip_id = fake_clip(repo, paths)
    response = await idle.post(f"/api/ui/clips/{clip_id}/rerender")
    assert response.status_code == 200 and response.json()["job"]["kind"] == "render"
    assert (await idle.post("/api/ui/clips/unknown/rerender")).status_code == 404
    fresh = repo.create_clip(
        clip_id=None,
        collection_id="regular",
        title="Fresh",
        source_name="fresh.mp4",
        recipe=Recipe(),
        original=None,
        sort_key="fresh",
        needs_source=True,
        status="failed",
    )
    assert (await idle.post(f"/api/ui/clips/{fresh.id}/rerender")).status_code == 422


# --- preview ---------------------------------------------------------------------------------


async def test_preview_renders_without_publishing(live: Client, app: FastAPI, make_video: Video):
    clip = await ready_clip(live, app, make_video)
    assert clip["has_preview"] is False
    assert (await live.get(f"/api/ui/clips/{clip['id']}/preview")).status_code == 404
    response = await live.post(
        f"/api/ui/clips/{clip['id']}/preview", json={**clip["recipe"], "trim_end": 3}
    )
    assert response.status_code == 200 and response.json()["job"]["kind"] == "preview"
    await app.state.jobs.wait_idle()
    after = (await live.get(f"/api/ui/clips/{clip['id']}")).json()
    assert after["has_preview"] is True
    assert after["render"] == clip["render"] and after["recipe"] == clip["recipe"]
    video = await live.get(f"/api/ui/clips/{clip['id']}/preview")
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
    assert video.content[4:8] == b"ftyp"


# --- streams ---------------------------------------------------------------------------------


@pytest.mark.parametrize("what", ["original", "render"])
async def test_streams_serve_ranges(live: Client, app: FastAPI, make_video: Video, what: str):
    clip = await ready_clip(live, app, make_video)
    url = f"/api/ui/clips/{clip['id']}/{what}"
    full = await live.get(url)
    assert full.status_code == 200 and full.headers["content-type"] == "video/mp4"
    assert full.headers["accept-ranges"] == "bytes"
    part = await live.get(url, headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.content == full.content[:100]
    assert part.headers["content-range"] == f"bytes 0-99/{len(full.content)}"
    tail = await live.get(url, headers={"Range": "bytes=100-"})
    assert tail.status_code == 206 and tail.content == full.content[100:]


async def test_render_stream_is_the_published_file(idle: Client, repo: Repository, paths: Paths):
    clip_id = fake_clip(repo, paths)
    response = await idle.get(f"/api/ui/clips/{clip_id}/render")
    assert response.status_code == 200 and response.content == b"rendered-bytes"
    partial = await idle.get(f"/api/ui/clips/{clip_id}/render", headers={"Range": "bytes=2-4"})
    assert partial.status_code == 206 and partial.content == b"nde"


async def test_missing_streams_are_404(idle: Client, repo: Repository, paths: Paths):
    clip = repo.create_clip(
        clip_id=None,
        collection_id="regular",
        title="Bare",
        source_name="bare.mp4",
        recipe=Recipe(),
        original=None,
        sort_key="bare",
    )
    for what in (
        "original",
        "preview",
        "render",
        "poster.jpg",
        "filmstrip.json",
        "filmstrip/0.jpg",
    ):
        assert (await idle.get(f"/api/ui/clips/{clip.id}/{what}")).status_code == 404, what
        assert (await idle.get(f"/api/ui/clips/unknown/{what}")).status_code == 404, what
    published = fake_clip(repo, paths, title="Published")
    render_file = next((paths.renders_dir / published).iterdir())
    render_file.unlink()
    assert (await idle.get(f"/api/ui/clips/{published}/render")).status_code == 404


# --- thumbnails ------------------------------------------------------------------------------


async def test_thumbnail_endpoints(live: Client, app: FastAPI, paths: Paths, make_video: Video):
    clip = await ready_clip(live, app, make_video)
    base = f"/api/ui/clips/{clip['id']}"
    n = clip["render"]["n"]
    thumbs = paths.thumbs_dir / clip["id"]
    assert (thumbs / f"r{n}" / "poster.jpg").is_file()

    # The poster of the published render wins; the original's is the fallback.
    rendered = (thumbs / f"r{n}" / "poster.jpg").read_bytes()
    original = (thumbs / "original" / "poster.jpg").read_bytes()
    assert rendered != original
    assert (await live.get(base + "/poster.jpg")).content == rendered
    shutil.rmtree(thumbs / f"r{n}")
    assert (await live.get(base + "/poster.jpg")).content == original

    meta = (await live.get(base + "/filmstrip.json")).json()
    assert set(meta) == {"interval", "count", "width", "height"}
    first = await live.get(base + "/filmstrip/0.jpg")
    assert first.status_code == 200 and first.headers["content-type"] == "image/jpeg"
    assert first.content[:3] == b"\xff\xd8\xff"
    assert (await live.get(base + f"/filmstrip/{meta['count'] - 1}.jpg")).status_code == 200
    assert (await live.get(base + f"/filmstrip/{meta['count']}.jpg")).status_code == 404
    assert (await live.get(base + "/filmstrip/-1.jpg")).status_code == 404
    assert (await live.get(base + "/filmstrip/x.jpg")).status_code == 422


# --- test on device --------------------------------------------------------------------------


@pytest.fixture
def device(app: FastAPI, repo: Repository) -> FakeSupervisor:
    repo.update_settings(Settings(test_targets=[TestTarget(**TARGET)]))
    supervisor = FakeSupervisor()
    app.state.supervisor = supervisor
    return supervisor


async def test_test_on_device_plays_the_published_render(
    idle: Client, repo: Repository, paths: Paths, device: FakeSupervisor
):
    clip_id = fake_clip(repo, paths)
    render = repo.get_clip(clip_id).render
    assert render is not None
    response = await idle.post(
        f"/api/ui/clips/{clip_id}/test", json={"target_id": "den", "source": "render"}
    )
    expected = MEDIA_SOURCE + render.relative_path
    assert response.status_code == 200
    assert response.json() == {"ok": True, "media_content_id": expected}
    assert expected == (
        f"media-source://media_source/local/cinema-studio/renders/{clip_id}/"
        f"{Path(render.relative_path).name}"
    )
    assert device.calls == [
        (
            "media_player",
            "play_media",
            {
                "entity_id": "media_player.den",
                "media_content_id": expected,
                "media_content_type": "video",
            },
        )
    ]


async def test_test_on_device_copies_the_preview(
    idle: Client, repo: Repository, paths: Paths, device: FakeSupervisor
):
    clip_id = fake_clip(repo, paths)
    preview = paths.work_dir / "previews" / f"{clip_id}.mp4"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"preview-bytes")
    response = await idle.post(
        f"/api/ui/clips/{clip_id}/test", json={"target_id": "den", "source": "preview"}
    )
    assert response.status_code == 200
    media_id = response.json()["media_content_id"]
    pattern = (
        rf"^{re.escape(MEDIA_SOURCE)}cinema-studio/renders/_test/{clip_id}-[0-9a-f]{{8}}\.mp4$"
    )
    assert re.fullmatch(pattern, media_id)
    copy = paths.media_dir / media_id.removeprefix(MEDIA_SOURCE)
    assert copy.read_bytes() == b"preview-bytes" and preview.is_file()
    assert device.calls[0][2]["media_content_id"] == media_id
    # A second test gets its own copy.
    again = await idle.post(
        f"/api/ui/clips/{clip_id}/test", json={"target_id": "den", "source": "preview"}
    )
    assert again.json()["media_content_id"] != media_id
    assert len(list((paths.renders_dir / "_test").iterdir())) == 2


async def test_test_on_device_errors(
    idle: Client, app: FastAPI, repo: Repository, paths: Paths, device: FakeSupervisor
):
    clip_id = fake_clip(repo, paths)
    url = f"/api/ui/clips/{clip_id}/test"
    render = {"target_id": "den", "source": "render"}
    assert (await idle.post(url, json={**render, "target_id": "nope"})).status_code == 404
    assert (await idle.post(url, json={**render, "source": "other"})).status_code == 422
    # No preview yet.
    assert (await idle.post(url, json={**render, "source": "preview"})).status_code == 404
    assert (await idle.post("/api/ui/clips/unknown/test", json=render)).status_code == 404
    assert device.calls == []

    device.error = SupervisorError("boom")
    assert (await idle.post(url, json=render)).status_code == 502
    device.error = None

    app.state.supervisor = SupervisorClient(None)
    unavailable = await idle.post(url, json=render)
    assert unavailable.status_code == 503 and "Supervisor" in unavailable.json()["detail"]
    assert not (paths.renders_dir / "_test").exists()


async def test_render_source_needs_a_published_render(
    idle: Client, repo: Repository, device: FakeSupervisor
):
    clip = repo.create_clip(
        clip_id=None,
        collection_id="regular",
        title="Unrendered",
        source_name="u.mp4",
        recipe=Recipe(),
        original=original_info(),
        sort_key="u",
    )
    response = await idle.post(
        f"/api/ui/clips/{clip.id}/test", json={"target_id": "den", "source": "render"}
    )
    assert response.status_code == 404 and device.calls == []


@pytest.mark.parametrize(
    "entity", ["media_player.otocuma_dp", "cover.garage", "remote.tv", "switch.plug", "light.x"]
)
async def test_protected_and_foreign_entities_are_refused(
    idle: Client,
    app: FastAPI,
    repo: Repository,
    paths: Paths,
    device: FakeSupervisor,
    monkeypatch: pytest.MonkeyPatch,
    entity: str,
):
    # Settings validation already blocks these; the endpoint must not rely on it, so build
    # settings that bypass validation as a hand-edited database could.
    unsafe = Settings.model_construct(
        test_targets=[TestTarget.model_construct(id="bad", label="Bad", entity_id=entity)],
        protected_entities=["media_player.otocuma_dp", "cover.ocl_screen_projector"],
    )
    monkeypatch.setattr(repo, "get_settings", lambda: unsafe)
    clip_id = fake_clip(repo, paths)
    response = await idle.post(
        f"/api/ui/clips/{clip_id}/test", json={"target_id": "bad", "source": "render"}
    )
    assert response.status_code == 403 and device.calls == []


# --- clip metadata and bulk ------------------------------------------------------------------


def other_collection(repo: Repository, small_profile_settings: dict[str, object]) -> str:
    repo.create_processing_profile(
        ProcessingProfileCreate(id="alt", name="Alt", settings=small_profile_settings)
    )
    repo.create_collection(CollectionCreate(name="Alt", processing_profile_id="alt"))
    return "alt"


async def test_patch_clip(
    idle: Client, repo: Repository, paths: Paths, small_profile_settings: dict[str, object]
):
    clip_id = fake_clip(repo, paths)
    renamed = await idle.patch(
        f"/api/ui/clips/{clip_id}", json={"title": "Renamed", "enabled": False, "notes": "n"}
    )
    assert renamed.status_code == 200
    assert (renamed.json()["title"], renamed.json()["enabled"]) == ("Renamed", False)
    assert repo.get_clip(clip_id).render_pending is False
    target = other_collection(repo, small_profile_settings)
    assert (
        await idle.patch(f"/api/ui/clips/{clip_id}", json={"collection_id": "nope"})
    ).status_code == 422
    moved = await idle.patch(f"/api/ui/clips/{clip_id}", json={"collection_id": target})
    assert moved.json()["collection_id"] == target and moved.json()["render_pending"] is True
    assert [j["kind"] for j in (await idle.get("/api/ui/jobs")).json()] == ["render"]
    assert (await idle.patch("/api/ui/clips/unknown", json={"title": "x"})).status_code == 404
    assert (await idle.patch(f"/api/ui/clips/{clip_id}", json={"bogus": 1})).status_code == 422


async def test_bulk_enable_and_collection(
    idle: Client, repo: Repository, paths: Paths, small_profile_settings: dict[str, object]
):
    first, second = fake_clip(repo, paths, title="A"), fake_clip(repo, paths, title="B")
    target = other_collection(repo, small_profile_settings)
    off = await idle.post(
        "/api/ui/clips/bulk", json={"ids": [first, second], "set": {"enabled": False}}
    )
    assert off.json() == {"updated": 2, "queued": 0}
    assert not repo.get_clip(first).enabled and not repo.get_clip(second).enabled
    moved = await idle.post(
        "/api/ui/clips/bulk", json={"ids": [first, "ghost"], "set": {"collection_id": target}}
    )
    assert moved.json() == {"updated": 1, "queued": 1}  # another processing profile: re-render
    assert repo.get_clip(first).collection_id == target and repo.get_clip(first).render_pending
    assert repo.get_clip(second).collection_id == "regular"
    same = await idle.post(
        "/api/ui/clips/bulk", json={"ids": [second], "set": {"collection_id": "regular"}}
    )
    assert same.json() == {"updated": 1, "queued": 0}
    bad = await idle.post(
        "/api/ui/clips/bulk", json={"ids": [first], "set": {"collection_id": "nope"}}
    )
    assert bad.status_code == 422


async def test_bulk_profile_sets_and_clears_the_override(
    idle: Client, repo: Repository, paths: Paths
):
    repo.create_normalization_profile(
        NormalizationProfileCreate(id="calm", name="Calm", target_lufs=-20, true_peak=-1.5, lra=7)
    )
    first, second = fake_clip(repo, paths, title="A"), fake_clip(repo, paths, title="B")
    response = await idle.post(
        "/api/ui/clips/bulk", json={"ids": [first, second, first], "set": {"profile_id": "calm"}}
    )
    assert response.json() == {"updated": 2, "queued": 2}
    assert {repo.get_clip(c).recipe.profile_id for c in (first, second)} == {"calm"}
    assert all(repo.get_clip(c).render_pending for c in (first, second))
    jobs = [j for j in (await idle.get("/api/ui/jobs")).json() if j["kind"] == "render"]
    assert sorted(j["clip_id"] for j in jobs) == sorted([first, second])
    cleared = await idle.post(
        "/api/ui/clips/bulk", json={"ids": [first], "set": {"profile_id": None}}
    )
    assert cleared.json() == {"updated": 1, "queued": 1}
    assert repo.get_clip(first).recipe.profile_id is None
    assert repo.get_clip(second).recipe.profile_id == "calm"


async def test_bulk_profile_validates_before_changing_anything(
    idle: Client, repo: Repository, paths: Paths
):
    clip_id = fake_clip(repo, paths)
    unknown_profile = await idle.post(
        "/api/ui/clips/bulk",
        json={"ids": [clip_id], "set": {"profile_id": "nope", "enabled": False}},
    )
    assert unknown_profile.status_code == 422
    unknown_clip = await idle.post(
        "/api/ui/clips/bulk",
        json={"ids": [clip_id, "ghost"], "set": {"profile_id": None, "enabled": False}},
    )
    assert unknown_clip.status_code == 404
    clip = repo.get_clip(clip_id)
    assert clip.enabled and not clip.render_pending


# --- source repair ---------------------------------------------------------------------------


def needs_source_clip(repo: Repository, recipe: Recipe | None = None) -> str:
    clip = repo.create_clip(
        clip_id=None,
        collection_id="regular",
        title="Legacy",
        source_name="legacy.mp4",
        recipe=recipe or Recipe(),
        original=None,
        sort_key="legacy",
        needs_source=True,
        status="failed",
    )
    repo.set_status(clip.id, "failed", "needs source")
    return clip.id


async def test_source_repair_restores_a_needs_source_clip(
    live: Client, app: FastAPI, repo: Repository, paths: Paths, make_video: Video
):
    clip_id = needs_source_clip(repo)
    source = make_video(name="Fixed.MP4", seconds=3)
    upload_id = await start_upload(live, source)
    response = await live.post(f"/api/ui/clips/{clip_id}/source", json={"upload_id": upload_id})
    assert response.status_code == 200, response.text
    clip = response.json()
    assert clip["needs_source"] is False and clip["render_pending"] is True
    assert clip["status"] == "processing" and clip["error"] is None
    assert clip["original"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (
        Path(clip["original"]["filename"]).name == "Fixed.mp4"
        and clip["original"]["size"] == source.stat().st_size
    )
    assert (paths.originals_dir / clip_id / clip["original"]["filename"]).is_file()
    assert sorted(p.name for p in paths.originals_dir.iterdir()) == [clip_id]
    assert not list(paths.work_dir.glob("upload-*")) and not list(paths.uploads_dir.iterdir())

    queued = {j["kind"] for j in (await live.get("/api/ui/jobs")).json() if j["clip_id"] == clip_id}
    assert {"render", "thumbs"} <= queued
    await app.state.jobs.wait_idle()
    done = repo.get_clip(clip_id)
    assert done.status == "ready" and done.render is not None and not done.render_pending
    assert done.has_thumbs


async def test_source_repair_replaces_a_good_source(
    live: Client, app: FastAPI, repo: Repository, paths: Paths, make_video: Video
):
    clip = await ready_clip(live, app, make_video)
    old_poster = (paths.thumbs_dir / clip["id"] / "original" / "poster.jpg").read_bytes()
    replacement = make_video(name="other.mp4", seconds=3, width=192, height=108)
    upload_id = await start_upload(live, replacement)
    response = await live.post(f"/api/ui/clips/{clip['id']}/source", json={"upload_id": upload_id})
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["original"]["sha256"] != clip["original"]["sha256"]
    assert updated["original"]["width"] == 192 and updated["status"] == "ready"
    assert updated["render"]["id"] == clip["render"]["id"]  # old render stays until the new one
    assert (paths.originals_dir / clip["id"] / updated["original"]["filename"]).is_file()
    await app.state.jobs.wait_idle()
    final = repo.get_clip(clip["id"])
    assert final.render is not None and final.render.id != clip["render"]["id"]
    assert not final.render_pending
    assert (paths.thumbs_dir / clip["id"] / "original" / "poster.jpg").read_bytes() != old_poster


async def test_source_repair_rejections_keep_the_original(
    live: Client, app: FastAPI, repo: Repository, paths: Paths, make_video: Video, tmp_path: Path
):
    clip = await ready_clip(live, app, make_video)
    url = f"/api/ui/clips/{clip['id']}/source"
    before = (paths.originals_dir / clip["id"] / clip["original"]["filename"]).read_bytes()

    def unchanged() -> None:
        current = repo.get_clip(clip["id"])
        assert (
            current.original is not None and current.original.sha256 == clip["original"]["sha256"]
        )
        files = list((paths.originals_dir / clip["id"]).iterdir())
        assert [f.read_bytes() for f in files] == [before]
        assert sorted(p.name for p in paths.originals_dir.iterdir()) == [clip["id"]]

    assert (await live.post(url, json={"upload_id": "unknown"})).status_code == 404
    partial = (await live.post("/api/ui/uploads", json={"filename": "x.mp4", "size": 3})).json()
    assert (await live.post(url, json={"upload_id": partial["upload_id"]})).status_code == 422
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"junk" * 10000)
    not_video = await live.post(url, json={"upload_id": await start_upload(live, junk)})
    assert not_video.status_code == 422 and "video" in not_video.json()["detail"]
    assert (
        await live.post("/api/ui/clips/unknown/source", json={"upload_id": "x"})
    ).status_code == 404
    unchanged()

    # A source too short for the clip's trim is refused rather than silently breaking the recipe.
    await live.put(f"/api/ui/clips/{clip['id']}/recipe", json={**clip["recipe"], "trim_start": 3.5})
    await app.state.jobs.wait_idle()
    short = make_video(name="short.mp4", seconds=2)
    refused = await live.post(url, json={"upload_id": await start_upload(live, short)})
    assert refused.status_code == 422 and "Trim" in refused.json()["detail"]
    assert repo.get_clip(clip["id"]).original == OriginalInfo(**clip["original"])
    assert [f.name for f in (paths.originals_dir / clip["id"]).iterdir()] == [
        clip["original"]["filename"]
    ]
    assert sorted(p.name for p in paths.originals_dir.iterdir()) == [clip["id"]]


async def test_source_swap_failure_leaves_the_old_original(
    live: Client,
    app: FastAPI,
    repo: Repository,
    paths: Paths,
    make_video: Video,
    monkeypatch: pytest.MonkeyPatch,
):
    clip = await ready_clip(live, app, make_video)
    url = f"/api/ui/clips/{clip['id']}/source"
    upload_id = await start_upload(live, make_video(name="next.mp4", seconds=2))

    def explode(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(repo, "replace_original", explode)
    with pytest.raises(OSError, match="disk full"):
        await live.post(url, json={"upload_id": upload_id})
    assert [p.name for p in (paths.originals_dir / clip["id"]).iterdir()] == [
        clip["original"]["filename"]
    ]
    assert sorted(p.name for p in paths.originals_dir.iterdir()) == [clip["id"]]
    assert repo.get_clip(clip["id"]).original == OriginalInfo(**clip["original"])
    assert not list(paths.work_dir.glob("upload-*"))


# --- delete ----------------------------------------------------------------------------------


async def test_delete_clip_removes_files_and_retires_the_render(
    live: Client, app: FastAPI, repo: Repository, paths: Paths, make_video: Video
):
    clip = await ready_clip(live, app, make_video)
    await live.post(f"/api/ui/clips/{clip['id']}/preview", json=clip["recipe"])
    await app.state.jobs.wait_idle()
    render_file = paths.media_dir / clip["render"]["relative_path"]
    preview = paths.work_dir / "previews" / f"{clip['id']}.mp4"
    assert preview.is_file() and render_file.is_file()
    assert (paths.thumbs_dir / clip["id"]).is_dir() and (paths.originals_dir / clip["id"]).is_dir()

    response = await live.delete(f"/api/ui/clips/{clip['id']}")
    assert response.status_code == 204
    assert not (paths.originals_dir / clip["id"]).exists()
    assert not (paths.thumbs_dir / clip["id"]).exists() and not preview.exists()
    assert render_file.is_file()  # the garbage collector removes it later
    assert [r.state for r in repo.list_renders() if r.clip_id == clip["id"]] == ["retired"]
    assert (await live.get(f"/api/ui/clips/{clip['id']}")).status_code == 404
    assert (await live.delete(f"/api/ui/clips/{clip['id']}")).status_code == 404
    assert (await live.get("/api/ui/clips")).json() == []


# --- jobs ------------------------------------------------------------------------------------


async def test_jobs_list_running_then_queued_then_finished(
    idle: Client, app: FastAPI, repo: Repository, paths: Paths
):
    first, second = fake_clip(repo, paths, title="A"), fake_clip(repo, paths, title="B")
    for clip_id in (first, second):
        assert (await idle.post(f"/api/ui/clips/{clip_id}/rerender")).status_code == 200
    thumbs = app.state.jobs.enqueue_thumbs(first)
    jobs = (await idle.get("/api/ui/jobs")).json()
    assert [(j["kind"], j["clip_id"], j["status"]) for j in jobs] == [
        ("render", first, "queued"),
        ("render", second, "queued"),
        ("thumbs", first, "queued"),
    ]
    assert jobs[2]["id"] == thumbs.id
    assert {"id", "kind", "clip_id", "clip_title", "status", "progress", "error"} <= set(jobs[0])


async def test_finished_jobs_are_newest_first(live: Client, app: FastAPI, make_video: Video):
    await ready_clip(live, app, make_video)
    kinds = [j["kind"] for j in (await live.get("/api/ui/jobs")).json()]
    assert kinds[0] == "thumbs" and kinds[-1] == "probe"
    assert set(kinds) == {"probe", "render", "thumbs"}


@pytest.mark.parametrize(
    "kind", ["original", "preview", "render", "poster.jpg", "filmstrip.json", "filmstrip/0.jpg"]
)
async def test_media_symlinks_rejected(
    idle: Client, repo: Repository, paths: Paths, tmp_path: Path, kind: str
):
    clip_id = fake_clip(repo, paths)
    clip = repo.get_clip(clip_id)
    assert clip.render is not None
    root = paths.thumbs_dir / clip_id / "original"
    root.mkdir(parents=True)
    (root / "filmstrip.json").write_text('{"count":1}')
    candidates = {
        "original": paths.originals_dir / clip_id / "movie.mp4",
        "preview": paths.work_dir / "previews" / f"{clip_id}.mp4",
        "render": paths.media_dir / clip.render.relative_path,
        "poster.jpg": root / "poster.jpg",
        "filmstrip.json": root / "filmstrip.json",
        "filmstrip/0.jpg": root / "0000.jpg",
    }
    outside = tmp_path / "secret"
    outside.write_bytes(b"secret")
    target = candidates[kind]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    target.symlink_to(outside)
    assert (await idle.get(f"/api/ui/clips/{clip_id}/{kind}")).status_code == 422


async def test_delete_cleanup_failure_logged(
    idle: Client,
    repo: Repository,
    paths: Paths,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    clip_id = fake_clip(repo, paths)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("cleanup denied")

    monkeypatch.setattr(api_ui_clips.shutil, "rmtree", fail)
    assert (await idle.delete(f"/api/ui/clips/{clip_id}")).status_code == 204
    assert "cleanup denied" in caplog.text


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("versioned", [False, True])
async def test_replacement_placement_keeps_old_readable_and_settles(
    idle: Client,
    app: FastAPI,
    repo: Repository,
    paths: Paths,
    make_video: Video,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
    versioned: bool,
):
    clip_id = fake_clip(repo, paths)
    old = repo.get_clip(clip_id)
    assert old.original is not None
    if versioned:
        repo.set_original(
            clip_id, old.original.model_copy(update={"filename": "v" + "a" * 32 + "/movie.mp4"})
        )
        old = repo.get_clip(clip_id)
        assert old.original is not None
    original_path = paths.originals_dir / clip_id / old.original.filename
    original_path.parent.mkdir(parents=True, exist_ok=True)
    original_path.write_bytes(b"old source")
    monkeypatch.setattr(uploads, "CHUNK_SIZE", CHUNK)
    monkeypatch.setattr(api_ui_clips, "CHUNK_SIZE", CHUNK)
    upload_id = await start_upload(idle, make_video(name="replacement.mp4", seconds=2))
    placed = threading.Event()
    release = threading.Event()
    store = app.state.store
    real_store = store.store_original

    def pause(*args: Any, **kwargs: Any) -> Path:
        result: Path = real_store(*args, **kwargs)
        placed.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(store, "store_original", pause)
    task = asyncio.create_task(
        idle.post(f"/api/ui/clips/{clip_id}/source", json={"upload_id": upload_id})
    )
    try:
        assert await asyncio.to_thread(placed.wait, 10)
        assert repo.get_clip(clip_id).original == old.original
        response = await idle.get(f"/api/ui/clips/{clip_id}/original")
        assert response.content == b"old source"
        if cancel:
            task.cancel()
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await task).status_code == 200
        current = repo.get_clip(clip_id)
        assert current.original is not None
        assert re.fullmatch(r"v[0-9a-f]{32}/replacement.mp4", current.original.filename)
        assert (paths.originals_dir / clip_id / current.original.filename).is_file()
        assert not original_path.exists()
        if versioned:
            assert not original_path.parent.exists()
        assert current.render_pending and not current.needs_source
        assert {job.kind for job in app.state.jobs.list_jobs()} == {"thumbs", "render"}
    finally:
        release.set()
        if not task.done():
            await task


@pytest.mark.parametrize("source", ["preview", "render"])
async def test_device_symlink_rejected(
    idle: Client,
    repo: Repository,
    paths: Paths,
    device: FakeSupervisor,
    tmp_path: Path,
    source: str,
):
    clip_id = fake_clip(repo, paths)
    clip = repo.get_clip(clip_id)
    assert clip.render is not None
    target = (
        paths.work_dir / "previews" / f"{clip_id}.mp4"
        if source == "preview"
        else paths.media_dir / clip.render.relative_path
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    outside = tmp_path / "secret"
    outside.write_bytes(b"secret")
    target.symlink_to(outside)
    response = await idle.post(
        f"/api/ui/clips/{clip_id}/test", json={"target_id": "den", "source": source}
    )
    assert response.status_code == 422
    assert device.calls == []
    assert not (paths.renders_dir / "_test").exists()


async def test_source_transaction_failure_rolls_back_placed_version(
    live: Client,
    app: FastAPI,
    repo: Repository,
    paths: Paths,
    make_video: Video,
):
    clip = await ready_clip(live, app, make_video)
    before = repo.get_clip(clip["id"])
    upload_id = await start_upload(live, make_video(name="new.mp4", seconds=2))
    app.state.db.connection.execute(
        "CREATE TRIGGER reject_source BEFORE UPDATE OF original ON clips "
        "BEGIN SELECT RAISE(ABORT, 'source commit failed'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="source commit failed"):
        await live.post(f"/api/ui/clips/{clip['id']}/source", json={"upload_id": upload_id})
    assert repo.get_clip(clip["id"]) == before
    assert not list((paths.originals_dir / clip["id"]).glob("v*"))
    assert not list(paths.work_dir.glob("upload-*"))
    original = before.original
    assert original is not None
    assert (paths.originals_dir / clip["id"] / original.filename).is_file()
    assert not any(job.status == "queued" for job in app.state.jobs.list_jobs())
