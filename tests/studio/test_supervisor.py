"""Supervisor and Core proxy client contracts, against a mock transport."""

import json
from collections.abc import Callable

import httpx
import pytest

from cinema_studio.supervisor import SupervisorClient, SupervisorError, describe_error

pytestmark = pytest.mark.studio

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler, token: str | None = "sup-token") -> SupervisorClient:
    return SupervisorClient(token, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def recorder(response: httpx.Response) -> tuple[list[httpx.Request], Handler]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    return seen, handler


def test_available_follows_the_token():
    assert SupervisorClient("token").available
    assert not SupervisorClient(None).available
    assert not SupervisorClient("").available


async def test_unavailable_client_refuses_without_a_request():
    seen, handler = recorder(httpx.Response(200, json={"data": {}}))
    client = make_client(handler, token=None)
    with pytest.raises(SupervisorError):
        await client.self_info()
    with pytest.raises(SupervisorError):
        await client.fire_event("x", {})
    assert seen == []
    await client.aclose()


async def test_self_info_unwraps_data_and_authenticates():
    seen, handler = recorder(httpx.Response(200, json={"result": "ok", "data": {"hostname": "h"}}))
    client = make_client(handler)
    assert await client.self_info() == {"hostname": "h"}
    request = seen[0]
    assert (request.method, str(request.url)) == ("GET", "http://supervisor/addons/self/info")
    assert request.headers["authorization"] == "Bearer sup-token"
    await client.aclose()


async def test_core_config_returns_the_raw_document():
    seen, handler = recorder(httpx.Response(200, json={"internal_url": "http://ha:8123"}))
    client = make_client(handler)
    assert await client.core_config() == {"internal_url": "http://ha:8123"}
    assert str(seen[0].url) == "http://supervisor/core/api/config"
    await client.aclose()


async def test_core_and_network_info_unwrap_data():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"path": request.url.path}})

    client = make_client(handler)
    assert await client.core_info() == {"path": "/core/info"}
    assert await client.network_info() == {"path": "/network/info"}
    await client.aclose()


async def test_publish_discovery_posts_the_service_payload():
    seen, handler = recorder(httpx.Response(200, json={"result": "ok", "data": {"uuid": "u-1"}}))
    client = make_client(handler)
    config = {"host": "h", "port": 8099, "token": "t", "instance_id": "i"}
    assert await client.publish_discovery(config) == "u-1"
    request = seen[0]
    assert (request.method, str(request.url)) == ("POST", "http://supervisor/discovery")
    assert request.headers["authorization"] == "Bearer sup-token"
    assert json.loads(request.content) == {"service": "cinema_studio", "config": config}
    await client.aclose()


async def test_delete_discovery_targets_the_uuid():
    seen, handler = recorder(httpx.Response(200, json={"result": "ok", "data": {}}))
    client = make_client(handler)
    await client.delete_discovery("u-1")
    assert (seen[0].method, str(seen[0].url)) == ("DELETE", "http://supervisor/discovery/u-1")
    await client.aclose()


async def test_fire_event_posts_to_the_core_proxy():
    seen, handler = recorder(httpx.Response(200, json={"message": "Event fired."}))
    client = make_client(handler)
    await client.fire_event("cinema_studio_catalog_changed", {"revision": 7})
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "http://supervisor/core/api/events/cinema_studio_catalog_changed"
    assert request.headers["authorization"] == "Bearer sup-token"
    assert json.loads(request.content) == {"revision": 7}
    await client.aclose()


async def test_call_service_posts_to_the_core_proxy():
    seen, handler = recorder(httpx.Response(200, json=[]))
    client = make_client(handler)
    await client.call_service("media_player", "play_media", {"entity_id": "media_player.a"})
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "http://supervisor/core/api/services/media_player/play_media"
    assert json.loads(request.content) == {"entity_id": "media_player.a"}
    await client.aclose()


async def test_custom_base_url():
    seen, handler = recorder(httpx.Response(200, json={"data": {}}))
    client = SupervisorClient(
        "t",
        base_url="http://localhost:9000/",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await client.network_info()
    assert str(seen[0].url) == "http://localhost:9000/network/info"
    await client.aclose()


async def test_http_errors_become_supervisor_errors_with_the_message():
    _, handler = recorder(httpx.Response(400, json={"result": "error", "message": "no such app"}))
    client = make_client(handler)
    with pytest.raises(SupervisorError, match="no such app"):
        await client.self_info()
    with pytest.raises(SupervisorError, match="400"):
        await client.fire_event("x", {})
    await client.aclose()


async def test_errors_without_a_json_body_still_report_the_status():
    _, handler = recorder(httpx.Response(502, text="bad gateway"))
    client = make_client(handler)
    with pytest.raises(SupervisorError, match="502"):
        await client.core_config()
    await client.aclose()


async def test_transport_errors_become_supervisor_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = make_client(handler)
    with pytest.raises(SupervisorError, match="refused"):
        await client.self_info()
    await client.aclose()


async def test_transport_errors_without_a_message_name_their_type():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    client = make_client(handler)
    with pytest.raises(SupervisorError, match="ReadTimeout"):
        await client.self_info()
    await client.aclose()


def test_describe_error_falls_back_to_the_exception_type():
    assert describe_error(ValueError("boom")) == "boom"
    assert describe_error(TimeoutError()) == "TimeoutError"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=[1, 2]),
        httpx.Response(200, json={"result": "ok"}),
        httpx.Response(200, json={"data": "text"}),
    ],
)
async def test_malformed_payloads_become_supervisor_errors(response: httpx.Response):
    _, handler = recorder(response)
    client = make_client(handler)
    with pytest.raises(SupervisorError):
        await client.self_info()
    await client.aclose()


async def test_discovery_without_a_uuid_is_an_error():
    _, handler = recorder(httpx.Response(200, json={"data": {}}))
    client = make_client(handler)
    with pytest.raises(SupervisorError):
        await client.publish_discovery({})
    await client.aclose()


async def test_aclose_closes_the_http_client():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    client = SupervisorClient("t", client=http)
    await client.aclose()
    assert http.is_closed
    await client.aclose()
