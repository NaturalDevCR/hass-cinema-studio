"""Shared setup for entity and diagnostics tests."""

import copy
from datetime import UTC, datetime
from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cinema_studio.const import DOMAIN

BASE = "http://studio:8099/api/v1"
JULY = datetime(2026, 7, 1, 12, tzinfo=UTC)
OCTOBER = datetime(2026, 10, 4, 12, tzinfo=UTC)


def clip_for(template: dict[str, Any], clip_id: str, collection: str, size: int, **extra: Any):
    clip = copy.deepcopy(template)
    path = f"cinema-studio/renders/{clip_id}/{clip_id}.mp4"
    clip.update(id=clip_id, collection_id=collection, title=clip_id.title(), **extra)
    clip["render"].update(id=f"r-{clip_id}", relative_path=path, media_path=path, size=size)
    return clip


def build_payload(catalog_payload):
    """Regular (a, b, disabled e, unverified c, invalid x) plus a Halloween collection (d)."""
    data = copy.deepcopy(catalog_payload)
    data["revision"] = 7
    template = data["clips"][0]
    data["seasons"].append(
        {
            "id": "halloween",
            "name": "Halloween",
            "color": "#f97316",
            "icon": "mdi:ghost",
            "start": "10-01",
            "end": "10-31",
            "priority": 10,
            "collection_id": "spooky",
        }
    )
    data["seasons"][0]["color"] = "#64748b"
    data["collections"][0]["icon"] = "mdi:movie"
    data["collections"].append(
        {**data["collections"][0], "id": "spooky", "name": "Spooky", "icon": "mdi:ghost"}
    )
    invalid = clip_for(template, "x", "regular", 5)
    invalid["render"]["duration"] = 0
    data["clips"] = [
        clip_for(template, "clip-a", "regular", 5),
        clip_for(template, "clip-b", "regular", 7),
        clip_for(template, "clip-c", "regular", 9),
        clip_for(template, "clip-d", "spooky", 6),
        clip_for(template, "clip-e", "regular", 8, enabled=False),
        invalid,
    ]
    return data


def write_renders(media_root, payload, skip=("clip-c", "x")):
    for clip in payload["clips"]:
        if clip["id"] in skip:
            continue
        path = media_root / clip["render"]["relative_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"0" * clip["render"]["size"])


def mock_studio(aioclient_mock, payload, version="1.0"):
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{BASE}/health",
        json={"status": "ok", "version": version, "api_version": 1, "instance_id": "studio-id"},
    )
    aioclient_mock.get(f"{BASE}/catalog", json=payload)
    aioclient_mock.post(f"{BASE}/selections", status=204)


def mock_offline(aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", exc=TimeoutError())
    aioclient_mock.post(f"{BASE}/selections", exc=TimeoutError())


def new_entry(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "studio", "port": 8099, "token": "secret"},
        unique_id="studio-id",
        options={"scan_interval": 3600, **(options or {})},
    )
    entry.add_to_hass(hass)
    return entry


async def setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
