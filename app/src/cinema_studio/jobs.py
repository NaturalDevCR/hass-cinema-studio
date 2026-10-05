"""One FIFO worker for probes, renders, previews and thumbnails, plus edit propagation.

The queue is meant to be driven from the event loop (enqueue helpers, propagation helpers and
``wait_idle``); the blocking parts of a job run in worker threads or subprocesses.

A render freezes its inputs when it starts: the recipe, normalization targets, validated
processing settings, the original and the intro/outro assets are resolved once, the files are
hard-linked into ``.work/<job_id>/inputs`` (so replacing them meanwhile cannot change the
output) and hashed into an ``inputs_fingerprint``. The render is published with that
fingerprint; ``render_pending`` is cleared only if the clip's current state still produces the
same fingerprint, otherwise a newer render is queued.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import logging
import os
import secrets
import shutil
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from . import media
from .config import Paths
from .errors import InvalidError, NotFoundError, StudioError
from .fence import GarbageCollector, GcResult
from .ffmpeg import RenderPlan
from .models import (
    Clip,
    Job,
    JobKind,
    NormalizationProfile,
    OriginalInfo,
    Recipe,
    RenderRecord,
    utcnow_iso,
)
from .probe import probe
from .profiles import ProcessingProfile, resolve_profile_assets
from .render import RenderEngine, RenderOutput
from .repository import Repository
from .storage import MediaStore, validate_contained_path

_LOGGER = logging.getLogger(__name__)

_FINISHED_HISTORY = 50
_ERROR_LENGTH = 400
_GC_INTERVAL_S = 3600.0
_FILMSTRIP_MARKER = ".sha256"
_ASSET_ROLES = ("intro", "outro")


def render_timeout(seconds: float, per_minute: int = 120, minimum: float = 300.0) -> float:
    """Timeout of a render of ``seconds`` of media: ``max(300, 120 * minutes)``."""
    return max(minimum, per_minute * seconds / 60)


def inputs_fingerprint(
    recipe: Recipe,
    normalization: NormalizationProfile | None,
    profile: ProcessingProfile,
    original_sha256: str,
    asset_sha256s: Mapping[str, str | None],
) -> str:
    """Hash of everything a render's bytes depend on (the render's ``profile_fingerprint``)."""
    payload = {
        "recipe": recipe.model_dump(mode="json"),
        "normalization": None
        if normalization is None
        else {
            "target_lufs": normalization.target_lufs,
            "true_peak": normalization.true_peak,
            "lra": normalization.lra,
        },
        "processing": profile.model_dump(mode="json"),
        "original_sha256": original_sha256,
        "asset_sha256s": {role: asset_sha256s.get(role) for role in _ASSET_ROLES},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _link(source: Path, destination: Path) -> None:
    """Hard-link, falling back to a copy across filesystems."""
    try:
        os.link(source, destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        shutil.copy2(source, destination)


@dataclass
class _Entry:
    job: Job
    recipe: Recipe | None = None
    # Whether the job moved the clip into processing/rendering (so a failure must settle it).
    touched: bool = False


@dataclass(frozen=True)
class _Inputs:
    """The resolved, not yet linked inputs of a render."""

    clip: Clip
    original: OriginalInfo
    original_path: Path
    recipe: Recipe
    normalization: NormalizationProfile | None
    profile: ProcessingProfile
    # role -> (path, sha256 stored in the repository)
    assets: dict[str, tuple[Path, str | None]]

    def seconds(self) -> float:
        end = self.original.duration
        if self.recipe.trim_end is not None:
            end = min(end, self.recipe.trim_end)
        return max(end - self.recipe.trim_start, 0.0) + self.recipe.lead_in + self.recipe.tail_out


class JobQueue:
    gc_interval: float = _GC_INTERVAL_S

    def __init__(
        self,
        repo: Repository,
        store: MediaStore,
        engine: RenderEngine,
        paths: Paths,
        gc: GarbageCollector,
    ) -> None:
        self._repo = repo
        self._store = store
        self._engine = engine
        self._paths = paths
        self._gc = gc
        self._queued: deque[_Entry] = deque()
        self._finished: deque[Job] = deque(maxlen=_FINISHED_HISTORY)
        self._running: Job | None = None
        self._worker: asyncio.Task[None] | None = None
        self._gc_task: asyncio.Task[None] | None = None
        self._available = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()

    # --- lifecycle --------------------------------------------------------------------------

    async def start(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        self._recover()
        self._worker = asyncio.create_task(self._work(), name="cinema-studio-job-worker")
        self._gc_task = asyncio.create_task(self._gc_loop(), name="cinema-studio-gc")

    async def stop(self) -> None:
        for task in (self._gc_task, self._worker):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        self._gc_task = self._worker = None
        # Shutdown also settles jobs that never started, so wait_idle remains usable.
        while self._queued:
            entry = self._queued.popleft()
            self._fail(entry, "cancelled", cancelled=True)
            self._finish(entry.job)
        self._available.clear()
        self._idle.set()

    def _recover(self) -> None:
        """Settle what a crash left behind; ``storage.recover`` already handled ``rendering``."""
        queued = {entry.job.clip_id for entry in self._queued if entry.job.kind == "probe"}
        for clip in self._repo.list_clips():
            if clip.has_preview and not self._preview_path(clip.id).is_file():
                self._repo.set_flags(clip.id, has_preview=False)
            if clip.status != "processing" or clip.needs_source or clip.id in queued:
                continue
            try:
                present = self._original_path(clip).is_file()
            except (StudioError, OSError, media.MediaError):
                present = False
            if present:
                self.enqueue_probe(clip.id)
            else:
                self._repo.set_status(clip.id, "failed", "interrupted")

    async def _gc_loop(self) -> None:
        while True:
            await asyncio.sleep(self.gc_interval)
            try:
                await self.run_gc()
            except Exception:
                _LOGGER.exception("Garbage collection failed")

    async def run_gc(self) -> GcResult:
        return await asyncio.to_thread(self._gc.run)

    # --- enqueueing -------------------------------------------------------------------------

    def enqueue_probe(self, clip_id: str) -> Job:
        return self._enqueue("probe", clip_id)

    def enqueue_render(self, clip_id: str) -> Job:
        return self._enqueue("render", clip_id, coalesce=True)

    def enqueue_preview(self, clip_id: str, recipe: Recipe) -> Job:
        return self._enqueue("preview", clip_id, recipe.model_copy(deep=True))

    def enqueue_thumbs(self, clip_id: str) -> Job:
        return self._enqueue("thumbs", clip_id, coalesce=True)

    def _enqueue(
        self, kind: JobKind, clip_id: str, recipe: Recipe | None = None, *, coalesce: bool = False
    ) -> Job:
        if coalesce:
            for queued in self._queued:
                if queued.job.kind == kind and queued.job.clip_id == clip_id:
                    return queued.job
        clip = self._repo.get_clip(clip_id)
        job = Job(
            id=secrets.token_hex(6),
            kind=kind,
            clip_id=clip_id,
            clip_title=clip.title,
            created_at=utcnow_iso(),
        )
        self._queued.append(_Entry(job, recipe))
        self._idle.clear()
        self._available.set()
        return job

    def list_jobs(self) -> list[Job]:
        return (
            ([self._running] if self._running is not None else [])
            + [entry.job for entry in self._queued]
            + list(self._finished)
        )

    async def wait_idle(self, timeout: float = 120) -> None:
        await asyncio.wait_for(self._idle.wait(), timeout=timeout)

    # --- propagation ------------------------------------------------------------------------

    def _mark_and_enqueue(self, clip_ids: list[str]) -> list[str]:
        for clip_id in clip_ids:
            self._repo.set_flags(clip_id, render_pending=True)
            self.enqueue_render(clip_id)
        return clip_ids

    def on_processing_profile_changed(self, profile_id: str) -> list[str]:
        """Clips of the collections rendered with the profile."""
        return self._mark_and_enqueue(self._repo.clips_using_processing_profile(profile_id))

    def on_normalization_profile_changed(
        self, profile_id: str, *, targets_changed: bool = True
    ) -> list[str]:
        """Clips whose recipe uses the profile; a rename alone changes nothing."""
        if not targets_changed:
            return []
        return self._mark_and_enqueue(self._repo.clips_using_normalization_profile(profile_id))

    def on_collection_profile_changed(self, collection_id: str) -> list[str]:
        """Clips of a collection that now uses another processing profile."""
        return self._mark_and_enqueue(
            [clip.id for clip in self._repo.list_clips() if clip.collection_id == collection_id]
        )

    def on_asset_changed(self, filename: str) -> list[str]:
        """Clips whose collection profile uses the asset as intro or outro."""
        profiles = {
            record.id
            for record in self._repo.list_processing_profiles()
            if filename
            in (record.settings.get("intro_reference"), record.settings.get("outro_reference"))
        }
        collections = {
            collection.id
            for collection in self._repo.list_collections()
            if collection.processing_profile_id in profiles
        }
        return self._mark_and_enqueue(
            [clip.id for clip in self._repo.list_clips() if clip.collection_id in collections]
        )

    def on_clip_collection_changed(self, clip_id: str, previous_collection_id: str) -> list[str]:
        """The clip, when its new collection renders with another processing profile."""
        clip = self._repo.get_clip(clip_id)
        before = self._repo.get_collection(previous_collection_id).processing_profile_id
        after = self._repo.get_collection(clip.collection_id).processing_profile_id
        return self._mark_and_enqueue([clip_id] if before != after else [])

    # --- worker -----------------------------------------------------------------------------

    def _finish(self, job: Job) -> None:
        job.finished_at = utcnow_iso()
        self._finished.appendleft(job)

    def _fail(self, entry: _Entry, error: str, *, cancelled: bool = False) -> None:
        job = entry.job
        job.status = "failed"
        job.error = error[-_ERROR_LENGTH:]
        if not entry.touched or job.clip_id is None:
            return
        try:
            clip = self._repo.get_clip(job.clip_id)
            if cancelled and clip.render is not None:
                self._repo.set_status(clip.id, "ready")
            else:
                self._repo.set_status(clip.id, "failed", job.error)
        except StudioError as exc:
            _LOGGER.warning("Could not settle clip status for job %s: %s", job.id, exc)
        except Exception:
            _LOGGER.exception("Could not settle clip status for job %s", job.id)

    async def _work(self) -> None:
        while True:
            await self._available.wait()
            while self._queued:
                entry = self._queued.popleft()
                job = self._running = entry.job
                job.status = "running"
                job.started_at = utcnow_iso()
                try:
                    await self._execute(entry)
                except asyncio.CancelledError:
                    self._fail(entry, "cancelled", cancelled=True)
                    raise
                except Exception as exc:
                    error = str(exc) or type(exc).__name__
                    if isinstance(exc, (media.MediaError, StudioError)):
                        _LOGGER.warning("Job %s failed: %s", job.id, error)
                    else:
                        _LOGGER.exception("Job %s failed: %s", job.id, error)
                    self._fail(entry, error)
                else:
                    job.status = "done"
                    job.progress = 1.0
                finally:
                    self._finish(job)
                    self._running = None
                    shutil.rmtree(self._paths.work_dir / job.id, ignore_errors=True)
                    if not self._queued:
                        self._idle.set()
            self._available.clear()

    async def _execute(self, entry: _Entry) -> None:
        job = entry.job
        if job.clip_id is None:
            raise InvalidError("job has no clip")
        if job.kind == "probe":
            await self._probe(entry, job.clip_id)
        elif job.kind == "render":
            await self._render(entry, job.clip_id)
        elif job.kind == "preview":
            await self._preview(entry, job.clip_id)
        elif job.kind == "thumbs":
            await self._thumbs(job, job.clip_id)
        else:
            raise InvalidError(f"unsupported job kind '{job.kind}'")

    # --- shared resolution ------------------------------------------------------------------

    def _original_path(self, clip: Clip) -> Path:
        directory = self._paths.originals_dir / clip.id
        if clip.original is not None:
            path = directory / clip.original.filename
            validate_contained_path(path, self._paths.originals_dir)
            return path
        validate_contained_path(directory, self._paths.originals_dir)
        files = (
            [path for path in directory.iterdir() if path.is_file()] if directory.is_dir() else []
        )
        if len(files) != 1:
            raise media.MediaError("Expected exactly one original video file")
        validate_contained_path(files[0], self._paths.originals_dir)
        return files[0]

    def _preview_path(self, clip_id: str) -> Path:
        return self._paths.work_dir / "previews" / f"{clip_id}.mp4"

    def _resolve(self, clip_id: str, recipe: Recipe | None = None) -> _Inputs:
        clip = self._repo.get_clip(clip_id)
        if clip.needs_source or clip.original is None:
            raise InvalidError("needs source: upload the original video in Organize")
        collection = self._repo.get_collection(clip.collection_id)
        record = self._repo.get_processing_profile(collection.processing_profile_id)
        try:
            profile = ProcessingProfile.model_validate(record.settings)
            intro, outro = resolve_profile_assets(profile, self._paths)
        except (ValidationError, ValueError) as error:
            raise InvalidError(f"processing profile '{record.id}' is invalid: {error}") from error
        used = recipe if recipe is not None else clip.recipe
        normalization = (
            self._repo.get_normalization_profile(used.profile_id) if used.profile_id else None
        )
        assets: dict[str, tuple[Path, str | None]] = {}
        for role, reference, path in (
            ("intro", profile.intro_reference, intro),
            ("outro", profile.outro_reference, outro),
        ):
            if reference is None or path is None:
                continue
            assets[role] = (path, self._asset_sha256(reference, path))
        return _Inputs(
            clip=clip,
            original=clip.original,
            original_path=self._original_path(clip),
            recipe=used,
            normalization=normalization,
            profile=profile,
            assets=assets,
        )

    def _asset_sha256(self, reference: str, path: Path) -> str | None:
        try:
            asset = self._repo.get_asset(reference)
        except NotFoundError:
            asset = None
        if asset is None or asset.status != "ready" or not path.is_file():
            raise InvalidError(f"asset {reference} missing: upload it in Organize")
        return asset.sha256

    def _state_fingerprint(self, clip_id: str) -> str | None:
        """The fingerprint the clip's current state would produce (``None`` if not renderable)."""
        try:
            inputs = self._resolve(clip_id)
            shas = {
                role: stored if stored is not None else _hash_file(path)
                for role, (path, stored) in inputs.assets.items()
            }
        except (StudioError, OSError):
            return None
        return inputs_fingerprint(
            inputs.recipe, inputs.normalization, inputs.profile, inputs.original.sha256, shas
        )

    async def _freeze(
        self, job: Job, inputs: _Inputs, *, preview: bool
    ) -> tuple[RenderPlan, str, Path]:
        """Link the inputs under the job's work directory and describe the render."""
        output = self._store.staging_path(job.id, "out.mp4")
        directory = output.parent / "inputs"
        directory.mkdir(parents=True, exist_ok=True)
        source = directory / f"original{inputs.original_path.suffix}"
        await asyncio.to_thread(_link, inputs.original_path, source)
        # Hash the linked bytes, not the resolved metadata: the source may have been replaced
        # between resolution and linking, and the fingerprint must describe what is rendered.
        original_sha256 = await media.file_sha256(source)
        linked: dict[str, Path] = {}
        shas: dict[str, str | None] = {}
        for role, (path, _) in inputs.assets.items():
            destination = directory / f"{role}{path.suffix}"
            await asyncio.to_thread(_link, path, destination)
            linked[role] = destination
            shas[role] = await media.file_sha256(destination)
        fingerprint = inputs_fingerprint(
            inputs.recipe, inputs.normalization, inputs.profile, original_sha256, shas
        )
        plan = RenderPlan(
            source=source,
            output=output,
            profile=inputs.profile,
            recipe=inputs.recipe,
            normalization=inputs.normalization,
            intro=linked.get("intro"),
            outro=linked.get("outro"),
            source_duration=inputs.original.duration,
            preview=preview,
        )
        return plan, fingerprint, output

    # --- probe ------------------------------------------------------------------------------

    async def _probe(self, entry: _Entry, clip_id: str) -> None:
        entry.touched = True
        clip = self._repo.set_status(clip_id, "processing")
        source = self._original_path(clip)
        if not source.is_file():
            raise media.MediaError("The original video file is missing")
        info = await probe(source)
        maximum = self._repo.get_settings().max_duration_s
        if info.duration > maximum:
            raise InvalidError(f"Video is longer than {maximum} s")
        original = OriginalInfo(
            filename=source.relative_to(self._paths.originals_dir / clip_id).as_posix(),
            size=source.stat().st_size,
            sha256=await media.file_sha256(source),
            duration=info.duration,
            width=info.width or 0,
            height=info.height or 0,
            fps=info.fps,
            has_audio=info.has_audio,
            video_codec=info.video_codec or "",
        )
        clip.recipe.validate_for(original)
        self._repo.set_original(clip_id, original)
        self.enqueue_render(clip_id)
        self.enqueue_thumbs(clip_id)

    # --- render -----------------------------------------------------------------------------

    async def _render(self, entry: _Entry, clip_id: str) -> None:
        job = entry.job
        clip = self._repo.get_clip(clip_id)
        if clip.needs_source or clip.original is None:
            # Settle the clip as failed (keeping its published render) rather than leaving it be.
            entry.touched = True
            raise InvalidError("needs source: upload the original video in Organize")
        entry.touched = True
        self._repo.set_status(clip_id, "rendering" if clip.render is not None else "processing")
        inputs = self._resolve(clip_id)
        self._store.check_space(
            self._store.estimate_render_bytes(inputs.profile, inputs.seconds()),
            self._repo.get_settings().disk_reserve_bytes,
        )
        plan, fingerprint, _ = await self._freeze(job, inputs, preview=False)

        def progress(value: float) -> None:
            job.progress = min(1.0, max(0.0, value))

        output = await self._engine.render(plan, progress)
        await self._publish(clip_id, output, fingerprint)

    async def _publish(self, clip_id: str, output: RenderOutput, fingerprint: str) -> None:
        n = self._repo.next_render_n(clip_id)
        render_id, final = await self._publish_file(output.path, clip_id, n)
        timing = output.timing
        record = RenderRecord(
            id=render_id,
            clip_id=clip_id,
            n=n,
            relative_path=self._store.relative_path(final),
            size=final.stat().st_size,
            sha256=output.sha256,
            duration=timing.duration,
            content_start=timing.content_start,
            content_end=timing.content_end,
            lead_in=timing.lead_in,
            tail_out=timing.tail_out,
            content_duration=timing.content_duration,
            timing_source="measured",
            integrated_lufs=output.integrated_lufs,
            true_peak=output.true_peak,
            recipe_hash=output.recipe_hash,
            profile_fingerprint=fingerprint,
        )
        # No await between the check and the publish: the verdict cannot go stale in between.
        current = self._state_fingerprint(clip_id) == fingerprint
        try:
            self._repo.publish_render(record, clear_pending=current)
        except BaseException:
            final.unlink(missing_ok=True)
            raise
        if not current:
            # An older job finishing must never hide a newer edit.
            self._repo.set_flags(clip_id, render_pending=True)
            self.enqueue_render(clip_id)
        self.enqueue_thumbs(clip_id)

    async def _publish_file(self, staged: Path, clip_id: str, n: int) -> tuple[str, Path]:
        task = asyncio.ensure_future(
            asyncio.to_thread(self._store.publish_file, staged, clip_id, n)
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # The thread cannot be cancelled; settle it so no unrecorded render is left behind.
            with suppress(Exception):
                _, final = await task
                final.unlink(missing_ok=True)
            raise

    # --- preview ----------------------------------------------------------------------------

    async def _preview(self, entry: _Entry, clip_id: str) -> None:
        job = entry.job
        inputs = self._resolve(clip_id, entry.recipe)
        plan, _, output = await self._freeze(job, inputs, preview=True)

        def progress(value: float) -> None:
            job.progress = min(1.0, max(0.0, value))

        await self._engine.render(plan, progress)
        destination = self._preview_path(clip_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(output, destination)
        try:
            self._repo.set_flags(clip_id, has_preview=True)
        except NotFoundError:
            destination.unlink(missing_ok=True)
            raise

    # --- thumbnails -------------------------------------------------------------------------

    async def _thumbs(self, job: Job, clip_id: str) -> None:
        clip = self._repo.get_clip(clip_id)
        root = self._paths.thumbs_dir / clip_id
        made = False
        if clip.original is not None and not clip.needs_source:
            source = self._original_path(clip)
            if source.is_file():
                await self._original_thumbs(job, root, clip.original, source)
                made = True
        if clip.render is not None:
            render = clip.render
            poster = root / f"r{render.n}" / "poster.jpg"
            if not poster.is_file():
                at = min(render.content_start + 1.0, max(render.content_end - 0.1, 0.0))
                await media.make_poster(self._paths.media_dir / render.relative_path, poster, at)
            made = True
        if not made:
            raise InvalidError("nothing to create thumbnails from")
        self._repo.set_flags(clip_id, has_thumbs=True)

    async def _original_thumbs(
        self, job: Job, root: Path, original: OriginalInfo, source: Path
    ) -> None:
        """Poster and filmstrip of the original timeline, rebuilt only when the file changed."""
        target = root / "original"
        marker = target / _FILMSTRIP_MARKER
        complete = (
            marker.is_file()
            and marker.read_text() == original.sha256
            and (target / "poster.jpg").is_file()
            and (target / "filmstrip.json").is_file()
        )
        if complete:
            return
        scratch = root / f".original-{job.id}"
        backup = root / f".previous-{job.id}"
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        try:
            await media.make_filmstrip(source, scratch, duration=original.duration)
            await media.make_poster(source, scratch / "poster.jpg", min(1.0, original.duration / 2))
            (scratch / _FILMSTRIP_MARKER).write_text(original.sha256)
            if target.exists():
                os.replace(target, backup)
            os.replace(scratch, target)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
            shutil.rmtree(backup, ignore_errors=True)
