"""Pydantic models and small helpers shared across the Studio.

The JSON shapes mirror the types in the shared API reference (snake_case, ISO-8601 UTC
timestamps with a trailing ``Z``). Models that accept client input forbid unknown fields.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from .errors import InvalidError

ClipStatus = Literal["processing", "ready", "rendering", "failed"]
PlaybackMode = Literal["random", "sequential", "custom"]
RenderState = Literal["published", "retired", "unrecognized", "missing", "deleted"]
TimingSource = Literal["measured", "legacy_worker", "legacy_full_file"]
AssetStatus = Literal["ready", "missing"]
JobKind = Literal["probe", "render", "preview", "thumbs", "legacy_import"]
JobStatus = Literal["queued", "running", "done", "failed"]

DEFAULT_PROCESSING_PROFILE_ID = "compatibility-4k-loudness"
DEFAULT_LEAD_IN = 2.0
DEFAULT_TAIL_OUT = 2.0

_SLUG_MAX_LENGTH = 48
# Players and encoders may report a trim end a hair past the real duration.
_TRIM_END_TOLERANCE_S = 0.05
# Slack for float rounding when comparing fade lengths against the clip length.
_FADE_TOLERANCE_S = 1e-6
# Keeps season priorities well inside SQLite's INTEGER range.
_PRIORITY_LIMIT = 1000
_MAX_DURATION_S = 7200


def slugify(text: str) -> str:
    """Lowercase ASCII slug: accents stripped, runs of other characters become ``_``."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", folded.lower()).strip("_")
    return slug[:_SLUG_MAX_LENGTH].rstrip("_") or "item"


def utcnow_iso() -> str:
    """Current UTC time as ``2026-10-03T12:00:00Z``."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_sort_key(collection_id: str, clip_id: str) -> str:
    """Sequential-order key of a new clip (the same rule as the legacy Worker's)."""
    return f"{collection_id}/{clip_id}.mp4".casefold()


def _normalize_timestamp(value: str) -> str:
    """Parse an ISO-8601 timestamp (naive means UTC) and return it as ``YYYY-MM-DDTHH:MM:SSZ``."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is not None:
        try:
            parsed = parsed.astimezone(UTC)
        except OverflowError:
            raise ValueError("timestamp out of range") from None
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


# --- seasons ---------------------------------------------------------------------------------


class Season(BaseModel):
    id: str
    name: str
    color: str
    icon: str
    start: str | None
    end: str | None
    priority: int
    collection_id: str
    builtin: bool = False


class SeasonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str
    color: str = "#f59e0b"
    icon: str = "mdi:calendar-star"
    start: str
    end: str
    priority: int = Field(default=0, ge=-_PRIORITY_LIMIT, le=_PRIORITY_LIMIT)
    collection_id: str


class SeasonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    color: str | None = None
    icon: str | None = None
    start: str | None = None
    end: str | None = None
    priority: int | None = Field(default=None, ge=-_PRIORITY_LIMIT, le=_PRIORITY_LIMIT)
    collection_id: str | None = None


# --- collections -----------------------------------------------------------------------------


class Collection(BaseModel):
    id: str
    name: str
    color: str
    icon: str
    playback_mode: PlaybackMode
    order: list[str]
    processing_profile_id: str
    enabled: bool
    sort_order: int


class CollectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str
    color: str = "#f59e0b"
    icon: str = "mdi:movie-open"
    playback_mode: PlaybackMode = "random"
    processing_profile_id: str = DEFAULT_PROCESSING_PROFILE_ID


class CollectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    color: str | None = None
    icon: str | None = None
    playback_mode: PlaybackMode | None = None
    order: list[str] | None = None
    processing_profile_id: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None


# --- normalization and processing profiles ---------------------------------------------------


class NormalizationProfile(BaseModel):
    id: str
    name: str
    target_lufs: float
    true_peak: float
    lra: float


class NormalizationProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str
    target_lufs: float = Field(ge=-30, le=-5)
    true_peak: float = Field(ge=-9, le=0)
    lra: float = Field(ge=1, le=20)


class NormalizationProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    target_lufs: float | None = Field(default=None, ge=-30, le=-5)
    true_peak: float | None = Field(default=None, ge=-9, le=0)
    lra: float | None = Field(default=None, ge=1, le=20)


class ProcessingProfileRecord(BaseModel):
    """A stored processing profile; ``settings`` is validated by the injected settings hook."""

    id: str
    name: str
    settings: dict[str, object]


class ProcessingProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str
    settings: dict[str, object] = Field(default_factory=dict[str, object])


class ProcessingProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    settings: dict[str, object] | None = None


class Asset(BaseModel):
    filename: str
    size: int | None
    sha256: str | None
    status: AssetStatus


class AssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    size: int | None = None
    sha256: str | None = None
    status: AssetStatus | None = None


# --- clips -----------------------------------------------------------------------------------


class Crop(BaseModel):
    """Crop rectangle in source pixels."""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)


class OriginalInfo(BaseModel):
    filename: str
    size: int
    sha256: str
    duration: float
    width: int
    height: int
    fps: float | None
    has_audio: bool
    video_codec: str


class Recipe(BaseModel):
    """How a render is derived from the original; the defaults keep the whole clip."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    trim_start: float = Field(default=0.0, ge=0)
    trim_end: float | None = Field(default=None, ge=0)
    crop: Crop | None = None
    # None means "use the processing profile's fades".
    fade_in: float | None = Field(default=None, ge=0)
    fade_out: float | None = Field(default=None, ge=0)
    gain_db: float = Field(default=0.0, ge=-24, le=24)
    profile_id: str | None = None
    lead_in: float = Field(default=DEFAULT_LEAD_IN, ge=0)
    tail_out: float = Field(default=DEFAULT_TAIL_OUT, ge=0)

    def validate_for(self, original: OriginalInfo) -> None:
        """Check the recipe against the original's duration and frame size."""
        duration = original.duration
        if self.trim_end is not None:
            if self.trim_start >= self.trim_end:
                raise InvalidError("Trim start must be before trim end.")
            if self.trim_end > duration + _TRIM_END_TOLERANCE_S:
                raise InvalidError(
                    f"Trim end ({self.trim_end:g}s) is past the end of the video ({duration:g}s)."
                )
        end = duration if self.trim_end is None else min(self.trim_end, duration)
        length = end - self.trim_start
        if length <= 0:
            raise InvalidError(
                f"Trim start ({self.trim_start:g}s) is at or past the end of the video"
                f" ({duration:g}s)."
            )
        if self.crop is not None and (
            self.crop.x + self.crop.w > original.width
            or self.crop.y + self.crop.h > original.height
        ):
            raise InvalidError(
                f"The crop exceeds the source frame ({original.width}x{original.height})."
            )
        fades = (self.fade_in or 0.0) + (self.fade_out or 0.0)
        if fades > length + _FADE_TOLERANCE_S:
            raise InvalidError(
                f"Fade in plus fade out ({fades:g}s) is longer than the clip content ({length:g}s)."
            )


class Render(BaseModel):
    id: str
    n: int
    relative_path: str
    size: int
    sha256: str
    duration: float
    content_start: float
    content_end: float
    lead_in: float
    tail_out: float
    content_duration: float
    timing_source: TimingSource
    integrated_lufs: float | None
    true_peak: float | None
    recipe_hash: str
    profile_fingerprint: str
    published_at: str

    @computed_field
    @property
    def media_path(self) -> str:
        """Identical to ``relative_path``; kept separate for future media roots."""
        return self.relative_path


class RenderRecord(Render):
    """A row of the renders table: the Render plus its owner and lifecycle."""

    clip_id: str
    state: RenderState = "published"
    # Unrecognized, missing and deleted records have never been published.
    published_at: str | None = None  # pyright: ignore[reportIncompatibleVariableOverride]
    retired_at: str | None = None
    retired_revision: int | None = None
    created_at: str = Field(default_factory=utcnow_iso)

    def to_render(self) -> Render:
        """The public Render of a published record."""
        if self.published_at is None:
            raise InvalidError(f"Render '{self.id}' was never published.")
        return Render.model_validate(self.model_dump(include=set(Render.model_fields)))


class Clip(BaseModel):
    id: str
    collection_id: str
    title: str
    source_name: str
    enabled: bool
    notes: str
    original: OriginalInfo | None
    recipe: Recipe
    render: Render | None
    render_pending: bool
    status: ClipStatus
    error: str | None
    needs_source: bool
    sort_key: str
    selection_count: int
    last_selected_at: str | None
    has_preview: bool
    has_thumbs: bool
    created_at: str
    updated_at: str


class ClipUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    collection_id: str | None = None
    enabled: bool | None = None
    notes: str | None = None


class BulkSet(BaseModel):
    """Changes applied to many clips; ``profile_id`` is handled by the API layer."""

    model_config = ConfigDict(extra="forbid")

    collection_id: str | None = None
    enabled: bool | None = None
    profile_id: str | None = None


# --- settings --------------------------------------------------------------------------------


# Home Assistant entity id: lowercase slug domain and object id, no leading/trailing or
# double underscores (same rule as homeassistant.core.valid_entity_id).
_ENTITY_ID = re.compile(r"(?!.+__)(?!_)[\da-z_]+(?<!_)\.(?!_)[\da-z_]+(?<!_)")

DEFAULT_PROTECTED_ENTITIES = ["media_player.otocuma_dp", "cover.ocl_screen_projector"]


class TestTarget(BaseModel):
    """A media player the UI may play a clip on; only ``media_player.*`` entities qualify."""

    __test__ = False  # not a pytest test class

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    entity_id: str

    @field_validator("id", "label")
    @classmethod
    def _require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("entity_id")
    @classmethod
    def _require_media_player(cls, value: str) -> str:
        if not _ENTITY_ID.fullmatch(value) or not value.startswith("media_player."):
            raise ValueError("must be a media_player entity id, e.g. media_player.living_room")
        return value


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_upload_mb: int = Field(default=4096, ge=1)
    max_duration_s: int = Field(default=_MAX_DURATION_S, ge=1, le=_MAX_DURATION_S)
    default_lead_in: float = Field(default=DEFAULT_LEAD_IN, ge=0, allow_inf_nan=False)
    default_tail_out: float = Field(default=DEFAULT_TAIL_OUT, ge=0, allow_inf_nan=False)
    disk_reserve_bytes: int = Field(default=2147483648, ge=0)
    test_targets: list[TestTarget] = Field(default_factory=list[TestTarget])
    protected_entities: list[str] = Field(default_factory=lambda: list(DEFAULT_PROTECTED_ENTITIES))

    @model_validator(mode="after")
    def _targets_not_protected(self) -> Settings:
        protected = set(self.protected_entities)
        for target in self.test_targets:
            if target.entity_id in protected:
                raise ValueError(f"{target.entity_id} is protected and cannot be a test target")
        return self


# --- integration traffic and jobs ------------------------------------------------------------


class SelectionEvent(BaseModel):
    selection_id: str
    clip_id: str
    render_id: str
    catalog_revision: int
    selected_at: str

    @field_validator("selected_at")
    @classmethod
    def _normalize_selected_at(cls, value: str) -> str:
        return _normalize_timestamp(value)


class SelectionBatch(BaseModel):
    events: list[SelectionEvent] = Field(max_length=500)


class Job(BaseModel):
    id: str
    kind: JobKind
    clip_id: str | None
    clip_title: str
    status: JobStatus = "queued"
    progress: float = 0.0
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class LegacySkip(BaseModel):
    clip_id: str
    reason: str


class LegacyReport(BaseModel):
    run_id: str
    started_at: str
    finished_at: str | None
    catalog_revision: int
    imported: list[str]
    queued_for_render: list[str]
    needs_source: list[str]
    skipped: list[LegacySkip]
    missing_assets: list[str]
