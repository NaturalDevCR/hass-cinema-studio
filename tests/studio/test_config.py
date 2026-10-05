from __future__ import annotations

from pathlib import Path

import pytest

from cinema_studio.config import Paths, load_options

pytestmark = pytest.mark.studio


def test_paths_layout(paths: Paths) -> None:
    root = paths.media_dir / "cinema-studio"
    assert paths.root == root
    assert paths.originals_dir == root / "originals"
    assert paths.renders_dir == root / "renders"
    assert paths.assets_dir == root / "assets"
    assert paths.consumers_dir == root / "consumers"
    assert paths.work_dir == root / ".work"
    assert paths.gc_lock_path == root / ".gc.lock"
    assert paths.thumbs_dir == paths.data_dir / "thumbs"
    assert paths.uploads_dir == paths.data_dir / "uploads"
    assert paths.database_path == paths.data_dir / "studio.db"


def test_from_env_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CINEMA_STUDIO_DATA", "CINEMA_STUDIO_MEDIA", "CINEMA_STUDIO_DEV"):
        monkeypatch.delenv(name, raising=False)
    defaults = Paths.from_env()
    assert (defaults.data_dir, defaults.media_dir, defaults.dev_mode) == (
        Path("/data"),
        Path("/media"),
        False,
    )
    monkeypatch.setenv("CINEMA_STUDIO_DATA", "/tmp/d")
    monkeypatch.setenv("CINEMA_STUDIO_MEDIA", "/tmp/m")
    monkeypatch.setenv("CINEMA_STUDIO_DEV", "1")
    overridden = Paths.from_env()
    assert (overridden.data_dir, overridden.media_dir, overridden.dev_mode) == (
        Path("/tmp/d"),
        Path("/tmp/m"),
        True,
    )


def test_load_options(tmp_path: Path) -> None:
    good = tmp_path / "options.json"
    good.write_text('{"log_level": "debug"}', encoding="utf-8")
    assert load_options(good) == {"log_level": "debug"}
    assert load_options(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2", encoding="utf-8")
    assert load_options(bad) == {}
    listy = tmp_path / "list.json"
    listy.write_text("[1]", encoding="utf-8")
    assert load_options(listy) == {}
