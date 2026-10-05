from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from cinema_studio.db import Database
from cinema_studio.errors import ConflictError, InvalidError, NotFoundError
from cinema_studio.models import (
    Asset,
    AssetUpdate,
    BulkSet,
    ClipUpdate,
    CollectionCreate,
    CollectionUpdate,
    LegacyReport,
    LegacySkip,
    NormalizationProfileCreate,
    NormalizationProfileUpdate,
    OriginalInfo,
    ProcessingProfileCreate,
    ProcessingProfileUpdate,
    Recipe,
    RenderRecord,
    SeasonCreate,
    SeasonUpdate,
    SelectionEvent,
    Settings,
    TestTarget,
    default_sort_key,
)
from cinema_studio.repository import Repository

pytestmark = pytest.mark.studio

PROFILE = "compatibility-4k-loudness"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "studio.db")
    yield database
    database.close()


@pytest.fixture
def revisions() -> list[int]:
    return []


@pytest.fixture
def repo(db: Database, revisions: list[int]) -> Repository:
    return Repository(db, on_catalog_change=revisions.append)


def original(duration: float = 60.0) -> OriginalInfo:
    return OriginalInfo(
        filename="movie.mp4",
        size=1000,
        sha256="ab" * 32,
        duration=duration,
        width=1920,
        height=1080,
        fps=24.0,
        has_audio=True,
        video_codec="h264",
    )


def make_clip(repo: Repository, collection_id: str = "regular", clip_id: str | None = None) -> str:
    clip = repo.create_clip(
        clip_id=clip_id,
        collection_id=collection_id,
        title="Movie",
        source_name="movie.mp4",
        recipe=Recipe(),
        original=original(),
        sort_key="k",
    )
    return clip.id


def make_render(
    clip_id: str, n: int = 1, *, relative_path: str | None = None, **overrides: object
) -> RenderRecord:
    render_id = uuid.uuid4().hex
    fields: dict[str, object] = {
        "id": render_id,
        "clip_id": clip_id,
        "n": n,
        "relative_path": relative_path
        or f"cinema-studio/renders/{clip_id}/{clip_id}-r{n}-{render_id}.mp4",
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
    fields.update(overrides)
    return RenderRecord.model_validate(fields)


# --- seeds -----------------------------------------------------------------------------------


def test_seeds(repo: Repository, db: Database) -> None:
    assert db.connection.execute("PRAGMA user_version").fetchone()[0] == 1
    collection = repo.get_collection("regular")
    assert collection.model_dump() == {
        "id": "regular",
        "name": "Regular",
        "color": "#f59e0b",
        "icon": "mdi:movie-open",
        "playback_mode": "random",
        "order": [],
        "processing_profile_id": PROFILE,
        "enabled": True,
        "sort_order": 0,
    }
    profile = repo.get_processing_profile(PROFILE)
    assert (profile.name, profile.settings) == ("Compatibility 4K Loudness", {})
    season = repo.get_season("regular")
    assert (season.builtin, season.start, season.end, season.collection_id) == (
        True,
        None,
        None,
        "regular",
    )
    assert [
        (p.id, p.target_lufs, p.true_peak, p.lra) for p in repo.list_normalization_profiles()
    ] == [
        ("standard", -16.0, -1.5, 11.0),
        ("loud", -13.0, -1.0, 11.0),
        ("soft", -20.0, -1.5, 11.0),
        ("voice", -18.0, -1.5, 7.0),
    ]
    assert repo.get_settings().model_dump() == {
        "max_upload_mb": 4096,
        "max_duration_s": 7200,
        "default_lead_in": 2.0,
        "default_tail_out": 2.0,
        "disk_reserve_bytes": 2147483648,
        "test_targets": [],
        "protected_entities": ["media_player.otocuma_dp", "cover.ocl_screen_projector"],
    }
    assert repo.catalog_revision() == 0


def test_database_reopen_keeps_data_and_rejects_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "studio.db"
    first = Database(path)
    Repository(first).create_collection(CollectionCreate(name="Trailers"))
    first.connection.execute("PRAGMA user_version = 2")
    first.close()
    with pytest.raises(RuntimeError, match="newer"):
        Database(path)
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version = 1")
    raw.close()
    reopened = Database(path)
    assert [c.id for c in Repository(reopened).list_collections()] == ["regular", "trailers"]
    reopened.close()


# --- revision bump table ---------------------------------------------------------------------


def test_catalog_writes_bump_revision_and_notify(repo: Repository, revisions: list[int]) -> None:
    collection = repo.create_collection(CollectionCreate(name="Trailers"))
    assert revisions == [1]
    repo.update_collection(collection.id, CollectionUpdate(name="Trailers 2"))
    assert revisions == [1, 2]
    clip_id = make_clip(repo, collection.id)
    repo.set_collection_order(collection.id, [clip_id])
    assert revisions == [1, 2, 3]
    season = repo.create_season(
        SeasonCreate(name="Halloween", start="10-01", end="10-31", collection_id=collection.id)
    )
    repo.update_season(season.id, SeasonUpdate(priority=5))
    repo.delete_season(season.id)
    assert revisions == [1, 2, 3, 4, 5, 6]
    repo.update_clip(clip_id, ClipUpdate(title="New title"))
    repo.update_clip(clip_id, ClipUpdate(enabled=False))
    repo.update_clip(clip_id, ClipUpdate(collection_id="regular"))
    assert revisions[-3:] == [7, 8, 9]
    repo.set_recipe(clip_id, Recipe(gain_db=3.0))
    assert revisions[-1] == 10
    repo.bulk_update([clip_id], BulkSet(enabled=True))
    assert revisions[-1] == 11
    repo.publish_render(make_render(clip_id))
    assert revisions[-1] == 12
    repo.delete_clip(clip_id)
    assert revisions[-1] == 13
    repo.delete_collection(collection.id)
    assert revisions[-1] == 14
    assert repo.catalog_revision() == 14 == len(revisions)


def test_non_catalog_writes_do_not_bump(repo: Repository, revisions: list[int]) -> None:
    clip_id = make_clip(repo)
    repo.update_clip(clip_id, ClipUpdate(notes="just a note"))
    repo.update_clip(clip_id, ClipUpdate(title=repo.get_clip(clip_id).title))  # unchanged
    repo.set_original(clip_id, original(30.0))
    repo.set_status(clip_id, "processing")
    repo.set_status(clip_id, "rendering")
    repo.set_flags(clip_id, has_preview=True, has_thumbs=True, needs_source=True)
    repo.record_selections(
        [
            SelectionEvent(
                selection_id="s1",
                clip_id=clip_id,
                render_id="r1",
                catalog_revision=1,
                selected_at="2026-10-05T10:00:00Z",
            )
        ]
    )
    repo.update_settings(Settings(max_upload_mb=10))
    repo.create_normalization_profile(
        NormalizationProfileCreate(name="Quiet", target_lufs=-22, true_peak=-2, lra=8)
    )
    repo.update_normalization_profile("quiet", NormalizationProfileUpdate(lra=9))
    repo.delete_normalization_profile("quiet")
    repo.create_processing_profile(ProcessingProfileCreate(name="Mine", settings={"a": 1}))
    repo.update_processing_profile("mine", ProcessingProfileUpdate(name="Mine 2"))
    repo.delete_processing_profile("mine")
    repo.create_asset(Asset(filename="intro.mp4", size=None, sha256=None, status="missing"))
    repo.touch_consumer("entry-1", 3)
    repo.add_unrecognized_render(
        render_id="u1",
        clip_id=clip_id,
        relative_path=f"cinema-studio/renders/{clip_id}/orphan.mp4",
        size=1,
        mtime_iso="2026-10-01T00:00:00Z",
    )
    assert revisions == []
    assert repo.catalog_revision() == 0


def test_status_ready_and_failed_and_pending_flag_bump(
    repo: Repository, revisions: list[int]
) -> None:
    clip_id = make_clip(repo)
    repo.set_status(clip_id, "failed", "boom")
    assert revisions == [1]
    repo.set_status(clip_id, "ready")
    assert revisions == [1, 2]
    repo.set_flags(clip_id, render_pending=True)
    assert revisions == [1, 2, 3]
    repo.set_flags(clip_id, render_pending=True)  # unchanged
    assert revisions == [1, 2, 3]


def test_failed_write_does_not_bump(repo: Repository, revisions: list[int]) -> None:
    with pytest.raises(NotFoundError):
        repo.update_clip("missing", ClipUpdate(title="x"))
    with pytest.raises(InvalidError):
        repo.update_clip(make_clip(repo), ClipUpdate(collection_id="nope"))
    assert revisions == []


# --- seasons ---------------------------------------------------------------------------------


def test_season_requires_existing_collection(repo: Repository) -> None:
    with pytest.raises(InvalidError, match="ghost"):
        repo.create_season(
            SeasonCreate(name="Halloween", start="10-01", end="10-31", collection_id="ghost")
        )
    season = repo.create_season(
        SeasonCreate(name="Halloween", start="10-01", end="10-31", collection_id="regular")
    )
    with pytest.raises(InvalidError, match="ghost"):
        repo.update_season(season.id, SeasonUpdate(collection_id="ghost"))
    assert repo.get_season(season.id).collection_id == "regular"


def test_season_validation_and_conflicts(repo: Repository) -> None:
    with pytest.raises(InvalidError, match="MM-DD"):
        repo.create_season(
            SeasonCreate(name="Bad", start="1-1", end="10-31", collection_id="regular")
        )
    with pytest.raises(InvalidError, match="no such day"):
        repo.create_season(
            SeasonCreate(name="Bad", start="02-30", end="10-31", collection_id="regular")
        )
    repo.create_season(
        SeasonCreate(name="Halloween", start="10-01", end="10-31", collection_id="regular")
    )
    with pytest.raises(ConflictError):
        repo.create_season(
            SeasonCreate(name="Halloween", start="10-01", end="10-31", collection_id="regular")
        )
    with pytest.raises(NotFoundError):
        repo.get_season("nope")


def test_regular_season_only_allows_cosmetics_and_collection(repo: Repository) -> None:
    trailers = repo.create_collection(CollectionCreate(name="Trailers"))
    updated = repo.update_season(
        "regular", SeasonUpdate(name="Normal", color="#000000", collection_id=trailers.id)
    )
    assert (updated.name, updated.color, updated.collection_id) == (
        "Normal",
        "#000000",
        trailers.id,
    )
    with pytest.raises(InvalidError, match="regular"):
        repo.update_season("regular", SeasonUpdate(start="01-01", end="02-01"))
    with pytest.raises(InvalidError, match="regular"):
        repo.update_season("regular", SeasonUpdate(priority=3))
    with pytest.raises(InvalidError, match="regular"):
        repo.delete_season("regular")


def test_seasons_are_listed_regular_first_then_priority(repo: Repository) -> None:
    low = repo.create_season(
        SeasonCreate(name="Low", start="01-01", end="01-02", collection_id="regular", priority=1)
    )
    high = repo.create_season(
        SeasonCreate(name="High", start="02-01", end="02-02", collection_id="regular", priority=9)
    )
    assert [s.id for s in repo.list_seasons()] == ["regular", high.id, low.id]


# --- collections -----------------------------------------------------------------------------


def test_collection_delete_rules(repo: Repository) -> None:
    with pytest.raises(InvalidError, match="regular"):
        repo.delete_collection("regular")
    with pytest.raises(NotFoundError):
        repo.delete_collection("ghost")
    with_clip = repo.create_collection(CollectionCreate(name="With clip"))
    clip_id = make_clip(repo, with_clip.id)
    with pytest.raises(ConflictError, match="clip"):
        repo.delete_collection(with_clip.id)
    repo.delete_clip(clip_id)
    with_season = repo.create_collection(CollectionCreate(name="With season"))
    repo.create_season(
        SeasonCreate(name="Easter", start="03-20", end="04-20", collection_id=with_season.id)
    )
    with pytest.raises(ConflictError, match="season"):
        repo.delete_collection(with_season.id)
    repo.delete_collection(with_clip.id)
    assert [c.id for c in repo.list_collections()] == ["regular", with_season.id]


def test_collection_create_validates_profile_and_conflicts(repo: Repository) -> None:
    with pytest.raises(InvalidError, match="ghost"):
        repo.create_collection(CollectionCreate(name="X", processing_profile_id="ghost"))
    repo.create_collection(CollectionCreate(name="Trailers"))
    with pytest.raises(ConflictError):
        repo.create_collection(CollectionCreate(name="Trailers"))
    with pytest.raises(InvalidError, match="Invalid id"):
        repo.create_collection(CollectionCreate(id="Bad Id!", name="X"))


def test_set_collection_order_filters_unknown_ids(repo: Repository) -> None:
    trailers = repo.create_collection(CollectionCreate(name="Trailers"))
    a = make_clip(repo, trailers.id)
    b = make_clip(repo, trailers.id)
    elsewhere = make_clip(repo, "regular")
    collection = repo.set_collection_order(trailers.id, [b, "ghost", elsewhere, a, b])
    assert collection.order == [b, a]
    assert repo.get_collection(trailers.id).order == [b, a]


def test_order_ignores_clips_that_left_the_collection(repo: Repository) -> None:
    trailers = repo.create_collection(CollectionCreate(name="Trailers"))
    a = make_clip(repo, trailers.id)
    b = make_clip(repo, trailers.id)
    repo.set_collection_order(trailers.id, [a, b])
    repo.update_clip(a, ClipUpdate(collection_id="regular"))
    assert repo.get_collection(trailers.id).order == [b]
    repo.delete_clip(b)
    assert repo.get_collection(trailers.id).order == []


def test_user_edit_flag_only_set_by_ui_writes(repo: Repository) -> None:
    trailers = repo.create_collection(CollectionCreate(name="Trailers"))
    clip_id = make_clip(repo, trailers.id)
    assert repo.collection_user_edited(trailers.id) is False
    repo.update_collection(trailers.id, CollectionUpdate(name="Imported"), user_edit=False)
    repo.set_collection_order(trailers.id, [clip_id], user_edit=False)
    assert repo.collection_user_edited(trailers.id) is False
    repo.update_collection(trailers.id, CollectionUpdate(name="Edited"))
    assert repo.collection_user_edited(trailers.id) is True
    other = repo.create_collection(CollectionCreate(name="Other"))
    repo.set_collection_order(other.id, [])
    assert repo.collection_user_edited(other.id) is True


def test_collection_update_validates_profile(repo: Repository) -> None:
    with pytest.raises(InvalidError, match="ghost"):
        repo.update_collection("regular", CollectionUpdate(processing_profile_id="ghost"))
    updated = repo.update_collection(
        "regular", CollectionUpdate(playback_mode="sequential", enabled=False, sort_order=4)
    )
    assert (updated.playback_mode, updated.enabled, updated.sort_order) == ("sequential", False, 4)


# --- profiles and assets ---------------------------------------------------------------------


def test_processing_profile_settings_go_through_the_validator(db: Database) -> None:
    def validator(settings: dict[str, object]) -> dict[str, object]:
        if "bad" in settings:
            raise ValueError("bad setting")
        return {**settings, "normalized": True}

    repo = Repository(db, validate_settings=validator)
    created = repo.create_processing_profile(
        ProcessingProfileCreate(name="Fast", settings={"video": 1})
    )
    assert created.settings == {"video": 1, "normalized": True}
    with pytest.raises(InvalidError, match="bad setting"):
        repo.create_processing_profile(ProcessingProfileCreate(name="Bad", settings={"bad": 1}))
    with pytest.raises(InvalidError, match="bad setting"):
        repo.update_processing_profile("fast", ProcessingProfileUpdate(settings={"bad": 1}))
    assert repo.get_processing_profile("fast").settings == {"video": 1, "normalized": True}


def test_processing_profile_delete_conflicts_when_used(repo: Repository) -> None:
    repo.create_processing_profile(ProcessingProfileCreate(name="Fast", settings={}))
    repo.create_collection(CollectionCreate(name="Quick", processing_profile_id="fast"))
    with pytest.raises(ConflictError, match="collection"):
        repo.delete_processing_profile("fast")
    with pytest.raises(ConflictError):
        repo.delete_processing_profile(PROFILE)
    assert repo.clips_using_processing_profile("fast") == []
    clip_id = make_clip(repo, "quick")
    assert repo.clips_using_processing_profile("fast") == [clip_id]


def test_normalization_profile_delete_conflicts_when_a_recipe_uses_it(repo: Repository) -> None:
    clip_id = make_clip(repo)
    repo.set_recipe(clip_id, Recipe(profile_id="loud"))
    assert repo.clips_using_normalization_profile("loud") == [clip_id]
    with pytest.raises(ConflictError, match="loud"):
        repo.delete_normalization_profile("loud")
    repo.set_recipe(clip_id, Recipe())
    repo.delete_normalization_profile("loud")
    with pytest.raises(NotFoundError):
        repo.get_normalization_profile("loud")


def test_recipe_must_reference_existing_normalization_profile(repo: Repository) -> None:
    clip_id = make_clip(repo)
    with pytest.raises(InvalidError, match="ghost"):
        repo.set_recipe(clip_id, Recipe(profile_id="ghost"))


def test_assets_crud_and_profile_reference_conflict(repo: Repository) -> None:
    repo.create_asset(Asset(filename="intro.mp4", size=None, sha256=None, status="missing"))
    with pytest.raises(ConflictError):
        repo.create_asset(Asset(filename="intro.mp4", size=1, sha256="x", status="ready"))
    with pytest.raises(InvalidError):
        repo.create_asset(Asset(filename="../evil.mp4", size=1, sha256="x", status="ready"))
    updated = repo.update_asset("intro.mp4", AssetUpdate(size=10, sha256="aa", status="ready"))
    assert (updated.size, updated.sha256, updated.status) == (10, "aa", "ready")
    assert [a.filename for a in repo.list_assets()] == ["intro.mp4"]
    repo.create_processing_profile(
        ProcessingProfileCreate(name="Branded", settings={"intro": {"asset": "intro.mp4"}})
    )
    with pytest.raises(ConflictError, match="branded"):
        repo.delete_asset("intro.mp4")
    repo.delete_processing_profile("branded")
    repo.delete_asset("intro.mp4")
    with pytest.raises(NotFoundError):
        repo.get_asset("intro.mp4")


# --- clips -----------------------------------------------------------------------------------


def test_create_clip_defaults_and_validation(repo: Repository) -> None:
    clip = repo.create_clip(
        clip_id=None,
        collection_id="regular",
        title="  Titanic  ",
        source_name="titanic.mp4",
        recipe=Recipe(),
        original=original(),
        sort_key=default_sort_key("regular", "ABC"),
    )
    uuid.UUID(clip.id)
    assert clip.title == "Titanic"
    assert (clip.status, clip.render, clip.render_pending, clip.needs_source) == (
        "processing",
        None,
        False,
        False,
    )
    assert clip.sort_key == "regular/abc.mp4"
    assert repo.get_clip(clip.id) == clip
    assert [c.id for c in repo.list_clips()] == [clip.id]
    with pytest.raises(ConflictError):
        make_clip(repo, clip_id=clip.id)
    with pytest.raises(InvalidError, match="ghost"):
        make_clip(repo, "ghost")
    with pytest.raises(InvalidError, match="Invalid id"):
        make_clip(repo, clip_id="../x")
    with pytest.raises(InvalidError, match="title"):
        repo.create_clip(
            clip_id=None,
            collection_id="regular",
            title=" ",
            source_name="x.mp4",
            recipe=Recipe(),
            original=None,
            sort_key="k",
        )


def test_create_clip_without_original_may_need_source(repo: Repository) -> None:
    clip = repo.create_clip(
        clip_id="worker-id-1",
        collection_id="regular",
        title="Imported",
        source_name="imported.mp4",
        recipe=Recipe(),
        original=None,
        sort_key="k",
        needs_source=True,
        status="ready",
    )
    assert (clip.id, clip.original, clip.needs_source, clip.status) == (
        "worker-id-1",
        None,
        True,
        "ready",
    )


def test_recipe_is_validated_against_the_original(repo: Repository) -> None:
    clip_id = make_clip(repo)
    with pytest.raises(InvalidError, match="past the end"):
        repo.set_recipe(clip_id, Recipe(trim_end=120.0))
    updated = repo.set_recipe(clip_id, Recipe(trim_start=1.0, trim_end=10.0))
    assert updated.render_pending is True
    assert updated.recipe.trim_end == 10.0


def test_set_status_records_and_clears_error(repo: Repository) -> None:
    clip_id = make_clip(repo)
    failed = repo.set_status(clip_id, "failed", "ffmpeg exploded")
    assert (failed.status, failed.error) == ("failed", "ffmpeg exploded")
    assert repo.set_status(clip_id, "rendering").error is None


def test_bulk_update_skips_unknown_ids_and_counts_matches(
    repo: Repository, revisions: list[int]
) -> None:
    trailers = repo.create_collection(CollectionCreate(name="Trailers"))
    a, b = make_clip(repo), make_clip(repo)
    before = len(revisions)
    assert repo.bulk_update([a, b, "ghost"], BulkSet(collection_id=trailers.id, enabled=False)) == 2
    assert len(revisions) == before + 1
    assert [(c.collection_id, c.enabled) for c in map(repo.get_clip, (a, b))] == [
        (trailers.id, False)
    ] * 2
    with pytest.raises(InvalidError):
        repo.bulk_update([a], BulkSet(collection_id="ghost"))
    assert repo.bulk_update([a], BulkSet(enabled=False)) == 1
    assert len(revisions) == before + 1  # nothing changed, nothing bumped


def test_record_selections_counts_and_keeps_latest_timestamp(repo: Repository) -> None:
    clip_id = make_clip(repo)

    def event(n: int, at: str) -> SelectionEvent:
        return SelectionEvent(
            selection_id=f"s{n}",
            clip_id=clip_id,
            render_id="r",
            catalog_revision=1,
            selected_at=at,
        )

    repo.record_selections(
        [
            event(1, "2026-10-05T12:00:00Z"),
            event(2, "2026-10-05T09:00:00+00:00"),
            SelectionEvent(
                selection_id="s3",
                clip_id="deleted-clip",
                render_id="r",
                catalog_revision=1,
                selected_at="2026-10-05T10:00:00Z",
            ),
        ]
    )
    clip = repo.get_clip(clip_id)
    assert (clip.selection_count, clip.last_selected_at) == (2, "2026-10-05T12:00:00Z")


# --- renders ---------------------------------------------------------------------------------


def test_publish_render_points_clip_and_retires_previous(
    repo: Repository, revisions: list[int]
) -> None:
    clip_id = make_clip(repo)
    repo.set_recipe(clip_id, Recipe(gain_db=1.0))
    first = make_render(clip_id, 1)
    clip = repo.publish_render(first)
    assert (clip.status, clip.render_pending, clip.error) == ("ready", False, None)
    assert clip.render is not None and clip.render.id == first.id
    assert clip.render.media_path == first.relative_path
    second = make_render(clip_id, 2)
    before = repo.catalog_revision()
    clip = repo.publish_render(second)
    new_revision = repo.catalog_revision()
    assert new_revision == before + 1 == revisions[-1]
    assert clip.render is not None and clip.render.id == second.id
    old = repo.get_render(first.id)
    assert (old.state, old.retired_revision) == ("retired", new_revision)
    assert old.retired_at is not None
    assert repo.get_render(second.id).state == "published"
    assert repo.get_render(second.id).published_at is not None


def test_publish_render_stores_rounded_timing(repo: Repository) -> None:
    clip_id = make_clip(repo)
    render = make_render(
        clip_id,
        duration=10.00049,
        content_start=1.00049,
        content_end=9.00049,
        lead_in=1.0,
        tail_out=1.0,
        content_duration=8.0,
    )
    repo.publish_render(render)
    stored = repo.get_render(render.id)
    assert (stored.duration, stored.content_start, stored.content_end) == (10.0, 1.0, 9.0)


def test_publish_render_with_invalid_timing_changes_nothing(
    repo: Repository, revisions: list[int]
) -> None:
    clip_id = make_clip(repo)
    good = make_render(clip_id, 1)
    repo.publish_render(good)
    revision = repo.catalog_revision()
    bad = make_render(clip_id, 2, content_duration=1.0)
    with pytest.raises(InvalidError, match="content_duration mismatch"):
        repo.publish_render(bad)
    assert repo.catalog_revision() == revision
    assert revisions[-1] == revision
    assert [r.id for r in repo.list_renders()] == [good.id]
    clip = repo.get_clip(clip_id)
    assert clip.render is not None and clip.render.id == good.id
    assert repo.get_render(good.id).state == "published"


def test_publish_render_unknown_clip_and_duplicate(repo: Repository) -> None:
    with pytest.raises(NotFoundError):
        repo.publish_render(make_render("ghost"))
    clip_id = make_clip(repo)
    render = make_render(clip_id)
    repo.publish_render(render)
    with pytest.raises(ConflictError):
        repo.publish_render(render)


def test_next_render_n_counts_every_row_including_deleted(repo: Repository) -> None:
    clip_id = make_clip(repo)
    assert repo.next_render_n(clip_id) == 1
    first = make_render(clip_id, 1)
    repo.publish_render(first)
    assert repo.next_render_n(clip_id) == 2
    repo.publish_render(make_render(clip_id, 2))
    repo.mark_render(first.id, "deleted")
    repo.add_unrecognized_render(
        render_id="u1",
        clip_id=clip_id,
        relative_path=f"cinema-studio/renders/{clip_id}/orphan.mp4",
        size=1,
        mtime_iso="2026-10-01T00:00:00Z",
    )
    assert repo.next_render_n(clip_id) == 4
    assert repo.next_render_n("other-clip") == 1


def test_unrecognized_render_is_recorded_unpublished(repo: Repository) -> None:
    clip_id = make_clip(repo)
    repo.add_unrecognized_render(
        render_id="u1",
        clip_id=clip_id,
        relative_path=f"cinema-studio/renders/{clip_id}/orphan.mp4",
        size=77,
        mtime_iso="2026-10-01T00:00:00Z",
    )
    record = repo.get_render("u1")
    assert (record.state, record.size, record.created_at, record.published_at) == (
        "unrecognized",
        77,
        "2026-10-01T00:00:00Z",
        None,
    )
    assert [r.id for r in repo.list_renders(states={"unrecognized"})] == ["u1"]
    assert repo.list_renders(states={"published"}) == []
    with pytest.raises(NotFoundError):
        repo.get_render("ghost")


def test_delete_clip_retires_its_published_render(repo: Repository) -> None:
    clip_id = make_clip(repo)
    render = make_render(clip_id)
    repo.publish_render(render)
    revision = repo.catalog_revision()
    repo.delete_clip(clip_id)
    with pytest.raises(NotFoundError):
        repo.get_clip(clip_id)
    retired = repo.get_render(render.id)
    assert (retired.state, retired.retired_revision) == ("retired", revision + 1)
    assert retired.retired_at is not None
    assert repo.catalog_document("inst")["clips"] == []
    with pytest.raises(NotFoundError):
        repo.delete_clip(clip_id)


def test_mark_render_bumps_only_when_published_state_changes(
    repo: Repository, revisions: list[int]
) -> None:
    clip_id = make_clip(repo)
    first, second = make_render(clip_id, 1), make_render(clip_id, 2)
    repo.publish_render(first)
    repo.publish_render(second)
    before = len(revisions)
    repo.mark_render(first.id, "deleted")  # retired -> deleted: catalog unaffected
    assert len(revisions) == before
    repo.mark_render(second.id, "missing")  # published -> missing: leaves the catalog
    assert len(revisions) == before + 1
    with pytest.raises(NotFoundError):
        repo.mark_render("ghost", "missing")


def test_fallback_after_missing_picks_newest_earlier_existing_render(
    repo: Repository,
) -> None:
    clip_id = make_clip(repo)
    r1, r2, r3 = (make_render(clip_id, n) for n in (1, 2, 3))
    for render in (r1, r2, r3):
        repo.publish_render(render)
    repo.mark_render(r3.id, "missing")
    revision = repo.catalog_revision()
    clip = repo.fallback_after_missing(clip_id, lambda path: path == r1.relative_path)
    assert clip.render is not None and clip.render.id == r1.id  # r2's file is gone: skipped
    assert (clip.status, clip.error) == ("ready", None)
    assert repo.get_render(r1.id).state == "published"
    assert repo.get_render(r1.id).retired_revision is None
    assert repo.get_render(r2.id).state == "retired"
    assert repo.get_render(r3.id).state == "missing"
    assert repo.catalog_revision() == revision + 1


def test_fallback_after_missing_ignores_deleted_renders_and_marks_failed(
    repo: Repository,
) -> None:
    clip_id = make_clip(repo)
    r1, r2 = make_render(clip_id, 1), make_render(clip_id, 2)
    repo.publish_render(r1)
    repo.publish_render(r2)
    repo.mark_render(r1.id, "deleted")
    repo.mark_render(r2.id, "missing")
    revision = repo.catalog_revision()
    clip = repo.fallback_after_missing(clip_id, lambda _path: True)
    assert clip.render is None
    assert clip.status == "failed"
    assert clip.error is not None and "missing" in clip.error
    assert repo.catalog_revision() == revision


def test_fallback_after_missing_without_candidates_marks_failed(repo: Repository) -> None:
    clip_id = make_clip(repo)
    only = make_render(clip_id, 1)
    repo.publish_render(only)
    repo.mark_render(only.id, "missing")
    clip = repo.fallback_after_missing(clip_id, lambda _path: True)
    assert clip.status == "failed" and clip.render is None


def test_fallback_after_missing_leaves_a_healthy_clip_alone(repo: Repository) -> None:
    clip_id = make_clip(repo)
    repo.publish_render(make_render(clip_id, 1))
    clip = repo.fallback_after_missing(clip_id, lambda _path: False)
    assert clip.status == "ready" and clip.render is not None


# --- consumers, settings, legacy -------------------------------------------------------------


def test_touch_consumer_and_list_seen(repo: Repository, db: Database) -> None:
    repo.touch_consumer("a", 3)
    repo.touch_consumer("b", None)
    repo.touch_consumer("a", None)  # keeps the held revision it already reported
    db.connection.execute("INSERT INTO consumers_seen VALUES ('old', '2020-01-01T00:00:00Z', 1)")
    seen = dict(repo.list_consumers_seen())
    assert set(seen) == {"a", "b"}
    assert (
        db.connection.execute(
            "SELECT held_revision FROM consumers_seen WHERE consumer_id = 'a'"
        ).fetchone()[0]
        == 3
    )
    assert {c for c, _ in repo.list_consumers_seen(since_days=100000)} == {"a", "b", "old"}


def test_settings_roundtrip_and_validation(repo: Repository) -> None:
    updated = repo.update_settings(
        Settings(
            max_upload_mb=100,
            test_targets=[TestTarget(id="tv", label="TV", entity_id="media_player.tv")],
        )
    )
    assert repo.get_settings() == updated
    assert updated.test_targets[0].entity_id == "media_player.tv"
    with pytest.raises(ValueError, match="media_player"):
        TestTarget(id="x", label="X", entity_id="light.kitchen")
    with pytest.raises(ValueError, match="protected"):
        Settings(
            test_targets=[
                TestTarget(id="p", label="P", entity_id="media_player.otocuma_dp"),
            ]
        )


def test_legacy_reports(repo: Repository) -> None:
    assert repo.last_legacy_report() is None
    first = LegacyReport(
        run_id="run-1",
        started_at="2026-10-05T10:00:00Z",
        finished_at=None,
        catalog_revision=0,
        imported=[],
        queued_for_render=[],
        needs_source=[],
        skipped=[],
        missing_assets=[],
    )
    repo.save_legacy_report(first)
    second = first.model_copy(
        update={
            "run_id": "run-2",
            "imported": ["c1"],
            "skipped": [LegacySkip(clip_id="c2", reason="no file")],
        }
    )
    repo.save_legacy_report(second)
    assert repo.last_legacy_report() == second
    finished = first.model_copy(update={"finished_at": "2026-10-05T10:05:00Z"})
    repo.save_legacy_report(finished)  # re-saving a run (stage -> commit) replaces it
    assert repo.last_legacy_report() == finished


# --- catalog document ------------------------------------------------------------------------

CATALOG_KEYS = {
    "contract_version",
    "revision",
    "instance_id",
    "generated_at",
    "seasons",
    "collections",
    "clips",
}
RENDER_KEYS = {
    "id", "n", "relative_path", "media_path", "size", "sha256", "duration", "content_start",
    "content_end", "lead_in", "tail_out", "content_duration", "timing_source",
    "integrated_lufs", "true_peak", "recipe_hash", "profile_fingerprint", "published_at",
}  # fmt: skip


def test_catalog_document_matches_the_contract_shape(repo: Repository) -> None:
    trailers = repo.create_collection(CollectionCreate(name="Trailers"))
    published = make_clip(repo, trailers.id)
    unpublished = make_clip(repo, trailers.id)
    repo.set_collection_order(trailers.id, [unpublished, published])
    repo.publish_render(make_render(published))
    repo.create_season(
        SeasonCreate(name="Halloween", start="10-01", end="10-31", collection_id=trailers.id)
    )
    document = repo.catalog_document("inst-1")
    assert set(document) == CATALOG_KEYS
    assert document["contract_version"] == 1
    assert document["instance_id"] == "inst-1"
    assert document["revision"] == repo.catalog_revision()
    seasons = document["seasons"]
    assert isinstance(seasons, list)
    assert [set(s) for s in seasons] == [  # type: ignore[arg-type]
        {"id", "name", "color", "icon", "start", "end", "priority", "collection_id"}
    ] * 2
    collections = {c["id"]: c for c in document["collections"]}  # type: ignore[index, union-attr]
    assert set(collections["trailers"]) == {
        "id", "name", "color", "icon", "playback_mode", "order", "enabled",
    }  # fmt: skip
    assert collections["trailers"]["order"] == [published]
    clips = document["clips"]
    assert isinstance(clips, list) and len(clips) == 1
    clip = clips[0]
    assert set(clip) == {
        "id", "collection_id", "title", "source_name", "enabled", "sort_key", "render_pending",
        "render",
    }  # fmt: skip
    assert clip["id"] == published
    assert set(clip["render"]) == RENDER_KEYS


def test_catalog_document_excludes_clips_whose_render_is_not_published(repo: Repository) -> None:
    clip_id = make_clip(repo)
    render = make_render(clip_id)
    repo.publish_render(render)
    assert [c["id"] for c in repo.catalog_document("i")["clips"]] == [clip_id]  # type: ignore[union-attr]
    repo.mark_render(render.id, "missing")
    assert repo.catalog_document("i")["clips"] == []
    assert repo.catalog_document("i")["revision"] == repo.catalog_revision()
