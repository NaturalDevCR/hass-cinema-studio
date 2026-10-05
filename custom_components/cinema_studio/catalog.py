"""Typed, validated view of the App's published catalog."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from .const import CONTRACT_VERSION
from .timing import Timing, timing_problems


@dataclass(frozen=True)
class SeasonDef:
    id: str
    name: str
    color: str
    icon: str
    start: str | None
    end: str | None
    priority: int
    collection_id: str


@dataclass(frozen=True)
class CollectionDef:
    id: str
    name: str
    color: str
    icon: str
    playback_mode: str
    order: tuple[str, ...]
    enabled: bool


@dataclass(frozen=True)
class RenderDef:
    id: str
    n: int
    relative_path: str
    media_path: str
    size: int
    sha256: str
    timing: Timing
    timing_source: str
    profile_fingerprint: str
    integrated_lufs: float | None


@dataclass(frozen=True)
class ClipDef:
    id: str
    collection_id: str
    title: str
    source_name: str
    enabled: bool
    sort_key: str
    render_pending: bool
    render: RenderDef


class _Named(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...


@dataclass(frozen=True)
class Catalog:
    contract_version: int
    revision: int
    instance_id: str
    seasons: tuple[SeasonDef, ...]
    collections: tuple[CollectionDef, ...]
    clips: tuple[ClipDef, ...]
    invalid_clip_ids: tuple[str, ...]

    def find_collection(self, ref: str) -> CollectionDef | None:
        return _find(self.collections, ref)

    def find_season(self, ref: str) -> SeasonDef | None:
        return _find(self.seasons, ref)

    def render_ids(self) -> frozenset[str]:
        return frozenset(clip.render.id for clip in self.clips)


def _find[T: _Named](items: tuple[T, ...], ref: str) -> T | None:
    exact = next((item for item in items if item.id == ref), None)
    if exact is not None:
        return exact
    folded = ref.casefold()
    return next(
        (item for item in items if item.id.casefold() == folded or item.name.casefold() == folded),
        None,
    )


def _obj(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, Any], value)


def _get(data: Mapping[str, Any], key: str, kind: type | tuple[type, ...], context: str) -> Any:
    value = data.get(key)
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise ValueError(f"{context}.{key} is missing or invalid")
    return value


def parse_catalog(data: Mapping[str, Any]) -> Catalog:
    root = _obj(data, "catalog")
    version = _get(root, "contract_version", int, "catalog")
    if version != CONTRACT_VERSION:
        raise ValueError(f"unsupported contract_version: {version}")
    seasons = tuple(
        _parse_season(_obj(item, "season")) for item in _get(root, "seasons", list, "catalog")
    )
    collections = tuple(
        _parse_collection(_obj(item, "collection"))
        for item in _get(root, "collections", list, "catalog")
    )
    invalid: list[str] = []
    clips: list[ClipDef] = []
    for item in _get(root, "clips", list, "catalog"):
        raw = _obj(item, "clip")
        clip_id = _get(raw, "id", str, "clip")
        try:
            clips.append(_parse_clip(raw))
        except (ValueError, OverflowError):
            invalid.append(clip_id)
    return Catalog(
        version,
        _get(root, "revision", int, "catalog"),
        _get(root, "instance_id", str, "catalog"),
        seasons,
        collections,
        tuple(clips),
        tuple(invalid),
    )


def _parse_season(data: Mapping[str, Any]) -> SeasonDef:
    start, end = data.get("start"), data.get("end")
    if (
        start is not None
        and not isinstance(start, str)
        or end is not None
        and not isinstance(end, str)
    ):
        raise ValueError("season dates must be strings or null")
    return SeasonDef(
        _get(data, "id", str, "season"),
        _get(data, "name", str, "season"),
        _get(data, "color", str, "season"),
        _get(data, "icon", str, "season"),
        start,
        end,
        _get(data, "priority", int, "season"),
        _get(data, "collection_id", str, "season"),
    )


def _parse_collection(data: Mapping[str, Any]) -> CollectionDef:
    order = _get(data, "order", list, "collection")
    if not all(isinstance(value, str) for value in order):
        raise ValueError("collection.order must contain strings")
    return CollectionDef(
        _get(data, "id", str, "collection"),
        _get(data, "name", str, "collection"),
        _get(data, "color", str, "collection"),
        _get(data, "icon", str, "collection"),
        _get(data, "playback_mode", str, "collection"),
        tuple(order),
        _get(data, "enabled", bool, "collection"),
    )


def _parse_clip(data: Mapping[str, Any]) -> ClipDef:
    clip_id = _get(data, "id", str, "clip")
    r = _obj(data.get("render"), "render")
    vals = [
        _get(r, key, (int, float), "render")
        for key in (
            "duration",
            "content_start",
            "content_end",
            "lead_in",
            "tail_out",
            "content_duration",
        )
    ]
    if any(isinstance(v, bool) or not math.isfinite(v) for v in vals):
        raise ValueError("render timing must be finite")
    timing = Timing(*map(float, vals))
    path = _get(r, "relative_path", str, "render")
    segments = path.split("/")
    if (
        "\\" in path
        or any(segment in {"", ".", ".."} for segment in segments)
        or not path.startswith(f"cinema-studio/renders/{clip_id}/")
    ):
        raise ValueError("render path is unsafe or outside clip directory")
    if r.get("media_path") != path:
        raise ValueError("render media_path must match relative_path")
    if timing_problems(timing):
        raise ValueError("render timing is invalid")
    lufs = r.get("integrated_lufs")
    if lufs is not None and (
        not isinstance(lufs, (int, float)) or isinstance(lufs, bool) or not math.isfinite(lufs)
    ):
        raise ValueError("integrated_lufs is invalid")
    render = RenderDef(
        _get(r, "id", str, "render"),
        _get(r, "n", int, "render"),
        path,
        _get(r, "media_path", str, "render"),
        _get(r, "size", int, "render"),
        _get(r, "sha256", str, "render"),
        timing,
        _get(r, "timing_source", str, "render"),
        _get(r, "profile_fingerprint", str, "render"),
        float(lufs) if lufs is not None else None,
    )
    return ClipDef(
        clip_id,
        _get(data, "collection_id", str, "clip"),
        _get(data, "title", str, "clip"),
        _get(data, "source_name", str, "clip"),
        _get(data, "enabled", bool, "clip"),
        _get(data, "sort_key", str, "clip"),
        _get(data, "render_pending", bool, "clip"),
        render,
    )


EMPTY_CATALOG = Catalog(CONTRACT_VERSION, 0, "", (), (), (), ())
