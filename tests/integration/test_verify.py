"""Published files must be regular, contained and the declared size."""

from dataclasses import replace
from pathlib import Path

import pytest

from custom_components.cinema_studio.catalog import parse_catalog
from custom_components.cinema_studio.verify import render_path, verify_all, verify_render

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "case", ["ok", "size", "symlink", "escape", "directory", "missing", "parent_link"]
)
def test_verify(tmp_path: Path, catalog_payload: dict, case: str) -> None:
    render = parse_catalog(catalog_payload).clips[0].render
    path = render_path(tmp_path, render)
    assert path == tmp_path / render.relative_path
    path.parent.mkdir(parents=True)
    if case == "escape":
        render = replace(render, relative_path="cinema-studio/renders/../../outside.mp4")
        (tmp_path / "outside.mp4").write_bytes(b"12345")
    elif case == "parent_link":
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "a.mp4").write_bytes(b"12345")
        path.parent.rmdir()
        path.parent.symlink_to(outside, target_is_directory=True)
    elif case == "symlink":
        target = path.parent / "target.mp4"
        target.write_bytes(b"12345")
        path.symlink_to(target)
    elif case == "directory":
        path.mkdir()
    elif case != "missing":
        path.write_bytes(b"12345" if case == "ok" else b"123")
    assert verify_render(tmp_path, render) is (case == "ok")
    assert verify_all(tmp_path, iter([render])) == {render.id: case == "ok"}
