"""User, Supervisor discovery, and options flows."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cinema_studio.const import DOMAIN

pytestmark = pytest.mark.integration
DATA = {"host": "studio", "port": 8099, "token": "secret"}
HEALTH = {"status": "ok", "version": "1.0.0", "api_version": 1, "instance_id": "studio-id"}
URL = "http://studio:8099/api/v1/health"


@pytest.fixture(autouse=True)
def mock_entry_setup():
    with patch("custom_components.cinema_studio.async_setup_entry", return_value=True):
        yield


async def test_user_success(hass, aioclient_mock):
    aioclient_mock.get(URL, json=HEALTH)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cinema Studio"
    assert result["data"] == DATA
    assert result["result"].unique_id == "studio-id"
    await hass.async_block_till_done()


@pytest.mark.parametrize("status, error", [(503, "cannot_connect"), (401, "invalid_auth")])
async def test_user_errors(hass, aioclient_mock, status, error):
    aioclient_mock.get(URL, status=status)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=DATA
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


def discovery(token="secret"):
    return HassioServiceInfo(
        config={**DATA, "token": token, "instance_id": "studio-id"},
        name="Cinema Studio",
        slug="cinema_studio",
        uuid="1234",
    )


async def test_hassio_success(hass, aioclient_mock):
    aioclient_mock.get(URL, json=HEALTH)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=discovery()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hassio_confirm"
    assert result["description_placeholders"] == {"addon": "Cinema Studio"}
    assert aioclient_mock.call_count == 0
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == DATA
    assert result["result"].unique_id == "studio-id"
    await hass.async_block_till_done()


async def test_hassio_rediscovery(hass, aioclient_mock):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="studio-id")
    entry.add_to_hass(hass)
    info = discovery("rotated")
    info.config["host"] = "new-studio"
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data == {**DATA, "host": "new-studio", "token": "rotated"}
    assert aioclient_mock.call_count == 0


async def test_hassio_different_instance(hass, aioclient_mock):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="studio-id")
    entry.add_to_hass(hass)
    info = discovery("rotated")
    info.config["instance_id"] = "another-studio"
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert entry.data == DATA
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize("status, error", [(503, "cannot_connect"), (403, "invalid_auth")])
async def test_hassio_errors(hass, aioclient_mock, status, error):
    aioclient_mock.get(URL, status=status)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=discovery()
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    if error == "invalid_auth":
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == error
    else:
        assert result["step_id"] == "hassio_confirm"
        assert result["errors"] == {"base": error}


async def test_hassio_identity_mismatch(hass, aioclient_mock):
    aioclient_mock.get(URL, json={**HEALTH, "instance_id": "another-studio"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=discovery()
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_single_instance(hass, aioclient_mock):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="studio-id")
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert aioclient_mock.call_count == 0


async def test_options(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="studio-id")
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    options = {
        "season_entity": "input_select.season",
        "scan_interval": 60.0,
        "history_reset_mode": "daily",
        "history_reset_time": "04:30:00",
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], options)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == options


@pytest.mark.parametrize(
    "instance_id, reason",
    [
        ("studio-id", "reauth_successful"),
        ("another-studio", "unique_id_mismatch"),
    ],
)
async def test_reauth(hass, aioclient_mock, instance_id, reason):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="studio-id")
    entry.add_to_hass(hass)
    aioclient_mock.get(URL, json={**HEALTH, "instance_id": instance_id})
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=DATA,
    )
    assert result["step_id"] == "user"
    with patch.object(hass.config_entries, "async_reload", return_value=True) as reload:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**DATA, "token": "rotated"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert entry.data["token"] == ("rotated" if instance_id == "studio-id" else "secret")
    assert reload.await_count == (1 if instance_id == "studio-id" else 0)


async def test_options_defaults_and_optional_season(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"]({}) == {
        "scan_interval": 30,
        "history_reset_mode": "on_exhaustion",
        "history_reset_time": "00:00:00",
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        "scan_interval": 30,
        "history_reset_mode": "on_exhaustion",
        "history_reset_time": "00:00:00",
    }


async def test_options_current_values(hass):
    options = {
        "season_entity": "sensor.season",
        "scan_interval": 90,
        "history_reset_mode": "daily",
        "history_reset_time": "03:00:00",
    }
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, options=options)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"]({}) == {
        "scan_interval": 90,
        "history_reset_mode": "daily",
        "history_reset_time": "03:00:00",
    }
    suggested = {
        field.schema: field.description["suggested_value"]
        for field in result["data_schema"].schema
        if field.description and "suggested_value" in field.description
    }
    assert suggested == {"season_entity": "sensor.season"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 90.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        "scan_interval": 90,
        "history_reset_mode": "daily",
        "history_reset_time": "03:00:00",
    }


@pytest.mark.parametrize(
    "config",
    [
        {},
        *[
            {
                key: value
                for key, value in {**DATA, "instance_id": "studio-id"}.items()
                if key != missing
            }
            for missing in ("host", "port", "token", "instance_id")
        ],
        *[
            {**DATA, "instance_id": "studio-id", key: value}
            for key, value in [
                ("host", 1),
                ("host", " "),
                ("port", "8099"),
                ("port", True),
                ("port", 0),
                ("port", 65536),
                ("token", None),
                ("token", ""),
                ("instance_id", []),
                ("instance_id", ""),
            ]
        ],
    ],
)
async def test_invalid_discovery(hass, aioclient_mock, config):
    info = discovery()
    info.config = config
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_discovery_info"
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize("source", ["user", "reauth", "reconfigure"])
async def test_strip_credentials(hass, aioclient_mock, source):
    context = {"source": source}
    if source != "user":
        entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="studio-id")
        entry.add_to_hass(hass)
        context["entry_id"] = entry.entry_id
    aioclient_mock.get(URL, json=HEALTH)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context=context, data=DATA if source == "reauth" else None
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**DATA, "host": " studio ", "token": " secret "}
    )
    assert result["type"] is (
        FlowResultType.CREATE_ENTRY if source == "user" else FlowResultType.ABORT
    )
    assert (result["data"] if source == "user" else entry.data) == DATA
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer secret"
    await hass.async_block_till_done()


@pytest.mark.parametrize("source", ["user", "reauth", "reconfigure"])
async def test_empty_host(hass, aioclient_mock, source):
    context = {"source": source}
    if source != "user":
        entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="studio-id")
        entry.add_to_hass(hass)
        context["entry_id"] = entry.entry_id
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context=context, data=DATA if source == "reauth" else None
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**DATA, "host": "  "}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"host": "invalid_host"}
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize(
    "instance_id,reason", [("studio-id", "reconfigure_successful"), ("other", "unique_id_mismatch")]
)
async def test_reconfigure(hass, aioclient_mock, instance_id, reason):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="studio-id")
    entry.add_to_hass(hass)
    new_data = {"host": "new-studio", "port": 8100, "token": "rotated"}
    aioclient_mock.get(
        "http://new-studio:8100/api/v1/health", json={**HEALTH, "instance_id": instance_id}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert result["step_id"] == "reconfigure"
    with patch.object(hass.config_entries, "async_reload", return_value=True) as reload:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], new_data)
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert entry.data == (new_data if instance_id == "studio-id" else DATA)
    assert reload.await_count == (1 if instance_id == "studio-id" else 0)
