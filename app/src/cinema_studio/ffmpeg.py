"""Pure FFmpeg argv construction from typed processing profiles and recipes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from .models import NormalizationProfile, Recipe
from .profiles import ProcessingProfile, TwoPassLoudness, validate_profile


def frame_aligned_duration(duration_seconds: float, frame_rate: int) -> float:
    """Round a requested pad up to an integral number of output frames."""
    frame_count = math.ceil(duration_seconds * frame_rate - 1e-9)
    return frame_count / frame_rate


@dataclass(frozen=True)
class LoudnessStats:
    input_i: float
    input_tp: float
    input_lra: float
    input_thresh: float
    target_offset: float


@dataclass(frozen=True)
class RenderPlan:
    source: Path
    output: Path
    profile: ProcessingProfile
    recipe: Recipe
    normalization: NormalizationProfile | None
    intro: Path | None
    outro: Path | None
    source_duration: float
    preview: bool
    # Controller-approved probe metadata, populated by RenderEngine before build.
    source_has_audio: bool = True
    source_fps: float | None = None
    intro_duration: float | None = None
    intro_has_audio: bool = True
    outro_duration: float | None = None
    outro_has_audio: bool = True
    source_width: int | None = None
    source_height: int | None = None
    intro_loudness: LoudnessStats | None = None
    outro_loudness: LoudnessStats | None = None
    final_loudness: LoudnessStats | None = None
    source_silent: bool = False
    intro_silent: bool = False
    outro_silent: bool = False


def effective_profile(plan: RenderPlan) -> ProcessingProfile:
    """Apply normalization targets and bounded preview encoding on a fresh profile."""
    profile = validate_profile(plan.profile)
    if plan.normalization is not None:
        n = plan.normalization
        profile.loudness = TwoPassLoudness(
            integrated_lufs=n.target_lufs,
            true_peak_dbtp=n.true_peak,
            lra_lu=n.lra,
            final_mix_normalization=profile.loudness.final_mix_normalization,
        )
    if plan.preview:
        width, height = profile.video.width, profile.video.height
        if width > 1280 or height > 720:
            width, height = 1280, 720
        elif width > 640 or height > 360:
            width, height = 640, 360
        profile.video.width, profile.video.height = width, height
        profile.video.scaling.width, profile.video.scaling.height = width, height
        profile.video.preset = "veryfast"
        from .profiles import CrfQuality

        profile.video.quality = CrfQuality(crf=28)
    return profile


class FfmpegCommandBuilder:
    """Build argv vectors; no probes, shell, or caller-provided raw filters."""

    def __init__(self, executable: str = "ffmpeg") -> None:
        self.executable = executable

    @staticmethod
    def _video_filter(profile: ProcessingProfile) -> str:
        scaling = profile.video.scaling
        if scaling.strategy == "crop":
            geometry = (
                f"scale={scaling.width}:{scaling.height}:force_original_aspect_ratio=increase,"
                f"crop={scaling.width}:{scaling.height},setsar=1"
            )
        else:
            geometry = (
                f"scale={scaling.width}:{scaling.height}:force_original_aspect_ratio=decrease,"
                f"pad={scaling.width}:{scaling.height}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar={scaling.sar_num}/{scaling.sar_den}"
            )
        return f"{geometry},fps={profile.video.fps},format={profile.video.pixel_format}"

    @staticmethod
    def _audio_filter(profile: ProcessingProfile, duration_seconds: float) -> str:
        layout = "stereo" if profile.audio.channels == 2 else f"{profile.audio.channels}c"
        items = [f"aformat=channel_layouts={layout}", f"aresample={profile.audio.sample_rate}"]
        if profile.audio.pad_or_trim:
            items.extend(["apad", f"atrim=duration={max(0.0, duration_seconds):.3f}"])
        return ",".join(items)

    @staticmethod
    def loudnorm_filter(
        profile: ProcessingProfile, measured: LoudnessStats | None = None
    ) -> str | None:
        loudness = profile.loudness
        if loudness.mode == "disabled":
            return None
        text = (
            f"loudnorm=I={loudness.integrated_lufs:g}:"
            f"TP={loudness.true_peak_dbtp:g}:LRA={loudness.lra_lu:g}"
        )
        if measured is not None:
            text += (
                f":measured_I={measured.input_i:g}:measured_TP={measured.input_tp:g}"
                f":measured_LRA={measured.input_lra:g}:measured_thresh={measured.input_thresh:g}"
                f":offset={measured.target_offset:g}:linear=true"
            )
        return text

    def build(self, plan: RenderPlan, measured: LoudnessStats | None) -> list[str]:
        profile = effective_profile(plan)
        recipe = plan.recipe
        end = min(recipe.trim_end or plan.source_duration, plan.source_duration)
        duration = end - recipe.trim_start
        if duration <= 0:
            raise ValueError("trim must leave positive content duration")
        command = [
            self.executable,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-progress",
            "pipe:1",
            "-filter_complex_threads",
            "1",
        ]
        if profile.decode_error_policy == "fail":
            command += ["-xerror"]
        inputs = [("clip", plan.source, duration, plan.source_has_audio, measured)]
        for name, path, length, audio, stats in (
            ("intro", plan.intro, plan.intro_duration, plan.intro_has_audio, plan.intro_loudness),
            ("outro", plan.outro, plan.outro_duration, plan.outro_has_audio, plan.outro_loudness),
        ):
            if path is not None:
                if length is None or not math.isfinite(length) or length <= 0:
                    raise ValueError(f"{name} duration must be probed before building")
                inputs.append((name, path, length, audio, stats))
        graph: list[str] = []
        for index, (name, path, length, has_audio, stats) in enumerate(inputs):
            command += ["-i", str(path)]
            vf = "setpts=PTS-STARTPTS,"
            af = "asetpts=PTS-STARTPTS,"
            if name == "clip":
                vf = f"trim=start={recipe.trim_start:g}:end={end:g},setpts=PTS-STARTPTS,"
                af = f"atrim=start={recipe.trim_start:g}:end={end:g},asetpts=PTS-STARTPTS,"
                if recipe.crop is not None:
                    c = recipe.crop
                    if c.w < 2 or c.h < 2:
                        raise ValueError("crop must contain at least one even pixel pair")
                    vf += f"crop={c.w // 2 * 2}:{c.h // 2 * 2}:{c.x // 2 * 2}:{c.y // 2 * 2},"
            vf += self._video_filter(profile)
            af += self._audio_filter(profile, length)
            silent = {
                "clip": plan.source_silent,
                "intro": plan.intro_silent,
                "outro": plan.outro_silent,
            }[name]
            loudnorm = (
                None
                if plan.preview or not has_audio or silent
                else self.loudnorm_filter(profile, stats)
            )
            if loudnorm is not None:
                af += "," + loudnorm
            if name == "clip":
                fade_in = (
                    f"{recipe.fade_in:.3f}"
                    if recipe.fade_in is not None
                    else f"{profile.fade_in_seconds:g}"
                )
                fade_out = (
                    f"{recipe.fade_out:.3f}"
                    if recipe.fade_out is not None
                    else f"{profile.fade_out_seconds:g}"
                )
                fade_start = max(0, length - float(fade_out))
                vf += f",fade=t=in:st=0:d={fade_in},fade=t=out:st={fade_start:g}:d={fade_out}"
                af += (
                    f",volume={recipe.gain_db:g}dB,afade=t=in:st=0:d={fade_in},"
                    f"afade=t=out:st={fade_start:g}:d={fade_out}"
                )
                if recipe.gain_db > 0:
                    peak = (
                        profile.loudness.true_peak_dbtp
                        if profile.loudness.mode == "two_pass"
                        else -1.5
                    )
                    af += f",alimiter=limit={10 ** (peak / 20):.8f}:level=false:latency=true"
            # loudnorm internally upsamples; restore the profile rate on every branch.
            af += (
                f",aresample={profile.audio.sample_rate},"
                f"asettb=1/{profile.audio.sample_rate},asetpts=N/SR/TB"
            )
            graph.append(f"[{index}:v]{vf}[v_{name}]")
            if not has_audio:
                if profile.audio.missing_policy.mode != "silence":
                    raise ValueError(f"{name} audio is required by this processing profile")
                layout = "stereo" if profile.audio.channels == 2 else f"{profile.audio.channels}c"
                graph.append(
                    f"anullsrc=channel_layout={layout}:sample_rate={profile.audio.sample_rate},"
                    f"atrim=duration={plan.source_duration if name == 'clip' else length:g},"
                    f"{af}[a_{name}]"
                )
            else:
                graph.append(f"[{index}:a]{af}[a_{name}]")
        video_label, audio_label = "v_clip", "a_clip"
        total_duration = duration
        for name, path, length in (
            ("intro", plan.intro, plan.intro_duration),
            ("outro", plan.outro, plan.outro_duration),
        ):
            if path is None:
                continue
            assert length is not None
            from_name, to_name = ("intro", "clip") if name == "intro" else ("clip", "outro")
            transition = next(
                (
                    t.duration_seconds
                    for t in profile.transitions
                    if t.from_segment == from_name and t.to_segment == to_name
                ),
                0.0,
            )
            if transition >= min(length, total_duration):
                raise ValueError("transition must be shorter than both adjacent segments")
            vleft, vright = (
                ("v_intro", video_label) if name == "intro" else (video_label, "v_outro")
            )
            aleft, aright = (
                ("a_intro", audio_label) if name == "intro" else (audio_label, "a_outro")
            )
            vnew = "v_intro_clip" if name == "intro" else "v_final_transition"
            anew = "a_intro_clip" if name == "intro" else "a_final_transition"
            if transition > 0:
                offset = (length if name == "intro" else total_duration) - transition
                graph += [
                    f"[{vleft}][{vright}]xfade=transition=fade:duration={transition:g}:offset={offset:g}[{vnew}]",
                    f"[{aleft}][{aright}]acrossfade=d={transition:g}[{anew}]",
                ]
            else:
                graph.append(
                    f"[{vleft}][{aleft}][{vright}][{aright}]concat=n=2:v=1:a=1[{vnew}][{anew}]"
                )
            video_label, audio_label = vnew, anew
            total_duration += length - transition
        final_norm = None if plan.preview else self.loudnorm_filter(profile, plan.final_loudness)
        if plan.final_loudness is not None and final_norm is not None:
            graph.append(
                f"[{audio_label}]{final_norm},aresample={profile.audio.sample_rate},"
                f"asettb=1/{profile.audio.sample_rate},asetpts=N/SR/TB[a_normalized]"
            )
            audio_label = "a_normalized"
        lead = frame_aligned_duration(recipe.lead_in, profile.video.fps)
        tail = frame_aligned_duration(recipe.tail_out, profile.video.fps)
        video_pad: list[str] = []
        audio_pad: list[str] = []
        if lead > 0:
            video_pad += [f"start_duration={lead:g}", "start_mode=add"]
            audio_pad += [f"adelay=delays={round(lead * profile.audio.sample_rate)}S:all=1"]
        if tail > 0:
            video_pad += [f"stop_duration={tail:g}", "stop_mode=add"]
            audio_pad += [f"apad=pad_dur={tail:g}"]
        if video_pad:
            graph += [
                f"[{video_label}]tpad={':'.join(video_pad)}:color=black[v_padded]",
                f"[{audio_label}]{','.join(audio_pad)},asetpts=N/SR/TB[a_padded]",
            ]
            video_label, audio_label = "v_padded", "a_padded"
        command += [
            "-filter_complex",
            ";".join(graph),
            "-map",
            f"[{video_label}]",
            "-map",
            f"[{audio_label}]",
            "-r",
            str(profile.video.fps),
            "-c:v",
            profile.video.codec,
            "-preset",
            profile.video.preset,
            "-profile:v",
            profile.video.h264_profile,
            "-level:v",
            profile.video.level,
        ]
        if profile.video.quality.mode == "crf":
            command += ["-crf", f"{profile.video.quality.crf:g}"]
        else:
            command += ["-b:v", f"{profile.video.quality.bitrate_kbps}k"]
        if profile.video.maxrate_kbps is not None:
            command += ["-maxrate", f"{profile.video.maxrate_kbps}k"]
        if profile.video.bufsize_kbps is not None:
            command += ["-bufsize", f"{profile.video.bufsize_kbps}k"]
        if profile.video.keyframe_interval_seconds is not None:
            command += [
                "-g",
                str(round(profile.video.keyframe_interval_seconds * profile.video.fps)),
            ]
        command += [
            "-pix_fmt",
            profile.video.pixel_format,
            "-c:a",
            profile.audio.codec,
            "-b:a",
            f"{profile.audio.bitrate_kbps}k",
            "-ar",
            str(profile.audio.sample_rate),
            "-ac",
            str(profile.audio.channels),
        ]
        if profile.video.fast_start and profile.output.container == "mp4":
            command += ["-movflags", "+faststart"]
        command.append(str(plan.output))
        return command
