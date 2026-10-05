"""Probe, compile, validate and measure an unpublished render."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from .ffmpeg import (
    FfmpegCommandBuilder,
    LoudnessStats,
    RenderPlan,
    effective_profile,
    frame_aligned_duration,
)
from .media import (
    MediaError,
    analyze_loudness,
    file_sha256,
    legacy_fingerprint,
    measure_loudness,
    run_process,
)
from .models import NormalizationProfile, OriginalInfo, Recipe
from .probe import MediaProbe, probe
from .profiles import ProcessingProfile, profile_fingerprint
from .timing import Timing
from .timing_validation import validate_timing


@dataclass(frozen=True)
class RenderOutput:
    path: Path
    timing: Timing
    size: int
    sha256: str
    integrated_lufs: float | None
    true_peak: float | None
    profile_fingerprint: str
    recipe_hash: str


def recipe_hash(recipe: Recipe, normalization: NormalizationProfile | None) -> str:
    payload = {
        "recipe": recipe.model_dump(mode="json"),
        "normalization": normalization.model_dump(mode="json") if normalization else None,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def valid_output(info: MediaProbe, profile: ProcessingProfile) -> bool:
    valid_streams = bool(
        info.valid
        and info.duration > 0
        and info.width == profile.video.width
        and info.height == profile.video.height
        and info.fps is not None
        and abs(info.fps - profile.video.fps) < 0.05
        and info.has_audio
    )
    if not valid_streams:
        return False
    return not (
        info.video_duration is not None
        and info.audio_duration is not None
        and abs(info.video_duration - info.audio_duration) > max(0.1, 1 / profile.video.fps)
    )


def compiled_timing(plan: RenderPlan, info: MediaProbe) -> Timing:
    lead = frame_aligned_duration(plan.recipe.lead_in, plan.profile.video.fps)
    tail = frame_aligned_duration(plan.recipe.tail_out, plan.profile.video.fps)
    end = (info.video_duration or info.duration) - tail if tail > 0 else info.duration
    return validate_timing(Timing(info.duration, lead, end, lead, info.duration - end, end - lead))


def _stats(data: dict[str, float | None]) -> LoudnessStats | None:
    values = [
        data[key] for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    ]
    if any(value is None for value in values):
        return None
    return LoudnessStats(*(value for value in values if value is not None))


def _same_file(left: Path, right: Path) -> bool:
    """Recognize identical paths, symlinks and existing hard links."""
    if left.resolve() == right.resolve():
        return True
    try:
        return left.samefile(right)
    except FileNotFoundError:
        return False


class RenderEngine:
    def __init__(
        self, builder: FfmpegCommandBuilder, *, timeout_for: Callable[[float], float]
    ) -> None:
        self.builder = builder
        self.timeout_for = timeout_for

    async def render(
        self, plan: RenderPlan, on_progress: Callable[[float], None] | None = None
    ) -> RenderOutput:
        temporary: Path | None = None
        stderr_tail = ""
        output_is_safe = False
        try:
            if any(
                asset is not None and _same_file(asset, plan.output)
                for asset in (plan.source, plan.intro, plan.outro)
            ):
                raise MediaError("render output must differ from all inputs")
            output_is_safe = True
            source = await probe(plan.source)
            intro = await probe(plan.intro) if plan.intro is not None else None
            outro = await probe(plan.outro) if plan.outro is not None else None
            plan = replace(
                plan,
                source_duration=source.duration,
                source_has_audio=source.has_audio,
                source_fps=source.fps,
                source_width=source.width,
                source_height=source.height,
                intro_duration=intro.duration if intro else None,
                intro_has_audio=intro.has_audio if intro else False,
                outro_duration=outro.duration if outro else None,
                outro_has_audio=outro.has_audio if outro else False,
            )
            plan.recipe.validate_for(
                OriginalInfo(
                    filename=plan.source.name,
                    size=plan.source.stat().st_size,
                    sha256="",
                    duration=source.duration,
                    width=source.width or 0,
                    height=source.height or 0,
                    fps=source.fps,
                    has_audio=source.has_audio,
                    video_codec=source.video_codec or "",
                )
            )
            profile = effective_profile(plan)
            timeout = self.timeout_for(
                source.duration
                + (intro.duration if intro else 0)
                + (outro.duration if outro else 0)
            )
            measured: LoudnessStats | None = None
            loudnorm = self.builder.loudnorm_filter(profile)
            if not plan.preview and loudnorm is not None:
                if source.has_audio:
                    measured = _stats(
                        await analyze_loudness(
                            plan.source,
                            loudnorm,
                            start=plan.recipe.trim_start,
                            end=plan.recipe.trim_end or source.duration,
                            timeout=timeout,
                            executable=self.builder.executable,
                        )
                    )
                plan = replace(plan, source_silent=source.has_audio and measured is None)
                for name, asset, info in (
                    ("intro", plan.intro, intro),
                    ("outro", plan.outro, outro),
                ):
                    if asset is not None and info is not None and info.has_audio:
                        stats = _stats(
                            await analyze_loudness(
                                asset, loudnorm, timeout=timeout, executable=self.builder.executable
                            )
                        )
                        plan = replace(
                            plan, **{f"{name}_loudness": stats, f"{name}_silent": stats is None}
                        )
            plan.output.parent.mkdir(parents=True, exist_ok=True)
            last_progress = 0.0

            def progress(line: str) -> None:
                nonlocal last_progress
                if line.startswith("out_time_us=") and on_progress is not None:
                    try:
                        seconds = float(line.partition("=")[2]) / 1_000_000
                    except ValueError:
                        return
                    expected = plan.source_duration + plan.recipe.lead_in + plan.recipe.tail_out
                    last_progress = max(last_progress, min(0.99, seconds / max(expected, 0.001)))
                    on_progress(last_progress)

            # Clips normalizes each branch and optionally normalizes the composed mix.
            if (
                not plan.preview
                and loudnorm is not None
                and profile.loudness.final_mix_normalization
            ):
                temporary = plan.output.with_name(
                    f".{plan.output.stem}-{uuid4().hex}.mix{plan.output.suffix}"
                )
                # Calibrate the composed mix without user gain so final normalization
                # compensates fades/transitions while preserving the recipe's gain.
                mix_plan = replace(
                    plan,
                    output=temporary,
                    recipe=plan.recipe.model_copy(update={"gain_db": 0.0}),
                    final_loudness=None,
                )
                _, stderr = await run_process(
                    self.builder.build(mix_plan, measured), timeout=timeout, on_line=progress
                )
                stderr_tail = stderr.decode(errors="replace")[-1000:]
                mix_probe = await probe(temporary)
                mix_timing = compiled_timing(mix_plan, mix_probe)
                final = _stats(
                    await analyze_loudness(
                        temporary,
                        loudnorm,
                        start=mix_timing.content_start,
                        end=mix_timing.content_end,
                        timeout=timeout,
                        executable=self.builder.executable,
                    )
                )
                plan = replace(plan, final_loudness=final)
            enforce_peak = not plan.preview and (
                profile.loudness.mode != "disabled" or plan.recipe.gain_db > 0
            )
            ceiling = (
                profile.loudness.true_peak_dbtp if profile.loudness.mode == "two_pass" else -1.5
            )
            # Check the actual encoded audio, including AAC reconstruction peaks.
            # At most two corrections reuse calibration and preserve the recipe.
            correction = 0
            while True:
                _, stderr = await run_process(
                    self.builder.build(plan, measured), timeout=timeout, on_line=progress
                )
                stderr_tail = stderr.decode(errors="replace")[-1000:]
                info = await probe(plan.output)
                if not valid_output(info, profile):
                    raise MediaError(
                        "compiled output has invalid dimensions, fps, audio or A/V synchronization"
                    )
                timing = compiled_timing(plan, info)
                lufs, peak = await measure_loudness(
                    plan.output, start=timing.content_start, end=timing.content_end
                )
                if not enforce_peak or peak is None or peak <= ceiling + 0.3:
                    break
                if correction == 2:
                    raise MediaError("true peak above ceiling")
                plan = replace(
                    plan, peak_reduction_db=(plan.peak_reduction_db + peak - ceiling + 0.2)
                )
                correction += 1
            digest = await file_sha256(plan.output)
            assets: dict[str, object] = {}
            for name, path in (("intro", plan.intro), ("outro", plan.outro)):
                if path is not None:
                    assets[f"{name}_fingerprint"] = legacy_fingerprint(
                        await file_sha256(path), path.stat().st_size
                    )
            output = RenderOutput(
                plan.output,
                timing,
                plan.output.stat().st_size,
                digest,
                lufs,
                peak,
                profile_fingerprint(plan.profile, assets),
                recipe_hash(plan.recipe, plan.normalization),
            )
            if on_progress is not None:
                on_progress(1.0)
            return output
        except asyncio.CancelledError:
            if output_is_safe:
                plan.output.unlink(missing_ok=True)
            raise
        except Exception as exc:
            # Never delete an original when an invalid plan aliases its output.
            if output_is_safe:
                plan.output.unlink(missing_ok=True)
            detail = f"{str(exc)[-1000:]}\n{stderr_tail}".strip()
            raise MediaError(detail) from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
