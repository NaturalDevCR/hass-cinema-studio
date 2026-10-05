"""Ingress UI endpoints for state, settings, organization, profiles, assets and cleanup."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import shutil
import unicodedata
from collections.abc import Callable
from datetime import date as date_type
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from starlette.datastructures import UploadFile
from starlette.responses import Response

from . import __version__
from .errors import InvalidError, NotFoundError
from .fence import ConsumerFile, GcFence, GcResult
from .jobs import JobQueue
from .lifecycle import publish_discovery
from .media import MediaError, file_sha256
from .models import (
    Asset,
    AssetUpdate,
    Collection,
    CollectionCreate,
    CollectionUpdate,
    NormalizationProfile,
    NormalizationProfileCreate,
    NormalizationProfileUpdate,
    ProcessingProfileCreate,
    ProcessingProfileRecord,
    ProcessingProfileUpdate,
    Recipe,
    Season,
    SeasonCreate,
    SeasonUpdate,
    Settings,
)
from .probe import probe
from .repository import Repository
from .seasons import resolve_calendar_season
from .storage import MediaStore, validate_contained_path

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ui")

ASSET_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v"})
_REGULAR = "regular"
_UPLOAD_CHUNK = 1024 * 1024
_MULTIPART_OVERHEAD = 64 * 1024
_MAX_NAME_LENGTH = 200
_UNSAFE_NAME_CHARS = re.compile(r"[^\w.\- ]+")


class OrderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_ids: list[str]


class NormalizationApply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_ids: list[str] | None = None
    collection_id: str | None = None


def _repo(request: Request) -> Repository:
    repo: Repository = request.app.state.repo
    return repo


def _jobs(request: Request) -> JobQueue:
    jobs: JobQueue = request.app.state.jobs
    return jobs


# --- state and token -------------------------------------------------------------------------


def _read_consumer_files(fence: GcFence) -> tuple[dict[str, ConsumerFile], list[str]]:
    try:
        return fence.read_consumers()
    except (InvalidError, OSError):
        return {}, []  # no consumers directory yet


def _consumer_rows(
    seen: list[tuple[str, str]], files: dict[str, ConsumerFile], broken: list[str]
) -> list[dict[str, object]]:
    last_seen = dict(seen)
    rows: list[dict[str, object]] = []
    for consumer_id in sorted({*last_seen, *files, *broken}):
        consumer = files.get(consumer_id)
        rows.append(
            {
                "consumer_id": consumer_id,
                "last_seen_at": last_seen.get(consumer_id),
                "held_revision": consumer.held_revision if consumer else None,
                "file_present": consumer_id in files or consumer_id in broken,
                "pins": len(consumer.pins) if consumer else 0,
            }
        )
    return rows


@router.get("/state")
async def get_state(request: Request) -> dict[str, object]:
    state = request.app.state
    repo = _repo(request)
    store: MediaStore = state.store
    storage, (files, broken) = await asyncio.gather(
        asyncio.to_thread(store.storage_usage, repo),
        asyncio.to_thread(_read_consumer_files, state.fence),
    )
    last: tuple[GcResult, str] | None = state.gc_last
    legacy = repo.last_legacy_report()
    return {
        "version": __version__,
        "api_token_masked": state.tokens.masked(),
        "catalog_revision": repo.catalog_revision(),
        "discovery": state.discovery_status,
        "storage": storage,
        "gc": {
            "enabled": not storage["network_fs"],
            "halted_reason": last[0].halted_reason if last else None,
            "last_run_at": last[1] if last else None,
            "deleted_last_run": len(last[0].deleted) if last else 0,
        },
        "consumers": _consumer_rows(repo.list_consumers_seen(), files, broken),
        "legacy_import": legacy.model_dump(mode="json") if legacy else None,
        "settings": repo.get_settings().model_dump(mode="json"),
    }


@router.get("/token")
async def get_token(request: Request) -> dict[str, str]:
    return {"token": request.app.state.tokens.get()}


@router.post("/token/rotate")
async def rotate_token(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    request.app.state.tokens.rotate()
    if request.app.state.supervisor.available:
        background_tasks.add_task(publish_discovery, request.app)
    return {"api_token_masked": request.app.state.tokens.masked()}


# --- settings --------------------------------------------------------------------------------


@router.get("/settings", response_model=Settings)
async def get_settings(request: Request) -> Settings:
    return _repo(request).get_settings()


@router.put("/settings", response_model=Settings)
async def put_settings(data: Settings, request: Request) -> Settings:
    # Entity domains and the protected list are validated by the model itself.
    seen: set[str] = set()
    for target in data.test_targets:
        if target.id in seen:
            raise InvalidError(f"Test target id '{target.id}' is duplicated.")
        seen.add(target.id)
    return _repo(request).update_settings(data)


# --- collections -----------------------------------------------------------------------------


@router.get("/collections", response_model=list[Collection])
async def list_collections(request: Request) -> list[Collection]:
    return _repo(request).list_collections()


@router.get("/collections/{collection_id}", response_model=Collection)
async def get_collection(collection_id: str, request: Request) -> Collection:
    return _repo(request).get_collection(collection_id)


@router.post("/collections", response_model=Collection)
async def create_collection(data: CollectionCreate, request: Request) -> Collection:
    return _repo(request).create_collection(data)


@router.patch("/collections/{collection_id}")
async def patch_collection(
    collection_id: str, data: CollectionUpdate, request: Request
) -> dict[str, object]:
    repo = _repo(request)
    before = repo.get_collection(collection_id)
    collection = repo.update_collection(collection_id, data)
    affected: list[str] = []
    if collection.processing_profile_id != before.processing_profile_id:
        affected = _jobs(request).on_collection_profile_changed(collection_id)
    return {"collection": collection, "affected_clip_ids": affected}


@router.put("/collections/{collection_id}/order", response_model=Collection)
async def set_collection_order(collection_id: str, data: OrderBody, request: Request) -> Collection:
    return _repo(request).set_collection_order(collection_id, data.clip_ids)


@router.delete("/collections/{collection_id}", status_code=204)
async def delete_collection(collection_id: str, request: Request) -> Response:
    repo = _repo(request)
    repo.get_collection(collection_id)
    if collection_id == _REGULAR:
        raise HTTPException(status_code=400, detail="The regular collection cannot be deleted.")
    repo.delete_collection(collection_id)
    return Response(status_code=204)


# --- seasons ---------------------------------------------------------------------------------


@router.get("/seasons", response_model=list[Season])
async def list_seasons(request: Request) -> list[Season]:
    return _repo(request).list_seasons()


@router.get("/seasons/resolve")
async def resolve_season(date: str, request: Request) -> dict[str, str]:
    try:
        parsed = date_type.fromisoformat(date)
    except ValueError:
        raise InvalidError("Date must use YYYY-MM-DD format.") from None
    if parsed.isoformat() != date:
        raise InvalidError("Date must use YYYY-MM-DD format.")
    repo = _repo(request)
    season_id = resolve_calendar_season(repo.list_seasons(), parsed)
    return {
        "date": date,
        "season_id": season_id,
        "collection_id": repo.get_season(season_id).collection_id,
    }


@router.get("/seasons/{season_id}", response_model=Season)
async def get_season(season_id: str, request: Request) -> Season:
    return _repo(request).get_season(season_id)


@router.post("/seasons", response_model=Season)
async def create_season(data: SeasonCreate, request: Request) -> Season:
    return _repo(request).create_season(data)


@router.patch("/seasons/{season_id}", response_model=Season)
async def patch_season(season_id: str, data: SeasonUpdate, request: Request) -> Season:
    return _repo(request).update_season(season_id, data)


@router.delete("/seasons/{season_id}", status_code=204)
async def delete_season(season_id: str, request: Request) -> Response:
    repo = _repo(request)
    if repo.get_season(season_id).builtin:
        raise HTTPException(status_code=400, detail="The regular season cannot be deleted.")
    repo.delete_season(season_id)
    return Response(status_code=204)


# --- normalization profiles ------------------------------------------------------------------


@router.get("/normalization-profiles", response_model=list[NormalizationProfile])
async def list_normalization_profiles(request: Request) -> list[NormalizationProfile]:
    return _repo(request).list_normalization_profiles()


@router.post("/normalization-profiles", response_model=NormalizationProfile)
async def create_normalization_profile(
    data: NormalizationProfileCreate, request: Request
) -> NormalizationProfile:
    return _repo(request).create_normalization_profile(data)


@router.patch("/normalization-profiles/{profile_id}")
async def patch_normalization_profile(
    profile_id: str, data: NormalizationProfileUpdate, request: Request
) -> dict[str, object]:
    repo = _repo(request)
    before = repo.get_normalization_profile(profile_id)
    profile = repo.update_normalization_profile(profile_id, data)
    targets_changed = (profile.target_lufs, profile.true_peak, profile.lra) != (
        before.target_lufs,
        before.true_peak,
        before.lra,
    )
    affected = _jobs(request).on_normalization_profile_changed(
        profile_id, targets_changed=targets_changed
    )
    return {"profile": profile, "affected_clip_ids": affected}


@router.delete("/normalization-profiles/{profile_id}", status_code=204)
async def delete_normalization_profile(profile_id: str, request: Request) -> Response:
    _repo(request).delete_normalization_profile(profile_id)
    return Response(status_code=204)


@router.post("/normalization-profiles/{profile_id}/apply")
async def apply_normalization_profile(
    profile_id: str, data: NormalizationApply, request: Request
) -> dict[str, int]:
    repo = _repo(request)
    profile = repo.get_normalization_profile(profile_id)
    if (data.clip_ids is None) == (data.collection_id is None):
        raise InvalidError("Provide exactly one of clip_ids or collection_id.")
    if data.collection_id is not None:
        repo.get_collection(data.collection_id)
        clip_ids = [c.id for c in repo.list_clips() if c.collection_id == data.collection_id]
    else:
        clip_ids = list(dict.fromkeys(data.clip_ids or []))
    # Resolve and validate every clip before changing any, so a bad id leaves nothing half-done.
    updates: list[tuple[str, Recipe]] = []
    for clip_id in clip_ids:
        clip = repo.get_clip(clip_id)
        recipe = clip.recipe.model_copy(update={"profile_id": profile.id})
        if clip.original is not None:
            recipe.validate_for(clip.original)
        updates.append((clip_id, recipe))
    jobs = _jobs(request)
    for clip_id, recipe in updates:
        repo.set_recipe(clip_id, recipe)
        jobs.enqueue_render(clip_id)
    return {"queued": len(updates)}


# --- processing profiles ---------------------------------------------------------------------


@router.get("/processing-profiles", response_model=list[ProcessingProfileRecord])
async def list_processing_profiles(request: Request) -> list[ProcessingProfileRecord]:
    return _repo(request).list_processing_profiles()


@router.post("/processing-profiles", response_model=ProcessingProfileRecord)
async def create_processing_profile(
    data: ProcessingProfileCreate, request: Request
) -> ProcessingProfileRecord:
    return _repo(request).create_processing_profile(data)


@router.patch("/processing-profiles/{profile_id}")
async def patch_processing_profile(
    profile_id: str, data: ProcessingProfileUpdate, request: Request
) -> dict[str, object]:
    repo = _repo(request)
    before = repo.get_processing_profile(profile_id)
    profile = repo.update_processing_profile(profile_id, data)
    affected: list[str] = []
    if profile.settings != before.settings:  # a rename changes no render
        affected = _jobs(request).on_processing_profile_changed(profile_id)
    return {"profile": profile, "affected_clip_ids": affected}


@router.delete("/processing-profiles/{profile_id}", status_code=204)
async def delete_processing_profile(profile_id: str, request: Request) -> Response:
    _repo(request).delete_processing_profile(profile_id)
    return Response(status_code=204)


# --- assets ----------------------------------------------------------------------------------


def _safe_asset_name(raw: str | None) -> str:
    """The upload's base name with anything but letters, digits, ``._- `` replaced."""
    base = unicodedata.normalize("NFC", (raw or "").replace("\\", "/").rsplit("/", 1)[-1]).strip()
    name = _UNSAFE_NAME_CHARS.sub("_", base).strip()
    if not name or name.startswith(".") or len(name) > _MAX_NAME_LENGTH:
        raise InvalidError("The file needs a usable name that does not start with a dot.")
    return name


async def _stage_upload(file: UploadFile, staged: Path, limit: int) -> None:
    written = 0
    with staged.open("wb") as handle:
        while chunk := await file.read(_UPLOAD_CHUNK):
            written += len(chunk)
            if written > limit:
                raise HTTPException(status_code=413, detail="The file exceeds the upload limit.")
            await asyncio.to_thread(handle.write, chunk)
        handle.flush()
        await asyncio.to_thread(os.fsync, handle.fileno())


@router.get("/assets", response_model=list[Asset])
async def list_assets(request: Request) -> list[Asset]:
    return _repo(request).list_assets()


def _declared_length_exceeds(request: Request, limit: int) -> bool:
    """Whether Content-Length already says the body is over the limit (plus multipart framing)."""
    try:
        declared = int(request.headers.get("content-length", ""))
    except ValueError:
        return False  # absent or chunked: the post-spool check still applies
    return declared > limit + _MULTIPART_OVERHEAD


def _publish_asset_row(repo: Repository, name: str, size: int, sha256: str) -> Callable[[], None]:
    """Create or update the asset row and return a callable that undoes exactly that change."""
    try:
        previous: Asset | None = repo.get_asset(name)
    except NotFoundError:
        previous = None
    if previous is None:
        repo.create_asset(Asset(filename=name, size=size, sha256=sha256, status="ready"))
        return lambda: repo.delete_asset(name)
    repo.update_asset(name, AssetUpdate(size=size, sha256=sha256, status="ready"))
    restore = AssetUpdate(size=previous.size, sha256=previous.sha256, status=previous.status)

    def undo() -> None:
        repo.update_asset(name, restore)

    return undo


@router.post("/assets")
async def upload_asset(request: Request) -> dict[str, object]:
    state = request.app.state
    repo = _repo(request)
    store: MediaStore = state.store
    limit = repo.get_settings().max_upload_mb * 1024 * 1024
    if _declared_length_exceeds(request, limit):  # before Starlette spools the body to disk
        raise HTTPException(status_code=413, detail="The file exceeds the upload limit.")
    form = await request.form()
    try:
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise InvalidError("A file is required.")
        name = _safe_asset_name(file.filename)
        if Path(name).suffix.lower() not in ASSET_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type; use one of {', '.join(sorted(ASSET_EXTENSIONS))}.",
            )
        staged = store.staging_path(f"asset-{secrets.token_hex(6)}", name)
        try:
            await _stage_upload(file, staged, limit)
            try:
                info = await probe(staged)
            except MediaError:
                raise InvalidError("The file is not a readable video.") from None
            if not info.valid or info.duration <= 0:
                raise InvalidError("The file is not a readable video.")
            sha256 = await file_sha256(staged)
            size = staged.stat().st_size
            target = _asset_path(request, name)
            # Row first: a database failure leaves the published file and row untouched. If the
            # file then cannot be published, the row change is undone.
            undo = _publish_asset_row(repo, name, size, sha256)
            try:
                await asyncio.to_thread(os.replace, staged, target)
            except BaseException:
                try:
                    undo()
                except Exception:
                    _LOGGER.exception("Could not restore the asset row for %s", name)
                raise
        finally:
            shutil.rmtree(staged.parent, ignore_errors=True)
    finally:
        await form.close()
    asset = repo.get_asset(name)
    return {"asset": asset, "affected_clip_ids": _jobs(request).on_asset_changed(name)}


def _asset_path(request: Request, name: str) -> Path:
    paths = request.app.state.paths
    paths.assets_dir.mkdir(parents=True, exist_ok=True)
    validate_contained_path(paths.assets_dir, paths.media_dir)
    target: Path = paths.assets_dir / name
    validate_contained_path(target, paths.assets_dir)
    return target


@router.delete("/assets/{filename}", status_code=204)
async def delete_asset(filename: str, request: Request) -> Response:
    _repo(request).delete_asset(filename)  # 404 / 409 before the file is touched
    try:
        _asset_path(request, filename).unlink(missing_ok=True)
    except (InvalidError, OSError) as exc:
        _LOGGER.warning("Could not remove asset file %s: %s", filename, exc)
    return Response(status_code=204)


# --- garbage collection ----------------------------------------------------------------------


@router.post("/gc/run")
async def run_gc(request: Request) -> dict[str, object]:
    try:
        result = await _jobs(request).run_gc()
    except TimeoutError:
        raise HTTPException(
            status_code=503, detail="Another cleanup is already running; try again shortly."
        ) from None
    return {"deleted": len(result.deleted), "halted_reason": result.halted_reason}
