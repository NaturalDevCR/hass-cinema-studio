"""Bounded ffprobe collection with validated stream durations and frame rates."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import cast

from .media import MediaError, run_process


@dataclass(frozen=True)
class MediaProbe:
    valid: bool
    duration: float
    video_duration: float | None
    audio_duration: float | None
    width: int | None
    height: int | None
    fps: float | None
    has_audio: bool
    video_codec: str | None


def _rate(value: object) -> float | None:
    try:
        if not isinstance(value, (str, int, float)):
            return None
        result = float(Fraction(value)) if isinstance(value, str) and "/" in value else float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def _stream_duration(stream: dict[str, object]) -> float | None:
    direct = _rate(stream.get("duration"))
    if direct is not None:
        return direct
    ticks = _rate(stream.get("duration_ts"))
    base = _rate(stream.get("time_base"))
    if ticks is not None and base is not None and math.isfinite(ticks * base):
        return ticks * base
    return None


async def probe(path: Path) -> MediaProbe:
    stdout, _ = await run_process(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    try:
        payload = cast("dict[str, object]", json.loads(stdout))
        streams_raw = payload.get("streams")
        format_raw = payload.get("format")
        if not isinstance(streams_raw, list) or not isinstance(format_raw, dict):
            raise ValueError("missing streams/format")
        streams = [
            cast("dict[str, object]", s)
            for s in cast("list[object]", streams_raw)
            if isinstance(s, dict)
        ]
        fmt = cast("dict[str, object]", format_raw)
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if video is None:
            raise ValueError("no video stream")
        duration = _rate(fmt.get("duration"))
        # Still images have a video stream but no duration; needed for JPEG dimensions.
        if duration is None:
            if video.get("codec_name") not in {"mjpeg", "png"}:
                raise ValueError("invalid media duration")
            duration = 0.0
        width = _rate(video.get("width"))
        height = _rate(video.get("height"))
        if not width or not height:
            raise ValueError("invalid video dimensions")
        codec = video.get("codec_name")
        return MediaProbe(
            True,
            duration,
            _stream_duration(video),
            _stream_duration(audio) if audio is not None else None,
            int(width),
            int(height),
            _rate(video.get("r_frame_rate")),
            audio is not None,
            codec if isinstance(codec, str) else None,
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise MediaError(f"ffprobe returned malformed metadata: {exc}") from exc
