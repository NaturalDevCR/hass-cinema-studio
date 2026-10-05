"""Fixtures for Cinema Studio tests."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from cinema_studio.config import Paths


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    p = Paths(
        data_dir=tmp_path / "data",
        media_dir=tmp_path / "media",
        static_dir=tmp_path / "static",
        dev_mode=False,
    )
    p.data_dir.mkdir(parents=True)
    p.media_dir.mkdir(parents=True)
    return p


@pytest.fixture
def make_video(tmp_path: Path) -> Callable[..., Path]:
    """Generate a small test video (testsrc + sine) with ffmpeg."""

    def _make(
        name: str = "clip.mp4",
        seconds: float = 4.0,
        width: int = 320,
        height: int = 180,
        fps: int = 24,
        audio: bool = True,
        volume_db: float = -20.0,
    ) -> Path:
        out = tmp_path / "fixtures" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={width}x{height}:rate={fps}:duration={seconds}",
        ]
        if audio:
            cmd += [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={seconds}:sample_rate=48000",
                "-af",
                f"volume={volume_db}dB",
            ]
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        if audio:
            cmd += ["-c:a", "aac", "-shortest"]
        cmd.append(str(out))
        subprocess.run(cmd, check=True)
        return out

    return _make


@pytest.fixture
def small_profile_settings() -> dict[str, object]:
    """A fast ProcessingProfile for tests: 320x180@24, ultrafast, loudness two-pass -18."""
    return {
        "video": {
            "width": 320,
            "height": 180,
            "fps": 24,
            "preset": "ultrafast",
            "scaling": {"strategy": "aspect_fit", "width": 320, "height": 180},
        },
        "loudness": {
            "mode": "two_pass",
            "integrated_lufs": -18,
            "true_peak_dbtp": -1.5,
            "lra_lu": 11,
        },
    }
