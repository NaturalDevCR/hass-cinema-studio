import pytest

from tests.integration.studio_support import (
    JULY,
    build_payload,
    mock_studio,
    new_entry,
    setup,
    write_renders,
)


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


@pytest.fixture(autouse=True)
def media_root(hass, tmp_path, catalog_payload):
    """Isolate all integration media writes and seed the published render."""
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    path = tmp_path / "media" / catalog_payload["clips"][0]["render"]["relative_path"]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"12345")
    return tmp_path / "media"


@pytest.fixture
def make_render_file(media_root):
    """Create a render at the shared catalog filename convention."""

    def create(clip_id, render_id, n, size):
        path = media_root / "cinema-studio/renders" / clip_id / f"{clip_id}-r{n}-{render_id}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"0" * size)
        return path

    return create


@pytest.fixture
def payload(catalog_payload):
    """A richer catalog: two collections, two seasons, one unverified and one invalid clip."""
    return build_payload(catalog_payload)


@pytest.fixture
def july(freezer):
    """Pin the clock to July so season tests do not depend on the real calendar."""
    freezer.move_to(JULY)
    return freezer


@pytest.fixture
async def loaded_entry(hass, july, aioclient_mock, payload, media_root):
    write_renders(media_root, payload)
    entry = new_entry(hass)
    mock_studio(aioclient_mock, payload)
    await setup(hass, entry)
    return entry
