"""Blocking verification of published render files."""

import os
import stat
from collections.abc import Iterable
from pathlib import Path

from .catalog import RenderDef


def render_path(media_root: Path, render: RenderDef) -> Path:
    return media_root / render.relative_path


def verify_render(media_root: Path, render: RenderDef) -> bool:
    path = render_path(media_root, render)
    try:
        if path.is_symlink():
            return False
        root = os.path.realpath(media_root / "cinema-studio/renders") + os.sep
        if not os.path.realpath(path).startswith(root):
            return False
        info = path.stat()
        return stat.S_ISREG(info.st_mode) and info.st_size == render.size
    except (OSError, ValueError):
        return False


def verify_all(media_root: Path, renders: Iterable[RenderDef]) -> dict[str, bool]:
    return {render.id: verify_render(media_root, render) for render in renders}
