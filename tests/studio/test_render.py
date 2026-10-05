"""Real compiler behavior and Clips timing/output validation regressions."""

import re
from dataclasses import replace

import pytest

from cinema_studio.ffmpeg import FfmpegCommandBuilder, RenderPlan
from cinema_studio.media import MediaError, run_process
from cinema_studio.models import NormalizationProfile, Recipe
from cinema_studio.probe import MediaProbe, probe
from cinema_studio.profiles import ProcessingProfile
from cinema_studio.render import RenderEngine, compiled_timing, recipe_hash, valid_output
from cinema_studio.timing import timing_problems

pytestmark = pytest.mark.studio


def make_plan(src, tmp_path, settings, **kwargs):
    base = RenderPlan(
        src,
        tmp_path / "out.mp4",
        ProcessingProfile.model_validate(settings),
        Recipe(),
        None,
        None,
        None,
        5,
        False,
    )
    return replace(base, **kwargs)


def engine(builder=None):
    return RenderEngine(builder or FfmpegCommandBuilder(), timeout_for=lambda _: 30)


async def test_trim_black_silent_margins(make_video, small_profile_settings, tmp_path):
    p = make_plan(
        make_video(seconds=5),
        tmp_path,
        small_profile_settings,
        recipe=Recipe(trim_start=1, trim_end=3, fade_in=0, fade_out=0),
    )
    progress = []
    out = await engine().render(p, progress.append)
    assert out.timing.duration == pytest.approx(6, abs=0.1)
    assert out.timing.content_start == 2
    assert out.timing.content_end == pytest.approx(4, abs=0.05)
    assert not timing_problems(out.timing)
    assert out.size > 0 and len(out.sha256) == 64 and len(out.recipe_hash) == 16
    assert progress and progress[-1] == 1
    for at in (1, 5):
        raw, _ = await run_process(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(at),
                "-i",
                str(out.path),
                "-frames:v",
                "1",
                "-pix_fmt",
                "gray",
                "-f",
                "rawvideo",
                "-",
            ]
        )
        assert raw and sum(raw) / len(raw) < 20
    for at in (0, 4.1):
        _, stderr = await run_process(
            [
                "ffmpeg",
                "-hide_banner",
                "-ss",
                str(at),
                "-t",
                "1.8",
                "-i",
                str(out.path),
                "-af",
                "volumedetect",
                "-vn",
                "-f",
                "null",
                "-",
            ]
        )
        maximum = re.search(r"max_volume: ([\d.-]+) dB", stderr.decode())
        assert maximum and float(maximum[1]) < -60


async def test_crop(make_video, small_profile_settings, tmp_path):
    p = make_plan(
        make_video(seconds=2),
        tmp_path,
        small_profile_settings,
        recipe=Recipe.model_validate({"crop": {"x": 0, "y": 0, "w": 160, "h": 90}}),
    )
    out = await engine().render(p)
    info = await probe(out.path)
    assert info.valid and (info.width, info.height) == (320, 180)


@pytest.mark.parametrize(
    "override,target",
    [
        (None, -18),
        (NormalizationProfile(id="loud", name="Loud", target_lufs=-13, true_peak=-1, lra=11), -13),
    ],
)
async def test_normalization(make_video, small_profile_settings, tmp_path, override, target):
    p = make_plan(
        make_video(seconds=5, volume_db=-30),
        tmp_path,
        small_profile_settings,
        normalization=override,
        recipe=Recipe(fade_in=0, fade_out=0),
    )
    out = await engine().render(p)
    assert out.integrated_lufs == pytest.approx(target, abs=1)


async def test_assets_transitions(make_video, small_profile_settings, tmp_path):
    settings = dict(
        small_profile_settings,
        fade_in_seconds=0,
        fade_out_seconds=0,
        transitions=[
            {
                "type": "fade",
                "from_segment": "intro",
                "to_segment": "clip",
                "duration_seconds": 0.5,
            },
            {
                "type": "fade",
                "from_segment": "clip",
                "to_segment": "outro",
                "duration_seconds": 0.5,
            },
        ],
    )
    asset = make_video(name="intro.mp4", seconds=1, fps=30)
    p = make_plan(make_video(seconds=3), tmp_path, settings, intro=asset, outro=asset)
    out = await engine().render(p)
    assert out.timing.duration == pytest.approx(8, abs=0.1)
    assert not timing_problems(out.timing)


async def test_preview_no_two_pass_and_small_dimensions(
    make_video, small_profile_settings, tmp_path
):
    class Spy(FfmpegCommandBuilder):
        def build(self, plan, measured):
            assert measured is None and plan.source_has_audio and plan.source_fps == 24
            return super().build(plan, measured)

    p = make_plan(make_video(seconds=2), tmp_path, small_profile_settings, preview=True)
    out = await engine(Spy()).render(p)
    info = await probe(out.path)
    assert (info.width, info.height) == (320, 180)


async def test_failure_removes_output(tmp_path, small_profile_settings):
    src = tmp_path / "bad.mp4"
    src.write_text("text")
    p = make_plan(src, tmp_path, small_profile_settings)
    p.output.write_text("stale")
    with pytest.raises(MediaError):
        await engine().render(p)
    assert not p.output.exists()


def test_hash_canonical_and_every_field():
    original = Recipe()
    assert recipe_hash(original, None) == recipe_hash(
        Recipe.model_validate(dict(reversed(list(original.model_dump().items())))), None
    )
    for field, value in {
        "trim_start": 1,
        "trim_end": 3,
        "crop": {"x": 0, "y": 0, "w": 2, "h": 2},
        "fade_in": 0.1,
        "fade_out": 0.1,
        "gain_db": 1,
        "profile_id": "loud",
        "lead_in": 1,
        "tail_out": 1,
    }.items():
        assert recipe_hash(
            Recipe.model_validate(dict(original.model_dump(), **{field: value})), None
        ) != recipe_hash(original, None)
    norm = NormalizationProfile(id="loud", name="Loud", target_lufs=-13, true_peak=-1, lra=11)
    assert recipe_hash(original, norm) != recipe_hash(original, None)


def test_output_validation_and_zero_tail(tmp_path, small_profile_settings):
    p = make_plan(
        tmp_path / "src.mp4", tmp_path, small_profile_settings, recipe=Recipe(lead_in=0, tail_out=0)
    )
    info = MediaProbe(True, 7.25, 7, 7.25, 320, 180, 24, True, "h264")
    assert not valid_output(info, p.profile)
    t = compiled_timing(p, info)
    assert t.content_end == 7.25 and t.tail_out == 0


async def test_silence_policy_with_trim_and_assets(make_video, small_profile_settings, tmp_path):
    settings = dict(
        small_profile_settings,
        audio={"missing_policy": {"mode": "silence"}},
        fade_in_seconds=0,
        fade_out_seconds=0,
        transitions=[],
    )
    p = make_plan(
        make_video(seconds=4, audio=False),
        tmp_path,
        settings,
        recipe=Recipe(trim_start=1, trim_end=3),
        intro=make_video(name="silent-intro.mp4", seconds=1, audio=False),
    )
    out = await engine().render(p)
    assert out.timing.duration == pytest.approx(7, abs=0.1)
    assert out.integrated_lufs is None and out.true_peak is None


async def test_fades_loudness_default(make_video, small_profile_settings, tmp_path):
    p = make_plan(make_video(seconds=5, volume_db=-30), tmp_path, small_profile_settings)
    out = await engine().render(p)
    assert out.integrated_lufs == pytest.approx(-18, abs=1)


async def test_required_missing_audio_and_encoding_failure(
    make_video, small_profile_settings, tmp_path
):
    p = make_plan(make_video(seconds=2, audio=False), tmp_path, small_profile_settings)
    with pytest.raises(MediaError, match="audio"):
        await engine().render(p)
    assert not p.output.exists()

    class InvalidEncoder(FfmpegCommandBuilder):
        def build(self, plan, measured):
            argv = super().build(plan, measured)
            argv[argv.index("-c:v") + 1] = "invalid-cinema-codec"
            return argv

    p = replace(p, source=make_video(name="good.mp4", seconds=2))
    with pytest.raises(MediaError) as error:
        await engine(InvalidEncoder()).render(p)
    assert len(str(error.value)) <= 2100
    assert "invalid-cinema-codec" in str(error.value) and not p.output.exists()


async def test_probed_output_validation_failure(make_video, small_profile_settings, tmp_path):
    class WrongSize(FfmpegCommandBuilder):
        def build(self, plan, measured):
            argv = super().build(plan, measured)
            index = argv.index("-filter_complex") + 1
            argv[index] = argv[index].replace("320:180", "160:90")
            return argv

    p = make_plan(make_video(seconds=2), tmp_path, small_profile_settings, preview=True)
    with pytest.raises(MediaError, match="dimensions"):
        await engine(WrongSize()).render(p)
    assert not p.output.exists()


async def test_disabled_loudness_fractional_margins(make_video, small_profile_settings, tmp_path):
    settings = dict(small_profile_settings, loudness={"mode": "disabled"})

    class Spy(FfmpegCommandBuilder):
        def build(self, plan, measured):
            assert measured is None
            argv = super().build(plan, measured)
            assert "loudnorm=" not in argv[argv.index("-filter_complex") + 1]
            return argv

    p = make_plan(
        make_video(seconds=2),
        tmp_path,
        settings,
        recipe=Recipe(lead_in=0.01, tail_out=0.01, fade_in=0, fade_out=0, gain_db=3),
    )
    out = await engine(Spy()).render(p)
    assert out.timing.lead_in == 0.042
    assert out.timing.duration == pytest.approx(2 + 2 / 24, abs=0.05)


async def test_output_cannot_alias_source(make_video, small_profile_settings, tmp_path):
    src = make_video(seconds=1)
    before = src.read_bytes()
    p = make_plan(src, tmp_path, small_profile_settings, output=src)
    with pytest.raises(MediaError, match="differ"):
        await engine().render(p)
    assert src.read_bytes() == before


async def test_gain_survives_final_mix_normalization(make_video, small_profile_settings, tmp_path):
    src = make_video(seconds=4, volume_db=-30)
    p = make_plan(
        src, tmp_path, small_profile_settings, recipe=Recipe(fade_in=0, fade_out=0, gain_db=3)
    )
    out = await engine().render(p)
    assert out.integrated_lufs == pytest.approx(-15, abs=1)
    assert out.true_peak is not None and out.true_peak <= -1.3
    assert not list(tmp_path.glob(".*.mix.mp4"))


async def test_render_timeout_cleanup(make_video, small_profile_settings, tmp_path):
    p = make_plan(make_video(seconds=2), tmp_path, small_profile_settings)
    p.output.write_text("stale")
    renderer = RenderEngine(FfmpegCommandBuilder(), timeout_for=lambda _: 0.000001)
    with pytest.raises(MediaError, match="timed out"):
        await renderer.render(p)
    assert not p.output.exists() and not list(tmp_path.glob(".*.mix.mp4"))


async def test_positive_gain_true_peak_after_fades(make_video, small_profile_settings, tmp_path):
    p = make_plan(
        make_video(seconds=4), tmp_path, small_profile_settings, recipe=Recipe(gain_db=24)
    )
    out = await engine().render(p)
    assert out.true_peak is not None and out.true_peak <= -1.3


async def test_final_normalization_cannot_amplify_limited_peaks(
    make_video, small_profile_settings, tmp_path
):
    from cinema_studio.ffmpeg import LoudnessStats
    from cinema_studio.media import measure_loudness

    p = make_plan(
        make_video(seconds=4, volume_db=-30),
        tmp_path,
        small_profile_settings,
        recipe=Recipe(gain_db=24, fade_in=0, fade_out=0, lead_in=0, tail_out=0),
        final_loudness=LoudnessStats(-24, -20, 1, -34, 0),
    )
    # Calibration excludes gain: final normalization amplifies the already limited signal.
    argv = FfmpegCommandBuilder().build(p, LoudnessStats(-51, -48, 1, -61, 0))
    await run_process(argv)
    _, peak = await measure_loudness(p.output)
    assert peak is not None and peak <= -1.5 + 0.3


@pytest.mark.parametrize("aliased_input", ["source", "intro", "outro"])
async def test_hard_link_output_preserves_inputs(
    make_video, small_profile_settings, tmp_path, aliased_input
):
    src = make_video(seconds=2)
    asset = make_video(name="asset.mp4", seconds=2)
    p = make_plan(src, tmp_path, small_profile_settings, preview=True)
    original = src if aliased_input == "source" else asset
    if aliased_input != "source":
        p = replace(p, **{aliased_input: asset})
    before = original.read_bytes()
    p.output.hardlink_to(original)
    with pytest.raises(MediaError, match="differ"):
        await engine().render(p)
    assert original.read_bytes() == before
    assert p.output.exists() and p.output.samefile(original)


@pytest.mark.parametrize(
    "peaks,reductions,fails,mode",
    [
        ([-1.11, -1.4], [0, 0.59], False, "normal"),
        ([-0.5, -1, -1.3], [0, 1.2, 1.9], False, "normal"),
        ([-0.5, -0.5, -0.5], [0, 1.2, 2.4], True, "normal"),
        ([-1.2], [0], False, "normal"),
        ([None], [0], False, "normal"),
        ([-0.5], [0], False, "preview"),
        ([-1.11, -1.4], [0, 0.59], False, "disabled"),
        ([-0.5], [0], False, "disabled_no_gain"),
    ],
)
async def test_encoded_peak_correction_is_bounded(
    tmp_path, small_profile_settings, monkeypatch, peaks, reductions, fails, mode
):
    import cinema_studio.render as render_module

    settings = dict(
        small_profile_settings,
        audio={"missing_policy": {"mode": "silence"}},
        loudness={
            "mode": "two_pass",
            "integrated_lufs": -18,
            "true_peak_dbtp": -1.5,
            "lra_lu": 11,
            "final_mix_normalization": False,
        },
    )
    if mode.startswith("disabled"):
        settings["loudness"] = {"mode": "disabled"}
    src = tmp_path / "source.mp4"
    src.write_bytes(b"source")
    p = make_plan(
        src,
        tmp_path,
        settings,
        preview=mode == "preview",
        recipe=Recipe(gain_db=0 if mode == "disabled_no_gain" else 24),
    )
    builds = []
    measured_regions = []
    remaining_peaks = iter(peaks)

    class Spy(FfmpegCommandBuilder):
        def build(self, plan, measured):
            builds.append(plan)
            return super().build(plan, measured)

    async def fake_probe(path):
        duration = 4 if path == src else 8
        return MediaProbe(True, duration, duration, duration, 320, 180, 24, path != src, "h264")

    async def fake_run(argv, **kwargs):
        p.output.write_bytes(f"encode-{len(builds)}".encode())
        return b"", b""

    async def fake_measure(path, *, start, end):
        measured_regions.append((path, start, end))
        return -18, next(remaining_peaks)

    monkeypatch.setattr(render_module, "probe", fake_probe)
    monkeypatch.setattr(render_module, "run_process", fake_run)
    monkeypatch.setattr(render_module, "measure_loudness", fake_measure)
    if fails:
        with pytest.raises(MediaError, match="true peak above ceiling"):
            await engine(Spy()).render(p)
        assert not p.output.exists()
    else:
        out = await engine(Spy()).render(p)
        assert out.true_peak == peaks[-1]
        import hashlib

        assert out.sha256 == hashlib.sha256(p.output.read_bytes()).hexdigest()
    assert len(builds) == len(reductions)
    assert [plan.peak_reduction_db for plan in builds] == pytest.approx(reductions)
    assert measured_regions == [(p.output, 2, 6)] * len(reductions)


async def test_high_gain_aac_output_meets_measured_peak_ceiling(
    make_video, small_profile_settings, tmp_path
):
    from cinema_studio.media import measure_loudness

    video = make_video(seconds=4)
    source = tmp_path / "multiple-tones.mp4"
    await run_process(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(video),
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.3*sin(2*PI*997*t)+0.3*sin(2*PI*1499*t):s=48000:d=4",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ]
    )
    settings = dict(small_profile_settings, audio={"bitrate_kbps": 64})
    p = make_plan(source, tmp_path, settings, recipe=Recipe(gain_db=24))
    out = await engine().render(p)
    codecs, _ = await run_process(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            str(out.path),
        ]
    )
    assert codecs.strip() == b"aac"
    _, peak = await measure_loudness(
        out.path, start=out.timing.content_start, end=out.timing.content_end
    )
    assert peak is not None and peak <= -1.5 + 0.3
    assert out.true_peak == peak
