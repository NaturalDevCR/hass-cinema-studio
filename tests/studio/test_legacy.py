"""Legacy imports verify real Worker files and preserve stable hard links."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cinema_studio.app import create_app
from cinema_studio.config import Paths
from cinema_studio.errors import ConflictError, InvalidError
from cinema_studio.legacy import LegacyImporter, LegacyManifest
from cinema_studio.media import file_sha256, legacy_fingerprint
from cinema_studio.models import CollectionUpdate

pytestmark = pytest.mark.studio
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
TIMING = {
    "content_duration_seconds": 2.0,
    "lead_in_duration_seconds": 1.0,
    "tail_out_duration_seconds": 1.0,
    "content_start_offset_seconds": 1.0,
    "content_end_offset_seconds": 3.0,
}


@pytest.fixture
def client(paths: Paths) -> Iterator[TestClient]:
    with TestClient(create_app(paths, start_background=False)) as client:
        client.app.state.store.ensure_dirs()
        yield client


@pytest.fixture
async def manifest(paths: Paths, make_video: Callable[..., Path]) -> LegacyManifest:
    source = paths.media_dir / "cinema-collections/source"
    compiled = paths.media_dir / "cinema-collections/compiled"
    video = make_video()
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
                    "ordered_clip_ids": ["worker-1"],
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
                    "id": "worker-1",
                    "collection_id": "regular",
                    "state": "ready",
                    "relative_source_path": "regular/movie.mp4",
                    "relative_output_path": "regular/movie.mp4",
                    "output_available": True,
                    "output_duration_seconds": 4.0,
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
    assert stage.staged == ["worker-1"] and stage.rejected == []
    assert (paths.work_dir / "import" / stage.run_id / "stage.json").is_file()
    # A new instance can commit persisted staging.
    report = await importer(client, paths).commit(stage.run_id, manifest.clips)
    repo = client.app.state.repo
    clip = repo.get_clip("worker-1")
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
    ) == (4, 1, 3, 2, 1, 1)
    assert clip.recipe.lead_in == 1 and clip.recipe.tail_out == 1
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
        clip.output_duration_seconds = 5
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
        assert imported.render.content_start == 0 and imported.render.content_end == 4
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


@pytest.mark.parametrize("field", ["relative_source_path", "relative_output_path", "id"])
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
    other = manifest.clips[0].model_copy(deep=True, update={"id": "worker-2"})
    manifest.clips.append(other)
    manifest.collections[0].ordered_clip_ids = [other.id, "worker-1"]
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    await legacy.commit(stage.run_id, manifest.clips)
    repo = client.app.state.repo
    assert repo.get_collection("regular").order == [other.id, "worker-1"]
    repo.set_collection_order("regular", ["worker-1", other.id])
    repo.update_collection("regular", CollectionUpdate(playback_mode="sequential"))
    stage = await legacy.stage(manifest)
    report = await legacy.commit(stage.run_id, manifest.clips)
    assert [s.reason for s in report.skipped] == ["already_imported", "already_imported"]
    assert repo.get_collection("regular").order == ["worker-1", other.id]
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
    with pytest.raises(InvalidError, match="DB failure"):
        await legacy.commit(stage.run_id, manifest.clips)
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
    assert response.status_code == 200 and response.json()["imported"] == ["worker-1"]


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
    with pytest.raises(ConflictError, match="test render failure"):
        await legacy.commit(stage.run_id, manifest.clips)
    assert client.app.state.repo.list_clips() == []
    assert client.app.state.repo.list_renders() == []
    assert list(paths.originals_dir.rglob("*.mp4")) == []
    assert list(paths.renders_dir.rglob("*.mp4")) == []
    assert (paths.work_dir / "import" / stage.run_id / "out/worker-1.mp4").is_file()
    with db.transaction() as conn:
        conn.execute("DROP TRIGGER fail_import")
    report = await legacy.commit(stage.run_id, manifest.clips)
    assert report.imported == ["worker-1"]


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
        assert report.needs_source == ["worker-1"]
    else:
        assert report.queued_for_render == ["worker-1"]


async def test_deleted_clip_and_rejected_report(
    client: TestClient, paths: Paths, manifest: LegacyManifest
) -> None:
    manifest.clips.append(
        manifest.clips[0].model_copy(update={"id": "deleted", "state": "deleted"})
    )
    manifest.clips[0].relative_source_path = "../../outside.mp4"
    legacy = importer(client, paths)
    stage = await legacy.stage(manifest)
    assert stage.staged == [] and len(stage.rejected) == 1
    report = await legacy.commit(stage.run_id, manifest.clips)
    assert [(s.clip_id, s.reason) for s in report.skipped] == [("worker-1", "unsafe_path")]
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
    assert report.queued_for_render == ["worker-1"]
    assert client.app.state.repo.get_clip("worker-1").render is None
