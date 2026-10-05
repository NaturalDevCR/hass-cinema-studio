"""Two-phase, fingerprint-verified import of a stopped legacy Worker catalog."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, TypeAdapter, field_validator

from .config import Paths
from .errors import ConflictError, InvalidError, NotFoundError
from .jobs import JobQueue
from .media import MediaError, file_sha256, legacy_fingerprint
from .models import (
    Asset,
    AssetUpdate,
    CollectionCreate,
    CollectionUpdate,
    LegacyReport,
    LegacySkip,
    OriginalInfo,
    PlaybackMode,
    ProcessingProfileCreate,
    Recipe,
    RenderRecord,
    SeasonCreate,
    SeasonUpdate,
    TimingSource,
)
from .probe import probe
from .profiles import validate_relative_path, validate_settings
from .render import recipe_hash
from .repository import Repository
from .storage import MediaStore, validate_contained_path
from .timing import Timing
from .timing_validation import validate_timing

_LOGGER = logging.getLogger(__name__)

_TIMING_KEYS = (
    "content_duration_seconds",
    "lead_in_duration_seconds",
    "tail_out_duration_seconds",
    "content_start_offset_seconds",
    "content_end_offset_seconds",
)
_WORKER_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_COMPONENT = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class LegacyWorker(BaseModel):
    version: str
    queue_depth: int = Field(ge=0)
    active_job_ids: list[str]


class LegacyRoots(BaseModel):
    source: str
    compiled: str


class LegacyCollection(BaseModel):
    id: str
    name: str
    playback_mode: PlaybackMode
    ordered_clip_ids: list[str]
    processing_profile_id: str
    enabled: bool


class LegacyProfile(BaseModel):
    id: str
    name: str
    settings: dict[str, object]


class LegacySeason(BaseModel):
    id: str
    name: str
    start: str | None
    end: str | None
    priority: int
    collection_id: str


class LegacyClip(BaseModel):
    id: str
    collection_id: str
    state: str
    relative_source_path: str
    relative_output_path: str | None
    output_duration_seconds: float | None
    output_available: bool
    metadata: dict[str, object]
    updated_at: str


class LegacyManifest(BaseModel):
    worker: LegacyWorker
    roots: LegacyRoots
    collections: list[LegacyCollection]
    profiles: list[LegacyProfile]
    assets: list[str]
    seasons: list[LegacySeason]
    clips: list[LegacyClip]


class LegacyStageResponse(BaseModel):
    run_id: str
    staged: list[str]
    rejected: list[LegacySkip]


class LegacyStageRequest(BaseModel):
    phase: Literal["stage"]
    manifest: LegacyManifest


class LegacyCommitRequest(BaseModel):
    phase: Literal["commit"]
    run_id: str
    clips: list[LegacyClip]


legacy_request: TypeAdapter[LegacyStageRequest | LegacyCommitRequest] = TypeAdapter(
    Annotated[LegacyStageRequest | LegacyCommitRequest, Field(discriminator="phase")]
)


class _Verdict(BaseModel):
    clip_id: str
    source: str | None = None
    original: OriginalInfo | None = None
    output: str | None = None
    output_sha256: str | None = None
    output_size: int | None = None
    timing: dict[str, float] | None = None
    timing_source: TimingSource | None = None
    lead_in: float | None = None
    tail_out: float | None = None


class _Stage(BaseModel):
    started_at: str
    manifest: LegacyManifest
    verdicts: list[_Verdict]
    rejected: list[LegacySkip]

    @field_validator("started_at")
    @classmethod
    def _aware_timestamp(cls, value: str) -> str:
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("stage timestamp must include a timezone")
        return value


def _iso(now: datetime) -> str:
    return now.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_file(root: Path, relative: str, studio: Path) -> Path:
    try:
        validate_relative_path(relative)
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or target.is_relative_to(studio):
            raise ValueError("path escapes Worker root")
        return target
    except (ValueError, OSError, RuntimeError) as exc:
        raise InvalidError("unsafe_path") from exc


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidError("invalid timing")
    try:
        result = float(value)
    except OverflowError as exc:
        raise InvalidError("invalid timing") from exc
    if not math.isfinite(result):
        raise InvalidError("invalid timing")
    return result


def _timing(clip: LegacyClip) -> tuple[Timing, TimingSource]:
    duration = _number(clip.output_duration_seconds)
    present = [key in clip.metadata for key in _TIMING_KEYS]
    if not any(present):
        return validate_timing(Timing(duration, 0, duration, 0, 0, duration)), "legacy_full_file"
    if not all(present):
        raise InvalidError("partial timing")
    content, lead, tail, start, end = (_number(clip.metadata[key]) for key in _TIMING_KEYS)
    return validate_timing(Timing(duration, start, end, lead, tail, content)), "legacy_worker"


class LegacyImporter:
    def __init__(
        self,
        paths: Paths,
        repo: Repository,
        store: MediaStore,
        jobs: JobQueue,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.paths = paths
        self.repo = repo
        self.store = store
        self.jobs = jobs
        self.now = now
        self._lock = asyncio.Lock()

    @property
    def _root(self) -> Path:
        return self.paths.work_dir / "import"

    def _run_path(self, run_id: str) -> Path:
        if not _COMPONENT.fullmatch(run_id):
            raise InvalidError("Invalid import run id")
        path = self._root / run_id
        validate_contained_path(path, self.paths.media_dir)
        return path

    def discard_stale(self) -> None:
        """Clean up synchronously on the event loop; background callers use cleanup_stale."""
        if not self._lock.locked():
            self._discard_stale()

    async def cleanup_stale(self) -> None:
        """Wait for stage/commit, then fence the filesystem worker until it finishes."""
        async with self._lock:
            worker = asyncio.create_task(asyncio.to_thread(self._discard_stale))
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                # Cancelling a to_thread await does not stop its worker. Keep the lock held,
                # including on repeated cancellation, until no filesystem work remains.
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
                worker.result()
                raise

    def _discard_stale(self) -> None:
        if not self._root.exists():
            return
        validate_contained_path(self._root, self.paths.media_dir)
        cutoff = self.now().astimezone(UTC) - timedelta(hours=1)
        for run in self._root.iterdir():
            if run.is_symlink() or not run.is_dir():
                run.unlink()
                continue
            validate_contained_path(run, self.paths.media_dir)
            try:
                stage = _Stage.model_validate_json((run / "stage.json").read_text())
                started = datetime.fromisoformat(stage.started_at)
            except ValueError as exc:
                shutil.rmtree(run)
                raise InvalidError("corrupt import stage") from exc
            except OSError:
                started = datetime.fromtimestamp(run.stat().st_mtime, UTC)
            if started < cutoff:
                shutil.rmtree(run)

    def _roots(self, manifest: LegacyManifest) -> tuple[Path, Path]:
        roots: list[Path] = []
        for raw in (manifest.roots.source, manifest.roots.compiled):
            try:
                path = Path(raw)
                resolved = path.resolve()
                if (
                    not path.is_absolute()
                    or not resolved.is_dir()
                    or not resolved.is_relative_to(self.paths.media_dir.resolve())
                    or resolved.is_relative_to(self.paths.root.resolve())
                ):
                    raise ValueError("invalid root")
            except (OSError, RuntimeError, ValueError) as exc:
                raise InvalidError(
                    "Worker roots must be directories under media, outside Studio"
                ) from exc
            roots.append(resolved)
        return roots[0], roots[1]

    async def stage(self, manifest: LegacyManifest) -> LegacyStageResponse:
        if self._lock.locked():
            raise ConflictError("Another legacy import is active")
        started_at = self.now()
        async with self._lock:
            self._discard_stale()
            if self._root.exists() and any(self._root.iterdir()):
                raise ConflictError("Another legacy import is active")
            local = started_at.astimezone()
            if (
                manifest.worker.queue_depth
                or manifest.worker.active_job_ids
                or (local.hour == 3 and local.minute < 30)
            ):
                raise InvalidError("The Worker must be idle and outside its maintenance window")
            source_root, output_root = self._roots(manifest)
            valid_profiles = {profile.id for profile in self.repo.list_processing_profiles()}
            invalid_profiles: set[str] = set()
            for profile in manifest.profiles:
                try:
                    validate_settings(profile.settings)
                except ValueError:
                    invalid_profiles.add(profile.id)
                    continue
                valid_profiles.add(profile.id)
            profile_for = {c.id: c.processing_profile_id for c in manifest.collections}
            run_id = uuid4().hex
            stage_file = self.store.staging_path(f"import/{run_id}", "stage.json")
            run = stage_file.parent
            verdicts: list[_Verdict] = []
            rejected: list[LegacySkip] = []
            seen: set[str] = set()
            try:
                for clip in manifest.clips:
                    if clip.state == "deleted":
                        continue
                    if clip.id in seen:
                        raise InvalidError("Duplicate Worker clip id")
                    seen.add(clip.id)
                    reason = None
                    profile_id = profile_for.get(clip.collection_id)
                    if not _WORKER_ID.fullmatch(clip.id):
                        reason = "invalid_id"
                    elif profile_id is None:
                        reason = "collection_missing"
                    elif profile_id in invalid_profiles:
                        reason = "profile_invalid"
                    elif profile_id not in valid_profiles:
                        reason = "profile_missing"
                    if reason is not None:
                        rejected.append(LegacySkip(clip_id=clip.id, reason=reason))
                        continue
                    try:
                        source = _safe_file(
                            source_root, clip.relative_source_path, self.paths.root.resolve()
                        )
                        output = None
                        if clip.output_available and clip.relative_output_path:
                            output = _safe_file(
                                output_root, clip.relative_output_path, self.paths.root.resolve()
                            )
                    except InvalidError:
                        rejected.append(LegacySkip(clip_id=clip.id, reason="unsafe_path"))
                        continue
                    verdict = _Verdict(clip_id=clip.id)
                    try:
                        timing, timing_source = _timing(clip)
                        if timing_source == "legacy_worker":
                            verdict.lead_in, verdict.tail_out = timing.lead_in, timing.tail_out
                    except InvalidError:
                        pass
                    source_name = Path(clip.relative_source_path).name
                    staged_source = self.store.staging_path(
                        f"import/{run_id}/src/{clip.id}", source_name
                    )
                    try:
                        sha, size = await self._link_verified(
                            source, staged_source, clip.metadata.get("source_fingerprint")
                        )
                        info = await probe(staged_source)
                        if not info.valid or info.duration <= 0:
                            raise MediaError("invalid source")
                        verdict.original = OriginalInfo(
                            filename=source_name,
                            size=size,
                            sha256=sha,
                            duration=info.duration,
                            width=info.width or 0,
                            height=info.height or 0,
                            fps=info.fps,
                            has_audio=info.has_audio,
                            video_codec=info.video_codec or "unknown",
                        )
                        verdict.source = staged_source.relative_to(run).as_posix()
                    except (OSError, MediaError, InvalidError):
                        staged_source.unlink(missing_ok=True)
                        rejected.append(LegacySkip(clip_id=clip.id, reason="needs_source"))
                    if output is not None:
                        staged_output = self.store.staging_path(
                            f"import/{run_id}/out", f"{clip.id}.mp4"
                        )
                        try:
                            sha, size = await self._link_verified(
                                output, staged_output, clip.metadata.get("output_fingerprint")
                            )
                            timing, timing_source = _timing(clip)
                            info = await probe(staged_output)
                            if (
                                not info.valid
                                or abs(info.duration - _number(clip.output_duration_seconds))
                                > 0.05 + 1e-9
                            ):
                                raise InvalidError("output duration mismatch")
                            verdict.output = staged_output.relative_to(run).as_posix()
                            verdict.output_sha256, verdict.output_size = sha, size
                            verdict.timing, verdict.timing_source = timing.as_dict(), timing_source
                        except (OSError, MediaError, InvalidError):
                            staged_output.unlink(missing_ok=True)
                            rejected.append(LegacySkip(clip_id=clip.id, reason="output_invalid"))
                    verdicts.append(verdict)
                record = _Stage(
                    started_at=_iso(started_at),
                    manifest=manifest,
                    verdicts=verdicts,
                    rejected=rejected,
                )
                stage_file.write_text(record.model_dump_json(), encoding="utf-8")
            except BaseException:
                shutil.rmtree(run)
                raise
            return LegacyStageResponse(
                run_id=run_id, staged=[v.clip_id for v in verdicts], rejected=rejected
            )

    async def _link_verified(self, source: Path, target: Path, expected: object) -> tuple[str, int]:
        if not isinstance(expected, str) or not expected or not source.is_file():
            raise InvalidError("Missing file or fingerprint")
        os.link(source, target)
        sha = await file_sha256(target)
        size = target.stat().st_size
        if legacy_fingerprint(sha, size) != expected:
            raise InvalidError("Fingerprint mismatch")
        return sha, size

    async def commit(self, run_id: str, clips: list[LegacyClip]) -> LegacyReport:
        if self._lock.locked():
            raise ConflictError("Another legacy import is active")
        async with self._lock:
            self._discard_stale()
            run = self._run_path(run_id)
            try:
                stage = _Stage.model_validate_json((run / "stage.json").read_text())
            except FileNotFoundError as exc:
                raise NotFoundError("Import run not found") from exc
            except (ValueError, OSError) as exc:
                shutil.rmtree(run)
                raise InvalidError("corrupt import stage") from exc
            report = LegacyReport(
                run_id=run_id,
                started_at=stage.started_at,
                finished_at=None,
                catalog_revision=self.repo.catalog_revision(),
                imported=[],
                queued_for_render=[],
                needs_source=[],
                skipped=[],
                missing_assets=[],
            )
            staged_ids = {v.clip_id for v in stage.verdicts}
            report.skipped.extend(r for r in stage.rejected if r.clip_id not in staged_ids)
            try:
                await self._import_catalog(stage.manifest, report)
                refetched = {clip.id: clip for clip in clips}
                originals = {clip.id: clip for clip in stage.manifest.clips}
                for verdict in stage.verdicts:
                    try:
                        clip = originals[verdict.clip_id]
                        fresh = refetched.get(clip.id)
                        reason = None
                        if fresh is None:
                            reason = "missing_from_refetch"
                        elif fresh.updated_at != clip.updated_at or any(
                            fresh.metadata.get(k) != clip.metadata.get(k)
                            for k in ("source_fingerprint", "output_fingerprint")
                        ):
                            reason = "changed_during_import"
                        else:
                            try:
                                self.repo.get_clip(clip.id)
                            except NotFoundError:
                                pass
                            else:
                                reason = "already_imported"
                        if reason is not None:
                            report.skipped.append(LegacySkip(clip_id=clip.id, reason=reason))
                            continue
                        await self._import_clip(run, clip, verdict, report)
                    except Exception as exc:
                        _LOGGER.exception(
                            "Legacy import %s failed for clip %s", run_id, verdict.clip_id
                        )
                        # Expose only the class: tool errors may contain private paths or secrets.
                        report.skipped.append(
                            LegacySkip(
                                clip_id=verdict.clip_id,
                                reason=f"import_error: {type(exc).__name__}",
                            )
                        )
                for collection in stage.manifest.collections:
                    try:
                        edited = self.repo.collection_user_edited(collection.id)
                    except NotFoundError:
                        continue  # Invalid profiles cannot create collections.
                    if not edited and self._profile_exists(collection.processing_profile_id):
                        self.repo.update_collection(
                            collection.id,
                            CollectionUpdate(
                                playback_mode=collection.playback_mode,
                                processing_profile_id=collection.processing_profile_id,
                                enabled=collection.enabled,
                            ),
                            user_edit=False,
                        )
                        self.repo.set_collection_order(
                            collection.id, collection.ordered_clip_ids, user_edit=False
                        )
            finally:
                report.finished_at = _iso(self.now())
                report.catalog_revision = self.repo.catalog_revision()
                self.repo.save_legacy_report(report)
                shutil.rmtree(run)
            return report

    def _profile_exists(self, profile_id: str) -> bool:
        try:
            self.repo.get_processing_profile(profile_id)
        except NotFoundError:
            return False
        return True

    async def _import_catalog(self, manifest: LegacyManifest, report: LegacyReport) -> None:
        for profile in manifest.profiles:
            try:
                settings = validate_settings(profile.settings)
            except ValueError:
                continue
            if not self._profile_exists(profile.id):
                self.repo.create_processing_profile(
                    ProcessingProfileCreate(id=profile.id, name=profile.name, settings=settings)
                )
        references = set(manifest.assets)
        for profile in manifest.profiles:
            for role in ("intro_reference", "outro_reference"):
                reference = profile.settings.get(role)
                if isinstance(reference, str):
                    references.add(reference)
        for filename in sorted(references):
            file: Path | None = None
            try:
                validate_relative_path(filename)
                file = (self.paths.assets_dir / filename).resolve()
                if not file.is_relative_to(self.paths.assets_dir.resolve()):
                    raise ValueError("asset escapes root")
                ready = file.is_file()
            except (ValueError, OSError, RuntimeError):
                ready = False
            asset = Asset(
                filename=filename,
                size=file.stat().st_size if ready and file is not None else None,
                sha256=await file_sha256(file) if ready and file is not None else None,
                status="ready" if ready else "missing",
            )
            try:
                self.repo.get_asset(filename)
            except NotFoundError:
                self.repo.create_asset(asset)
            else:
                self.repo.update_asset(
                    filename, AssetUpdate(size=asset.size, sha256=asset.sha256, status=asset.status)
                )
            if not ready:
                report.missing_assets.append(filename)
        for collection in manifest.collections:
            if not self._profile_exists(collection.processing_profile_id):
                continue
            try:
                self.repo.get_collection(collection.id)
            except NotFoundError:
                self.repo.create_collection(
                    CollectionCreate(
                        id=collection.id,
                        name=collection.name,
                        playback_mode=collection.playback_mode,
                        processing_profile_id=collection.processing_profile_id,
                    )
                )
        for season in manifest.seasons:
            try:
                self.repo.get_collection(season.collection_id)
            except NotFoundError:
                continue
            if season.id == "regular":
                self.repo.update_season("regular", SeasonUpdate(collection_id=season.collection_id))
                continue
            values = season.model_dump(exclude={"id"})
            try:
                self.repo.get_season(season.id)
            except NotFoundError:
                self.repo.create_season(SeasonCreate.model_validate({"id": season.id, **values}))
            else:
                self.repo.update_season(season.id, SeasonUpdate.model_validate(values))

    async def _import_clip(
        self, run: Path, clip: LegacyClip, verdict: _Verdict, report: LegacyReport
    ) -> None:
        settings = self.repo.get_settings()
        recipe = Recipe(
            lead_in=verdict.lead_in if verdict.lead_in is not None else settings.default_lead_in,
            tail_out=verdict.tail_out
            if verdict.tail_out is not None
            else settings.default_tail_out,
        )
        links: list[Path] = []
        render = None
        published_output: Path | None = None
        try:
            if verdict.source is not None and verdict.original is not None:
                original = self.store.store_original(
                    run / verdict.source, clip.id, verdict.original.filename, link=True
                )
                links.append(original)
            if verdict.output is not None:
                assert verdict.timing is not None and verdict.timing_source is not None
                assert verdict.output_size is not None and verdict.output_sha256 is not None
                render_id, final = self.store.publish_file(run / verdict.output, clip.id, n=1)
                links.append(final)
                published_output = final
                render = RenderRecord(
                    id=render_id,
                    clip_id=clip.id,
                    n=1,
                    relative_path=self.store.relative_path(final),
                    size=verdict.output_size,
                    sha256=verdict.output_sha256,
                    duration=verdict.timing["duration"],
                    content_start=verdict.timing["content_start"],
                    content_end=verdict.timing["content_end"],
                    lead_in=verdict.timing["lead_in"],
                    tail_out=verdict.timing["tail_out"],
                    content_duration=verdict.timing["content_duration"],
                    timing_source=verdict.timing_source,
                    integrated_lufs=None,
                    true_peak=None,
                    recipe_hash=recipe_hash(recipe, None),
                    profile_fingerprint=str(clip.metadata.get("profile_fingerprint") or ""),
                    published_at=_iso(self.now()),
                )
            self.repo.import_legacy_clip(
                clip_id=clip.id,
                collection_id=clip.collection_id,
                title=Path(clip.relative_source_path).stem,
                source_name=Path(clip.relative_source_path).name,
                recipe=recipe,
                original=verdict.original,
                needs_source=verdict.original is None,
                sort_key=(
                    clip.relative_output_path or f"{clip.collection_id}/{clip.id}.mp4"
                ).casefold(),
                render=render,
            )
        except BaseException:
            # publish_file consumes staging; restore its link so a failed commit can be retried.
            try:
                if published_output is not None and verdict.output is not None:
                    output = run / verdict.output
                    if not output.exists():
                        os.link(published_output, output)
            finally:
                for link in reversed(links):
                    link.unlink(missing_ok=True)
            raise
        report.imported.append(clip.id)
        if verdict.original is None:
            report.needs_source.append(clip.id)
        elif render is None:
            try:
                self.jobs.enqueue_render(clip.id)
            except Exception:
                try:
                    self.jobs.enqueue_render(clip.id)
                except Exception:
                    self.repo.set_status(clip.id, "failed", "render not queued")
                    raise
            report.queued_for_render.append(clip.id)
