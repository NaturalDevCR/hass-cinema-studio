"""Action registration and delegation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.cinema_studio.const import DOMAIN
from custom_components.cinema_studio.services import async_register_services

pytestmark = pytest.mark.integration


async def test_actions(hass):
    manager = SimpleNamespace(
        async_select=AsyncMock(return_value={"clip_id": "a"}),
        async_reset=AsyncMock(return_value=["regular"]),
        legacy=SimpleNamespace(async_run=AsyncMock()),
    )
    coordinator = SimpleNamespace(async_request_refresh=AsyncMock())
    entry = SimpleNamespace(runtime_data=SimpleNamespace(manager=manager, coordinator=coordinator))
    await async_register_services(hass)
    await async_register_services(hass)
    with patch.object(hass.config_entries, "async_loaded_entries", return_value=[entry]):
        response = await hass.services.async_call(
            DOMAIN,
            "select_next_clip",
            {"collection_id": "regular", "season": "Regular", "dry_run": True},
            blocking=True,
            return_response=True,
        )
        assert response == {"clip_id": "a"}
        manager.async_select.assert_awaited_once_with(
            collection_ref="regular", season_ref="Regular", dry_run=True
        )
        await hass.services.async_call(DOMAIN, "reset_history", {}, blocking=True)
        manager.async_reset.assert_awaited_once_with(None)
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        coordinator.async_request_refresh.assert_awaited_once()
        await hass.services.async_call(
            DOMAIN, "import_legacy", {"history_only": True}, blocking=True
        )
        manager.legacy.async_run.assert_awaited_once_with(True)


async def test_unloaded(hass):
    await async_register_services(hass)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "select_next_clip", {}, blocking=True)
    assert err.value.translation_key == "not_ready"


@pytest.mark.parametrize("language", ["en", "es"])
def test_service_descriptions(language, monkeypatch, tmp_path):
    import json
    from pathlib import Path

    monkeypatch.chdir(tmp_path)
    data = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / f"custom_components/cinema_studio/translations/{language}.json"
        ).read_text()
    )
    for service in data["services"].values():
        assert service["description"] != service["name"]
        for field in service.get("fields", {}).values():
            assert field["description"]
