import pytest


@pytest.fixture
def catalog_payload() -> dict:
    return {
        "contract_version": 1,
        "revision": 4,
        "instance_id": "abc",
        "seasons": [
            {
                "id": "regular",
                "name": "Regular",
                "color": "",
                "icon": "",
                "start": None,
                "end": None,
                "priority": 0,
                "collection_id": "regular",
            }
        ],
        "collections": [
            {
                "id": "regular",
                "name": "Regular",
                "color": "",
                "icon": "",
                "playback_mode": "random",
                "order": [],
                "enabled": True,
            }
        ],
        "clips": [
            {
                "id": "clip-a",
                "collection_id": "regular",
                "title": "Film",
                "source_name": "film.mp4",
                "enabled": True,
                "sort_key": "Film",
                "render_pending": False,
                "render": {
                    "id": "r1",
                    "n": 1,
                    "relative_path": "cinema-studio/renders/clip-a/a.mp4",
                    "media_path": "cinema-studio/renders/clip-a/a.mp4",
                    "size": 5,
                    "sha256": "abc",
                    "duration": 8.0,
                    "content_start": 2.0,
                    "content_end": 6.0,
                    "lead_in": 2.0,
                    "tail_out": 2.0,
                    "content_duration": 4.0,
                    "timing_source": "measured",
                    "profile_fingerprint": "fp",
                    "integrated_lufs": None,
                },
            }
        ],
    }


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make custom_components/ discoverable."""
