"""Studio HTTP client contract tests."""

import json
from unittest.mock import patch

import pytest
from aiohttp import ClientConnectionError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.cinema_studio.api import (
    StudioAuthError,
    StudioClient,
    StudioConnectionError,
    StudioRequestError,
)

pytestmark = pytest.mark.integration
BASE = "http://studio:8099/api/v1"


@pytest.fixture
async def client(hass, aioclient_mock):
    return StudioClient(async_get_clientsession(hass), "studio", 8099, "secret", "entry-1")


async def test_health_and_bearer(client, aioclient_mock):
    health = {"status": "ok", "version": "1.0.0", "api_version": 1, "instance_id": "studio-id"}
    aioclient_mock.get(f"{BASE}/health", json=health)
    assert await client.health() == health
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer secret"
    assert aioclient_mock.mock_calls[0][3]["X-Cinema-Consumer"] == "entry-1"


async def test_ten_second_timeout(hass, client, aioclient_mock):
    aioclient_mock.get(
        f"{BASE}/health",
        json={"status": "ok", "version": "1.0.0", "api_version": 1, "instance_id": "studio-id"},
    )
    with patch.object(
        async_get_clientsession(hass), "_request", wraps=aioclient_mock.match_request
    ) as request:
        await client.health()
    assert request.call_args.kwargs["timeout"].total == 10


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("endpoint", ["health", "catalog", "post_selections"])
async def test_auth_error(client, aioclient_mock, status, endpoint):
    if endpoint == "post_selections":
        aioclient_mock.post(f"{BASE}/selections", status=status)
        operation = client.post_selections([])
    else:
        aioclient_mock.get(f"{BASE}/{endpoint}", status=status)
        operation = getattr(client, endpoint)()
    with pytest.raises(StudioAuthError):
        await operation


async def test_catalog_200(client, aioclient_mock, catalog_payload):
    aioclient_mock.get(f"{BASE}/catalog", json=catalog_payload, headers={"ETag": '"rev-7"'})
    result = await client.catalog()
    assert result.data == catalog_payload
    assert result.etag == '"rev-7"'


async def test_catalog_304(client, aioclient_mock):
    aioclient_mock.get(f"{BASE}/catalog", status=304)
    result = await client.catalog('"rev-7"')
    assert result.data is None
    assert result.etag == '"rev-7"'
    assert aioclient_mock.mock_calls[0][3]["If-None-Match"] == '"rev-7"'


@pytest.mark.parametrize("error", [TimeoutError(), ClientConnectionError()])
async def test_network_error(client, aioclient_mock, error):
    aioclient_mock.get(f"{BASE}/health", exc=error)
    with pytest.raises(StudioConnectionError):
        await client.health()


@pytest.mark.parametrize("status", [404, 500, 503])
async def test_http_error(client, aioclient_mock, status):
    aioclient_mock.get(f"{BASE}/health", status=status)
    with pytest.raises(StudioConnectionError):
        await client.health()


@pytest.mark.parametrize("payload", [[], {"status": "ok"}, "bad json"])
async def test_invalid_health(client, aioclient_mock, payload):
    aioclient_mock.get(f"{BASE}/health", text=json.dumps(payload))
    with pytest.raises(StudioConnectionError):
        await client.health()


async def test_post_selections(client, aioclient_mock):
    events = [
        {
            "selection_id": "sel-1",
            "clip_id": "clip-a",
            "render_id": "r1",
            "catalog_revision": 4,
            "selected_at": "2026-10-03T12:00:00Z",
        }
    ]
    aioclient_mock.post(f"{BASE}/selections", status=204)
    await client.post_selections(events)
    assert aioclient_mock.mock_calls[0][2] == {"events": events}
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer secret"


@pytest.mark.parametrize("endpoint", ["health", "catalog"])
async def test_malformed_json(client, aioclient_mock, endpoint):
    aioclient_mock.get(f"{BASE}/{endpoint}", text="{")
    with pytest.raises(StudioConnectionError):
        await getattr(client, endpoint)()


async def test_legacy_endpoints(client, aioclient_mock):
    stage = {"phase": "stage", "manifest": {}}
    commit = {"phase": "commit", "run_id": "run-1", "clips": []}
    aioclient_mock.post(f"{BASE}/import/legacy", json={"run_id": "run-1"})
    assert await client.legacy_stage(stage) == {"run_id": "run-1"}
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/import/legacy", json={"catalog_revision": 4})
    assert await client.legacy_commit(commit) == {"catalog_revision": 4}
    assert all(call[3]["X-Cinema-Consumer"] == "entry-1" for call in aioclient_mock.mock_calls)


@pytest.mark.parametrize("operation", ["legacy_stage", "legacy_commit"])
async def test_legacy_long_timeout(hass, client, aioclient_mock, operation):
    aioclient_mock.post(f"{BASE}/import/legacy", json={"run_id": "run-1"})
    with patch.object(
        async_get_clientsession(hass), "_request", wraps=aioclient_mock.match_request
    ) as request:
        await getattr(client, operation)({"phase": "x"})
    assert request.call_count == 1
    assert request.call_args.kwargs["timeout"].total == 1800


@pytest.mark.parametrize(
    ("status", "detail"),
    [(409, "another run is active"), (422, [{"loc": ["body"], "msg": "bad"}]), (400, "nope")],
)
async def test_request_error_with_detail(client, aioclient_mock, status, detail):
    aioclient_mock.post(f"{BASE}/import/legacy", status=status, json={"detail": detail})
    with pytest.raises(StudioRequestError) as err:
        await client.legacy_commit({"phase": "commit"})
    assert err.value.status == status
    assert err.value.detail == detail
    assert isinstance(err.value, StudioConnectionError)
    assert not isinstance(err.value, StudioAuthError)


@pytest.mark.parametrize("body", ["not json", json.dumps({"other": 1}), json.dumps([1])])
async def test_4xx_without_detail_is_plain_connection_error(client, aioclient_mock, body):
    aioclient_mock.post(f"{BASE}/selections", status=409, text=body)
    with pytest.raises(StudioConnectionError) as err:
        await client.post_selections([])
    assert not isinstance(err.value, StudioRequestError)


async def test_5xx_with_detail_is_plain_connection_error(client, aioclient_mock):
    aioclient_mock.get(f"{BASE}/health", status=503, json={"detail": "starting"})
    with pytest.raises(StudioConnectionError) as err:
        await client.health()
    assert not isinstance(err.value, StudioRequestError)


async def test_304_only_valid_for_catalog(client, aioclient_mock):
    aioclient_mock.get(f"{BASE}/health", status=304)
    with pytest.raises(StudioConnectionError):
        await client.health()
