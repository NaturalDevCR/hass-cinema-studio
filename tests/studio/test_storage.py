"""Immutable publication and startup recovery."""

import errno
import os
import time
from contextlib import closing
from uuid import UUID, uuid4

import pytest

from cinema_studio.db import Database
from cinema_studio.errors import InvalidError
from cinema_studio.profiles import ProcessingProfile
from cinema_studio.repository import Repository
from cinema_studio.storage import RENDER_NAME, MediaStore, recover
from tests.studio.test_repository import make_clip, make_render

pytestmark = pytest.mark.studio


def test_publication(paths, monkeypatch):
    store = MediaStore(paths)
    store.ensure_dirs()
    staged = store.staging_path("job", "output.mp4")
    staged.write_bytes(b"video")
    inode = staged.stat().st_ino
    clip = str(uuid4())
    first, second = UUID(int=1), UUID(int=2)
    directory = paths.renders_dir / clip
    directory.mkdir()
    existing = directory / f"{clip}-r1-{first.hex}.mp4"
    existing.write_bytes(b"existing")
    ids = iter([first, second])
    monkeypatch.setattr("cinema_studio.storage.uuid4", lambda: next(ids))
    render_id, final = store.publish_file(staged, clip, 1)
    assert render_id == second.hex
    assert RENDER_NAME.fullmatch(final.name)
    assert final.stat().st_ino == inode
    assert not staged.exists()
    assert existing.read_bytes() == b"existing"
    assert store.relative_path(final) == f"cinema-studio/renders/{clip}/{final.name}"


def test_original(paths, monkeypatch):
    store = MediaStore(paths)
    source = paths.media_dir / "source.mp4"
    source.write_bytes(b"original")
    original = store.store_original(source, "clip", "../movie.mp4", link=True)
    assert original.parent == paths.originals_dir / "clip"
    assert original.stat().st_ino == source.stat().st_ino
    replacement = source.with_suffix(".new")
    replacement.write_bytes(b"replaced")
    os.replace(replacement, source)
    assert original.read_bytes() == b"original"

    def cross_device(*args):
        raise OSError(errno.EXDEV, "cross device")

    monkeypatch.setattr("cinema_studio.storage.os.link", cross_device)
    copied = store.store_original(source, "other", "movie.mp4", link=True)
    assert copied.read_bytes() == b"replaced"
    moved = store.store_original(source, "third", "movie.mp4", link=False)
    assert moved.exists() and not source.exists()


def test_recovery(paths, caplog):
    store = MediaStore(paths)
    store.ensure_dirs()
    with closing(Database(paths.database_path)) as db:
        repo = Repository(db)
        clip = make_clip(repo)
        earlier = make_render(clip)
        repo.publish_render(earlier)
        earlier_path = paths.media_dir / earlier.relative_path
        earlier_path.parent.mkdir(parents=True)
        earlier_path.write_bytes(b"old")
        missing = make_render(clip, 2)
        repo.publish_render(missing)
        failed = make_clip(repo)
        repo.publish_render(make_render(failed))
        interrupted = make_clip(repo)
        repo.set_status(interrupted, "rendering")
        repo.set_status(clip, "rendering")
        orphan_id = uuid4().hex
        orphan = earlier_path.parent / f"{clip}-r3-{orphan_id}.mp4"
        orphan.write_bytes(b"orphan")
        unknown = earlier_path.parent / "unknown.txt"
        unknown.write_bytes(b"keep")
        store.staging_path("job", "x").write_bytes(b"discard")
        recent = store.staging_path("import/recent", "x")
        recent.write_bytes(b"keep")
        old = store.staging_path("import/old", "x")
        old.write_bytes(b"discard")
        os.utime(old.parent, (time.time() - 3601, time.time() - 3601))
        assert recover(store, repo) == {"unrecognized": 1, "missing": 2, "interrupted": 2}
        assert repo.get_render(orphan_id).state == "unrecognized"
        assert orphan.read_bytes() == b"orphan"
        assert repo.get_clip(clip).render.id == earlier.id
        assert repo.get_clip(failed).status == "failed"
        assert repo.get_clip(interrupted).error == "interrupted"
        assert recent.exists() and not old.exists()
        assert not (paths.work_dir / "job").exists()
        assert unknown.exists() and "unknown.txt" in caplog.text
        assert recover(store, repo) == {"unrecognized": 0, "missing": 0, "interrupted": 0}


def test_space_and_usage(paths, monkeypatch):
    store = MediaStore(paths)
    store.ensure_dirs()
    monkeypatch.setattr(store, "free_bytes", lambda: 100)
    store.check_space(80, 20)
    with pytest.raises(InvalidError, match="not enough free space"):
        store.check_space(81, 20)
    assert store.estimate_render_bytes(ProcessingProfile(), 10) == int(
        (20000 + 192) * 125 * 10 * 1.2 * 2
    )
    with closing(Database(paths.database_path)) as db:
        repo = Repository(db)
        (paths.originals_dir / "x").write_bytes(b"123")
        store.staging_path("job", "x").write_bytes(b"12")
        usage = store.storage_usage(repo)
        assert usage["originals_bytes"] == 3 and usage["work_bytes"] == 2
        assert usage["network_fs"] is False


def test_collision_limit(paths, monkeypatch):
    store = MediaStore(paths)
    staged = store.staging_path("job", "video.mp4")
    staged.write_bytes(b"new")
    clip = str(uuid4())
    fixed = UUID(int=1)
    directory = paths.renders_dir / clip
    directory.mkdir(parents=True)
    final = directory / f"{clip}-r1-{fixed.hex}.mp4"
    final.write_bytes(b"old")
    calls = []

    def draw():
        calls.append(1)
        return fixed

    monkeypatch.setattr("cinema_studio.storage.uuid4", draw)
    with pytest.raises(FileExistsError):
        store.publish_file(staged, clip, 1)
    assert len(calls) == 5
    assert staged.read_bytes() == b"new" and final.read_bytes() == b"old"


@pytest.mark.parametrize(
    "filesystem,expected",
    [("nfs4", True), ("cifs", True), ("smb3", True), ("fuse.sshfs", True), ("ext4", False)],
)
def test_network_mount(paths, monkeypatch, filesystem, expected):
    from pathlib import Path

    def mounts(self, *args, **kwargs):
        assert self == Path("/proc/mounts")
        return f"root / ext4 rw 0 0\nserver {paths.media_dir} {filesystem} rw 0 0\n"

    monkeypatch.setattr(Path, "read_text", mounts)
    assert MediaStore(paths).is_network_fs() is expected
