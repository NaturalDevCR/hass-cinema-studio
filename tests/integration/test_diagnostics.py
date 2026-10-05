"""Redacted diagnostics and the integration's distributable brand artwork."""

import struct
import zlib
from pathlib import Path

import pytest
from homeassistant.components.diagnostics import REDACTED
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cinema_studio.const import DOMAIN
from custom_components.cinema_studio.diagnostics import async_get_config_entry_diagnostics
from tests.integration.studio_support import mock_offline, mock_studio, setup, write_renders

pytestmark = pytest.mark.integration


async def test_diagnostics_redacts_token_and_summarizes_runtime(hass, loaded_entry, aioclient_mock):
    mock_offline(aioclient_mock)  # keep the selection event queued
    manager = loaded_entry.runtime_data.manager
    await manager.async_select(collection_ref="regular", season_ref=None, dry_run=False)
    await hass.async_block_till_done(wait_background_tasks=True)
    before = manager._state()
    result = await async_get_config_entry_diagnostics(hass, loaded_entry)
    assert result["entry_data"] == {"host": "studio", "port": 8099, "token": REDACTED}
    assert result["options"] == dict(loaded_entry.options)  # holds no credentials
    assert result["catalog"] == {
        "revision": 7,
        "seasons": 2,
        "collections": 2,
        "clips": 5,
        "invalid_clips": 1,
    }
    assert result["verification"] == {"verified": 4, "unverified": 1}
    assert [pin["render_id"] for pin in result["pins"]] == [
        manager.last_selection("regular")["render_id"]
    ]
    assert result["pins"][0]["expires_at"].endswith("Z")
    assert result["activation"] == {
        "last_effective_season": None,
        "last_effective_collection": None,
    }
    assert result["history"] == {"regular": 1}
    assert result["selection_queue"] == 1
    assert result["connected"] is True
    assert result["ready"] is True
    assert "secret" not in repr(result)
    assert loaded_entry.data["token"] == "secret"
    assert manager._state() == before


async def test_diagnostics_redacts_token_in_options_and_nested_fields(
    hass, aioclient_mock, payload, media_root
):
    write_renders(media_root, payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "studio", "port": 8099, "token": "secret", "extra": {"api_token": "s1"}},
        unique_id="studio-id",
        options={"scan_interval": 3600, "token": "s2", "nested": [{"api_token": "s3"}]},
    )
    entry.add_to_hass(hass)
    mock_studio(aioclient_mock, payload)
    await setup(hass, entry)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["entry_data"]["token"] == REDACTED
    assert result["entry_data"]["extra"] == {"api_token": REDACTED}
    assert result["options"]["token"] == REDACTED
    assert result["options"]["nested"] == [{"api_token": REDACTED}]
    assert result["options"]["scan_interval"] == 3600
    for leaked in ("secret", "s1", "s2", "s3"):
        assert f"'{leaked}'" not in repr(result)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_diagnostics_offline_and_idle(hass, loaded_entry):
    loaded_entry.runtime_data.coordinator.data.connected = False
    result = await async_get_config_entry_diagnostics(hass, loaded_entry)
    assert result["connected"] is False
    assert result["pins"] == []
    assert result["history"] == {}
    assert result["selection_queue"] == 0


def _pixel(raw: bytes, x: int, y: int) -> tuple[int, int, int, int]:
    """Decode a PNG written with filter 0 on every row, 8-bit RGBA."""
    pos, chunks = 8, {}
    while pos < len(raw):
        (length,) = struct.unpack(">I", raw[pos : pos + 4])
        chunks.setdefault(raw[pos + 4 : pos + 8], raw[pos + 8 : pos + 8 + length])
        pos += 12 + length
    assert chunks[b"IHDR"][8:10] == b"\x08\x06"
    data = zlib.decompress(chunks[b"IDAT"])
    start = y * (1 + 256 * 4) + 1 + x * 4
    assert data[start - 1 - x * 4] == 0
    return tuple(data[start : start + 4])  # type: ignore[return-value]


def test_brand_icon_is_amber_square_with_white_film_glyph():
    raw = (Path("custom_components/cinema_studio/brand") / "icon.png").read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert raw[12:16] == b"IHDR"
    assert struct.unpack(">II", raw[16:24]) == (256, 256)
    assert _pixel(raw, 0, 0)[3] == 0  # rounded corner is transparent
    assert _pixel(raw, 20, 128) == (0xF5, 0x9E, 0x0B, 255)  # amber #f59e0b
    assert _pixel(raw, 60, 128) == (255, 255, 255, 255)  # film body
