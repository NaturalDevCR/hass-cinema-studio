"""Ingress UI clips: uploads, recipes, previews, streams, thumbnails, test on device and jobs."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import secrets
import shutil
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict

from . import media
from .config import Paths
from .errors import InvalidError, NotFoundError
from .jobs import JobQueue
from .models import (
    BulkSet,
    Clip,
    ClipUpdate,
    Job,
    OriginalInfo,
    Recipe,
    default_sort_key,
)
from .probe import probe
from .repository import Repository
from .storage import TEST_RENDER_DIR, MediaStore, validate_contained_path
from .supervisor import SupervisorClient, SupervisorError
from .uploads import (
    CHUNK_SIZE,
    UnsupportedUploadError,
    UploadStore,
    UploadTooLargeError,
    safe_filename,
)

router = APIRouter(prefix="/api/ui")

MIN_CROP_SIDE = 64
MAX_MARGIN_S = 10.0
_MEDIA_SOURCE_PREFIX = "media-source://media_source/local/"
_NO_CACHE = {"Cache-Control": "no-store"}


class UploadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    size: int


class UploadComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str
    title: str | None = None


class SourceReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: str


class BulkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str]
    set: BulkSet


class TestRequest(BaseModel):
    __test__ = False  # not a pytest test class

    model_config = ConfigDict(extra="forbid")

    target_id: str
    source: Literal["preview", "render"]


def _repo(request: Request) -> Repository:
    repo: Repository = request.app.state.repo
    return repo


def _jobs(request: Request) -> JobQueue:
    jobs: JobQueue = request.app.state.jobs
    return jobs


def _paths(request: Request) -> Paths:
    paths: Paths = request.app.state.paths
    return paths


def _store(request: Request) -> MediaStore:
    store: MediaStore = request.app.state.store
    return store


def _uploads(request: Request) -> UploadStore:
    uploads: UploadStore = request.app.state.uploads
    return uploads


def _supervisor(request: Request) -> SupervisorClient:
    supervisor: SupervisorClient = request.app.state.supervisor
    return supervisor


def _preview_path(paths: Paths, clip_id: str) -> Path:
    # Where the job worker leaves a finished preview (see JobQueue._preview_path).
    return paths.work_dir / "previews" / f"{clip_id}.mp4"


def _media_source_uri(relative_path: str) -> str:
    return _MEDIA_SOURCE_PREFIX + relative_path


# --- recipes ---------------------------------------------------------------------------------


def _validate_recipe(repo: Repository, clip: Clip, recipe: Recipe) -> None:
    """Everything a recipe must satisfy against the clip's original and the stored profiles."""
    if clip.original is None:
        raise InvalidError("The clip has no usable original yet.")
    recipe.validate_for(clip.original)
    if recipe.crop is not None and (recipe.crop.w < MIN_CROP_SIDE or recipe.crop.h < MIN_CROP_SIDE):
        raise InvalidError(f"The crop must be at least {MIN_CROP_SIDE}x{MIN_CROP_SIDE} pixels.")
    for label, margin in (("Lead-in", recipe.lead_in), ("Tail-out", recipe.tail_out)):
        if margin > MAX_MARGIN_S:
            raise InvalidError(f"{label} must be between 0 and {MAX_MARGIN_S:g} seconds.")
    _check_profile(repo, recipe.profile_id)


def _check_profile(repo: Repository, profile_id: str | None) -> None:
    if profile_id is None:
        return
    try:
        repo.get_normalization_profile(profile_id)
    except NotFoundError as exc:
        raise InvalidError(str(exc)) from exc


# --- clips -----------------------------------------------------------------------------------


@router.get("/clips")
async def list_clips(request: Request) -> list[Clip]:
    return _repo(request).list_clips()


@router.post("/clips/bulk")
async def bulk_update(data: BulkUpdate, request: Request) -> dict[str, int]:
    repo = _repo(request)
    jobs = _jobs(request)
    ids = list(dict.fromkeys(data.ids))
    change_profile = "profile_id" in data.set.model_fields_set
    if data.set.collection_id is not None:
        try:
            repo.get_collection(data.set.collection_id)
        except NotFoundError as exc:
            raise InvalidError(str(exc)) from exc
    recipes: list[tuple[str, Recipe]] = []
    if change_profile:
        # Resolve and validate every clip before changing any, so a bad id leaves nothing done.
        _check_profile(repo, data.set.profile_id)
        for clip_id in ids:
            clip = repo.get_clip(clip_id)
            recipe = clip.recipe.model_copy(update={"profile_id": data.set.profile_id})
            if clip.original is not None:
                recipe.validate_for(clip.original)
            recipes.append((clip_id, recipe))
    wanted = set(ids)
    previous = {clip.id: clip.collection_id for clip in repo.list_clips() if clip.id in wanted}
    updated = repo.bulk_update(ids, data.set)
    queued: set[str] = set()
    if data.set.collection_id is not None:
        for clip_id, before in previous.items():
            queued.update(jobs.on_clip_collection_changed(clip_id, before))
    for clip_id, recipe in recipes:
        repo.set_recipe(clip_id, recipe)
        jobs.enqueue_render(clip_id)
        queued.add(clip_id)
    return {"updated": updated, "queued": len(queued)}


@router.get("/clips/{clip_id}")
async def get_clip(clip_id: str, request: Request) -> Clip:
    return _repo(request).get_clip(clip_id)


@router.patch("/clips/{clip_id}")
async def patch_clip(clip_id: str, data: ClipUpdate, request: Request) -> Clip:
    repo = _repo(request)
    before = repo.get_clip(clip_id).collection_id
    clip = repo.update_clip(clip_id, data)
    if clip.collection_id != before:
        _jobs(request).on_clip_collection_changed(clip_id, before)
        clip = repo.get_clip(clip_id)
    return clip


@router.put("/clips/{clip_id}/recipe")
async def put_recipe(clip_id: str, data: Recipe, request: Request) -> dict[str, Clip | Job]:
    repo = _repo(request)
    _validate_recipe(repo, repo.get_clip(clip_id), data)
    clip = repo.set_recipe(clip_id, data)
    return {"clip": clip, "job": _jobs(request).enqueue_render(clip_id)}


@router.post("/clips/{clip_id}/preview")
async def post_preview(clip_id: str, data: Recipe, request: Request) -> dict[str, Job]:
    repo = _repo(request)
    _validate_recipe(repo, repo.get_clip(clip_id), data)
    return {"job": _jobs(request).enqueue_preview(clip_id, data)}


@router.post("/clips/{clip_id}/rerender")
async def rerender(clip_id: str, request: Request) -> dict[str, Job]:
    clip = _repo(request).get_clip(clip_id)
    if clip.original is None or clip.needs_source:
        raise InvalidError("The clip needs its original video before it can be rendered.")
    return {"job": _jobs(request).enqueue_render(clip_id)}


def _remove_clip_files(paths: Paths, clip_id: str) -> None:
    for directory in (paths.originals_dir / clip_id, paths.thumbs_dir / clip_id):
        shutil.rmtree(directory, ignore_errors=True)
    _preview_path(paths, clip_id).unlink(missing_ok=True)


@router.delete("/clips/{clip_id}", status_code=204)
async def delete_clip(clip_id: str, request: Request) -> Response:
    repo = _repo(request)
    repo.get_clip(clip_id)
    repo.delete_clip(clip_id)  # retires the render; the garbage collector removes it later
    await asyncio.to_thread(_remove_clip_files, _paths(request), clip_id)
    return Response(status_code=204)


# --- streams and thumbnails ------------------------------------------------------------------


def _original_file(paths: Paths, clip: Clip) -> Path:
    directory = paths.originals_dir / clip.id
    if clip.original is not None:
        candidate = directory / clip.original.filename
        if candidate.is_file():
            return candidate
        raise NotFoundError("Original video is missing.")
    files = [file for file in directory.iterdir() if file.is_file()] if directory.is_dir() else []
    if len(files) != 1:
        raise NotFoundError("Original video is missing.")
    return files[0]


def _render_file(paths: Paths, clip: Clip) -> Path:
    if clip.render is None:
        raise NotFoundError("Rendered video is missing.")
    file = paths.media_dir / clip.render.relative_path
    if not file.is_file():
        raise NotFoundError("Rendered video is missing.")
    return file


@router.get("/clips/{clip_id}/original")
async def get_original(clip_id: str, request: Request) -> FileResponse:
    clip = _repo(request).get_clip(clip_id)
    file = _original_file(_paths(request), clip)
    media_type = mimetypes.guess_type(file.name)[0] or "video/mp4"
    return FileResponse(file, media_type=media_type, headers=_NO_CACHE)


@router.get("/clips/{clip_id}/preview")
async def get_preview(clip_id: str, request: Request) -> FileResponse:
    _repo(request).get_clip(clip_id)
    file = _preview_path(_paths(request), clip_id)
    if not file.is_file():
        raise NotFoundError("Preview video is missing.")
    return FileResponse(file, media_type="video/mp4", headers=_NO_CACHE)


@router.get("/clips/{clip_id}/render")
async def get_render(clip_id: str, request: Request) -> FileResponse:
    clip = _repo(request).get_clip(clip_id)
    return FileResponse(_render_file(_paths(request), clip), media_type="video/mp4")


@router.get("/clips/{clip_id}/poster.jpg")
async def get_poster(clip_id: str, request: Request) -> FileResponse:
    clip = _repo(request).get_clip(clip_id)
    root = _paths(request).thumbs_dir / clip_id
    candidates = [root / "original" / "poster.jpg"]
    if clip.render is not None:
        candidates.insert(0, root / f"r{clip.render.n}" / "poster.jpg")
    for candidate in candidates:
        if candidate.is_file():
            return FileResponse(candidate, media_type="image/jpeg", headers=_NO_CACHE)
    raise NotFoundError("Poster is missing.")


def _filmstrip_count(directory: Path) -> int:
    try:
        metadata: object = json.loads((directory / "filmstrip.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise NotFoundError("Filmstrip is missing.") from None
    count = cast("dict[str, object]", metadata).get("count") if isinstance(metadata, dict) else None
    if not isinstance(count, int):
        raise NotFoundError("Filmstrip is missing.")
    return count


@router.get("/clips/{clip_id}/filmstrip.json")
async def get_filmstrip(clip_id: str, request: Request) -> FileResponse:
    _repo(request).get_clip(clip_id)
    file = _paths(request).thumbs_dir / clip_id / "original" / "filmstrip.json"
    if not file.is_file():
        raise NotFoundError("Filmstrip is missing.")
    return FileResponse(file, media_type="application/json", headers=_NO_CACHE)


@router.get("/clips/{clip_id}/filmstrip/{index}.jpg")
async def get_filmstrip_frame(clip_id: str, index: int, request: Request) -> FileResponse:
    _repo(request).get_clip(clip_id)
    directory = _paths(request).thumbs_dir / clip_id / "original"
    if not 0 <= index < _filmstrip_count(directory):
        raise NotFoundError("Filmstrip frame does not exist.")
    file = directory / f"{index:04d}.jpg"
    if not file.is_file():
        raise NotFoundError("Filmstrip frame does not exist.")
    return FileResponse(file, media_type="image/jpeg", headers=_NO_CACHE)


# --- test on device --------------------------------------------------------------------------


def _copy_preview_for_test(paths: Paths, source: Path, clip_id: str) -> str:
    """Copy a preview under ``renders/_test`` (swept after an hour); returns its media path."""
    validate_contained_path(paths.renders_dir, paths.media_dir)
    directory = paths.renders_dir / TEST_RENDER_DIR
    directory.mkdir(mode=0o755, parents=True, exist_ok=True)
    validate_contained_path(directory, paths.renders_dir)
    target = directory / f"{clip_id}-{secrets.token_hex(4)}.mp4"
    shutil.copyfile(source, target)
    return target.relative_to(paths.media_dir).as_posix()


@router.post("/clips/{clip_id}/test")
async def test_on_device(clip_id: str, data: TestRequest, request: Request) -> dict[str, object]:
    repo = _repo(request)
    clip = repo.get_clip(clip_id)
    settings = repo.get_settings()
    target = next((item for item in settings.test_targets if item.id == data.target_id), None)
    if target is None:
        raise NotFoundError("Unknown test target.")
    # Re-checked here so a hand-edited setting can never reach a protected or non-player entity.
    if not target.entity_id.startswith("media_player.") or (
        target.entity_id in settings.protected_entities
    ):
        raise HTTPException(status_code=403, detail="This entity cannot be used as a test target.")
    paths = _paths(request)
    if data.source == "preview":
        source = _preview_path(paths, clip_id)
        if not source.is_file():
            raise NotFoundError("Preview video is missing.")
    else:
        source = _render_file(paths, clip)
    supervisor = _supervisor(request)
    if not supervisor.available:
        raise HTTPException(status_code=503, detail="The Supervisor API is not available")
    if data.source == "preview":
        relative = await asyncio.to_thread(_copy_preview_for_test, paths, source, clip_id)
    else:
        assert clip.render is not None  # _render_file raised otherwise
        relative = clip.render.relative_path
    media_content_id = _media_source_uri(relative)
    try:
        await supervisor.call_service(
            "media_player",
            "play_media",
            {
                "entity_id": target.entity_id,
                "media_content_id": media_content_id,
                "media_content_type": "video",
            },
        )
    except SupervisorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "media_content_id": media_content_id}


# --- uploads ---------------------------------------------------------------------------------


@router.post("/uploads")
async def create_upload(data: UploadCreate, request: Request) -> dict[str, str | int]:
    try:
        upload_id = await asyncio.to_thread(_uploads(request).create, data.filename, data.size)
    except UnsupportedUploadError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return {"upload_id": upload_id, "chunk_size": CHUNK_SIZE}


@router.put("/uploads/{upload_id}/chunks/{index}")
async def put_chunk(upload_id: str, index: int, request: Request) -> dict[str, int]:
    uploads = _uploads(request)
    try:
        limit = await asyncio.to_thread(uploads.chunk_limit, upload_id, index)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError as exc:
                raise InvalidError("Invalid Content-Length.") from exc
            if declared_length > limit:
                raise UploadTooLargeError("Chunk exceeds the maximum or declared upload size.")
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > limit:
                raise UploadTooLargeError("Chunk exceeds the maximum or declared upload size.")
            data.extend(chunk)
        received = await asyncio.to_thread(uploads.write_chunk, upload_id, index, bytes(data))
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return {"received": received}


def _title_from(filename: str) -> str:
    stem = Path(filename).stem
    return re.sub(r"\s+", " ", stem.replace("-", " ").replace("_", " ")).strip() or stem or "clip"


def _stage_upload(request: Request, upload_id: str, filename: str) -> Path:
    """Move the finished upload next to the other work files; returns the staged file."""
    name = safe_filename(filename)
    staged = _store(request).staging_path(f"upload-{upload_id}", name)
    return _uploads(request).finish(upload_id, staged.parent)


def _store_new_original(request: Request, upload_id: str, filename: str, clip_id: str) -> None:
    staged = _stage_upload(request, upload_id, filename)
    try:
        _store(request).store_original(staged, clip_id, staged.name, link=False)
    finally:
        shutil.rmtree(staged.parent, ignore_errors=True)


async def _settled[T](work: asyncio.Future[T]) -> T:
    """Await a thread-backed task so cancelling the request cannot leave it half done."""
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        # A running thread cannot be cancelled; settle it before the caller cleans up after it.
        with suppress(Exception):
            await work
        raise


@router.post("/uploads/{upload_id}/complete")
async def complete_upload(upload_id: str, data: UploadComplete, request: Request) -> Clip:
    uploads = _uploads(request)
    repo = _repo(request)
    filename = await asyncio.to_thread(uploads.ready_filename, upload_id)
    try:
        repo.get_collection(data.collection_id)
    except NotFoundError as exc:
        raise InvalidError(str(exc)) from exc
    settings = repo.get_settings()
    source_name = safe_filename(filename, preserve_extension_case=True)
    clip_id = str(uuid.uuid4())
    clip = repo.create_clip(
        clip_id=clip_id,
        collection_id=data.collection_id,
        title=data.title if data.title and data.title.strip() else _title_from(source_name),
        source_name=source_name,
        recipe=Recipe(lead_in=settings.default_lead_in, tail_out=settings.default_tail_out),
        original=None,
        sort_key=default_sort_key(data.collection_id, clip_id),
    )
    try:
        await _settled(
            asyncio.ensure_future(
                asyncio.to_thread(_store_new_original, request, upload_id, filename, clip_id)
            )
        )
    except BaseException:
        shutil.rmtree(_paths(request).originals_dir / clip_id, ignore_errors=True)
        repo.delete_clip(clip_id)
        raise
    _jobs(request).enqueue_probe(clip_id)
    return repo.get_clip(clip.id)


# --- source repair ---------------------------------------------------------------------------


async def _probe_original(staged: Path, max_duration_s: int) -> OriginalInfo:
    try:
        info = await probe(staged)
        sha256 = await media.file_sha256(staged)
    except media.MediaError:
        raise InvalidError("The file is not a readable video.") from None
    if not info.valid or info.duration <= 0 or not info.width or not info.height:
        raise InvalidError("The file is not a readable video.")
    if info.duration > max_duration_s:
        raise InvalidError(f"Video is longer than {max_duration_s} s")
    return OriginalInfo(
        filename=staged.name,
        size=staged.stat().st_size,
        sha256=sha256,
        duration=info.duration,
        width=info.width,
        height=info.height,
        fps=info.fps,
        has_audio=info.has_audio,
        video_codec=info.video_codec or "",
    )


def _swap_original(paths: Paths, store: MediaStore, staged: Path, clip_id: str) -> None:
    """Write the new original beside the old directory, swap them, then delete the old one."""
    token = secrets.token_hex(4)
    fresh_id, old_id = f"{clip_id}.new-{token}", f"{clip_id}.old-{token}"
    fresh = paths.originals_dir / fresh_id
    final = paths.originals_dir / clip_id
    retired = paths.originals_dir / old_id
    try:
        store.store_original(staged, fresh_id, staged.name, link=False)
        validate_contained_path(final, paths.originals_dir)
        if final.exists():
            os.replace(final, retired)
        os.replace(fresh, final)
    except BaseException:
        shutil.rmtree(fresh, ignore_errors=True)
        if retired.exists() and not final.exists():
            os.replace(retired, final)  # put the old original back
        raise
    shutil.rmtree(retired, ignore_errors=True)


@router.post("/clips/{clip_id}/source")
async def replace_source(clip_id: str, data: SourceReplace, request: Request) -> Clip:
    repo = _repo(request)
    clip = repo.get_clip(clip_id)
    uploads = _uploads(request)
    filename = await asyncio.to_thread(uploads.ready_filename, data.upload_id)
    paths = _paths(request)
    staged = await asyncio.to_thread(_stage_upload, request, data.upload_id, filename)
    try:
        original = await _probe_original(staged, repo.get_settings().max_duration_s)
        clip.recipe.validate_for(original)
        await _settled(
            asyncio.ensure_future(
                asyncio.to_thread(_swap_original, paths, _store(request), staged, clip_id)
            )
        )
    finally:
        shutil.rmtree(staged.parent, ignore_errors=True)
    repo.set_original(clip_id, original)
    repo.set_flags(clip_id, needs_source=False, render_pending=True, has_preview=False)
    _preview_path(paths, clip_id).unlink(missing_ok=True)
    if clip.status == "failed":
        repo.set_status(clip_id, "ready" if clip.render is not None else "processing")
    jobs = _jobs(request)
    jobs.enqueue_thumbs(clip_id)
    jobs.enqueue_render(clip_id)
    return repo.get_clip(clip_id)


# --- jobs ------------------------------------------------------------------------------------


@router.get("/jobs")
async def list_jobs(request: Request) -> list[Job]:
    return _jobs(request).list_jobs()
