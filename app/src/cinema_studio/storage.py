"""Immutable media publication and filesystem recovery."""

from __future__ import annotations

import errno
import logging
import os
import re
import shutil
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .config import Paths
from .errors import InvalidError
from .profiles import ProcessingProfile
from .repository import Repository

RENDER_NAME = re.compile(r"^(?P<clip>[0-9a-f-]{36})-r(?P<n>\d+)-(?P<uuid>[0-9a-f]{32})\.mp4$")
# Short-lived copies of previews played on a device live here, outside the render catalog.
TEST_RENDER_DIR = "_test"
_LOGGER = logging.getLogger(__name__)


def _component(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise InvalidError("invalid path component")
    return value


def validate_contained_path(path: Path, root: Path) -> None:
    """Reject symlinks from root down and paths outside its real location."""
    try:
        relative = path.relative_to(root)
        if ".." in relative.parts:
            raise ValueError("path traversal")
        current = root
        for part in ("", *relative.parts):
            if part:
                current = current / part
            if current.is_symlink():
                raise ValueError("symlink component")
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("path escapes root")
    except (ValueError, OSError, RuntimeError) as error:
        raise InvalidError(f"unsafe media path: {path}") from error


def _sync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _bytes(directory: Path) -> int:
    return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())


class MediaStore:
    def __init__(self, paths: Paths) -> None:
        self.paths = paths

    def ensure_dirs(self) -> None:
        for directory in (
            self.paths.root,
            self.paths.originals_dir,
            self.paths.renders_dir,
            self.paths.assets_dir,
            self.paths.consumers_dir,
            self.paths.work_dir,
        ):
            self._ensure_directory(directory)

    def _ensure_directory(self, directory: Path) -> None:
        validate_contained_path(directory, self.paths.media_dir)
        directory.mkdir(mode=0o755, parents=True, exist_ok=True)
        validate_contained_path(directory, self.paths.media_dir)

    def _validate_write(self, path: Path, root: Path) -> None:
        validate_contained_path(root, self.paths.media_dir)
        validate_contained_path(path, root)

    def staging_path(self, job_id: str, name: str) -> Path:
        # Import staging uses import/<run_id> beneath the work root.
        parts = job_id.split("/")
        for part in parts:
            _component(part)
        path = self.paths.work_dir.joinpath(*parts) / _component(name)
        self._validate_write(path, self.paths.work_dir)
        self._ensure_directory(path.parent)
        return path

    def publish_file(self, staged: Path, clip_id: str, n: int) -> tuple[str, Path]:
        _component(clip_id)
        directory = self.paths.renders_dir / clip_id
        self._validate_write(directory, self.paths.renders_dir)
        self._ensure_directory(self.paths.renders_dir)
        try:
            directory.mkdir(mode=0o755)
        except FileExistsError:
            self._ensure_directory(directory)
        else:
            _sync_directory(self.paths.renders_dir)
        validate_contained_path(staged, self.paths.media_dir)
        if not stat.S_ISREG(staged.lstat().st_mode):
            raise InvalidError("staged render must be a regular file")
        with staged.open("rb") as source:
            os.fsync(source.fileno())
        for _ in range(5):
            render_uuid = uuid4().hex
            final = directory / f"{clip_id}-r{n}-{render_uuid}.mp4"
            try:
                os.link(staged, final)
            except FileExistsError:
                continue
            _sync_directory(directory)
            staged.unlink()
            return render_uuid, final
        raise FileExistsError("render UUID collision after 5 attempts")

    def relative_path(self, path: Path) -> str:
        return path.relative_to(self.paths.media_dir).as_posix()

    def store_original(self, src: Path, clip_id: str, filename: str, *, link: bool) -> Path:
        name = _component(filename.replace("\\", "/").rsplit("/", 1)[-1])
        destination = self.paths.originals_dir / _component(clip_id) / name
        self._validate_write(destination, self.paths.originals_dir)
        self._ensure_directory(destination.parent)
        if link:
            try:
                os.link(src, destination)
            except OSError as error:
                if error.errno != errno.EXDEV:
                    raise
                shutil.copy2(src, destination)
        else:
            shutil.move(src, destination)
        return destination

    def clean_work(self) -> None:
        cutoff = time.time() - 3600
        for path in self.paths.work_dir.iterdir():
            if path.name == "import" and path.is_dir() and not path.is_symlink():
                for run in path.iterdir():
                    if run.stat().st_mtime <= cutoff:
                        _remove(run)
            else:
                _remove(path)

    def scan_renders(self) -> list[tuple[str, str, Path, int, float]]:
        found: list[tuple[str, str, Path, int, float]] = []
        for path in self.paths.renders_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.relative_to(self.paths.renders_dir).parts[0] == TEST_RENDER_DIR:
                continue  # test-on-device copies are not renders
            match = RENDER_NAME.fullmatch(path.name)
            if match is None:
                _LOGGER.warning("Leaving non-render file untouched: %s", path)
                continue
            stat = path.stat()
            found.append((match["uuid"], match["clip"], path, stat.st_size, stat.st_mtime))
        return found

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.paths.media_dir).free

    def is_network_fs(self) -> bool:
        targets = (self.paths.renders_dir, self.paths.consumers_dir, self.paths.gc_lock_path)
        try:
            lines = Path("/proc/mounts").read_text().splitlines()
        except FileNotFoundError:
            return False
        for location in targets:
            target = location.resolve()
            best = -1
            filesystem = ""
            for line in lines:
                fields = line.split()
                if len(fields) < 3:
                    continue
                mount = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[1]))
                if target.is_relative_to(mount) and len(mount.parts) > best:
                    best, filesystem = len(mount.parts), fields[2]
            if filesystem in {"nfs", "nfs4", "cifs", "smb3", "fuse.sshfs"}:
                return True
        return False

    def estimate_render_bytes(self, profile: ProcessingProfile, seconds: float) -> int:
        video = profile.video
        bitrate = video.maxrate_kbps or video.quality.bitrate_kbps or 20000
        return int((bitrate + profile.audio.bitrate_kbps) * 1000 / 8 * seconds * 1.2 * 2)

    def check_space(self, needed: int, reserve: int) -> None:
        if self.free_bytes() < needed + reserve:
            raise InvalidError("not enough free space for render and disk reserve")

    def storage_usage(self, repo: Repository) -> dict[str, int]:
        return {
            "free_bytes": self.free_bytes(),
            "network_fs": self.is_network_fs(),
            "originals_bytes": _bytes(self.paths.originals_dir),
            "renders_bytes": _bytes(self.paths.renders_dir),
            "retired_bytes": sum(
                (self.paths.media_dir / r.relative_path).stat().st_size
                for r in repo.list_renders(states={"retired"})
                if (self.paths.media_dir / r.relative_path).is_file()
            ),
            "work_bytes": _bytes(self.paths.work_dir),
        }


def recover(store: MediaStore, repo: Repository) -> dict[str, int]:
    store.ensure_dirs()
    store.clean_work()
    counts = dict(unrecognized=0, missing=0, interrupted=0)
    interrupted = [c.id for c in repo.list_clips() if c.status == "rendering"]
    records = repo.list_renders()
    known = {r.id for r in records}
    for render_id, clip_id, path, size, mtime in store.scan_renders():
        if render_id not in known:
            repo.add_unrecognized_render(
                render_id=render_id,
                clip_id=clip_id,
                relative_path=store.relative_path(path),
                size=size,
                mtime_iso=datetime.fromtimestamp(mtime, UTC).isoformat(),
            )
            known.add(render_id)
            counts["unrecognized"] += 1
    for record in records:
        if (
            record.state in {"published", "retired"}
            and not (store.paths.media_dir / record.relative_path).is_file()
        ):
            repo.mark_render(record.id, "missing")
            counts["missing"] += 1
            if record.state == "published":
                repo.fallback_after_missing(
                    record.clip_id, lambda relative: (store.paths.media_dir / relative).is_file()
                )
    for clip_id in interrupted:
        clip = repo.get_clip(clip_id)
        repo.set_status(
            clip_id, "ready" if clip.render else "failed", None if clip.render else "interrupted"
        )
        counts["interrupted"] += 1
    return counts
