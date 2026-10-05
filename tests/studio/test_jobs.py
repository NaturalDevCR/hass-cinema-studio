"""Real-ffmpeg job queue behavior: probe, render, preview, thumbnails, propagation, notifier."""

import asyncio
import hashlib
import logging
import os
import shutil
import threading
from types import SimpleNamespace

import pytest

from cinema_studio import media
from cinema_studio.db import Database
from cinema_studio.errors import NotFoundError
from cinema_studio.fence import GarbageCollector, GcFence, GcResult
from cinema_studio.ffmpeg import FfmpegCommandBuilder
from cinema_studio.jobs import JobQueue, render_timeout
from cinema_studio.models import (
    Asset,
    AssetUpdate,
    ClipUpdate,
    CollectionCreate,
    OriginalInfo,
    ProcessingProfileCreate,
    ProcessingProfileUpdate,
    Recipe,
)
from cinema_studio.notifier import CatalogNotifier
from cinema_studio.probe import probe
from cinema_studio.profiles import validate_settings
from cinema_studio.render import RenderEngine, recipe_hash
from cinema_studio.repository import Repository
from cinema_studio.storage import MediaStore

pytestmark = pytest.mark.studio

DEFAULT = "compatibility-4k-loudness"


@pytest.fixture
def repo(paths, small_profile_settings):
    db = Database(paths.database_path)
    repository = Repository(db, validate_settings=validate_settings)
    repository.update_processing_profile(
        DEFAULT, ProcessingProfileUpdate(settings=small_profile_settings)
    )
    yield repository
    db.close()


@pytest.fixture
def store(paths):
    media_store = MediaStore(paths)
    media_store.ensure_dirs()
    return media_store


@pytest.fixture
def engine():
    return RenderEngine(FfmpegCommandBuilder(), timeout_for=lambda _: 60)


def make_queue(repo, store, engine, paths, gc=None):
    collector = gc or GarbageCollector(paths, repo, GcFence(paths), store)
    return JobQueue(repo, store, engine, paths, collector)


@pytest.fixture
async def queue(repo, store, engine, paths):
    jobs = make_queue(repo, store, engine, paths)
    await jobs.start()
    try:
        yield jobs
    finally:
        await jobs.stop()


@pytest.fixture
def idle_queue(repo, store, engine, paths):
    """A queue whose worker never starts, so enqueued jobs stay queued."""
    return make_queue(repo, store, engine, paths)


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_clip(repo, store, src, *, title="Movie", collection_id="regular", recipe=None, **fields):
    clip = repo.create_clip(
        clip_id=None,
        collection_id=collection_id,
        title=title,
        source_name=src.name,
        recipe=recipe or Recipe(),
        original=None,
        sort_key=title.casefold(),
        **fields,
    )
    store.store_original(src, clip.id, src.name, link=False)
    return clip.id


async def uploaded(queue, repo, store, make_video, name="movie.mp4", seconds=4.0, **kwargs):
    """The upload flow: a clip with a stored original, probed and rendered by the queue."""
    clip_id = add_clip(repo, store, make_video(name=name, seconds=seconds), **kwargs)
    queue.enqueue_probe(clip_id)
    await queue.wait_idle()
    clip = repo.get_clip(clip_id)
    assert clip.status == "ready", clip.error
    return clip


def original_path(paths, clip):
    return paths.originals_dir / clip.id / clip.original.filename


def add_intro(repo, paths, make_video, settings, seconds=2.0):
    source = make_video(name="intro-src.mp4", seconds=seconds)
    destination = paths.assets_dir / "intro.mp4"
    shutil.copyfile(source, destination)
    repo.create_asset(
        Asset(
            filename="intro.mp4",
            size=destination.stat().st_size,
            sha256=sha256_of(destination),
            status="ready",
        )
    )
    repo.update_processing_profile(
        DEFAULT, ProcessingProfileUpdate(settings={**settings, "intro_reference": "intro.mp4"})
    )


def hook_engine(engine, monkeypatch, *, mutate=None, mutate_at="progress", hold_call=None):
    """Wrap ``engine.render``: run ``mutate`` once during call 1, optionally pause call N."""
    state = SimpleNamespace(
        calls=0, plans=[], entered=asyncio.Event(), release=asyncio.Event(), fired=False
    )
    real = engine.render

    def fire():
        if mutate is not None and not state.fired:
            state.fired = True
            mutate()

    async def render(plan, on_progress=None):
        state.calls += 1
        index = state.calls
        state.plans.append(plan)
        if hold_call == index:
            state.entered.set()
            await state.release.wait()
        if index == 1 and mutate_at == "before":
            fire()

        def progress(value):
            if index == 1 and mutate_at == "progress":
                fire()
            if on_progress is not None:
                on_progress(value)

        return await real(plan, progress)

    monkeypatch.setattr(engine, "render", render)
    return state


# --- upload flow -----------------------------------------------------------------------------


async def test_upload_flow_probes_renders_and_creates_thumbnails(
    queue, repo, store, paths, make_video
):
    src = make_video(seconds=4)
    clip_id = add_clip(repo, store, src)
    job = queue.enqueue_probe(clip_id)
    assert job.kind == "probe" and job.clip_id == clip_id and job.clip_title == "Movie"
    await queue.wait_idle()
    clip = repo.get_clip(clip_id)
    assert job.status == "done" and job.progress == 1 and job.error is None
    assert job.created_at.endswith("Z") and job.started_at and job.finished_at
    assert clip.status == "ready" and clip.error is None and not clip.render_pending
    assert clip.original is not None
    assert clip.original.sha256 == sha256_of(original_path(paths, clip))
    assert clip.original.duration == pytest.approx(4, abs=0.1)
    assert (clip.original.width, clip.original.height, clip.original.has_audio) == (320, 180, True)
    render = clip.render
    assert render is not None and render.n == 1 and render.timing_source == "measured"
    final = paths.media_dir / render.relative_path
    assert final.is_file() and final.stat().st_size == render.size
    assert render.sha256 == sha256_of(final)
    assert render.relative_path.startswith(f"cinema-studio/renders/{clip_id}/{clip_id}-r1-")
    assert render.duration == pytest.approx(8, abs=0.2) and render.content_start == 2.0
    assert render.content_duration == pytest.approx(4, abs=0.1)
    assert len(render.profile_fingerprint) == 64
    assert render.recipe_hash == recipe_hash(Recipe(), None)
    thumbs = paths.thumbs_dir / clip_id
    assert (thumbs / "original" / "poster.jpg").is_file()
    assert (thumbs / "original" / "filmstrip.json").is_file()
    assert (thumbs / "original" / "0000.jpg").is_file()
    assert (thumbs / "r1" / "poster.jpg").is_file()
    assert clip.has_thumbs
    assert [j.kind for j in reversed(queue.list_jobs())] == ["probe", "render", "thumbs"]
    assert not any(path.is_dir() and path.name != "previews" for path in paths.work_dir.iterdir())


async def test_recipe_edit_publishes_r2_and_retires_r1_with_its_file(
    queue, repo, store, paths, make_video
):
    clip = await uploaded(queue, repo, store, make_video)
    r1 = clip.render
    repo.set_recipe(clip.id, Recipe(trim_start=1, trim_end=3, fade_in=0, fade_out=0))
    assert repo.get_clip(clip.id).render_pending
    job = queue.enqueue_render(clip.id)
    await queue.wait_idle()
    updated = repo.get_clip(clip.id)
    assert job.status == "done"
    assert updated.render.n == 2 and updated.render.id != r1.id and not updated.render_pending
    assert updated.render.content_duration == pytest.approx(2, abs=0.1)
    retired = repo.get_render(r1.id)
    assert retired.state == "retired" and (paths.media_dir / r1.relative_path).is_file()
    assert (paths.thumbs_dir / clip.id / "r2" / "poster.jpg").is_file()


async def test_failure_keeps_the_published_render_and_the_worker_alive(
    queue, repo, store, paths, make_video
):
    clip = await uploaded(queue, repo, store, make_video)
    repo.set_recipe(clip.id, Recipe(gain_db=1.0))
    queue.enqueue_render(clip.id)
    await queue.wait_idle()
    r2 = repo.get_clip(clip.id).render
    assert r2.n == 2
    original_path(paths, clip).write_bytes(b"garbage")
    job = queue.enqueue_render(clip.id)
    await queue.wait_idle()
    failed = repo.get_clip(clip.id)
    assert job.status == "failed" and job.error and len(job.error) <= 400
    assert failed.status == "failed" and failed.error == job.error
    assert failed.render.id == r2.id and (paths.media_dir / r2.relative_path).is_file()
    assert not (paths.work_dir / job.id).exists()
    other = await uploaded(queue, repo, store, make_video, name="other.mp4", title="Other")
    assert other.render is not None


async def test_queued_renders_coalesce_but_a_running_one_does_not(
    queue, repo, store, paths, engine, make_video, monkeypatch
):
    clip = await uploaded(queue, repo, store, make_video)
    state = hook_engine(engine, monkeypatch, hold_call=1)
    running = queue.enqueue_render(clip.id)
    await asyncio.wait_for(state.entered.wait(), 60)
    assert running.status == "running"
    queued = queue.enqueue_render(clip.id)
    assert queued.id != running.id and queued.status == "queued"
    assert queue.enqueue_render(clip.id) is queued
    other = add_clip(repo, store, make_video(name="b.mp4"), title="B")
    other_job = queue.enqueue_render(other)
    assert other_job.id != queued.id
    ids = [job.id for job in queue.list_jobs()[:3]]
    assert ids == [running.id, queued.id, other_job.id]
    state.release.set()
    await queue.wait_idle()
    assert [running.status, queued.status] == ["done", "done"]
    assert repo.get_clip(clip.id).render.n == 3


# --- frozen inputs ---------------------------------------------------------------------------

STALE_DELTA = {"recipe": 0.0, "processing": 0.0, "asset": 1.0, "source": -1.0}


@pytest.mark.parametrize("variant", list(STALE_DELTA))
async def test_stale_job_publishes_its_frozen_inputs_and_stays_pending(
    variant, queue, repo, store, paths, engine, make_video, small_profile_settings, monkeypatch
):
    add_intro(repo, paths, make_video, small_profile_settings)
    clip = await uploaded(queue, repo, store, make_video)
    repo.set_recipe(clip.id, Recipe(gain_db=1.0))

    def mutate_recipe():
        repo.set_recipe(clip.id, Recipe(gain_db=2.0))

    def mutate_processing():
        repo.update_processing_profile(
            DEFAULT,
            ProcessingProfileUpdate(
                settings={
                    **small_profile_settings,
                    "intro_reference": "intro.mp4",
                    "fade_out_seconds": 0.5,
                }
            ),
        )

    new_intro = make_video(name="intro-new.mp4", seconds=3)
    new_source = make_video(name="source-new.mp4", seconds=3)

    def mutate_asset():
        os.replace(new_intro, paths.assets_dir / "intro.mp4")
        repo.update_asset(
            "intro.mp4",
            AssetUpdate(
                size=(paths.assets_dir / "intro.mp4").stat().st_size,
                sha256=sha256_of(paths.assets_dir / "intro.mp4"),
            ),
        )

    replacement = OriginalInfo(
        filename=clip.original.filename,
        size=new_source.stat().st_size,
        sha256=sha256_of(new_source),
        duration=3.0,
        width=320,
        height=180,
        fps=24.0,
        has_audio=True,
        video_codec="h264",
    )

    def mutate_source():
        os.replace(new_source, original_path(paths, clip))
        repo.set_original(clip.id, replacement)

    mutation = {
        "recipe": mutate_recipe,
        "processing": mutate_processing,
        "asset": mutate_asset,
        "source": mutate_source,
    }[variant]
    state = hook_engine(engine, monkeypatch, mutate=mutation, hold_call=2)
    first = queue.enqueue_render(clip.id)
    await asyncio.wait_for(state.entered.wait(), 60)
    # The stale job finished and published what it rendered, then queued a newer render.
    stale = repo.get_clip(clip.id)
    assert first.status == "done" and stale.render.n == 2
    assert stale.render_pending and stale.status == "rendering"
    assert [j.kind for j in queue.list_jobs() if j.status in {"running", "queued"}][0] == "render"
    assert state.calls == 2
    state.release.set()
    await queue.wait_idle()
    fresh = repo.get_clip(clip.id)
    assert fresh.render.n == 3 and not fresh.render_pending and fresh.status == "ready"
    assert fresh.render.profile_fingerprint != stale.render.profile_fingerprint
    assert fresh.render.duration - stale.render.duration == pytest.approx(
        STALE_DELTA[variant], abs=0.2
    )
    if variant == "recipe":
        assert stale.render.recipe_hash == recipe_hash(Recipe(gain_db=1.0), None)
        assert fresh.render.recipe_hash == recipe_hash(Recipe(gain_db=2.0), None)


async def test_inputs_are_hard_linked_so_a_replaced_asset_cannot_change_the_job(
    queue, repo, store, paths, engine, make_video, small_profile_settings, monkeypatch
):
    add_intro(repo, paths, make_video, small_profile_settings, seconds=2)
    clip = await uploaded(queue, repo, store, make_video)
    baseline = clip.render
    new_intro = make_video(name="intro-new.mp4", seconds=3)

    def replace_asset():
        os.replace(new_intro, paths.assets_dir / "intro.mp4")
        repo.update_asset(
            "intro.mp4",
            AssetUpdate(sha256=sha256_of(paths.assets_dir / "intro.mp4")),
        )

    state = hook_engine(engine, monkeypatch, mutate=replace_asset, mutate_at="before")
    repo.set_recipe(clip.id, Recipe(gain_db=1.0))
    job = queue.enqueue_render(clip.id)
    await queue.wait_idle()
    plan = state.plans[0]
    inputs = paths.work_dir / job.id / "inputs"
    assert plan.source.parent == inputs and plan.intro.parent == inputs
    assert plan.source.name != plan.output.name
    renders = {r.n: r for r in repo.list_renders()}
    # r2 was rendered from the frozen (old, 2 s) intro; r3 picked up the replacement (3 s).
    assert renders[2].duration == pytest.approx(baseline.duration, abs=0.2)
    assert renders[3].duration == pytest.approx(baseline.duration + 1, abs=0.2)
    assert not (paths.work_dir / job.id).exists()
    assert repo.get_clip(clip.id).render.n == 3 and not repo.get_clip(clip.id).render_pending


async def test_missing_asset_fails_with_an_actionable_message(
    queue, repo, store, paths, make_video, small_profile_settings
):
    clip = await uploaded(queue, repo, store, make_video)
    repo.create_asset(Asset(filename="intro.mp4", size=None, sha256=None, status="missing"))
    repo.update_processing_profile(
        DEFAULT,
        ProcessingProfileUpdate(
            settings={**small_profile_settings, "intro_reference": "intro.mp4"}
        ),
    )
    repo.set_flags(clip.id, render_pending=True)
    job = queue.enqueue_render(clip.id)
    await queue.wait_idle()
    failed = repo.get_clip(clip.id)
    assert job.status == "failed"
    assert job.error == "asset intro.mp4 missing: upload it in Organize"
    assert failed.status == "failed" and failed.error == job.error
    assert failed.render.n == 1 and failed.render_pending


async def test_insufficient_space_fails_before_rendering(
    queue, repo, store, make_video, monkeypatch
):
    clip = await uploaded(queue, repo, store, make_video)
    monkeypatch.setattr(store, "free_bytes", lambda: 0)
    job = queue.enqueue_render(clip.id)
    await queue.wait_idle()
    failed = repo.get_clip(clip.id)
    assert job.status == "failed" and "not enough free space" in job.error
    assert failed.status == "failed" and failed.render.n == 1


async def test_clip_without_original_is_refused_and_left_untouched(queue, repo, store):
    clip = repo.create_clip(
        clip_id=None,
        collection_id="regular",
        title="Legacy",
        source_name="legacy.mp4",
        recipe=Recipe(),
        original=None,
        sort_key="legacy",
        needs_source=True,
        status="ready",
    )
    job = queue.enqueue_render(clip.id)
    await queue.wait_idle()
    assert job.status == "failed" and "needs source" in job.error
    assert repo.get_clip(clip.id).status == "ready"


async def test_unexpected_errors_are_truncated_and_do_not_kill_the_worker(
    queue, repo, store, engine, make_video, monkeypatch, caplog
):
    clip = await uploaded(queue, repo, store, make_video)

    async def broken(plan, on_progress=None):
        raise RuntimeError("x" * 1000 + "tail")

    monkeypatch.setattr(engine, "render", broken)
    with caplog.at_level(logging.ERROR, logger="cinema_studio.jobs"):
        failed = queue.enqueue_render(clip.id)
        await queue.wait_idle()
    assert failed.status == "failed" and failed.error == "x" * 396 + "tail"
    assert "Job" in caplog.text
    monkeypatch.undo()
    retry = queue.enqueue_render(clip.id)
    await queue.wait_idle()
    assert retry.status == "done" and repo.get_clip(clip.id).status == "ready"


# --- previews --------------------------------------------------------------------------------


async def test_preview_keeps_clip_and_catalog_untouched(queue, repo, store, paths, make_video):
    clip = await uploaded(queue, repo, store, make_video)
    revision = repo.catalog_revision()
    job = queue.enqueue_preview(clip.id, Recipe(trim_start=1, trim_end=3, fade_in=0, fade_out=0))
    await queue.wait_idle()
    stored = repo.get_clip(clip.id)
    preview = paths.work_dir / "previews" / f"{clip.id}.mp4"
    assert job.status == "done" and job.kind == "preview"
    assert stored.has_preview and stored.status == "ready"
    assert stored.recipe == clip.recipe and stored.render == clip.render
    assert repo.catalog_revision() == revision
    assert (await probe(preview)).duration == pytest.approx(6, abs=0.2)
    content = preview.read_bytes()
    bad = queue.enqueue_preview(clip.id, Recipe(trim_start=10))
    await queue.wait_idle()
    assert bad.status == "failed" and preview.read_bytes() == content
    assert repo.get_clip(clip.id).status == "ready" and repo.catalog_revision() == revision
    assert not list((paths.work_dir / "previews").glob(".*"))


async def test_preview_recipe_is_copied_at_enqueue(queue, repo, store, paths, make_video):
    clip = await uploaded(queue, repo, store, make_video)
    recipe = Recipe(trim_end=1, fade_in=0, fade_out=0)
    job = queue.enqueue_preview(clip.id, recipe)
    recipe.trim_end = 3
    await queue.wait_idle()
    preview = paths.work_dir / "previews" / f"{clip.id}.mp4"
    assert job.status == "done"
    assert (await probe(preview)).duration == pytest.approx(5, abs=0.2)


# --- thumbnails ------------------------------------------------------------------------------


async def test_original_thumbnails_are_made_once_per_original_and_poster_follows_content(
    queue, repo, store, paths, make_video, monkeypatch
):
    films, posters = [], []
    real_film, real_poster = media.make_filmstrip, media.make_poster

    async def film(src, dst, *, duration):
        films.append(src)
        return await real_film(src, dst, duration=duration)

    async def poster(src, dst, at):
        posters.append((dst.relative_to(paths.thumbs_dir).as_posix(), at))
        await real_poster(src, dst, at)

    monkeypatch.setattr(media, "make_filmstrip", film)
    monkeypatch.setattr(media, "make_poster", poster)
    clip = await uploaded(queue, repo, store, make_video)
    assert len(films) == 1
    assert (f"{clip.id}/r1/poster.jpg", pytest.approx(clip.render.content_start + 1)) in posters
    queue.enqueue_thumbs(clip.id)
    await queue.wait_idle()
    assert len(films) == 1
    new_source = make_video(name="replacement.mp4", seconds=3)
    os.replace(new_source, original_path(paths, clip))
    repo.set_original(
        clip.id,
        clip.original.model_copy(
            update={"sha256": sha256_of(original_path(paths, clip)), "duration": 3.0}
        ),
    )
    queue.enqueue_thumbs(clip.id)
    await queue.wait_idle()
    assert len(films) == 2
    assert not list((paths.thumbs_dir / clip.id).glob(".*"))
    assert (paths.thumbs_dir / clip.id / "original" / "poster.jpg").is_file()


# --- propagation -----------------------------------------------------------------------------


@pytest.fixture
def world(repo, idle_queue, small_profile_settings):
    repo.create_processing_profile(
        ProcessingProfileCreate(
            id="p2", name="Second", settings={**small_profile_settings, "intro_reference": "i.mp4"}
        )
    )
    for collection_id, profile in (("c1", DEFAULT), ("c2", DEFAULT), ("c3", "p2")):
        repo.create_collection(
            CollectionCreate(id=collection_id, name=collection_id, processing_profile_id=profile)
        )
    clips = {}
    for name, collection_id, recipe in (
        ("a", "c1", Recipe()),
        ("b", "c2", Recipe()),
        ("c", "c3", Recipe()),
        ("d", "c3", Recipe(profile_id="loud")),
        ("e", "regular", Recipe(profile_id="loud")),
    ):
        clips[name] = repo.create_clip(
            clip_id=name,
            collection_id=collection_id,
            title=name,
            source_name=f"{name}.mp4",
            recipe=recipe,
            original=None,
            sort_key=name,
        ).id
    return clips


def pending(repo):
    return {clip.id for clip in repo.list_clips() if clip.render_pending}


def queued_renders(queue):
    return [j.clip_id for j in queue.list_jobs() if j.kind == "render" and j.status == "queued"]


def test_processing_profile_change_marks_the_clips_of_its_collections(repo, idle_queue, world):
    revision = repo.catalog_revision()
    affected = idle_queue.on_processing_profile_changed(DEFAULT)
    assert set(affected) == {"a", "b", "e"} == pending(repo)
    assert sorted(queued_renders(idle_queue)) == ["a", "b", "e"]
    assert repo.catalog_revision() > revision
    idle_queue.on_processing_profile_changed(DEFAULT)
    assert sorted(queued_renders(idle_queue)) == ["a", "b", "e"]


def test_normalization_change_marks_clips_using_it_only_when_targets_changed(
    repo, idle_queue, world
):
    assert idle_queue.on_normalization_profile_changed("loud", targets_changed=False) == []
    assert pending(repo) == set() and queued_renders(idle_queue) == []
    assert set(idle_queue.on_normalization_profile_changed("loud")) == {"d", "e"}
    assert pending(repo) == {"d", "e"} and sorted(queued_renders(idle_queue)) == ["d", "e"]


def test_collection_profile_change_marks_that_collection(repo, idle_queue, world):
    assert set(idle_queue.on_collection_profile_changed("c3")) == {"c", "d"}
    assert pending(repo) == {"c", "d"} and sorted(queued_renders(idle_queue)) == ["c", "d"]


def test_asset_change_marks_clips_whose_profile_uses_it(
    repo, idle_queue, world, small_profile_settings
):
    repo.create_processing_profile(
        ProcessingProfileCreate(
            id="p3", name="Outro", settings={**small_profile_settings, "outro_reference": "o.mp4"}
        )
    )
    repo.create_collection(CollectionCreate(id="c4", name="c4", processing_profile_id="p3"))
    repo.create_clip(
        clip_id="f",
        collection_id="c4",
        title="f",
        source_name="f.mp4",
        recipe=Recipe(),
        original=None,
        sort_key="f",
    )
    assert set(idle_queue.on_asset_changed("i.mp4")) == {"c", "d"}
    assert pending(repo) == {"c", "d"}
    assert idle_queue.on_asset_changed("o.mp4") == ["f"]
    assert idle_queue.on_asset_changed("unused.mp4") == []
    assert pending(repo) == {"c", "d", "f"}


def test_moving_a_clip_to_a_collection_with_another_profile_marks_it(repo, idle_queue, world):
    repo.update_clip("a", ClipUpdate(collection_id="c2"))
    assert idle_queue.on_clip_collection_changed("a", "c1") == []
    assert pending(repo) == set()
    repo.update_clip("a", ClipUpdate(collection_id="c3"))
    assert idle_queue.on_clip_collection_changed("a", "c2") == ["a"]
    assert pending(repo) == {"a"} and queued_renders(idle_queue) == ["a"]


async def test_propagated_renders_run_and_clear_pending(
    queue, repo, store, paths, make_video, small_profile_settings
):
    clip = await uploaded(queue, repo, store, make_video)
    repo.update_processing_profile(
        DEFAULT,
        ProcessingProfileUpdate(settings={**small_profile_settings, "fade_in_seconds": 0.5}),
    )
    assert queue.on_processing_profile_changed(DEFAULT) == [clip.id]
    assert repo.get_clip(clip.id).render_pending
    await queue.wait_idle()
    updated = repo.get_clip(clip.id)
    assert updated.render.n == 2 and not updated.render_pending
    assert updated.render.profile_fingerprint != clip.render.profile_fingerprint


# --- lifecycle -------------------------------------------------------------------------------


async def test_start_recovers_interrupted_work(repo, store, engine, paths, make_video):
    interrupted = add_clip(repo, store, make_video(name="a.mp4"), title="Interrupted")
    orphan = repo.create_clip(
        clip_id=None,
        collection_id="regular",
        title="Orphan",
        source_name="o.mp4",
        recipe=Recipe(),
        original=None,
        sort_key="orphan",
    ).id
    repo.set_flags(orphan, has_preview=True)
    jobs = make_queue(repo, store, engine, paths)
    await jobs.start()
    try:
        await jobs.wait_idle()
        assert repo.get_clip(interrupted).status == "ready"
        failed = repo.get_clip(orphan)
        assert failed.status == "failed" and failed.error == "interrupted"
        assert not failed.has_preview
    finally:
        await jobs.stop()


async def test_stop_settles_the_running_job_and_restores_the_clip(
    repo, store, engine, paths, make_video, monkeypatch
):
    jobs = make_queue(repo, store, engine, paths)
    await jobs.start()
    clip = await uploaded(jobs, repo, store, make_video)
    state = hook_engine(engine, monkeypatch, hold_call=1)
    running = jobs.enqueue_render(clip.id)
    queued = jobs.enqueue_preview(clip.id, Recipe())
    await asyncio.wait_for(state.entered.wait(), 60)
    await jobs.stop()
    assert running.status == "failed" and running.error == "cancelled"
    assert queued.status == "failed" and queued.error == "cancelled"
    restored = repo.get_clip(clip.id)
    assert restored.status == "ready" and restored.render.n == 1
    assert not (paths.work_dir / running.id).exists()
    await jobs.wait_idle(1)


async def test_hourly_gc_runs_off_the_event_loop_thread(repo, store, engine, paths):
    threads = []

    class FakeGc:
        def run(self):
            threads.append(threading.get_ident())
            return GcResult([], None)

    jobs = make_queue(repo, store, engine, paths, gc=FakeGc())
    assert jobs.gc_interval == 3600
    jobs.gc_interval = 0.02
    await jobs.start()
    try:
        for _ in range(100):
            if len(threads) >= 2:
                break
            await asyncio.sleep(0.02)
        assert len(threads) >= 2 and threading.get_ident() not in threads
        result = await jobs.run_gc()
        assert result == GcResult([], None)
    finally:
        await jobs.stop()


async def test_a_failing_gc_does_not_stop_the_loop(repo, store, engine, paths, caplog):
    calls = []

    class BrokenGc:
        def run(self):
            calls.append(1)
            raise OSError("disk gone")

    jobs = make_queue(repo, store, engine, paths, gc=BrokenGc())
    jobs.gc_interval = 0.02
    with caplog.at_level(logging.ERROR, logger="cinema_studio.jobs"):
        await jobs.start()
        try:
            for _ in range(100):
                if len(calls) >= 2:
                    break
                await asyncio.sleep(0.02)
        finally:
            await jobs.stop()
    assert len(calls) >= 2 and "disk gone" in caplog.text


def test_unknown_clips_are_rejected_at_enqueue(idle_queue):
    for enqueue in (idle_queue.enqueue_probe, idle_queue.enqueue_render, idle_queue.enqueue_thumbs):
        with pytest.raises(NotFoundError):
            enqueue("ghost")
    with pytest.raises(NotFoundError):
        idle_queue.enqueue_preview("ghost", Recipe())


def test_render_timeout_scales_with_the_media_length():
    assert render_timeout(60) == 300
    assert render_timeout(600) == 1200
    assert render_timeout(0) == 300


# --- notifier --------------------------------------------------------------------------------


async def test_notifier_debounce_and_thread_safety():
    seen = []

    async def send(revision):
        seen.append(revision)

    notifier = CatalogNotifier(send, delay=0.1)
    try:
        notifier.mark_changed(1)
        notifier.mark_changed(2)
        await asyncio.to_thread(notifier.mark_changed, 3)
        await notifier.flush()
        assert seen == [3]
    finally:
        await notifier.close()


async def test_notifier_send_failure_and_close(caplog):
    seen = []

    async def send(revision):
        seen.append(revision)
        if revision == 1:
            raise RuntimeError("offline")

    notifier = CatalogNotifier(send, delay=0.1)
    notifier.mark_changed(1)
    await notifier.flush()
    assert "offline" in caplog.text
    notifier.mark_changed(2)
    await notifier.flush()
    assert seen == [1, 2]
    notifier.mark_changed(3)
    await notifier.close()
    notifier.mark_changed(4)
    await notifier.flush()
    assert seen == [1, 2]


async def test_notifier_marks_during_send_and_ignores_older_revisions():
    seen = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(revision):
        seen.append(revision)
        if revision == 1:
            entered.set()
            await release.wait()

    notifier = CatalogNotifier(send, delay=0.1)
    try:
        notifier.mark_changed(1)
        await asyncio.wait_for(entered.wait(), 5)
        await asyncio.to_thread(notifier.mark_changed, 3)
        notifier.mark_changed(2)
        release.set()
        await notifier.flush()
        assert seen == [1, 3]
    finally:
        await notifier.close()
