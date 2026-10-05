"""Ingress API for state, settings, organization, profiles, assets and garbage collection."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from cinema_studio import api_ui_organize
from cinema_studio.app import create_app
from cinema_studio.auth import INGRESS_PEER
from cinema_studio.config import Paths
from cinema_studio.models import (
    CollectionCreate,
    CollectionUpdate,
    NormalizationProfileCreate,
    OriginalInfo,
    ProcessingProfileCreate,
    Recipe,
    RenderRecord,
    SeasonCreate,
)
from cinema_studio.repository import Repository

pytestmark = pytest.mark.studio

DEFAULT = "compatibility-4k-loudness"


@pytest.fixture
def app(paths: Paths) -> Iterator[FastAPI]:
    application = create_app(paths, start_background=False)
    application.state.store.ensure_dirs()
    yield application
    application.state.db.close()


@pytest.fixture
def ingress(app: FastAPI) -> TestClient:
    return TestClient(app, client=(INGRESS_PEER, 50000))


@pytest.fixture
def repo(app: FastAPI) -> Repository:
    return app.state.repo


def make_clip(repo: Repository, collection_id: str = "regular", title: str = "Movie") -> str:
    """A clip with a published render, so a recipe or profile edit visibly marks it pending."""
    clip = repo.create_clip(
        clip_id=None,
        collection_id=collection_id,
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


def pending(repo: Repository) -> set[str]:
    return {clip.id for clip in repo.list_clips() if clip.render_pending}


def queued_renders(app: FastAPI) -> set[str]:
    return {
        job.clip_id
        for job in app.state.jobs.list_jobs()
        if job.kind == "render" and job.status == "queued" and job.clip_id is not None
    }


# --- state, token ----------------------------------------------------------------------------


def test_state_shape_and_masked_token(ingress: TestClient, app: FastAPI, repo: Repository):
    token = app.state.tokens.get()
    response = ingress.get("/api/ui/state")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "version",
        "api_token_masked",
        "catalog_revision",
        "discovery",
        "storage",
        "gc",
        "consumers",
        "legacy_import",
        "settings",
    }
    assert body["version"] == app.version
    assert body["api_token_masked"] == app.state.tokens.masked() != token
    assert body["catalog_revision"] == repo.catalog_revision()
    assert body["discovery"] == app.state.discovery_status
    assert set(body["storage"]) == {
        "free_bytes",
        "originals_bytes",
        "renders_bytes",
        "retired_bytes",
        "work_bytes",
        "network_fs",
    }
    assert body["gc"] == {
        "enabled": True,
        "halted_reason": None,
        "last_run_at": None,
        "deleted_last_run": 0,
    }
    assert body["consumers"] == []
    assert body["legacy_import"] is None
    assert body["settings"] == repo.get_settings().model_dump(mode="json")
    assert token not in response.text


def test_state_consumers_union_of_seen_and_files(
    ingress: TestClient, app: FastAPI, repo: Repository, paths: Paths
):
    repo.touch_consumer("seen-only", 3)
    repo.touch_consumer("both", 4)
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    for consumer_id, revision, pins in (("both", 7, 2), ("file-only", 9, 0)):
        (paths.consumers_dir / f"{consumer_id}.json").write_text(
            json.dumps(
                {
                    "consumer_id": consumer_id,
                    "generation": "g",
                    "seq": 1,
                    "written_at": datetime.now(UTC).isoformat(),
                    "held_revision": revision,
                    "held_render_ids": [],
                    "pins": [
                        {"render_id": f"{'a' * 31}{i}", "expires_at": expires} for i in range(pins)
                    ],
                }
            ),
            encoding="utf-8",
        )
    rows = {row["consumer_id"]: row for row in ingress.get("/api/ui/state").json()["consumers"]}
    assert set(rows) == {"seen-only", "both", "file-only"}
    assert rows["seen-only"]["file_present"] is False
    assert rows["seen-only"]["held_revision"] is None
    assert rows["seen-only"]["pins"] == 0
    assert rows["seen-only"]["last_seen_at"] is not None
    assert rows["both"] | {"last_seen_at": None} == {
        "consumer_id": "both",
        "last_seen_at": None,
        "held_revision": 7,
        "file_present": True,
        "pins": 2,
    }
    assert rows["both"]["last_seen_at"] is not None
    assert rows["file-only"]["last_seen_at"] is None
    assert rows["file-only"]["file_present"] is True


def test_state_lists_an_unparseable_consumer_file(ingress: TestClient, paths: Paths):
    (paths.consumers_dir / "broken.json").write_text("{nope", encoding="utf-8")
    [row] = ingress.get("/api/ui/state").json()["consumers"]
    assert row == {
        "consumer_id": "broken",
        "last_seen_at": None,
        "held_revision": None,
        "file_present": True,
        "pins": 0,
    }


def test_state_gc_reflects_the_last_run(ingress: TestClient, repo: Repository):
    repo.touch_consumer("ghost", None)  # seen, but no file: GC halts
    result = ingress.post("/api/ui/gc/run").json()
    assert result["halted_reason"] == "missing consumer files: ghost"
    gc = ingress.get("/api/ui/state").json()["gc"]
    assert gc["halted_reason"] == "missing consumer files: ghost"
    assert gc["deleted_last_run"] == 0
    assert gc["last_run_at"] is not None
    assert gc["enabled"] is True


def test_state_includes_the_last_legacy_report(ingress: TestClient, repo: Repository):
    from cinema_studio.models import LegacyReport

    report = LegacyReport(
        run_id="run1",
        started_at="2026-10-03T12:00:00Z",
        finished_at="2026-10-03T12:01:00Z",
        catalog_revision=2,
        imported=["a"],
        queued_for_render=[],
        needs_source=[],
        skipped=[],
        missing_assets=[],
    )
    repo.save_legacy_report(report)
    assert ingress.get("/api/ui/state").json()["legacy_import"] == report.model_dump(mode="json")


def test_token_and_rotate(ingress: TestClient, app: FastAPI):
    token = app.state.tokens.get()
    assert ingress.get("/api/ui/token").json() == {"token": token}
    rotated = ingress.post("/api/ui/token/rotate")
    assert rotated.status_code == 200
    assert app.state.tokens.get() != token
    assert rotated.json() == {"api_token_masked": app.state.tokens.masked()}


def test_token_rotate_republishes_discovery_when_supervisor_is_available(
    ingress: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
):
    calls: list[FastAPI] = []

    async def publish(application: FastAPI) -> None:
        calls.append(application)

    monkeypatch.setattr(api_ui_organize, "publish_discovery", publish)
    assert ingress.post("/api/ui/token/rotate").status_code == 200
    assert calls == []
    app.state.supervisor = type("Available", (), {"available": True})()
    assert ingress.post("/api/ui/token/rotate").status_code == 200
    assert calls == [app]


def test_ui_api_rejects_other_peers(app: FastAPI):
    denied = TestClient(app, client=("192.168.1.20", 50000))
    for path in ("/api/ui/state", "/api/ui/token", "/api/ui/settings", "/api/ui/assets"):
        response = denied.get(path)
        assert response.status_code == 403, path
        assert isinstance(response.json()["detail"], str)


# --- settings --------------------------------------------------------------------------------


def settings_body(ingress: TestClient) -> dict[str, object]:
    return ingress.get("/api/ui/settings").json()


def test_settings_round_trip(ingress: TestClient, repo: Repository):
    body = settings_body(ingress)
    assert body["protected_entities"] == ["media_player.otocuma_dp", "cover.ocl_screen_projector"]
    body["max_upload_mb"] = 512
    body["test_targets"] = [
        {"id": "den", "label": "Den", "entity_id": "media_player.den"},
        {"id": "kitchen", "label": "Kitchen", "entity_id": "media_player.kitchen"},
    ]
    saved = ingress.put("/api/ui/settings", json=body)
    assert saved.status_code == 200
    assert saved.json() == body
    assert settings_body(ingress) == body
    assert repo.get_settings().max_upload_mb == 512


@pytest.mark.parametrize(
    "entity_id", ["remote.projector", "cover.screen", "switch.x", "light.y", "media_player"]
)
def test_settings_reject_non_media_player_targets(ingress: TestClient, entity_id: str):
    body = settings_body(ingress)
    body["test_targets"] = [{"id": "t", "label": "T", "entity_id": entity_id}]
    response = ingress.put("/api/ui/settings", json=body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert settings_body(ingress)["test_targets"] == []


def test_settings_reject_protected_entity(ingress: TestClient):
    body = settings_body(ingress)
    body["test_targets"] = [{"id": "t", "label": "T", "entity_id": "media_player.otocuma_dp"}]
    response = ingress.put("/api/ui/settings", json=body)
    assert response.status_code == 422
    assert "protected" in response.json()["detail"]
    # A target only becomes legal once the entity is removed from the protected list.
    body["protected_entities"] = []
    assert ingress.put("/api/ui/settings", json=body).status_code == 200


def test_settings_reject_duplicate_target_ids(ingress: TestClient):
    body = settings_body(ingress)
    body["test_targets"] = [
        {"id": "den", "label": "Den", "entity_id": "media_player.den"},
        {"id": "den", "label": "Den 2", "entity_id": "media_player.den_2"},
    ]
    response = ingress.put("/api/ui/settings", json=body)
    assert response.status_code == 422
    assert "den" in response.json()["detail"]


# --- collections -----------------------------------------------------------------------------


def test_collection_crud_order_and_conflicts(ingress: TestClient, repo: Repository):
    assert [c["id"] for c in ingress.get("/api/ui/collections").json()] == ["regular"]
    created = ingress.post("/api/ui/collections", json={"name": "Horror Nights"})
    assert created.status_code == 200
    body = created.json()
    assert body["id"] == "horror_nights"
    assert body["processing_profile_id"] == DEFAULT
    assert body["playback_mode"] == "random"
    assert ingress.post("/api/ui/collections", json={"name": "Horror Nights"}).status_code == 409
    explicit = ingress.post("/api/ui/collections", json={"id": "kids", "name": "Kids"})
    assert explicit.json()["id"] == "kids"
    assert ingress.post("/api/ui/collections", json={"name": "X", "bogus": 1}).status_code == 422
    unknown = ingress.post(
        "/api/ui/collections", json={"name": "Odd", "processing_profile_id": "nope"}
    )
    assert unknown.status_code == 422

    first = make_clip(repo, "kids", "A")
    second = make_clip(repo, "kids", "B")
    outsider = make_clip(repo, "regular", "C")
    ordered = ingress.put(
        "/api/ui/collections/kids/order", json={"clip_ids": [second, outsider, first, second]}
    )
    assert ordered.status_code == 200
    assert ordered.json()["order"] == [second, first]  # foreign and duplicate ids dropped
    assert ingress.put("/api/ui/collections/ghost/order", json={"clip_ids": []}).status_code == 404

    renamed = ingress.patch(
        "/api/ui/collections/kids", json={"name": "Kids Club", "enabled": False}
    )
    assert renamed.status_code == 200
    assert renamed.json() == {
        "collection": {**ordered.json(), "name": "Kids Club", "enabled": False},
        "affected_clip_ids": [],
    }
    assert ingress.patch("/api/ui/collections/ghost", json={"name": "x"}).status_code == 404

    in_use = ingress.delete("/api/ui/collections/kids")
    assert in_use.status_code == 409
    for clip_id in (first, second):
        repo.delete_clip(clip_id)
    assert ingress.delete("/api/ui/collections/kids").status_code == 204
    assert ingress.delete("/api/ui/collections/kids").status_code == 404


def test_collection_get_by_id(ingress: TestClient, repo: Repository):
    repo.create_collection(CollectionCreate(id="movies", name="Movies"))
    response = ingress.get("/api/ui/collections/movies")
    assert response.status_code == 200
    assert response.json()["id"] == "movies"
    assert ingress.get("/api/ui/collections/regular").status_code == 200
    assert ingress.get("/api/ui/collections/ghost").status_code == 404


def test_collection_delete_conflicts_with_seasons_and_protects_regular(
    ingress: TestClient, repo: Repository
):
    repo.create_collection(CollectionCreate(id="xmas", name="Xmas"))
    repo.create_season(
        SeasonCreate(id="winter", name="Winter", start="12-01", end="12-31", collection_id="xmas")
    )
    response = ingress.delete("/api/ui/collections/xmas")
    assert response.status_code == 409
    assert "season" in response.json()["detail"]
    regular = ingress.delete("/api/ui/collections/regular")
    assert regular.status_code == 400
    assert isinstance(regular.json()["detail"], str)


def test_collection_profile_change_marks_exactly_its_clips_pending(
    ingress: TestClient, app: FastAPI, repo: Repository, small_profile_settings: dict[str, object]
):
    repo.create_collection(CollectionCreate(id="movies", name="Movies"))
    repo.create_collection(CollectionCreate(id="shorts", name="Shorts"))
    repo.create_processing_profile(
        ProcessingProfileCreate(id="small", name="Small", settings=small_profile_settings)
    )
    in_movies = [make_clip(repo, "movies", "M1"), make_clip(repo, "movies", "M2")]
    make_clip(repo, "shorts", "S1")
    make_clip(repo, "regular", "R1")
    assert pending(repo) == set()

    # Changing something other than the profile leaves clips alone.
    response = ingress.patch("/api/ui/collections/movies", json={"color": "#112233"})
    assert response.json()["affected_clip_ids"] == []
    assert pending(repo) == set()

    response = ingress.patch("/api/ui/collections/movies", json={"processing_profile_id": "small"})
    assert response.status_code == 200
    body = response.json()
    assert body["collection"]["processing_profile_id"] == "small"
    assert sorted(body["affected_clip_ids"]) == sorted(in_movies)
    assert pending(repo) == set(in_movies)
    assert queued_renders(app) == set(in_movies)

    # Setting the profile it already has is not a change.
    again = ingress.patch("/api/ui/collections/movies", json={"processing_profile_id": "small"})
    assert again.json()["affected_clip_ids"] == []

    unknown = ingress.patch("/api/ui/collections/movies", json={"processing_profile_id": "nope"})
    assert unknown.status_code == 422


# --- seasons ---------------------------------------------------------------------------------


def test_season_crud_resolve_and_regular_restrictions(ingress: TestClient, repo: Repository):
    repo.create_collection(CollectionCreate(id="xmas", name="Xmas"))
    assert [s["id"] for s in ingress.get("/api/ui/seasons").json()] == ["regular"]
    created = ingress.post(
        "/api/ui/seasons",
        json={
            "name": "Christmas",
            "start": "12-20",
            "end": "01-05",
            "priority": 5,
            "collection_id": "xmas",
        },
    )
    assert created.status_code == 200
    season = created.json()
    assert season["id"] == "christmas"
    assert season["builtin"] is False
    assert season["collection_id"] == "xmas"
    dup = ingress.post(
        "/api/ui/seasons",
        json={"name": "Christmas", "start": "12-20", "end": "01-05", "collection_id": "xmas"},
    )
    assert dup.status_code == 409
    bad_collection = ingress.post(
        "/api/ui/seasons",
        json={"name": "Odd", "start": "01-01", "end": "01-02", "collection_id": "ghost"},
    )
    assert bad_collection.status_code == 422
    bad_date = ingress.post(
        "/api/ui/seasons",
        json={"name": "Odd", "start": "13-01", "end": "01-02", "collection_id": "xmas"},
    )
    assert bad_date.status_code == 422

    patched = ingress.patch("/api/ui/seasons/christmas", json={"priority": 9, "color": "#ff0000"})
    assert patched.status_code == 200
    assert patched.json()["priority"] == 9
    assert patched.json()["color"] == "#ff0000"
    assert ingress.patch("/api/ui/seasons/ghost", json={"priority": 1}).status_code == 404

    inside = ingress.get("/api/ui/seasons/resolve", params={"date": "2026-12-25"})
    assert inside.status_code == 200
    assert inside.json() == {
        "date": "2026-12-25",
        "season_id": "christmas",
        "collection_id": "xmas",
    }
    wrapped = ingress.get("/api/ui/seasons/resolve", params={"date": "2027-01-02"}).json()
    assert wrapped["season_id"] == "christmas"
    outside = ingress.get("/api/ui/seasons/resolve", params={"date": "2026-06-01"}).json()
    assert outside == {"date": "2026-06-01", "season_id": "regular", "collection_id": "regular"}
    for bad in ("2026-6-1", "nope", "2026-02-30", ""):
        response = ingress.get("/api/ui/seasons/resolve", params={"date": bad})
        assert response.status_code == 422, bad
    assert ingress.get("/api/ui/seasons/resolve").status_code == 422

    assert ingress.get("/api/ui/seasons/christmas").json() == patched.json()
    assert ingress.get("/api/ui/seasons/regular").json()["builtin"] is True
    assert ingress.get("/api/ui/seasons/ghost").status_code == 404

    assert ingress.delete("/api/ui/seasons/regular").status_code == 400
    assert ingress.patch("/api/ui/seasons/regular", json={"start": "01-01"}).status_code == 422
    assert ingress.delete("/api/ui/seasons/christmas").status_code == 204
    assert ingress.delete("/api/ui/seasons/christmas").status_code == 404
    assert ingress.delete("/api/ui/collections/xmas").status_code == 204


# --- normalization profiles ------------------------------------------------------------------


def test_normalization_profile_crud_and_conflicts(ingress: TestClient, repo: Repository):
    listed = ingress.get("/api/ui/normalization-profiles").json()
    assert [p["id"] for p in listed] == ["standard", "loud", "soft", "voice"]
    assert listed[0] == {
        "id": "standard",
        "name": "Standard",
        "target_lufs": -16,
        "true_peak": -1.5,
        "lra": 11,
    }
    created = ingress.post(
        "/api/ui/normalization-profiles",
        json={"name": "Night", "target_lufs": -22, "true_peak": -2, "lra": 8},
    )
    assert created.status_code == 200
    assert created.json()["id"] == "night"
    dup = ingress.post(
        "/api/ui/normalization-profiles",
        json={"name": "Night", "target_lufs": -22, "true_peak": -2, "lra": 8},
    )
    assert dup.status_code == 409
    out_of_range = ingress.post(
        "/api/ui/normalization-profiles",
        json={"name": "Hot", "target_lufs": 0, "true_peak": -2, "lra": 8},
    )
    assert out_of_range.status_code == 422

    clip_id = make_clip(repo)
    repo.set_recipe(clip_id, Recipe(profile_id="night"))
    assert ingress.delete("/api/ui/normalization-profiles/night").status_code == 409
    repo.set_recipe(clip_id, Recipe())
    assert ingress.delete("/api/ui/normalization-profiles/night").status_code == 204
    assert ingress.delete("/api/ui/normalization-profiles/night").status_code == 404


def test_normalization_patch_marks_only_clips_using_it(
    ingress: TestClient, app: FastAPI, repo: Repository
):
    repo.create_normalization_profile(
        NormalizationProfileCreate(id="night", name="Night", target_lufs=-22, true_peak=-2, lra=8)
    )
    users = [make_clip(repo, title="U1"), make_clip(repo, title="U2")]
    make_clip(repo, title="Other")
    for clip_id in users:
        repo.set_recipe(clip_id, Recipe(profile_id="night"))
        repo.set_flags(clip_id, render_pending=False)
    assert pending(repo) == set()

    renamed = ingress.patch("/api/ui/normalization-profiles/night", json={"name": "Midnight"})
    assert renamed.status_code == 200
    assert renamed.json() == {
        "profile": {
            "id": "night",
            "name": "Midnight",
            "target_lufs": -22,
            "true_peak": -2,
            "lra": 8,
        },
        "affected_clip_ids": [],
    }
    assert pending(repo) == set()
    same = ingress.patch("/api/ui/normalization-profiles/night", json={"target_lufs": -22})
    assert same.json()["affected_clip_ids"] == []
    assert pending(repo) == set()

    changed = ingress.patch("/api/ui/normalization-profiles/night", json={"target_lufs": -24})
    assert changed.status_code == 200
    assert changed.json()["profile"]["target_lufs"] == -24
    assert sorted(changed.json()["affected_clip_ids"]) == sorted(users)
    assert pending(repo) == set(users)
    assert queued_renders(app) == set(users)
    assert ingress.patch("/api/ui/normalization-profiles/ghost", json={"lra": 5}).status_code == 404


def test_normalization_apply_to_clip_ids_and_collection(
    ingress: TestClient, app: FastAPI, repo: Repository
):
    repo.create_collection(CollectionCreate(id="movies", name="Movies"))
    a = make_clip(repo, "movies", "A")
    b = make_clip(repo, "movies", "B")
    c = make_clip(repo, "regular", "C")

    response = ingress.post("/api/ui/normalization-profiles/loud/apply", json={"clip_ids": [c, c]})
    assert response.status_code == 200
    assert response.json() == {"queued": 1}
    assert repo.get_clip(c).recipe.profile_id == "loud"
    assert pending(repo) == {c}
    assert queued_renders(app) == {c}

    response = ingress.post(
        "/api/ui/normalization-profiles/soft/apply", json={"collection_id": "movies"}
    )
    assert response.json() == {"queued": 2}
    assert {repo.get_clip(x).recipe.profile_id for x in (a, b)} == {"soft"}
    assert repo.get_clip(c).recipe.profile_id == "loud"
    assert queued_renders(app) == {a, b, c}


def test_normalization_apply_validates_before_changing_anything(
    ingress: TestClient, app: FastAPI, repo: Repository
):
    clip_id = make_clip(repo)
    url = "/api/ui/normalization-profiles/loud/apply"
    assert ingress.post(url, json={"clip_ids": [clip_id, "ghost"]}).status_code == 404
    assert repo.get_clip(clip_id).recipe.profile_id is None
    assert pending(repo) == set()
    assert queued_renders(app) == set()
    assert ingress.post(url, json={}).status_code == 422
    both = ingress.post(url, json={"clip_ids": [clip_id], "collection_id": "regular"})
    assert both.status_code == 422
    assert ingress.post(url, json={"collection_id": "ghost"}).status_code == 404
    missing = ingress.post("/api/ui/normalization-profiles/ghost/apply", json={"clip_ids": []})
    assert missing.status_code == 404


# --- processing profiles ---------------------------------------------------------------------


def test_processing_profile_crud_and_validation(
    ingress: TestClient, repo: Repository, small_profile_settings: dict[str, object]
):
    listed = ingress.get("/api/ui/processing-profiles").json()
    assert [p["id"] for p in listed] == [DEFAULT]
    assert set(listed[0]) == {"id", "name", "settings"}
    assert listed[0]["settings"]["profile_version"] == 1

    created = ingress.post(
        "/api/ui/processing-profiles",
        json={"name": "Small", "settings": small_profile_settings},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["id"] == "small"
    assert body["settings"]["video"]["width"] == 320
    assert (
        ingress.post(
            "/api/ui/processing-profiles",
            json={"name": "Small", "settings": small_profile_settings},
        ).status_code
        == 409
    )
    invalid = ingress.post(
        "/api/ui/processing-profiles",
        json={"name": "Bad", "settings": {"fade_in_seconds": -1}},
    )
    assert invalid.status_code == 422
    assert isinstance(invalid.json()["detail"], str)
    unknown_field = ingress.post(
        "/api/ui/processing-profiles", json={"name": "Odd", "settings": {"nope": 1}}
    )
    assert unknown_field.status_code == 422
    traversal = ingress.post(
        "/api/ui/processing-profiles",
        json={"name": "Trav", "settings": {"intro_reference": "../x.mp4"}},
    )
    assert traversal.status_code == 422

    repo.create_collection(
        CollectionCreate(id="movies", name="Movies", processing_profile_id="small")
    )
    assert ingress.delete("/api/ui/processing-profiles/small").status_code == 409
    assert ingress.delete("/api/ui/processing-profiles/ghost").status_code == 404
    repo.update_collection("movies", CollectionUpdate(processing_profile_id=DEFAULT))
    assert ingress.delete("/api/ui/processing-profiles/small").status_code == 204


def test_processing_profile_patch_marks_exactly_the_collections_clips(
    ingress: TestClient, app: FastAPI, repo: Repository, small_profile_settings: dict[str, object]
):
    repo.create_processing_profile(
        ProcessingProfileCreate(id="small", name="Small", settings=small_profile_settings)
    )
    repo.create_collection(
        CollectionCreate(id="movies", name="Movies", processing_profile_id="small")
    )
    in_movies = [make_clip(repo, "movies", "M1"), make_clip(repo, "movies", "M2")]
    make_clip(repo, "regular", "R1")

    renamed = ingress.patch("/api/ui/processing-profiles/small", json={"name": "Tiny"})
    assert renamed.status_code == 200
    assert renamed.json()["profile"]["name"] == "Tiny"
    assert renamed.json()["affected_clip_ids"] == []
    assert pending(repo) == set()

    settings = {**small_profile_settings, "fade_in_seconds": 0.5}
    changed = ingress.patch("/api/ui/processing-profiles/small", json={"settings": settings})
    assert changed.status_code == 200
    body = changed.json()
    assert body["profile"]["id"] == "small"
    assert body["profile"]["settings"]["fade_in_seconds"] == 0.5
    assert sorted(body["affected_clip_ids"]) == sorted(in_movies)
    assert pending(repo) == set(in_movies)
    assert queued_renders(app) == set(in_movies)

    invalid = ingress.patch(
        "/api/ui/processing-profiles/small", json={"settings": {"fade_in_seconds": -3}}
    )
    assert invalid.status_code == 422
    assert repo.get_processing_profile("small").settings["fade_in_seconds"] == 0.5
    assert ingress.patch("/api/ui/processing-profiles/ghost", json={"name": "x"}).status_code == 404


# --- assets ----------------------------------------------------------------------------------


def upload(
    ingress: TestClient, name: str, content: bytes, content_type: str = "video/mp4"
) -> Response:
    return ingress.post("/api/ui/assets", files={"file": (name, content, content_type)})


def test_asset_upload_probe_list_and_delete(
    ingress: TestClient, repo: Repository, paths: Paths, make_video: Callable[..., Path]
):
    video = make_video("intro.mp4", seconds=1.0)
    data = video.read_bytes()
    response = ingress.post("/api/ui/assets", files={"file": ("intro.mp4", data, "video/mp4")})
    assert response.status_code == 200
    body = response.json()
    assert body["affected_clip_ids"] == []
    asset = body["asset"]
    assert asset["filename"] == "intro.mp4"
    assert asset["size"] == len(data)
    assert asset["status"] == "ready"
    import hashlib

    assert asset["sha256"] == hashlib.sha256(data).hexdigest()
    assert (paths.assets_dir / "intro.mp4").read_bytes() == data
    assert list(paths.work_dir.rglob("*.mp4")) == []  # staging is cleaned up
    assert ingress.get("/api/ui/assets").json() == [asset]
    assert repo.get_asset("intro.mp4").status == "ready"

    assert ingress.delete("/api/ui/assets/intro.mp4").status_code == 204
    assert not (paths.assets_dir / "intro.mp4").exists()
    assert ingress.get("/api/ui/assets").json() == []
    assert ingress.delete("/api/ui/assets/intro.mp4").status_code == 404


def test_asset_upload_rejects_bad_extension_and_unprobeable_files(
    ingress: TestClient, paths: Paths
):
    wrong = upload(ingress, "notes.txt", b"hello", "text/plain")
    assert wrong.status_code == 415
    garbage = upload(ingress, "broken.mp4", b"this is not a video")
    assert garbage.status_code == 422
    assert isinstance(garbage.json()["detail"], str)
    assert ingress.get("/api/ui/assets").json() == []
    assert not (paths.assets_dir / "broken.mp4").exists()
    assert list(paths.work_dir.rglob("*.mp4")) == []
    no_file = ingress.post("/api/ui/assets", data={"x": "y"})
    assert no_file.status_code == 422


def test_asset_upload_sanitizes_the_file_name(
    ingress: TestClient, paths: Paths, make_video: Callable[..., Path]
):
    data = make_video("clip.mp4", seconds=1.0).read_bytes()
    response = upload(ingress, "../../etc/My Intro (final)!.MOV", data)
    assert response.status_code == 200
    filename = response.json()["asset"]["filename"]
    assert "/" not in filename
    assert not filename.startswith(".")
    assert filename.lower().endswith(".mov")
    assert (paths.assets_dir / filename).is_file()
    assert [p.name for p in paths.assets_dir.iterdir()] == [filename]
    hidden = upload(ingress, ".hidden.mp4", data)
    assert hidden.status_code == 422


def test_asset_upload_enforces_the_upload_limit(
    ingress: TestClient, repo: Repository, paths: Paths
):
    body = settings_body(ingress)
    body["max_upload_mb"] = 1
    assert ingress.put("/api/ui/settings", json=body).status_code == 200
    response = upload(ingress, "big.mp4", b"\0" * (1024 * 1024 + 1))
    assert response.status_code == 413
    assert ingress.get("/api/ui/assets").json() == []
    assert [p for p in paths.work_dir.rglob("*") if p.is_file()] == []


def test_asset_upload_rejects_an_oversized_content_length_before_spooling(
    ingress: TestClient, monkeypatch: pytest.MonkeyPatch, paths: Paths
):
    body = settings_body(ingress)
    body["max_upload_mb"] = 1
    assert ingress.put("/api/ui/settings", json=body).status_code == 200
    parsed: list[bool] = []

    async def spy(self: object, *args: object, **kwargs: object) -> object:
        parsed.append(True)
        raise AssertionError("the multipart body must not be parsed")

    monkeypatch.setattr("starlette.requests.Request.form", spy)
    response = ingress.post(
        "/api/ui/assets",
        content=b"\0" * (2 * 1024 * 1024),
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    assert response.status_code == 413
    assert parsed == []
    assert ingress.get("/api/ui/assets").json() == []
    assert [p for p in paths.work_dir.rglob("*") if p.is_file()] == []


def test_asset_replacement_keeps_old_bytes_and_row_when_the_db_write_fails(
    ingress: TestClient,
    repo: Repository,
    paths: Paths,
    make_video: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
):
    first = make_video("a.mp4", seconds=1.0).read_bytes()
    second = make_video("b.mp4", seconds=2.0).read_bytes()
    assert upload(ingress, "outro.mp4", first).status_code == 200
    before = repo.get_asset("outro.mp4")

    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("database is down")

    monkeypatch.setattr(Repository, "update_asset", boom)
    with pytest.raises(RuntimeError):
        upload(ingress, "outro.mp4", second)
    monkeypatch.undo()
    assert (paths.assets_dir / "outro.mp4").read_bytes() == first
    assert repo.get_asset("outro.mp4") == before
    assert [p for p in paths.work_dir.rglob("*") if p.is_file()] == []


def test_new_asset_leaves_no_file_when_the_db_write_fails(
    ingress: TestClient,
    repo: Repository,
    paths: Paths,
    make_video: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
):
    data = make_video("a.mp4", seconds=1.0).read_bytes()

    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("database is down")

    monkeypatch.setattr(Repository, "create_asset", boom)
    with pytest.raises(RuntimeError):
        upload(ingress, "fresh.mp4", data)
    monkeypatch.undo()
    assert not (paths.assets_dir / "fresh.mp4").exists()
    assert repo.list_assets() == []


def test_asset_replacement_restores_the_row_when_publishing_the_file_fails(
    ingress: TestClient,
    repo: Repository,
    paths: Paths,
    make_video: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
):
    first = make_video("a.mp4", seconds=1.0).read_bytes()
    second = make_video("b.mp4", seconds=2.0).read_bytes()
    assert upload(ingress, "outro.mp4", first).status_code == 200
    before = repo.get_asset("outro.mp4")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(api_ui_organize.os, "replace", boom)
    with pytest.raises(OSError):
        upload(ingress, "outro.mp4", second)
    monkeypatch.undo()
    assert (paths.assets_dir / "outro.mp4").read_bytes() == first
    assert repo.get_asset("outro.mp4") == before


def test_asset_delete_conflicts_with_a_referencing_profile(
    ingress: TestClient, repo: Repository, paths: Paths, make_video: Callable[..., Path]
):
    data = make_video("intro.mp4", seconds=1.0).read_bytes()
    assert upload(ingress, "intro.mp4", data).status_code == 200
    repo.create_processing_profile(
        ProcessingProfileCreate(
            id="branded", name="Branded", settings={"intro_reference": "intro.mp4"}
        )
    )
    response = ingress.delete("/api/ui/assets/intro.mp4")
    assert response.status_code == 409
    assert "branded" in response.json()["detail"]
    assert (paths.assets_dir / "intro.mp4").is_file()
    assert [a["filename"] for a in ingress.get("/api/ui/assets").json()] == ["intro.mp4"]


def test_asset_replacement_marks_exactly_the_clips_that_use_it(
    ingress: TestClient,
    app: FastAPI,
    repo: Repository,
    paths: Paths,
    make_video: Callable[..., Path],
):
    first = make_video("a.mp4", seconds=1.0).read_bytes()
    second = make_video("b.mp4", seconds=2.0).read_bytes()
    assert upload(ingress, "outro.mp4", first).status_code == 200
    repo.create_processing_profile(
        ProcessingProfileCreate(
            id="branded", name="Branded", settings={"outro_reference": "outro.mp4"}
        )
    )
    repo.create_collection(
        CollectionCreate(id="movies", name="Movies", processing_profile_id="branded")
    )
    users = [make_clip(repo, "movies", "M1"), make_clip(repo, "movies", "M2")]
    make_clip(repo, "regular", "R1")
    assert pending(repo) == set()

    response = upload(ingress, "outro.mp4", second)
    assert response.status_code == 200
    body = response.json()
    assert body["asset"]["size"] == len(second)
    assert sorted(body["affected_clip_ids"]) == sorted(users)
    assert pending(repo) == set(users)
    assert queued_renders(app) == set(users)
    assert (paths.assets_dir / "outro.mp4").read_bytes() == second
    assert [a.filename for a in repo.list_assets()] == ["outro.mp4"]


# --- garbage collection ----------------------------------------------------------------------


def test_gc_run_returns_the_result(ingress: TestClient, app: FastAPI):
    response = ingress.post("/api/ui/gc/run")
    assert response.status_code == 200
    assert response.json() == {"deleted": 0, "halted_reason": None}


def test_gc_run_deletes_old_unreferenced_retired_renders(
    ingress: TestClient, app: FastAPI, repo: Repository, paths: Paths
):
    clip_id = make_clip(repo)
    [record] = repo.list_renders(states={"published"})
    path = paths.media_dir / record.relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    repo.delete_clip(clip_id)
    retired = repo.get_render(record.id)
    assert retired.state == "retired"
    old = (datetime.now(UTC) - timedelta(hours=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    app.state.db.connection.execute(
        "UPDATE renders SET retired_at = ? WHERE id = ?", (old, record.id)
    )
    app.state.db.connection.commit()

    response = ingress.post("/api/ui/gc/run")
    assert response.json() == {"deleted": 1, "halted_reason": None}
    assert not path.exists()
    assert ingress.get("/api/ui/state").json()["gc"]["deleted_last_run"] == 1
