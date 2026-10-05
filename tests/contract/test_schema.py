import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2] / "contract"
SCHEMA = json.loads((ROOT / "selection_response.schema.json").read_text())

VALID = {
    "contract_version": 1,
    "instance_id": "abc",
    "catalog_revision": 3,
    "selection_id": "s1",
    "selected_at": "2026-10-05T03:30:00Z",
    "collection_id": "regular",
    "season": "regular",
    "requested_season": "regular",
    "season_source": "entity",
    "season_fallback": False,
    "playback_mode": "random",
    "history_reset": False,
    "activation_reset": False,
    "clip_id": "015a9551-1372-4e6c-85e6-288852848fb2",
    "title": "titanic-1",
    "source_name": "titanic-1.mp4",
    "render_id": "f" * 32,
    "render_n": 1,
    "relative_output_path": "cinema-studio/renders/015a9551-1372-4e6c-85e6-288852848fb2/x.mp4",
    "media_content_id": "media-source://media_source/local/cinema-studio/renders/015a9551-1372-4e6c-85e6-288852848fb2/x.mp4",
    "media_content_type": "video",
    "duration_seconds": 154.133,
    "duration": 154.133,
    "content_duration": 150.125,
    "lead_in_duration": 2.0,
    "tail_out_duration": 2.008,
    "content_start_offset": 2.0,
    "content_end_offset": 152.125,
    "timing_source": "legacy_worker",
    "timing_verified": True,
    "file_verified": True,
    "render_pending": False,
    "output_is_stale": False,
    "size": 123,
    "sha256": "a" * 64,
    "profile_fingerprint": "p",
}


def test_schema_is_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)


def test_valid_example_passes() -> None:
    Draft202012Validator(SCHEMA).validate(VALID)


def test_missing_key_fails() -> None:
    broken = dict(VALID)
    del broken["timing_verified"]
    assert list(Draft202012Validator(SCHEMA).iter_errors(broken))


def test_unverified_fails() -> None:
    assert list(Draft202012Validator(SCHEMA).iter_errors({**VALID, "file_verified": False}))
