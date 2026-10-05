"""Legacy imports verify real Worker files and preserve stable hard links."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cinema_studio import lifecycle
from cinema_studio.app import create_app
from cinema_studio.config import Paths
from cinema_studio.errors import ConflictError, InvalidError
from cinema_studio.legacy import LegacyImporter, LegacyManifest
from cinema_studio.media import file_sha256, legacy_fingerprint
from cinema_studio.models import CollectionUpdate
from cinema_studio.probe import probe
from cinema_studio.timing import Timing
from cinema_studio.timing_validation import validate_timing

pytestmark = pytest.mark.studio
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
CLIP_ID = "12345678-1234-4234-8234-123456789abc"
OTHER_ID = "abcdef12-1234-4234-8234-123456789abc"
DURATION = 20.0
# Production: total 154.133, content 150.125, lead 2.0, tail 2.008.
# At 20 seconds the rounded lead and tail remain distinct (.260 / .261).
SCALE = DURATION / 154.133
TIMING = {
    "content_duration_seconds": 150.125 * SCALE,
    "lead_in_duration_seconds": 2.0 * SCALE,
    "tail_out_duration_seconds": 2.008 * SCALE,
    "content_start_offset_seconds": 2.0 * SCALE,
    "content_end_offset_seconds": 152.125 * SCALE,
}
EXPECTED_TIMING = validate_timing(
    Timing(
        DURATION,
        TIMING["content_start_offset_seconds"],
        TIMING["content_end_offset_seconds"],
        TIMING["lead_in_duration_seconds"],
        TIMING["tail_out_duration_seconds"],
        TIMING["content_duration_seconds"],
    )
)


@pytest.fixture
def client(paths: Paths) -> Iterator[TestClient]:
    with TestClient(create_app(paths, start_background=False)) as client:
        client.app.state.store.ensure_dirs()
        yield client


@pytest.fixture
async def manifest(paths: Paths, make_video: Callable[..., Path]) -> LegacyManifest:
    source = paths.media_dir / "cinema-collections/source"
    compiled = paths.media_dir / "cinema-collections/compiled"
    video = make_video(seconds=DURATION)
    fingerprint = legacy_fingerprint(await file_sha256(video), video.stat().st_size)
    for root in (source, compiled):
        (root / "regular").mkdir(parents=True)
        shutil.copyfile(video, root / "regular/movie.mp4")
    return LegacyManifest.model_validate(
        {
            "worker": {"version": "1", "queue_depth": 0, "active_job_ids": []},
            "roots": {"source": str(source), "compiled": str(compiled)},
            "collections": [
                {
                    "id": "regular",
                    "name": "Regular",
                    "playback_mode": "custom",
                    "ordered_clip_ids": [CLIP_ID],
                    "processing_profile_id": "worker-profile",
                    "enabled": True,
                }
            ],
            "profiles": [{"id": "worker-profile", "name": "Worker", "settings": {}}],
            "assets": ["missing.mp4"],
            "seasons": [
                {
                    "id": "regular",
                    "name": "ignored",
                    "start": None,
                    "end": None,
                    "priority": 55,
                    "collection_id": "regular",
                },
                {
                    "id": "holiday",
                    "name": "Holiday",
                    "start": "12-01",
                    "end": "12-31",
                    "priority": 1,
                    "collection_id": "regular",
                },
            ],
            "clips": [
                {
                    "id": CLIP_ID,
                    "collection_id": "regular",
                    "state": "ready",
                    "relative_source_path": "regular/movie.mp4",
                    "relative_output_path": "regular/movie.mp4",
                    "output_available": True,
                    "output_duration_seconds": DURATION,
                    "updated_at": "2026-10-01T00:00:00Z",
                    "metadata": {
                        **TIMING,
                        "source_fingerprint": fingerprint,
                        "output_fingerprint": fingerprint,
                    },
                }
            ],
        }
    )


def importer(client: TestClient, paths: Paths, now: datetime = NOW) -> LegacyImporter:
    state = client.app.state
    return LegacyImporter(paths, state.repo, state.store, state.jobs, now=lambda: now)


async def test_happy_path(client: TestClient, paths: Paths, manifest: LegacyManifest) -> None:
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    assert stage.staged == [CLIP_ID] and stage.rejected == []
    assert (paths.work_dir / "import" / stage.run_id / "stage.json").is_file()
    # A new instance can commit persisted staging.
    report = await importer(client, paths).commit(stage.run_id, manifest.clips)
    repo = client.app.state.repo
    clip = repo.get_clip(CLIP_ID)
    assert report.imported == [clip.id]
    assert report.missing_assets == ["missing.mp4"]
    assert repo.get_asset("missing.mp4").status == "missing"
    assert repo.get_processing_profile("worker-profile").settings
    assert repo.get_season("holiday").start == "12-01"
    assert repo.get_season("regular").name == "Regular"
    assert clip.render is not None and clip.original is not None
    assert clip.render.timing_source == "legacy_worker"
    assert (
        clip.render.duration,
        clip.render.content_start,
        clip.render.content_end,
        clip.render.content_duration,
        clip.render.lead_in,
        clip.render.tail_out,
    ) == (
        EXPECTED_TIMING.duration,
        EXPECTED_TIMING.content_start,
        EXPECTED_TIMING.content_end,
        EXPECTED_TIMING.content_duration,
        EXPECTED_TIMING.lead_in,
        EXPECTED_TIMING.tail_out,
    )
    assert clip.recipe.lead_in == EXPECTED_TIMING.lead_in
    assert clip.recipe.tail_out == EXPECTED_TIMING.tail_out
    assert clip.recipe.lead_in != clip.recipe.tail_out
    assert clip.sort_key == "regular/movie.mp4"
    render_path = paths.media_dir / clip.render.relative_path
    worker_out = Path(manifest.roots.compiled) / "regular/movie.mp4"
    worker_source = Path(manifest.roots.source) / "regular/movie.mp4"
    original_path = paths.originals_dir / clip.id / clip.original.filename
    assert render_path.stat().st_ino == worker_out.stat().st_ino
    assert original_path.stat().st_ino == worker_source.stat().st_ino
    old_bytes = render_path.read_bytes()
    replacement = worker_out.with_suffix(".new")
    replacement.write_bytes(b"replaced Worker output")
    os.replace(replacement, worker_out)
    assert render_path.read_bytes() == old_bytes
    assert repo.get_collection("regular").order == [clip.id]
    assert repo.get_collection("regular").playback_mode == "custom"
    assert report.catalog_revision == repo.catalog_revision()
    assert repo.last_legacy_report() == report
    assert not (paths.work_dir / "import" / stage.run_id).exists()


@pytest.mark.parametrize(
    "case",
    [
        "output_mismatch",
        "source_mismatch",
        "output_missing_fp",
        "source_missing_fp",
        "partial",
        "invalid",
        "nonfinite",
        "duration",
        "absent",
        "null",
    ],
)
async def test_verdicts(
    client: TestClient, paths: Paths, manifest: LegacyManifest, case: str
) -> None:
    clip = manifest.clips[0]
    if case == "output_mismatch":
        clip.metadata["output_fingerprint"] = "wrong"
    elif case == "source_mismatch":
        clip.metadata["source_fingerprint"] = "wrong"
    elif case == "output_missing_fp":
        del clip.metadata["output_fingerprint"]
    elif case == "source_missing_fp":
        del clip.metadata["source_fingerprint"]
    elif case == "partial":
        del clip.metadata["content_duration_seconds"]
    elif case == "invalid":
        clip.metadata["content_duration_seconds"] = 100
    elif case == "nonfinite":
        clip.metadata["content_duration_seconds"] = float("nan")
    elif case == "duration":
        clip.output_duration_seconds = DURATION + 1
    elif case == "null":
        clip.metadata.update(dict.fromkeys(TIMING))
    else:
        for key in TIMING:
            del clip.metadata[key]
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    report = await legacy.commit(stage.run_id, manifest.clips)
    imported = client.app.state.repo.get_clip(clip.id)
    jobs = client.app.state.jobs.list_jobs()
    if case in {"source_mismatch", "source_missing_fp"}:
        assert report.needs_source == [clip.id]
        assert imported.needs_source and imported.original is None
        assert imported.render is not None
        assert not jobs
    elif case == "absent":
        assert imported.render is not None
        assert imported.render.timing_source == "legacy_full_file"
        assert imported.render.content_start == 0 and imported.render.content_end == DURATION
    else:
        assert imported.render is None and imported.status == "processing"
        assert report.queued_for_render == [clip.id]
        assert len(jobs) == 1 and jobs[0].kind == "render"


@pytest.mark.parametrize(
    "field", ["updated_at", "source_fingerprint", "output_fingerprint", "missing"]
)
async def test_refetch(
    client: TestClient, paths: Paths, manifest: LegacyManifest, field: str
) -> None:
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    clips = [c.model_copy(deep=True) for c in manifest.clips]
    if field == "missing":
        clips = []
    elif field == "updated_at":
        clips[0].updated_at = "later"
    else:
        clips[0].metadata[field] = "changed"
    report = await legacy.commit(stage.run_id, clips)
    assert report.skipped[0].reason == (
        "missing_from_refetch" if field == "missing" else "changed_during_import"
    )
    assert client.app.state.repo.list_clips() == []


@pytest.mark.parametrize("field", ["relative_source_path", "relative_output_path"])
async def test_unsafe_path(
    client: TestClient, paths: Paths, manifest: LegacyManifest, field: str
) -> None:
    setattr(manifest.clips[0], field, "../../etc/passwd")
    stage = await importer(client, paths).stage(manifest)
    assert stage.staged == []
    assert stage.rejected[0].reason == "unsafe_path"


@pytest.mark.parametrize("root", ["source", "compiled"])
@pytest.mark.parametrize("location", ["outside", "studio"])
async def test_roots(
    client: TestClient, paths: Paths, manifest: LegacyManifest, root: str, location: str
) -> None:
    setattr(manifest.roots, root, str(paths.data_dir if location == "outside" else paths.root))
    with pytest.raises(InvalidError):
        await importer(client, paths).stage(manifest)


@pytest.mark.parametrize("busy", ["queue", "active", "maintenance"])
async def test_worker_busy(
    client: TestClient, paths: Paths, manifest: LegacyManifest, busy: str
) -> None:
    if busy == "queue":
        manifest.worker.queue_depth = 1
    elif busy == "active":
        manifest.worker.active_job_ids = ["running"]
    now = NOW.astimezone().replace(hour=3, minute=15) if busy == "maintenance" else NOW
    with pytest.raises(InvalidError):
        await importer(client, paths, now).stage(manifest)


async def test_active_and_stale(client: TestClient, paths: Paths, manifest: LegacyManifest) -> None:
    stage = await importer(client, paths).stage(manifest)
    with pytest.raises(ConflictError):
        await importer(client, paths).stage(manifest)
    importer(client, paths, NOW + timedelta(hours=1, seconds=1)).discard_stale()
    assert not (paths.work_dir / "import" / stage.run_id).exists()
    assert (await importer(client, paths, NOW + timedelta(hours=2)).stage(manifest)).staged


async def test_order_rerun(client: TestClient, paths: Paths, manifest: LegacyManifest) -> None:
    other = manifest.clips[0].model_copy(deep=True, update={"id": OTHER_ID})
    manifest.clips.append(other)
    manifest.collections[0].ordered_clip_ids = [other.id, CLIP_ID]
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    await legacy.commit(stage.run_id, manifest.clips)
    repo = client.app.state.repo
    assert repo.get_collection("regular").order == [other.id, CLIP_ID]
    repo.set_collection_order("regular", [CLIP_ID, other.id])
    repo.update_collection("regular", CollectionUpdate(playback_mode="sequential"))
    stage = await legacy.stage(manifest)
    report = await legacy.commit(stage.run_id, manifest.clips)
    assert [s.reason for s in report.skipped] == ["already_imported", "already_imported"]
    assert repo.get_collection("regular").order == [CLIP_ID, other.id]
    assert repo.get_collection("regular").playback_mode == "sequential"


async def test_invalid_profile(client: TestClient, paths: Paths, manifest: LegacyManifest) -> None:
    manifest.profiles[0].settings = {"bad": "setting"}
    stage = await importer(client, paths).stage(manifest)
    assert stage.staged == [] and stage.rejected[0].reason == "profile_invalid"


async def test_file_rollback(
    client: TestClient, paths: Paths, manifest: LegacyManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)

    def fail(**kwargs: object) -> None:
        raise InvalidError("DB failure")

    monkeypatch.setattr(client.app.state.repo, "import_legacy_clip", fail)
    report = await legacy.commit(stage.run_id, manifest.clips)
    assert report.skipped[0].reason == "import_error: InvalidError"
    assert client.app.state.repo.last_legacy_report() == report
    assert list(paths.originals_dir.rglob("*.mp4")) == []
    assert list(paths.renders_dir.rglob("*.mp4")) == []
    assert client.app.state.repo.list_clips() == []


def test_api_wiring(client: TestClient, manifest: LegacyManifest) -> None:
    state = client.app.state
    state.legacy.now = lambda: NOW
    headers = {"Authorization": f"Bearer {state.tokens.get()}", "X-Cinema-Consumer": "test"}
    response = client.post(
        "/api/v1/import/legacy",
        headers=headers,
        json={"phase": "stage", "manifest": manifest.model_dump(mode="json")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    response = client.post(
        "/api/v1/import/legacy",
        headers=headers,
        json={
            "phase": "commit",
            "run_id": run_id,
            "clips": [c.model_dump(mode="json") for c in manifest.clips],
        },
    )
    assert response.status_code == 200 and response.json()["imported"] == [CLIP_ID]


async def test_catalog_assets_and_season_update(
    client: TestClient, paths: Paths, manifest: LegacyManifest
) -> None:
    asset = paths.assets_dir / "intro.mp4"
    asset.write_bytes(b"existing asset")
    manifest.profiles[0].settings = {"intro_reference": "intro.mp4"}
    manifest.assets.append("intro.mp4")
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    await legacy.commit(stage.run_id, manifest.clips)
    repo = client.app.state.repo
    ready = repo.get_asset("intro.mp4")
    assert ready.status == "ready" and ready.size == asset.stat().st_size
    assert ready.sha256 == await file_sha256(asset)
    manifest.seasons[1].name = "Updated holiday"
    manifest.seasons[1].priority = 2
    manifest.profiles[0].name = "Existing profile stays unchanged"
    stage = await legacy.stage(manifest)
    await legacy.commit(stage.run_id, manifest.clips)
    assert repo.get_season("holiday").name == "Updated holiday"
    assert repo.get_season("holiday").priority == 2
    assert repo.get_processing_profile("worker-profile").name == "Worker"


async def test_sql_failure_unlinks_files_and_retry_succeeds(
    client: TestClient, paths: Paths, manifest: LegacyManifest
) -> None:
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    db = client.app.state.db
    with db.transaction() as conn:
        conn.execute(
            "CREATE TRIGGER fail_import BEFORE INSERT ON renders "
            "BEGIN SELECT RAISE(ABORT, 'test render failure'); END"
        )
    report = await legacy.commit(stage.run_id, manifest.clips)
    assert report.skipped[0].reason == "import_error: ConflictError"
    assert client.app.state.repo.last_legacy_report() == report
    assert client.app.state.repo.list_clips() == []
    assert client.app.state.repo.list_renders() == []
    assert list(paths.originals_dir.rglob("*.mp4")) == []
    assert list(paths.renders_dir.rglob("*.mp4")) == []
    assert not (paths.work_dir / "import" / stage.run_id).exists()
    with db.transaction() as conn:
        conn.execute("DROP TRIGGER fail_import")
    stage = await legacy.stage(manifest)
    report = await legacy.commit(stage.run_id, manifest.clips)
    assert report.imported == [CLIP_ID]


@pytest.mark.parametrize("root", ["source", "compiled"])
async def test_symlink_escape(
    client: TestClient, paths: Paths, manifest: LegacyManifest, root: str
) -> None:
    target = Path(getattr(manifest.roots, root)) / "regular/movie.mp4"
    target.unlink()
    outside = paths.data_dir / "outside.mp4"
    outside.write_bytes(b"outside")
    target.symlink_to(outside)
    stage = await importer(client, paths).stage(manifest)
    assert stage.staged == [] and stage.rejected[0].reason == "unsafe_path"


@pytest.mark.parametrize("file", ["source", "compiled"])
async def test_missing_files(
    client: TestClient, paths: Paths, manifest: LegacyManifest, file: str
) -> None:
    (Path(getattr(manifest.roots, file)) / "regular/movie.mp4").unlink()
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    report = await legacy.commit(stage.run_id, manifest.clips)
    if file == "source":
        assert report.needs_source == [CLIP_ID]
    else:
        assert report.queued_for_render == [CLIP_ID]


async def test_deleted_clip_and_rejected_report(
    client: TestClient, paths: Paths, manifest: LegacyManifest
) -> None:
    manifest.clips.append(manifest.clips[0].model_copy(update={"id": OTHER_ID, "state": "deleted"}))
    manifest.clips[0].relative_source_path = "../../outside.mp4"
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    assert stage.staged == [] and len(stage.rejected) == 1
    report = await legacy.commit(stage.run_id, manifest.clips)
    assert [(s.clip_id, s.reason) for s in report.skipped] == [(CLIP_ID, "unsafe_path")]
    assert client.app.state.repo.list_clips() == []


def test_api_validation_and_unknown_run(client: TestClient) -> None:
    state = client.app.state
    headers = {"Authorization": f"Bearer {state.tokens.get()}", "X-Cinema-Consumer": "test"}
    for body in (
        {"phase": "unknown"},
        {"phase": "stage"},
        {"phase": "commit", "run_id": "../../escape", "clips": []},
    ):
        response = client.post("/api/v1/import/legacy", headers=headers, json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)
    response = client.post(
        "/api/v1/import/legacy",
        headers=headers,
        json={"phase": "commit", "run_id": "not-found", "clips": []},
    )
    assert response.status_code == 404


async def test_overflow_timing_is_rejected(
    client: TestClient, paths: Paths, manifest: LegacyManifest
) -> None:
    manifest.clips[0].metadata["content_duration_seconds"] = 10**400
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    report = await legacy.commit(stage.run_id, manifest.clips)
    assert report.queued_for_render == [CLIP_ID]
    assert client.app.state.repo.get_clip(CLIP_ID).render is None


@pytest.mark.parametrize("offset,accepted", [(0.2, False), (0.04, True), (0.06, False)])
async def test_probe_duration_tolerance_without_timing(
    client: TestClient, paths: Paths, manifest: LegacyManifest, offset: float, accepted: bool
) -> None:
    clip = manifest.clips[0]
    for key in TIMING:
        del clip.metadata[key]
    measured = await probe(Path(manifest.roots.compiled) / clip.relative_output_path)
    clip.output_duration_seconds = measured.duration + offset
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    assert stage.staged == [CLIP_ID]
    report = await legacy.commit(stage.run_id, manifest.clips)
    imported = client.app.state.repo.get_clip(CLIP_ID)
    assert (imported.render is not None) is accepted
    if accepted:
        assert stage.rejected == [] and report.queued_for_render == []
        assert imported.render.timing_source == "legacy_full_file"
    else:
        assert stage.rejected[0].reason == "output_invalid"
        assert report.queued_for_render == [CLIP_ID]


@pytest.mark.parametrize(
    "id", ["worker-1", CLIP_ID.upper(), CLIP_ID.replace("-", ""), "../../escape", "not-a-uuid"]
)
async def test_invalid_worker_id(
    client: TestClient, paths: Paths, manifest: LegacyManifest, id: str
) -> None:
    manifest.clips[0].id = id
    stage = await importer(client, paths).stage(manifest)
    assert stage.staged == []
    assert [(r.clip_id, r.reason) for r in stage.rejected] == [(id, "invalid_id")]


async def test_missing_collection(
    client: TestClient, paths: Paths, manifest: LegacyManifest
) -> None:
    manifest.clips[0].collection_id = "missing"
    stage = await importer(client, paths).stage(manifest)
    assert stage.staged == [] and stage.rejected[0].reason == "collection_missing"


async def test_existing_app_profile(
    client: TestClient, paths: Paths, manifest: LegacyManifest
) -> None:
    manifest.profiles = []
    manifest.collections[0].processing_profile_id = "compatibility-4k-loudness"
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    assert stage.staged == [CLIP_ID] and not stage.rejected
    report = await legacy.commit(stage.run_id, manifest.clips)
    assert report.imported == [CLIP_ID]


async def test_unknown_profile_is_not_invalid_settings(
    client: TestClient, paths: Paths, manifest: LegacyManifest
) -> None:
    manifest.profiles = []
    stage = await importer(client, paths).stage(manifest)
    assert stage.rejected[0].reason == "profile_missing"


async def test_young_run_kept(client: TestClient, paths: Paths, manifest: LegacyManifest) -> None:
    stage = await importer(client, paths).stage(manifest)
    importer(client, paths, NOW + timedelta(minutes=59)).discard_stale()
    assert (paths.work_dir / "import" / stage.run_id / "stage.json").is_file()


async def test_new_collection_order(
    client: TestClient, paths: Paths, manifest: LegacyManifest
) -> None:
    manifest.collections[0].id = "new-collection"
    manifest.clips[0].collection_id = "new-collection"
    other = manifest.clips[0].model_copy(update={"id": OTHER_ID})
    manifest.clips.append(other)
    manifest.collections[0].ordered_clip_ids = [OTHER_ID, CLIP_ID]
    manifest.seasons = []
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    await legacy.commit(stage.run_id, manifest.clips)
    collection = client.app.state.repo.get_collection("new-collection")
    assert collection.order == [OTHER_ID, CLIP_ID]
    assert collection.playback_mode == "custom"


@pytest.mark.parametrize("root", ["source", "compiled"])
async def test_worker_symlink_into_studio(
    client: TestClient, paths: Paths, manifest: LegacyManifest, root: str
) -> None:
    target = Path(getattr(manifest.roots, root)) / "regular/movie.mp4"
    target.unlink()
    studio_file = paths.originals_dir / "studio.mp4"
    studio_file.write_bytes(b"Studio owned")
    target.symlink_to(studio_file)
    stage = await importer(client, paths).stage(manifest)
    assert stage.staged == [] and stage.rejected[0].reason == "unsafe_path"


async def test_import_root_stray_file_removed(
    client: TestClient, paths: Paths, manifest: LegacyManifest
) -> None:
    root = paths.work_dir / "import"
    root.mkdir()
    stray = root / "stray-file"
    stray.write_text("ignored")
    stage = await importer(client, paths).stage(manifest)
    assert stage.staged == [CLIP_ID]
    assert not stray.exists()


@pytest.mark.parametrize("contents", ["{bad json", "{}", '{"started_at":"invalid"}'])
async def test_corrupt_stage_discarded(
    client: TestClient, paths: Paths, manifest: LegacyManifest, contents: str
) -> None:
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    run = paths.work_dir / "import" / stage.run_id
    (run / "stage.json").write_text(contents)
    with pytest.raises(InvalidError, match="corrupt"):
        await legacy.commit(stage.run_id, manifest.clips)
    assert not run.exists()


async def test_no_source_or_output_failed(
    client: TestClient, paths: Paths, manifest: LegacyManifest
) -> None:
    manifest.clips[0].metadata.update(source_fingerprint="wrong", output_fingerprint="wrong")
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    report = await legacy.commit(stage.run_id, manifest.clips)
    clip = client.app.state.repo.get_clip(CLIP_ID)
    assert clip.status == "failed"
    assert clip.error == "no usable source or output (re-import or upload source)"
    assert report.needs_source == [CLIP_ID] and report.queued_for_render == []


async def test_started_at_captured_before_verification(
    client: TestClient, paths: Paths, manifest: LegacyManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = importer(client, paths)
    original = legacy._link_verified

    async def slow(*args: object):
        legacy.now = lambda: NOW + timedelta(minutes=10)
        return await original(*args)

    monkeypatch.setattr(legacy, "_link_verified", slow)
    stage = await legacy.stage(manifest)
    report = await legacy.commit(stage.run_id, manifest.clips)
    assert report.started_at == "2026-10-05T12:00:00Z"


async def test_clip_failure_isolated_and_sanitized(
    client: TestClient,
    paths: Paths,
    manifest: LegacyManifest,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manifest.clips.append(manifest.clips[0].model_copy(update={"id": OTHER_ID}))
    repo = client.app.state.repo
    original = repo.import_legacy_clip

    def fail_first(**kwargs: object):
        if kwargs["clip_id"] == CLIP_ID:
            raise InvalidError(f"private path {paths.data_dir}\nsecret password=private")
        return original(**kwargs)

    monkeypatch.setattr(repo, "import_legacy_clip", fail_first)
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    report = await legacy.commit(stage.run_id, manifest.clips)
    assert report.imported == [OTHER_ID]
    assert [(s.clip_id, s.reason) for s in report.skipped] == [
        (CLIP_ID, "import_error: InvalidError")
    ]
    assert repo.last_legacy_report() == report
    assert not (paths.work_dir / "import" / stage.run_id).exists()
    assert not list((paths.originals_dir / CLIP_ID).glob("*.mp4"))
    assert not list((paths.renders_dir / CLIP_ID).glob("*.mp4"))
    diagnostics = [r for r in caplog.records if r.name == "cinema_studio.legacy"]
    assert len(diagnostics) == 1
    record = diagnostics[0]
    assert record.exc_info is not None and record.exc_info[0] is InvalidError
    assert "password=private" in str(record.exc_info[1])
    assert CLIP_ID in record.getMessage() and stage.run_id in record.getMessage()


@pytest.mark.parametrize("failures", [1, 2])
async def test_enqueue_retry_or_failed_status(
    client: TestClient,
    paths: Paths,
    manifest: LegacyManifest,
    monkeypatch: pytest.MonkeyPatch,
    failures: int,
) -> None:
    manifest.clips[0].metadata["output_fingerprint"] = "wrong"
    jobs = client.app.state.jobs
    original = jobs.enqueue_render
    calls = 0

    def enqueue(clip_id: str):
        nonlocal calls
        calls += 1
        if calls <= failures:
            raise RuntimeError("queue unavailable")
        return original(clip_id)

    monkeypatch.setattr(jobs, "enqueue_render", enqueue)
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    report = await legacy.commit(stage.run_id, manifest.clips)
    clip = client.app.state.repo.get_clip(CLIP_ID)
    assert calls == 2
    assert report.imported == [CLIP_ID]
    if failures == 1:
        assert report.queued_for_render == [CLIP_ID] and not report.skipped
        assert len(jobs.list_jobs()) == 1
        assert clip.status == "processing"
    else:
        assert not report.queued_for_render
        assert report.skipped[0].reason == "import_error: RuntimeError"
        assert clip.status == "failed" and clip.error == "render not queued"
    assert client.app.state.repo.last_legacy_report() == report


async def test_corrupt_stage_timestamp_returns_422(
    client: TestClient, paths: Paths, manifest: LegacyManifest
) -> None:
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    run = paths.work_dir / "import" / stage.run_id
    stage_file = run / "stage.json"
    saved = json.loads(stage_file.read_text())
    saved["started_at"] = "2026-10-05T12:00:00"  # Missing timezone is corrupt persisted state.
    stage_file.write_text(json.dumps(saved))
    client.app.state.legacy.now = lambda: NOW
    headers = {
        "Authorization": f"Bearer {client.app.state.tokens.get()}",
        "X-Cinema-Consumer": "test",
    }
    response = client.post(
        "/api/v1/import/legacy",
        headers=headers,
        json={
            "phase": "commit",
            "run_id": stage.run_id,
            "clips": [c.model_dump(mode="json") for c in manifest.clips],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "corrupt import stage"
    assert not run.exists()


async def test_housekeeping_waits_for_active_stage(
    client: TestClient, paths: Paths, manifest: LegacyManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = importer(client, paths)
    client.app.state.legacy = legacy
    paused = asyncio.Event()
    release = asyncio.Event()
    original = legacy._link_verified
    stage_file: Path | None = None

    async def pause_verification(source: Path, target: Path, expected: object):
        nonlocal stage_file
        if not paused.is_set():
            stage_file = target.parents[2] / "stage.json"
            stage_file.write_text('{"started_at":')
            paused.set()
            await release.wait()
        return await original(source, target, expected)

    # Inline executor dispatch so the old unlocked cleanup finishes deterministically,
    # without depending on a worker thread's scheduling or an elapsed-time assertion.
    async def inline_thread(func: Callable[..., object], *args: object, **kwargs: object):
        return func(*args, **kwargs)

    monkeypatch.setattr(legacy, "_link_verified", pause_verification)
    monkeypatch.setattr(asyncio, "to_thread", inline_thread)
    stage_task = asyncio.create_task(legacy.stage(manifest))
    cleanup_task = None
    try:
        await asyncio.wait_for(paused.wait(), 2)
        cleanup_task = asyncio.create_task(lifecycle._clean_up(client.app))
        await asyncio.sleep(0)  # Let cleanup reach the importer's lock.
        assert not cleanup_task.done(), "cleanup must wait for active staging"
        assert stage_file is not None and stage_file.read_text() == '{"started_at":'
        release.set()
        staged = await asyncio.wait_for(stage_task, 2)
        await asyncio.wait_for(cleanup_task, 2)
        assert stage_file.is_file()
        saved = json.loads(stage_file.read_text())
        assert saved["verdicts"][0]["clip_id"] == CLIP_ID
        report = await legacy.commit(staged.run_id, manifest.clips)
        assert report.imported == [CLIP_ID]
    finally:
        release.set()
        await asyncio.gather(
            stage_task,
            *([cleanup_task] if cleanup_task is not None else []),
            return_exceptions=True,
        )


async def test_cancelled_cleanup_keeps_lock_until_worker_finishes(
    client: TestClient, paths: Paths, manifest: LegacyManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = importer(client, paths)
    client.app.state.legacy = legacy
    staged = await legacy.stage(manifest)
    run = paths.work_dir / "import" / staged.run_id
    legacy.now = lambda: NOW + timedelta(hours=2)
    loop = asyncio.get_running_loop()
    worker_started = asyncio.Event()
    release_worker = threading.Event()
    rmtree = shutil.rmtree

    def slow_delete(path: Path):
        if path == run:
            loop.call_soon_threadsafe(worker_started.set)
            if not release_worker.wait(5):
                raise AssertionError("cleanup worker was not released")
        rmtree(path)

    monkeypatch.setattr(shutil, "rmtree", slow_delete)
    cleanup_task = asyncio.create_task(lifecycle._clean_up(client.app))
    try:
        await asyncio.wait_for(worker_started.wait(), 2)
        cleanup_task.cancel()
        await asyncio.sleep(0)
        assert legacy._lock.locked(), "cancellation must not release an active cleanup worker"
        cleanup_task.cancel()  # Repeated cancellation must also keep the worker fenced.
        await asyncio.sleep(0)
        assert legacy._lock.locked()
        with pytest.raises(ConflictError):
            await legacy.stage(manifest)
        release_worker.set()
        with pytest.raises(asyncio.CancelledError):
            await cleanup_task
        assert not run.exists() and not legacy._lock.locked()
        assert (await legacy.stage(manifest)).staged == [CLIP_ID]
    finally:
        release_worker.set()
        await asyncio.gather(cleanup_task, return_exceptions=True)
