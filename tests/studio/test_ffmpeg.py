"""Argv regressions ported from Clips, plus recipe filter order."""

from dataclasses import replace
from pathlib import Path

import pytest

from cinema_studio.ffmpeg import (
    FfmpegCommandBuilder,
    LoudnessStats,
    RenderPlan,
    frame_aligned_duration,
)
from cinema_studio.models import Recipe
from cinema_studio.profiles import ProcessingProfile

pytestmark = pytest.mark.studio


def plan(tmp_path: Path, **kwargs):
    base = RenderPlan(
        tmp_path / "source;still-a-file.mp4",
        tmp_path / "out.mp4",
        ProcessingProfile(),
        Recipe(),
        None,
        None,
        None,
        10,
        False,
    )
    return replace(base, **kwargs)


def graph(p, measured=None):
    argv = FfmpegCommandBuilder().build(p, measured)
    return argv[argv.index("-filter_complex") + 1]


def test_argument_vector_encoder_and_margins(tmp_path):
    p = plan(
        tmp_path,
        profile=ProcessingProfile.model_validate(
            {
                "decode_error_policy": "fail",
                "video": {
                    "maxrate_kbps": 8000,
                    "bufsize_kbps": 16000,
                    "keyframe_interval_seconds": 2,
                },
            }
        ),
    )
    argv = FfmpegCommandBuilder().build(p, None)
    assert str(p.source) in argv and argv[-1] == str(p.output)
    for flag, value in [
        ("-profile:v", "high"),
        ("-level:v", "5.1"),
        ("-maxrate", "8000k"),
        ("-bufsize", "16000k"),
        ("-g", "48"),
    ]:
        assert argv[argv.index(flag) + 1] == value
    assert "-xerror" in argv
    assert "start_duration=2" in graph(p) and "stop_duration=2" in graph(p)
    assert "adelay=delays=96000S:all=1" in graph(p) and "apad=pad_dur=2" in graph(p)


def test_recipe_order_fades_and_limiter(tmp_path):
    recipe = Recipe.model_validate(
        {
            "trim_start": 1,
            "trim_end": 3,
            "crop": {"x": 1, "y": 1, "w": 161, "h": 91},
            "fade_in": 0.5,
            "fade_out": 0.25,
            "gain_db": 3,
        }
    )
    g = graph(plan(tmp_path, recipe=recipe), LoudnessStats(-30, -20, 0, -40, 0))
    assert g.index("trim=start=1") < g.index("crop=160:90:0:0") < g.index("scale=")
    assert "fade=t=in:st=0:d=0.500" in g
    assert (
        g.index("atrim=start=1")
        < g.index("loudnorm=")
        < g.index("volume=3dB")
        < g.index("afade=")
        < g.index("alimiter=")
    )
    assert "measured_I=-30" in g
    assert "fade=t=in:st=0:d=1" in graph(plan(tmp_path))


def test_transitions_offsets_and_normalized_branches(tmp_path):
    p = plan(
        tmp_path,
        intro=tmp_path / "intro.mp4",
        outro=tmp_path / "outro.mp4",
        intro_duration=4,
        outro_duration=3,
    )
    g = graph(p)
    assert "duration=1:offset=3" in g and "duration=1:offset=12" in g
    assert g.count("fps=24,format=yuv420p") == 3
    assert "acrossfade=d=1" in g


def test_no_margins_and_missing_audio(tmp_path):
    p = plan(
        tmp_path,
        recipe=Recipe(lead_in=0, tail_out=0),
        source_has_audio=False,
        profile=ProcessingProfile.model_validate(
            {"audio": {"missing_policy": {"mode": "silence"}}}
        ),
    )
    assert "tpad=" not in graph(p) and "adelay=" not in graph(p)
    assert "anullsrc=" in graph(p)
    with pytest.raises(ValueError, match="audio"):
        graph(replace(p, profile=ProcessingProfile()))


@pytest.mark.parametrize(
    "seconds,expected", [(0, 0), (0.75, 0.75), (1.125, 1.125), (0.01, 1 / 24), (2, 2)]
)
def test_frame_alignment(seconds, expected):
    assert frame_aligned_duration(seconds, 24) == expected


def test_preview_size_quality_and_no_loudnorm(tmp_path):
    p = plan(tmp_path, preview=True)
    argv = FfmpegCommandBuilder().build(p, None)
    assert "scale=1280:720" in graph(p)
    assert argv[argv.index("-crf") + 1] == "28"
    assert argv[argv.index("-preset") + 1] == "veryfast"
    assert "loudnorm=" not in graph(p)
