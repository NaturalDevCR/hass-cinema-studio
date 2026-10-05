"""Supervisor App packaging metadata and assets."""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"


def test_dockerfile_uses_local_context_and_pinned_runtime() -> None:
    dockerfile = (APP / "Dockerfile").read_text()
    assert "ghcr.io/home-assistant/${BUILD_ARCH}-base-python:3.13-alpine3.22" in dockerfile
    assert "COPY src " in dockerfile
    assert "COPY rootfs /" in dockerfile
    for pin in (
        '"fastapi==0.115.14"',
        '"uvicorn[standard]==0.32.1"',
        '"httpx==0.28.1"',
        '"pydantic==2.11.7"',
        '"python-multipart==0.0.20"',
    ):
        assert pin in dockerfile
    assert "apk add --no-cache ffmpeg" in dockerfile
    assert "--no-cache-dir" in dockerfile
    assert "ui/package.json" in dockerfile
    assert "ui/package-lock.json" in dockerfile
    assert "COPY ui/" in dockerfile
    assert "image:" not in (APP / "config.yaml").read_text()
    assert (APP / "ui/package.json").is_file()
    assert (APP / "ui/package-lock.json").is_file()


def test_dockerfile_copy_sources_exist() -> None:
    for line in (APP / "Dockerfile").read_text().splitlines():
        parts = line.split()
        if not parts or parts[0] != "COPY" or "--from" in line:
            continue
        for source in parts[1:-1]:
            assert (APP / source).exists(), source


def test_entry_script_is_tracked_executable() -> None:
    entry = APP / "rootfs/usr/bin/cinema-studio"
    assert entry.is_file()
    records = subprocess.check_output(
        ["git", "ls-files", "-s", "--", "app/rootfs/usr/bin/cinema-studio"],
        cwd=ROOT,
        text=True,
    )
    assert any(line.startswith("100755 ") for line in records.splitlines())
    assert "exec python3 -m cinema_studio.main" in entry.read_text()


def test_translations_define_log_level() -> None:
    for locale in ("en", "es"):
        document = yaml.safe_load((APP / "translations" / f"{locale}.yaml").read_text())
        option = document["configuration"]["log_level"]
        assert option["name"]
        assert option["description"]


def _png_dimensions(path: Path) -> tuple[int, int]:
    contents = path.read_bytes()
    assert contents[:8] == b"\x89PNG\r\n\x1a\n"
    assert contents[12:16] == b"IHDR"
    width, height = struct.unpack(">II", contents[16:24])
    return width, height


def test_app_icons_are_pngs_with_supervisor_dimensions() -> None:
    assert _png_dimensions(APP / "icon.png") == (128, 128)
    assert _png_dimensions(APP / "logo.png") == (250, 100)


def test_docs_and_changelog_cover_required_topics() -> None:
    docs = (APP / "DOCS.md").read_text()
    for topic in ("cinema_studio.import_legacy", "/media", "8099", "Backups"):
        assert topic in docs
    assert (APP / "CHANGELOG.md").read_text().startswith("## 0.1.0")
