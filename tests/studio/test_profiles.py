import pytest

from cinema_studio.profiles import (
    AudioSettings,
    ProcessingProfile,
    RequiredAudio,
    validate_profile,
)


def test_invalid_dimensions_are_rejected():
    with pytest.raises(ValueError):
        validate_profile(ProcessingProfile(video={"width": 0}))


def test_crf_and_bitrate_conflict_is_rejected():
    with pytest.raises(ValueError):
        validate_profile(
            ProcessingProfile(video={"quality": {"mode": "crf", "crf": 23, "bitrate_kbps": 1000}})
        )


def test_unsafe_extension_is_rejected():
    with pytest.raises(ValueError):
        validate_profile(ProcessingProfile(output={"extension": "../movie"}))


def test_unsupported_transition_is_rejected():
    with pytest.raises(ValueError):
        validate_profile(ProcessingProfile(transitions=[{"type": "wipe", "duration_seconds": 1}]))


def test_invalid_lufs_target_is_rejected():
    with pytest.raises(ValueError):
        validate_profile(ProcessingProfile(loudness={"mode": "two_pass", "integrated_lufs": 2}))


def test_audio_policy_conflict_is_rejected():
    settings = AudioSettings.model_construct(missing_policy=RequiredAudio(), fallback="silence")
    with pytest.raises(ValueError, match="required audio"):
        settings.validate_policy()


def test_fades_must_fit_minimum_segment_duration():
    with pytest.raises(ValueError, match="minimum segment duration"):
        validate_profile(
            ProcessingProfile(
                fade_in_seconds=1,
                fade_out_seconds=1.5,
                minimum_segment_duration_seconds=2,
            )
        )


@pytest.mark.parametrize("reference", ["/tmp/intro.mp4", "../intro.mp4", "assets/../intro.mp4"])
def test_asset_references_reject_absolute_and_traversal_paths(reference):
    with pytest.raises(ValueError):
        ProcessingProfile(intro_reference=reference)


def test_asset_reference_accepts_safe_relative_path():
    assert (
        ProcessingProfile(intro_reference="intros/intro.mp4").intro_reference == "intros/intro.mp4"
    )


def test_hardware_acceleration_is_disabled_by_default():
    assert validate_profile(ProcessingProfile()).hardware_acceleration is False


def test_timeout_seconds_per_minute_defaults_to_a_validated_allowance():
    profile = validate_profile(ProcessingProfile())
    assert profile.timeout_seconds == 300
    assert profile.timeout_seconds_per_minute == 120


@pytest.mark.parametrize("value", [0, -1, 3601])
def test_timeout_seconds_per_minute_rejects_out_of_range_values(value):
    with pytest.raises(ValueError):
        ProcessingProfile(timeout_seconds_per_minute=value)


def test_rate_control_and_keyframe_fields_default_to_unset():
    video = validate_profile(ProcessingProfile()).video
    assert video.maxrate_kbps is None
    assert video.bufsize_kbps is None
    assert video.keyframe_interval_seconds is None


@pytest.mark.parametrize("field", ["maxrate_kbps", "bufsize_kbps", "keyframe_interval_seconds"])
def test_rate_control_fields_reject_non_positive_values(field):
    with pytest.raises(ValueError):
        ProcessingProfile(video={field: 0})


def test_rate_control_fields_accept_positive_values():
    video = validate_profile(
        ProcessingProfile(
            video={
                "maxrate_kbps": 8000,
                "bufsize_kbps": 16000,
                "keyframe_interval_seconds": 2.0,
            }
        )
    ).video
    assert video.maxrate_kbps == 8000
    assert video.bufsize_kbps == 16000
    assert video.keyframe_interval_seconds == 2.0


pytestmark = pytest.mark.studio


def test_settings_production_and_fingerprints():
    import json
    from pathlib import Path

    from cinema_studio.profiles import DEFAULT_PROFILE_ID, profile_fingerprint, validate_settings

    settings = json.loads(Path(".superpowers/sdd/production-profile.json").read_text())["settings"]
    profile = ProcessingProfile.model_validate(settings)
    assert validate_settings(settings) == profile.model_dump(mode="json")
    assert DEFAULT_PROFILE_ID == "compatibility-4k-loudness"
    first = profile_fingerprint(profile, {"intro_fingerprint": "one", "outro_fingerprint": "two"})
    assert first == profile_fingerprint(
        profile, {"outro_fingerprint": "two", "intro_fingerprint": "one"}
    )
    assert first != profile_fingerprint(
        profile, {"intro_fingerprint": "changed", "outro_fingerprint": "two"}
    )
    assert first != profile_fingerprint(
        profile.model_copy(update={"fade_in_seconds": 2}),
        {"intro_fingerprint": "one", "outro_fingerprint": "two"},
    )


def test_asset_resolution_is_contained(paths, tmp_path):
    from cinema_studio.profiles import resolve_profile_assets

    paths.assets_dir.mkdir(parents=True)
    profile = ProcessingProfile(intro_reference="intro.mp4")
    assert resolve_profile_assets(profile, paths) == (paths.assets_dir / "intro.mp4", None)
    (paths.assets_dir / "intro.mp4").symlink_to(tmp_path / "escape.mp4")
    with pytest.raises(ValueError, match="escapes"):
        resolve_profile_assets(profile, paths)


@pytest.mark.parametrize("field", ["fade_in_seconds", "fade_out_seconds"])
def test_profile_rejects_nonfinite_values(field):
    with pytest.raises(ValueError):
        ProcessingProfile.model_validate({field: float("nan")})
