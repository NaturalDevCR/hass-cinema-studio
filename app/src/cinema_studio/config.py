"""Filesystem layout and add-on options."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

DEFAULT_DATA_DIR = "/data"
DEFAULT_MEDIA_DIR = "/media"
_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Paths:
    """Where the Studio keeps its private data and its files under the shared media root."""

    data_dir: Path
    media_dir: Path
    static_dir: Path
    dev_mode: bool

    @property
    def root(self) -> Path:
        return self.media_dir / "cinema-studio"

    @property
    def originals_dir(self) -> Path:
        return self.root / "originals"

    @property
    def renders_dir(self) -> Path:
        return self.root / "renders"

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    @property
    def consumers_dir(self) -> Path:
        return self.root / "consumers"

    @property
    def work_dir(self) -> Path:
        return self.root / ".work"

    @property
    def gc_lock_path(self) -> Path:
        return self.root / ".gc.lock"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "studio.db"

    @classmethod
    def from_env(cls) -> Paths:
        """Build the paths from the container defaults and the CINEMA_STUDIO_* overrides."""
        return cls(
            data_dir=Path(os.environ.get("CINEMA_STUDIO_DATA", DEFAULT_DATA_DIR)),
            media_dir=Path(os.environ.get("CINEMA_STUDIO_MEDIA", DEFAULT_MEDIA_DIR)),
            static_dir=Path(__file__).resolve().parent / "static" / "ui",
            dev_mode=os.environ.get("CINEMA_STUDIO_DEV", "").strip().lower() in _TRUTHY,
        )


def load_options(path: Path) -> dict[str, object]:
    """Read the Supervisor options file; a missing or malformed file yields no options."""
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    options: dict[str, object] = {}
    if isinstance(loaded, dict):
        for key, value in cast("dict[object, object]", loaded).items():
            options[str(key)] = value
    return options
