"""SQLite-backed storage for seasons, collections, profiles, assets, clips and renders.

The repository is synchronous. It is called from async handlers on the event loop and from
worker threads; every access goes through :attr:`Database.lock`.

Every write that changes the catalog document served to the integration bumps
``meta.catalog_revision`` inside the same transaction and calls ``on_catalog_change(revision)``
after the commit. Selection counters, settings, profile and asset edits, the transient
``processing``/``rendering`` statuses and the preview/thumbnail flags do not change what the
integration has to re-read, so they never bump.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast

from .db import Database
from .errors import ConflictError, InvalidError, NotFoundError
from .models import (
    Asset,
    AssetUpdate,
    BulkSet,
    Clip,
    ClipStatus,
    ClipUpdate,
    Collection,
    CollectionCreate,
    CollectionUpdate,
    LegacyReport,
    NormalizationProfile,
    NormalizationProfileCreate,
    NormalizationProfileUpdate,
    OriginalInfo,
    ProcessingProfileCreate,
    ProcessingProfileRecord,
    ProcessingProfileUpdate,
    Recipe,
    RenderRecord,
    RenderState,
    Season,
    SeasonCreate,
    SeasonUpdate,
    SelectionEvent,
    Settings,
    slugify,
    utcnow_iso,
)
from .timing import Timing
from .timing_validation import validate_timing

_LOGGER = logging.getLogger(__name__)

_MMDD = re.compile(r"\d{2}-\d{2}")
_EXPLICIT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")
# Clip ids become directory names; imports keep the legacy Worker's ids (UUIDs).
_CLIP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

_SEASON_ORDER = "ORDER BY id = 'regular' DESC, priority DESC, name COLLATE NOCASE, id"
_COLLECTION_ORDER = "ORDER BY sort_order, name COLLATE NOCASE, id"

_RENDER_COLUMNS = (
    "id", "clip_id", "n", "relative_path", "size", "sha256", "duration", "content_start",
    "content_end", "lead_in", "tail_out", "content_duration", "timing_source",
    "integrated_lufs", "true_peak", "recipe_hash", "profile_fingerprint", "state",
    "published_at", "retired_at", "retired_revision", "created_at",
)  # fmt: skip

_Table = Literal[
    "seasons", "collections", "normalization_profiles", "processing_profiles", "clips", "renders"
]


def _dumps(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def _clean_text(label: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise InvalidError(f"The {label} must not be empty.")
    return cleaned


def _resolve_id(explicit: str | None, name: str) -> str:
    """Use the explicit id when given (it must be URL-safe), else slugify the name."""
    if explicit is None:
        return slugify(name)
    candidate = explicit.strip()
    if not _EXPLICIT_ID.fullmatch(candidate):
        raise InvalidError(
            f"Invalid id '{explicit}': use 1-48 lowercase letters, digits, '_' or '-'."
        )
    return candidate


def _validate_mmdd(label: str, value: str | None) -> str:
    if value is None:
        raise InvalidError(f"The season {label} date is required (MM-DD).")
    if not _MMDD.fullmatch(value):
        raise InvalidError(f"Invalid season {label} date '{value}': expected MM-DD.")
    try:
        # 2000 is a leap year, so 02-29 is accepted.
        date.fromisoformat(f"2000-{value}")
    except ValueError:
        raise InvalidError(f"Invalid season {label} date '{value}': no such day.") from None
    return value


def _dedupe(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _mentions(value: object, needle: str) -> bool:
    """Whether a JSON-like value contains the string anywhere (as a whole value)."""
    if isinstance(value, str):
        return value == needle
    if isinstance(value, dict):
        return any(_mentions(item, needle) for item in cast("dict[str, object]", value).values())
    if isinstance(value, list):
        return any(_mentions(item, needle) for item in cast("list[object]", value))
    return False


# --- row access ------------------------------------------------------------------------------


def _get_row(conn: sqlite3.Connection, table: _Table, label: str, entity_id: str) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(
        f"SELECT * FROM {table} WHERE id = ?", (entity_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"{label} '{entity_id}' not found.")
    return row


def _season_from_row(row: sqlite3.Row) -> Season:
    return Season(
        id=row["id"],
        name=row["name"],
        color=row["color"],
        icon=row["icon"],
        start=row["start"],
        end=row["end"],
        priority=row["priority"],
        collection_id=row["collection_id"],
        builtin=bool(row["builtin"]),
    )


def _clip_ids_by_collection(conn: sqlite3.Connection) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for row in conn.execute("SELECT id, collection_id FROM clips"):
        grouped.setdefault(row["collection_id"], set()).add(row["id"])
    return grouped


def _collection_from_row(row: sqlite3.Row, members: set[str]) -> Collection:
    """Build a Collection; the stored order only keeps ids of clips still in the collection."""
    stored: list[str] = json.loads(row["ord"])
    return Collection(
        id=row["id"],
        name=row["name"],
        color=row["color"],
        icon=row["icon"],
        playback_mode=row["playback_mode"],
        order=[clip_id for clip_id in stored if clip_id in members],
        processing_profile_id=row["processing_profile_id"],
        enabled=bool(row["enabled"]),
        sort_order=row["sort_order"],
    )


def _list_collections(conn: sqlite3.Connection) -> list[Collection]:
    members = _clip_ids_by_collection(conn)
    rows = conn.execute(f"SELECT * FROM collections {_COLLECTION_ORDER}").fetchall()
    return [_collection_from_row(row, members.get(row["id"], set())) for row in rows]


def _get_collection(conn: sqlite3.Connection, collection_id: str) -> Collection:
    row = _get_row(conn, "collections", "Collection", collection_id)
    members = {
        r["id"]
        for r in conn.execute("SELECT id FROM clips WHERE collection_id = ?", (collection_id,))
    }
    return _collection_from_row(row, members)


def _normalization_from_row(row: sqlite3.Row) -> NormalizationProfile:
    return NormalizationProfile(
        id=row["id"],
        name=row["name"],
        target_lufs=row["target_lufs"],
        true_peak=row["true_peak"],
        lra=row["lra"],
    )


def _processing_from_row(row: sqlite3.Row) -> ProcessingProfileRecord:
    return ProcessingProfileRecord(
        id=row["id"], name=row["name"], settings=json.loads(row["settings"])
    )


def _asset_from_row(row: sqlite3.Row) -> Asset:
    return Asset(
        filename=row["filename"], size=row["size"], sha256=row["sha256"], status=row["status"]
    )


def _record_from_row(row: sqlite3.Row) -> RenderRecord:
    return RenderRecord.model_validate({column: row[column] for column in _RENDER_COLUMNS})


def _get_record(conn: sqlite3.Connection, render_id: str) -> RenderRecord:
    return _record_from_row(_get_row(conn, "renders", "Render", render_id))


def _clip_from_row(row: sqlite3.Row, published: dict[str, RenderRecord]) -> Clip:
    original: str | None = row["original"]
    record = published.get(row["published_render_id"] or "")
    return Clip(
        id=row["id"],
        collection_id=row["collection_id"],
        title=row["title"],
        source_name=row["source_name"],
        enabled=bool(row["enabled"]),
        notes=row["notes"],
        original=OriginalInfo.model_validate_json(original) if original else None,
        recipe=Recipe.model_validate_json(row["recipe"]),
        render=record.to_render() if record is not None else None,
        render_pending=bool(row["render_pending"]),
        status=row["status"],
        error=row["error"],
        needs_source=bool(row["needs_source"]),
        sort_key=row["sort_key"],
        selection_count=row["selection_count"],
        last_selected_at=row["last_selected_at"],
        has_preview=bool(row["has_preview"]),
        has_thumbs=bool(row["has_thumbs"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _published_records(conn: sqlite3.Connection) -> dict[str, RenderRecord]:
    rows = conn.execute("SELECT * FROM renders WHERE state = 'published'").fetchall()
    return {row["id"]: _record_from_row(row) for row in rows}


def _get_clip(conn: sqlite3.Connection, clip_id: str) -> Clip:
    row = _get_row(conn, "clips", "Clip", clip_id)
    published: dict[str, RenderRecord] = {}
    if row["published_render_id"]:
        record = conn.execute(
            "SELECT * FROM renders WHERE id = ? AND state = 'published'",
            (row["published_render_id"],),
        ).fetchone()
        if record is not None:
            published[row["published_render_id"]] = _record_from_row(record)
    return _clip_from_row(row, published)


def _read_revision(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'catalog_revision'").fetchone()
    return int(row["value"]) if row else 0


def _increment_revision(conn: sqlite3.Connection) -> int:
    revision = _read_revision(conn) + 1
    conn.execute("UPDATE meta SET value = ? WHERE key = 'catalog_revision'", (str(revision),))
    return revision


# --- validation shared by several writes -----------------------------------------------------


def _check_collection(conn: sqlite3.Connection, collection_id: str) -> None:
    if conn.execute("SELECT 1 FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
        raise InvalidError(f"Collection '{collection_id}' does not exist.")


def _check_normalization_profile(conn: sqlite3.Connection, profile_id: str | None) -> None:
    if profile_id is None:
        return
    if (
        conn.execute("SELECT 1 FROM normalization_profiles WHERE id = ?", (profile_id,)).fetchone()
        is None
    ):
        raise InvalidError(f"Normalization profile '{profile_id}' does not exist.")


def _check_processing_profile(conn: sqlite3.Connection, profile_id: str) -> None:
    if (
        conn.execute("SELECT 1 FROM processing_profiles WHERE id = ?", (profile_id,)).fetchone()
        is None
    ):
        raise InvalidError(f"Processing profile '{profile_id}' does not exist.")


def _clips_using_normalization_profile(conn: sqlite3.Connection, profile_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM clips WHERE json_extract(recipe, '$.profile_id') = ? ORDER BY rowid",
        (profile_id,),
    ).fetchall()
    return [row["id"] for row in rows]


def _clips_using_processing_profile(conn: sqlite3.Connection, profile_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT clips.id FROM clips JOIN collections ON collections.id = clips.collection_id"
        " WHERE collections.processing_profile_id = ? ORDER BY clips.rowid",
        (profile_id,),
    ).fetchall()
    return [row["id"] for row in rows]


def _clip_changes(
    conn: sqlite3.Connection,
    clip: Clip,
    *,
    title: str | None = None,
    collection_id: str | None = None,
    enabled: bool | None = None,
    notes: str | None = None,
) -> bool:
    """Apply the given metadata (None means unchanged) after validating it.

    Return whether the catalog document changed; nothing is written when nothing changes.
    """
    new_title = _clean_text("title", title) if title is not None else clip.title
    new_collection = collection_id if collection_id is not None else clip.collection_id
    new_enabled = enabled if enabled is not None else clip.enabled
    new_notes = notes if notes is not None else clip.notes
    _check_collection(conn, new_collection)
    catalog_changed = (new_title, new_collection, new_enabled) != (
        clip.title,
        clip.collection_id,
        clip.enabled,
    )
    if not catalog_changed and new_notes == clip.notes:
        return False
    conn.execute(
        "UPDATE clips SET title = ?, collection_id = ?, enabled = ?, notes = ?, updated_at = ?"
        " WHERE id = ?",
        (new_title, new_collection, int(new_enabled), new_notes, utcnow_iso(), clip.id),
    )
    return catalog_changed


def _retire_published(conn: sqlite3.Connection, render_id: str | None, revision: int) -> None:
    if render_id is None:
        return
    conn.execute(
        "UPDATE renders SET state = 'retired', retired_at = ?, retired_revision = ?"
        " WHERE id = ? AND state = 'published'",
        (utcnow_iso(), revision, render_id),
    )


class _Transaction:
    """The connection of a write transaction plus whether it changes the catalog document."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.bump = False


class Repository:
    def __init__(
        self,
        db: Database,
        on_catalog_change: Callable[[int], None] | None = None,
        validate_settings: Callable[[dict[str, object]], dict[str, object]] = lambda s: s,
    ) -> None:
        self._db = db
        self._on_catalog_change = on_catalog_change
        self._validate_settings = validate_settings

    # --- plumbing ---------------------------------------------------------------------------

    @contextmanager
    def _read(self) -> Generator[sqlite3.Connection]:
        with self._db.lock:
            yield self._db.connection

    @contextmanager
    def _write(self) -> Generator[_Transaction]:
        """Run a write transaction; set ``tx.bump`` to bump the catalog revision on commit.

        The listener is notified after the commit, outside the transaction.
        """
        revision: int | None = None
        with self._db.transaction() as conn:
            tx = _Transaction(conn)
            yield tx
            if tx.bump:
                revision = _increment_revision(conn)
        if revision is not None and self._on_catalog_change is not None:
            try:
                self._on_catalog_change(revision)
            except Exception:
                _LOGGER.exception("Catalog change listener failed for revision %s", revision)

    def _checked_settings(self, settings: dict[str, object]) -> dict[str, object]:
        try:
            return self._validate_settings(settings)
        except ValueError as error:  # pydantic's ValidationError is a ValueError
            raise InvalidError(str(error)) from error

    # --- seasons ----------------------------------------------------------------------------

    def list_seasons(self) -> list[Season]:
        with self._read() as conn:
            rows = conn.execute(f"SELECT * FROM seasons {_SEASON_ORDER}").fetchall()
        return [_season_from_row(row) for row in rows]

    def get_season(self, season_id: str) -> Season:
        with self._read() as conn:
            return _season_from_row(_get_row(conn, "seasons", "Season", season_id))

    def create_season(self, data: SeasonCreate) -> Season:
        name = _clean_text("season name", data.name)
        season_id = _resolve_id(data.id, name)
        start = _validate_mmdd("start", data.start)
        end = _validate_mmdd("end", data.end)
        with self._write() as tx:
            conn = tx.conn
            if conn.execute("SELECT 1 FROM seasons WHERE id = ?", (season_id,)).fetchone():
                raise ConflictError(f"Season '{season_id}' already exists.")
            _check_collection(conn, data.collection_id)
            conn.execute(
                'INSERT INTO seasons (id, name, color, icon, start, "end", priority,'
                " collection_id, builtin) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    season_id,
                    name,
                    data.color,
                    data.icon,
                    start,
                    end,
                    data.priority,
                    data.collection_id,
                ),
            )
            tx.bump = True
            return _season_from_row(_get_row(conn, "seasons", "Season", season_id))

    def update_season(self, season_id: str, data: SeasonUpdate) -> Season:
        with self._write() as tx:
            conn = tx.conn
            current = _season_from_row(_get_row(conn, "seasons", "Season", season_id))
            name = _clean_text("season name", data.name) if data.name is not None else current.name
            color = data.color if data.color is not None else current.color
            icon = data.icon if data.icon is not None else current.icon
            priority = data.priority if data.priority is not None else current.priority
            start = data.start if "start" in data.model_fields_set else current.start
            end = data.end if "end" in data.model_fields_set else current.end
            collection_id = (
                data.collection_id if data.collection_id is not None else current.collection_id
            )
            _check_collection(conn, collection_id)
            if current.builtin:
                if (start, end, priority) != (current.start, current.end, current.priority):
                    raise InvalidError(
                        "The regular season only allows changing its name, color, icon and"
                        " collection."
                    )
            else:
                start = _validate_mmdd("start", start)
                end = _validate_mmdd("end", end)
            conn.execute(
                'UPDATE seasons SET name = ?, color = ?, icon = ?, start = ?, "end" = ?,'
                " priority = ?, collection_id = ? WHERE id = ?",
                (name, color, icon, start, end, priority, collection_id, season_id),
            )
            tx.bump = True
            return _season_from_row(_get_row(conn, "seasons", "Season", season_id))

    def delete_season(self, season_id: str) -> None:
        with self._write() as tx:
            season = _season_from_row(_get_row(tx.conn, "seasons", "Season", season_id))
            if season.builtin:
                raise InvalidError("The regular season cannot be deleted.")
            tx.conn.execute("DELETE FROM seasons WHERE id = ?", (season_id,))
            tx.bump = True

    # --- collections ------------------------------------------------------------------------

    def list_collections(self) -> list[Collection]:
        with self._read() as conn:
            return _list_collections(conn)

    def get_collection(self, collection_id: str) -> Collection:
        with self._read() as conn:
            return _get_collection(conn, collection_id)

    def collection_user_edited(self, collection_id: str) -> bool:
        """Whether a UI write ever touched the collection (the legacy import then leaves it)."""
        with self._read() as conn:
            row = _get_row(conn, "collections", "Collection", collection_id)
            return bool(row["user_edited"])

    def create_collection(self, data: CollectionCreate) -> Collection:
        name = _clean_text("collection name", data.name)
        collection_id = _resolve_id(data.id, name)
        with self._write() as tx:
            conn = tx.conn
            if conn.execute("SELECT 1 FROM collections WHERE id = ?", (collection_id,)).fetchone():
                raise ConflictError(f"Collection '{collection_id}' already exists.")
            _check_processing_profile(conn, data.processing_profile_id)
            sort_order: int = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM collections"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO collections (id, name, color, icon, playback_mode,"
                " processing_profile_id, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    collection_id,
                    name,
                    data.color,
                    data.icon,
                    data.playback_mode,
                    data.processing_profile_id,
                    sort_order,
                ),
            )
            tx.bump = True
            return _get_collection(conn, collection_id)

    def update_collection(
        self, collection_id: str, data: CollectionUpdate, *, user_edit: bool = True
    ) -> Collection:
        """Update a collection; UI writes keep ``user_edit`` so the legacy import skips it."""
        with self._write() as tx:
            conn = tx.conn
            current = _get_collection(conn, collection_id)
            name = (
                _clean_text("collection name", data.name) if data.name is not None else current.name
            )
            profile_id = (
                data.processing_profile_id
                if data.processing_profile_id is not None
                else current.processing_profile_id
            )
            _check_processing_profile(conn, profile_id)
            order = (
                current.order
                if data.order is None
                else self._filter_order(conn, collection_id, data.order)
            )
            conn.execute(
                "UPDATE collections SET name = ?, color = ?, icon = ?, playback_mode = ?,"
                " ord = ?, processing_profile_id = ?, enabled = ?, sort_order = ?,"
                " user_edited = MAX(user_edited, ?) WHERE id = ?",
                (
                    name,
                    data.color if data.color is not None else current.color,
                    data.icon if data.icon is not None else current.icon,
                    data.playback_mode if data.playback_mode is not None else current.playback_mode,
                    _dumps(order),
                    profile_id,
                    int(data.enabled if data.enabled is not None else current.enabled),
                    data.sort_order if data.sort_order is not None else current.sort_order,
                    int(user_edit),
                    collection_id,
                ),
            )
            tx.bump = True
            return _get_collection(conn, collection_id)

    def set_collection_order(
        self, collection_id: str, clip_ids: list[str], *, user_edit: bool = True
    ) -> Collection:
        """Store the custom playback order, dropping ids that are not clips of the collection."""
        with self._write() as tx:
            conn = tx.conn
            _get_row(conn, "collections", "Collection", collection_id)
            order = self._filter_order(conn, collection_id, clip_ids)
            conn.execute(
                "UPDATE collections SET ord = ?, user_edited = MAX(user_edited, ?) WHERE id = ?",
                (_dumps(order), int(user_edit), collection_id),
            )
            tx.bump = True
            return _get_collection(conn, collection_id)

    @staticmethod
    def _filter_order(
        conn: sqlite3.Connection, collection_id: str, clip_ids: list[str]
    ) -> list[str]:
        members = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM clips WHERE collection_id = ?", (collection_id,)
            )
        }
        return [clip_id for clip_id in _dedupe(clip_ids) if clip_id in members]

    def delete_collection(self, collection_id: str) -> None:
        with self._write() as tx:
            conn = tx.conn
            _get_row(conn, "collections", "Collection", collection_id)
            if collection_id == "regular":
                raise InvalidError("The regular collection cannot be deleted.")
            clips: int = conn.execute(
                "SELECT COUNT(*) FROM clips WHERE collection_id = ?", (collection_id,)
            ).fetchone()[0]
            if clips:
                raise ConflictError(f"Collection '{collection_id}' still has {clips} clip(s).")
            seasons: int = conn.execute(
                "SELECT COUNT(*) FROM seasons WHERE collection_id = ?", (collection_id,)
            ).fetchone()[0]
            if seasons:
                raise ConflictError(f"Collection '{collection_id}' is used by {seasons} season(s).")
            conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
            tx.bump = True

    # --- normalization profiles -------------------------------------------------------------

    def list_normalization_profiles(self) -> list[NormalizationProfile]:
        with self._read() as conn:
            rows = conn.execute("SELECT * FROM normalization_profiles ORDER BY rowid").fetchall()
        return [_normalization_from_row(row) for row in rows]

    def get_normalization_profile(self, profile_id: str) -> NormalizationProfile:
        with self._read() as conn:
            return _normalization_from_row(
                _get_row(conn, "normalization_profiles", "Normalization profile", profile_id)
            )

    def create_normalization_profile(
        self, data: NormalizationProfileCreate
    ) -> NormalizationProfile:
        name = _clean_text("profile name", data.name)
        profile_id = _resolve_id(data.id, name)
        with self._write() as tx:
            conn = tx.conn
            if conn.execute(
                "SELECT 1 FROM normalization_profiles WHERE id = ?", (profile_id,)
            ).fetchone():
                raise ConflictError(f"Normalization profile '{profile_id}' already exists.")
            conn.execute(
                "INSERT INTO normalization_profiles (id, name, target_lufs, true_peak, lra)"
                " VALUES (?, ?, ?, ?, ?)",
                (profile_id, name, data.target_lufs, data.true_peak, data.lra),
            )
            return _normalization_from_row(
                _get_row(conn, "normalization_profiles", "Normalization profile", profile_id)
            )

    def update_normalization_profile(
        self, profile_id: str, data: NormalizationProfileUpdate
    ) -> NormalizationProfile:
        with self._write() as tx:
            conn = tx.conn
            current = _normalization_from_row(
                _get_row(conn, "normalization_profiles", "Normalization profile", profile_id)
            )
            conn.execute(
                "UPDATE normalization_profiles SET name = ?, target_lufs = ?, true_peak = ?,"
                " lra = ? WHERE id = ?",
                (
                    _clean_text("profile name", data.name)
                    if data.name is not None
                    else current.name,
                    data.target_lufs if data.target_lufs is not None else current.target_lufs,
                    data.true_peak if data.true_peak is not None else current.true_peak,
                    data.lra if data.lra is not None else current.lra,
                    profile_id,
                ),
            )
            return _normalization_from_row(
                _get_row(conn, "normalization_profiles", "Normalization profile", profile_id)
            )

    def delete_normalization_profile(self, profile_id: str) -> None:
        with self._write() as tx:
            conn = tx.conn
            _get_row(conn, "normalization_profiles", "Normalization profile", profile_id)
            if _clips_using_normalization_profile(conn, profile_id):
                raise ConflictError(
                    f"Normalization profile '{profile_id}' is used by a clip recipe."
                )
            conn.execute("DELETE FROM normalization_profiles WHERE id = ?", (profile_id,))

    def clips_using_normalization_profile(self, profile_id: str) -> list[str]:
        """Clips whose recipe overrides the loudness target with this profile."""
        with self._read() as conn:
            return _clips_using_normalization_profile(conn, profile_id)

    # --- processing profiles ----------------------------------------------------------------

    def list_processing_profiles(self) -> list[ProcessingProfileRecord]:
        with self._read() as conn:
            rows = conn.execute("SELECT * FROM processing_profiles ORDER BY rowid").fetchall()
        return [_processing_from_row(row) for row in rows]

    def get_processing_profile(self, profile_id: str) -> ProcessingProfileRecord:
        with self._read() as conn:
            return _processing_from_row(
                _get_row(conn, "processing_profiles", "Processing profile", profile_id)
            )

    def create_processing_profile(self, data: ProcessingProfileCreate) -> ProcessingProfileRecord:
        name = _clean_text("profile name", data.name)
        profile_id = _resolve_id(data.id, name)
        settings = self._checked_settings(data.settings)
        with self._write() as tx:
            conn = tx.conn
            if conn.execute(
                "SELECT 1 FROM processing_profiles WHERE id = ?", (profile_id,)
            ).fetchone():
                raise ConflictError(f"Processing profile '{profile_id}' already exists.")
            conn.execute(
                "INSERT INTO processing_profiles (id, name, settings) VALUES (?, ?, ?)",
                (profile_id, name, _dumps(settings)),
            )
            return _processing_from_row(
                _get_row(conn, "processing_profiles", "Processing profile", profile_id)
            )

    def update_processing_profile(
        self, profile_id: str, data: ProcessingProfileUpdate
    ) -> ProcessingProfileRecord:
        settings = self._checked_settings(data.settings) if data.settings is not None else None
        with self._write() as tx:
            conn = tx.conn
            current = _processing_from_row(
                _get_row(conn, "processing_profiles", "Processing profile", profile_id)
            )
            conn.execute(
                "UPDATE processing_profiles SET name = ?, settings = ? WHERE id = ?",
                (
                    _clean_text("profile name", data.name)
                    if data.name is not None
                    else current.name,
                    _dumps(settings if settings is not None else current.settings),
                    profile_id,
                ),
            )
            return _processing_from_row(
                _get_row(conn, "processing_profiles", "Processing profile", profile_id)
            )

    def delete_processing_profile(self, profile_id: str) -> None:
        with self._write() as tx:
            conn = tx.conn
            _get_row(conn, "processing_profiles", "Processing profile", profile_id)
            if conn.execute(
                "SELECT 1 FROM collections WHERE processing_profile_id = ?", (profile_id,)
            ).fetchone():
                raise ConflictError(f"Processing profile '{profile_id}' is used by a collection.")
            conn.execute("DELETE FROM processing_profiles WHERE id = ?", (profile_id,))

    def clips_using_processing_profile(self, profile_id: str) -> list[str]:
        """Clips that belong to a collection rendered with this profile."""
        with self._read() as conn:
            return _clips_using_processing_profile(conn, profile_id)

    # --- assets -----------------------------------------------------------------------------

    def list_assets(self) -> list[Asset]:
        with self._read() as conn:
            rows = conn.execute("SELECT * FROM assets ORDER BY filename").fetchall()
        return [_asset_from_row(row) for row in rows]

    def get_asset(self, filename: str) -> Asset:
        with self._read() as conn:
            return _asset_from_row(self._asset_row(conn, filename))

    @staticmethod
    def _asset_row(conn: sqlite3.Connection, filename: str) -> sqlite3.Row:
        row: sqlite3.Row | None = conn.execute(
            "SELECT * FROM assets WHERE filename = ?", (filename,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Asset '{filename}' not found.")
        return row

    def create_asset(self, asset: Asset) -> Asset:
        name = asset.filename
        if not name or name != name.replace("\\", "/").rsplit("/", 1)[-1] or name.startswith("."):
            raise InvalidError(f"Invalid asset filename '{name}'.")
        with self._write() as tx:
            if tx.conn.execute("SELECT 1 FROM assets WHERE filename = ?", (name,)).fetchone():
                raise ConflictError(f"Asset '{name}' already exists.")
            tx.conn.execute(
                "INSERT INTO assets (filename, size, sha256, status) VALUES (?, ?, ?, ?)",
                (name, asset.size, asset.sha256, asset.status),
            )
            return _asset_from_row(self._asset_row(tx.conn, name))

    def update_asset(self, filename: str, data: AssetUpdate) -> Asset:
        with self._write() as tx:
            current = _asset_from_row(self._asset_row(tx.conn, filename))
            tx.conn.execute(
                "UPDATE assets SET size = ?, sha256 = ?, status = ? WHERE filename = ?",
                (
                    data.size if "size" in data.model_fields_set else current.size,
                    data.sha256 if "sha256" in data.model_fields_set else current.sha256,
                    data.status if data.status is not None else current.status,
                    filename,
                ),
            )
            return _asset_from_row(self._asset_row(tx.conn, filename))

    def delete_asset(self, filename: str) -> None:
        with self._write() as tx:
            self._asset_row(tx.conn, filename)
            for profile in tx.conn.execute("SELECT id, settings FROM processing_profiles"):
                if _mentions(json.loads(profile["settings"]), filename):
                    raise ConflictError(
                        f"Asset '{filename}' is referenced by processing profile '{profile['id']}'."
                    )
            tx.conn.execute("DELETE FROM assets WHERE filename = ?", (filename,))

    # --- clips ------------------------------------------------------------------------------

    def list_clips(self) -> list[Clip]:
        with self._read() as conn:
            published = _published_records(conn)
            rows = conn.execute("SELECT * FROM clips ORDER BY rowid").fetchall()
            return [_clip_from_row(row, published) for row in rows]

    def get_clip(self, clip_id: str) -> Clip:
        with self._read() as conn:
            return _get_clip(conn, clip_id)

    def create_clip(
        self,
        *,
        clip_id: str | None,
        collection_id: str,
        title: str,
        source_name: str,
        recipe: Recipe,
        original: OriginalInfo | None,
        sort_key: str,
        needs_source: bool = False,
        status: ClipStatus = "processing",
    ) -> Clip:
        clean_title = _clean_text("title", title)
        new_id = clip_id if clip_id is not None else str(uuid.uuid4())
        if not _CLIP_ID.fullmatch(new_id):
            raise InvalidError(f"Invalid id '{new_id}': use letters, digits, '_' or '-'.")
        if original is not None:
            recipe.validate_for(original)
        now = utcnow_iso()
        with self._write() as tx:
            conn = tx.conn
            if conn.execute("SELECT 1 FROM clips WHERE id = ?", (new_id,)).fetchone():
                raise ConflictError(f"Clip '{new_id}' already exists.")
            _check_collection(conn, collection_id)
            _check_normalization_profile(conn, recipe.profile_id)
            conn.execute(
                "INSERT INTO clips (id, collection_id, title, source_name, original, recipe,"
                " status, needs_source, sort_key, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id,
                    collection_id,
                    clean_title,
                    source_name,
                    original.model_dump_json() if original else None,
                    recipe.model_dump_json(),
                    status,
                    int(needs_source),
                    sort_key,
                    now,
                    now,
                ),
            )
            return _get_clip(conn, new_id)

    def update_clip(self, clip_id: str, data: ClipUpdate) -> Clip:
        with self._write() as tx:
            clip = _get_clip(tx.conn, clip_id)
            tx.bump = _clip_changes(
                tx.conn,
                clip,
                title=data.title,
                collection_id=data.collection_id,
                enabled=data.enabled,
                notes=data.notes,
            )
            return _get_clip(tx.conn, clip_id)

    def set_recipe(self, clip_id: str, recipe: Recipe) -> Clip:
        """Store a new recipe; the clip needs a new render, which the catalog advertises."""
        with self._write() as tx:
            conn = tx.conn
            clip = _get_clip(conn, clip_id)
            if clip.original is not None:
                recipe.validate_for(clip.original)
            _check_normalization_profile(conn, recipe.profile_id)
            conn.execute(
                "UPDATE clips SET recipe = ?, render_pending = 1, updated_at = ? WHERE id = ?",
                (recipe.model_dump_json(), utcnow_iso(), clip_id),
            )
            tx.bump = True
            return _get_clip(conn, clip_id)

    def set_original(self, clip_id: str, original: OriginalInfo) -> Clip:
        with self._write() as tx:
            _get_row(tx.conn, "clips", "Clip", clip_id)
            tx.conn.execute(
                "UPDATE clips SET original = ?, updated_at = ? WHERE id = ?",
                (original.model_dump_json(), utcnow_iso(), clip_id),
            )
            return _get_clip(tx.conn, clip_id)

    def set_status(self, clip_id: str, status: ClipStatus, error: str | None = None) -> Clip:
        with self._write() as tx:
            _get_row(tx.conn, "clips", "Clip", clip_id)
            tx.conn.execute(
                "UPDATE clips SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, utcnow_iso(), clip_id),
            )
            return _get_clip(tx.conn, clip_id)

    def set_flags(
        self,
        clip_id: str,
        *,
        has_preview: bool | None = None,
        has_thumbs: bool | None = None,
        render_pending: bool | None = None,
        needs_source: bool | None = None,
    ) -> None:
        """Set the given flags; only a change of ``render_pending`` reaches the catalog."""
        with self._write() as tx:
            row = _get_row(tx.conn, "clips", "Clip", clip_id)
            updates = {
                "has_preview": has_preview,
                "has_thumbs": has_thumbs,
                "render_pending": render_pending,
                "needs_source": needs_source,
            }
            for column, value in updates.items():
                if value is not None and bool(row[column]) != value:
                    tx.conn.execute(
                        f"UPDATE clips SET {column} = ? WHERE id = ?", (int(value), clip_id)
                    )
            tx.bump = render_pending is not None and bool(row["render_pending"]) != render_pending

    def delete_clip(self, clip_id: str) -> None:
        """Remove the clip and retire its published render (files are left to the GC)."""
        with self._write() as tx:
            conn = tx.conn
            row = _get_row(conn, "clips", "Clip", clip_id)
            _retire_published(conn, row["published_render_id"], _read_revision(conn) + 1)
            conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
            tx.bump = True

    def bulk_update(self, ids: list[str], data: BulkSet) -> int:
        """Apply collection/enabled changes to many clips; returns how many clips matched.

        Unknown ids are skipped. The batch is validated and applied atomically, and nothing is
        bumped when no clip would actually change. ``data.profile_id`` is handled by the API
        layer (it rewrites recipes).
        """
        with self._write() as tx:
            matched = 0
            for clip_id in _dedupe(ids):
                row = tx.conn.execute("SELECT id FROM clips WHERE id = ?", (clip_id,)).fetchone()
                if row is None:
                    continue
                matched += 1
                changed = _clip_changes(
                    tx.conn,
                    _get_clip(tx.conn, clip_id),
                    collection_id=data.collection_id,
                    enabled=data.enabled,
                )
                tx.bump = tx.bump or changed
            return matched

    def record_selections(self, events: list[SelectionEvent]) -> None:
        """Count selections reported by the integration; events for deleted clips are dropped."""
        if not events:
            return
        with self._write() as tx:
            tx.conn.executemany(
                "UPDATE clips SET selection_count = selection_count + 1,"
                " last_selected_at = CASE WHEN last_selected_at IS NULL OR last_selected_at < ?"
                " THEN ? ELSE last_selected_at END WHERE id = ?",
                [(event.selected_at, event.selected_at, event.clip_id) for event in events],
            )

    # --- renders ----------------------------------------------------------------------------

    def next_render_n(self, clip_id: str) -> int:
        """The next render number for the clip; deleted and unrecognized rows still count."""
        with self._read() as conn:
            return _next_render_n(conn, clip_id)

    def publish_render(self, render: RenderRecord, *, clear_pending: bool = True) -> Clip:
        """Publish a render atomically.

        Insert it, point the clip at it, retire the previous published render (stamped with the
        new catalog revision), mark the clip ready and bump the revision. ``clear_pending=False``
        keeps ``render_pending`` as it is (the render was made from inputs that are no longer
        current). The timing is rounded and checked first; nothing changes when it violates an
        invariant.
        """
        timing = validate_timing(
            Timing(
                duration=render.duration,
                content_start=render.content_start,
                content_end=render.content_end,
                lead_in=render.lead_in,
                tail_out=render.tail_out,
                content_duration=render.content_duration,
            )
        )
        now = utcnow_iso()
        record = render.model_copy(
            update={
                **timing.as_dict(),
                "state": "published",
                "published_at": render.published_at or now,
                "retired_at": None,
                "retired_revision": None,
            }
        )
        with self._write() as tx:
            conn = tx.conn
            clip_row = _get_row(conn, "clips", "Clip", record.clip_id)
            try:
                _insert_render(conn, record)
            except sqlite3.IntegrityError as error:
                raise ConflictError(f"Render '{record.id}' cannot be recorded: {error}") from error
            previous: str | None = clip_row["published_render_id"]
            if previous != record.id:
                _retire_published(conn, previous, _read_revision(conn) + 1)
            conn.execute(
                "UPDATE clips SET published_render_id = ?, status = 'ready', error = NULL,"
                " render_pending = CASE WHEN ? THEN 0 ELSE render_pending END, updated_at = ?"
                " WHERE id = ?",
                (record.id, int(clear_pending), now, record.clip_id),
            )
            tx.bump = True
            return _get_clip(conn, record.clip_id)

    def list_renders(self, *, states: set[RenderState] | None = None) -> list[RenderRecord]:
        with self._read() as conn:
            rows = conn.execute("SELECT * FROM renders ORDER BY clip_id, n, rowid").fetchall()
        records = [_record_from_row(row) for row in rows]
        return [r for r in records if states is None or r.state in states]

    def get_render(self, render_id: str) -> RenderRecord:
        with self._read() as conn:
            return _get_record(conn, render_id)

    def add_unrecognized_render(
        self, *, render_id: str, clip_id: str, relative_path: str, size: int, mtime_iso: str
    ) -> None:
        """Record a render file found on disk that the database does not know.

        It has no timing or checksum and is never published; ``mtime_iso`` is kept as its
        creation time so the GC can age it.
        """
        with self._write() as tx:
            record = RenderRecord(
                id=render_id,
                clip_id=clip_id,
                n=_next_render_n(tx.conn, clip_id),
                relative_path=relative_path,
                size=size,
                sha256="",
                duration=0.0,
                content_start=0.0,
                content_end=0.0,
                lead_in=0.0,
                tail_out=0.0,
                content_duration=0.0,
                timing_source="measured",
                integrated_lufs=None,
                true_peak=None,
                recipe_hash="",
                profile_fingerprint="",
                state="unrecognized",
                created_at=mtime_iso,
            )
            try:
                _insert_render(tx.conn, record)
            except sqlite3.IntegrityError as error:
                raise ConflictError(f"Render '{render_id}' cannot be recorded: {error}") from error

    def mark_render(self, render_id: str, state: RenderState) -> None:
        """Change a render's lifecycle state.

        The catalog revision is bumped only when the render enters or leaves ``published``.
        After a published render turns ``missing``, call :meth:`fallback_after_missing`.
        """
        with self._write() as tx:
            conn = tx.conn
            current = _get_record(conn, render_id)
            if current.state == state:
                return
            retired_at = current.retired_at
            if state == "retired" and retired_at is None:
                retired_at = utcnow_iso()
            conn.execute(
                "UPDATE renders SET state = ?, retired_at = ? WHERE id = ?",
                (state, retired_at, render_id),
            )
            tx.bump = "published" in (current.state, state)

    def fallback_after_missing(self, clip_id: str, exists: Callable[[str], bool]) -> Clip:
        """Repair a clip whose published render file went missing.

        Publish again the newest earlier render that is ``published`` or ``retired`` and whose
        file ``exists(relative_path)``; with none, mark the clip failed. A clip whose current
        render is healthy is returned unchanged.
        """
        with self._write() as tx:
            conn = tx.conn
            row = _get_row(conn, "clips", "Clip", clip_id)
            current_id: str | None = row["published_render_id"]
            if current_id is None:
                return _get_clip(conn, clip_id)
            current = _get_record(conn, current_id)
            if current.state == "published":
                return _get_clip(conn, clip_id)
            candidates = conn.execute(
                "SELECT * FROM renders WHERE clip_id = ? AND n < ?"
                " AND state IN ('published', 'retired') ORDER BY n DESC",
                (clip_id, current.n),
            ).fetchall()
            for candidate in candidates:
                if not exists(candidate["relative_path"]):
                    continue
                conn.execute(
                    "UPDATE renders SET state = 'published', retired_at = NULL,"
                    " retired_revision = NULL WHERE id = ?",
                    (candidate["id"],),
                )
                conn.execute(
                    "UPDATE clips SET published_render_id = ?, status = 'ready', error = NULL,"
                    " updated_at = ? WHERE id = ?",
                    (candidate["id"], utcnow_iso(), clip_id),
                )
                tx.bump = True
                return _get_clip(conn, clip_id)
            conn.execute(
                "UPDATE clips SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                (
                    "The published render file is missing and no earlier render is available.",
                    utcnow_iso(),
                    clip_id,
                ),
            )
            return _get_clip(conn, clip_id)

    # --- consumers seen via HTTP ------------------------------------------------------------

    def touch_consumer(self, consumer_id: str, held_revision: int | None) -> None:
        with self._write() as tx:
            tx.conn.execute(
                "INSERT INTO consumers_seen (consumer_id, last_seen_at, held_revision)"
                " VALUES (?, ?, ?) ON CONFLICT(consumer_id) DO UPDATE SET"
                " last_seen_at = excluded.last_seen_at,"
                " held_revision = COALESCE(excluded.held_revision, held_revision)",
                (consumer_id, utcnow_iso(), held_revision),
            )

    def list_consumers_seen(self, since_days: int = 30) -> list[tuple[str, str]]:
        cutoff = (datetime.now(UTC) - timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._read() as conn:
            rows = conn.execute(
                "SELECT consumer_id, last_seen_at FROM consumers_seen WHERE last_seen_at >= ?"
                " ORDER BY consumer_id",
                (cutoff,),
            ).fetchall()
        return [(row["consumer_id"], row["last_seen_at"]) for row in rows]

    # --- settings and catalog ---------------------------------------------------------------

    def get_settings(self) -> Settings:
        with self._read() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        stored = {row["key"]: json.loads(row["value"]) for row in rows}
        return Settings.model_validate(
            {k: v for k, v in stored.items() if k in Settings.model_fields}
        )

    def update_settings(self, data: Settings) -> Settings:
        with self._write() as tx:
            tx.conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(key, _dumps(value)) for key, value in data.model_dump(mode="json").items()],
            )
        return self.get_settings()

    def catalog_revision(self) -> int:
        with self._read() as conn:
            return _read_revision(conn)

    def catalog_document(self, instance_id: str) -> dict[str, object]:
        """The catalog served to the integration: clips with a published render, no internals."""
        with self._read() as conn:
            revision = _read_revision(conn)
            seasons = [
                _season_from_row(row)
                for row in conn.execute(f"SELECT * FROM seasons {_SEASON_ORDER}").fetchall()
            ]
            collections = _list_collections(conn)
            published = _published_records(conn)
            clip_rows = conn.execute(
                "SELECT * FROM clips WHERE published_render_id IS NOT NULL ORDER BY rowid"
            ).fetchall()
            clips = [
                _clip_from_row(row, published)
                for row in clip_rows
                if row["published_render_id"] in published
            ]
        in_catalog = {clip.id for clip in clips}
        return {
            "contract_version": 1,
            "revision": revision,
            "instance_id": instance_id,
            "generated_at": utcnow_iso(),
            "seasons": [season.model_dump(exclude={"builtin"}) for season in seasons],
            "collections": [
                {
                    **collection.model_dump(exclude={"sort_order", "processing_profile_id"}),
                    "order": [c for c in collection.order if c in in_catalog],
                }
                for collection in collections
            ],
            "clips": [
                {
                    "id": clip.id,
                    "collection_id": clip.collection_id,
                    "title": clip.title,
                    "source_name": clip.source_name,
                    "enabled": clip.enabled,
                    "sort_key": clip.sort_key,
                    "render_pending": clip.render_pending,
                    "render": clip.render.model_dump() if clip.render else None,
                }
                for clip in clips
            ],
        }

    # --- legacy import runs -----------------------------------------------------------------

    def save_legacy_report(self, report: LegacyReport) -> None:
        with self._write() as tx:
            tx.conn.execute(
                "INSERT OR REPLACE INTO legacy_reports (run_id, report, created_at)"
                " VALUES (?, ?, ?)",
                (report.run_id, report.model_dump_json(), utcnow_iso()),
            )

    def last_legacy_report(self) -> LegacyReport | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT report FROM legacy_reports ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        return LegacyReport.model_validate_json(row["report"]) if row else None


def _next_render_n(conn: sqlite3.Connection, clip_id: str) -> int:
    value: int = conn.execute(
        "SELECT COALESCE(MAX(n), 0) + 1 FROM renders WHERE clip_id = ?", (clip_id,)
    ).fetchone()[0]
    return value


def _insert_render(conn: sqlite3.Connection, record: RenderRecord) -> None:
    values = record.model_dump(include=set(_RENDER_COLUMNS))
    columns = ", ".join(_RENDER_COLUMNS)
    placeholders = ", ".join(f":{column}" for column in _RENDER_COLUMNS)
    conn.execute(f"INSERT INTO renders ({columns}) VALUES ({placeholders})", values)
