"""SQLite connection, schema and first-run seeds."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from .models import DEFAULT_PROCESSING_PROFILE_ID, Settings

SCHEMA_VERSION = 1

_SCHEMA = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE collections (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL, icon TEXT NOT NULL,
        playback_mode TEXT NOT NULL, ord TEXT NOT NULL DEFAULT '[]',
        processing_profile_id TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0, user_edited INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE seasons (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL, icon TEXT NOT NULL,
        start TEXT, "end" TEXT, priority INTEGER NOT NULL DEFAULT 0,
        collection_id TEXT NOT NULL REFERENCES collections(id),
        builtin INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE normalization_profiles (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, target_lufs REAL NOT NULL,
        true_peak REAL NOT NULL, lra REAL NOT NULL)""",
    "CREATE TABLE processing_profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
    " settings TEXT NOT NULL)",
    "CREATE TABLE assets (filename TEXT PRIMARY KEY, size INTEGER, sha256 TEXT,"
    " status TEXT NOT NULL)",
    """CREATE TABLE clips (
        id TEXT PRIMARY KEY, collection_id TEXT NOT NULL REFERENCES collections(id),
        title TEXT NOT NULL, source_name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
        notes TEXT NOT NULL DEFAULT '', original TEXT, recipe TEXT NOT NULL,
        published_render_id TEXT, render_pending INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL, error TEXT, needs_source INTEGER NOT NULL DEFAULT 0,
        sort_key TEXT NOT NULL, selection_count INTEGER NOT NULL DEFAULT 0,
        last_selected_at TEXT, has_preview INTEGER NOT NULL DEFAULT 0,
        has_thumbs INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""",
    """CREATE TABLE renders (
        id TEXT PRIMARY KEY, clip_id TEXT NOT NULL, n INTEGER NOT NULL,
        relative_path TEXT NOT NULL UNIQUE, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
        duration REAL NOT NULL, content_start REAL NOT NULL, content_end REAL NOT NULL,
        lead_in REAL NOT NULL, tail_out REAL NOT NULL, content_duration REAL NOT NULL,
        timing_source TEXT NOT NULL, integrated_lufs REAL, true_peak REAL,
        recipe_hash TEXT NOT NULL, profile_fingerprint TEXT NOT NULL, state TEXT NOT NULL,
        published_at TEXT, retired_at TEXT, retired_revision INTEGER,
        created_at TEXT NOT NULL)""",
    "CREATE INDEX renders_clip ON renders(clip_id, n)",
    """CREATE TABLE consumers_seen (
        consumer_id TEXT PRIMARY KEY, last_seen_at TEXT NOT NULL, held_revision INTEGER)""",
    """CREATE TABLE legacy_reports (
        run_id TEXT PRIMARY KEY, report TEXT NOT NULL, created_at TEXT NOT NULL)""",
)

_SEED_NORMALIZATION_PROFILES = (
    ("standard", "Standard", -16.0, -1.5, 11.0),
    ("loud", "Loud", -13.0, -1.0, 11.0),
    ("soft", "Soft", -20.0, -1.5, 11.0),
    ("voice", "Voice / announcement", -18.0, -1.5, 7.0),
)


class Database:
    """One shared SQLite connection, serialized by a re-entrant lock.

    The connection is created with ``check_same_thread=False`` and every access must hold
    :attr:`lock`, so it is safe to use from the event loop and from worker threads alike.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        # Autocommit mode: transactions are explicit (see ``transaction``).
        self.connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        try:
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA journal_mode = WAL")
            self.connection.execute("PRAGMA foreign_keys = ON")
            self._initialise()
        except BaseException:
            self.connection.close()
            raise

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        """Hold the lock and run the block in one write transaction (rolled back on error)."""
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
                self.connection.execute("COMMIT")
            except BaseException:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise

    def close(self) -> None:
        with self.lock:
            self.connection.close()

    def _initialise(self) -> None:
        with self.transaction() as conn:
            version: int = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"The database schema version ({version}) is newer than this app supports"
                    f" ({SCHEMA_VERSION}); refusing to open it."
                )
            if version == 0:
                for statement in _SCHEMA:
                    conn.execute(statement)
                _seed(conn)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _seed(conn: sqlite3.Connection) -> None:
    # The processing profile's settings stay empty here; the app factory fills the defaults
    # through the profile validator once it is wired in.
    conn.execute(
        "INSERT INTO processing_profiles (id, name, settings)"
        " VALUES (?, 'Compatibility 4K Loudness', '{}')",
        (DEFAULT_PROCESSING_PROFILE_ID,),
    )
    conn.execute(
        "INSERT INTO collections (id, name, color, icon, playback_mode, ord,"
        " processing_profile_id, enabled, sort_order)"
        " VALUES ('regular', 'Regular', '#f59e0b', 'mdi:movie-open', 'random', '[]', ?, 1, 0)",
        (DEFAULT_PROCESSING_PROFILE_ID,),
    )
    conn.execute(
        'INSERT INTO seasons (id, name, color, icon, start, "end", priority, collection_id,'
        " builtin) VALUES ('regular', 'Regular', '#64748b', 'mdi:calendar-blank', NULL, NULL, 0,"
        " 'regular', 1)"
    )
    conn.executemany(
        "INSERT INTO normalization_profiles (id, name, target_lufs, true_peak, lra)"
        " VALUES (?, ?, ?, ?, ?)",
        _SEED_NORMALIZATION_PROFILES,
    )
    conn.execute("INSERT INTO meta (key, value) VALUES ('catalog_revision', '0')")
    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        [
            (key, json.dumps(value, separators=(",", ":")))
            for key, value in Settings().model_dump(mode="json").items()
        ],
    )
