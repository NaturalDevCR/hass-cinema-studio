"""Client for the Home Assistant Supervisor API and its Core proxy."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote

import httpx

DISCOVERY_SERVICE = "cinema_studio"
_TIMEOUT = httpx.Timeout(10.0)


class SupervisorError(Exception):
    """The Supervisor (or Core through it) could not be reached or refused the request."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def describe_error(exc: BaseException) -> str:
    """A readable one-liner for an exception; some (timeouts) have an empty ``str``."""
    return str(exc) or type(exc).__name__


class SupervisorClient:
    """Talks to ``http://supervisor`` with the App's ``SUPERVISOR_TOKEN``.

    Without a token the client is *unavailable*: every call raises :class:`SupervisorError`
    without touching the network. An injected ``client`` is owned by this object and is closed by
    :meth:`aclose`.
    """

    def __init__(
        self,
        token: str | None,
        base_url: str = "http://supervisor",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token or None
        self._base_url = base_url.rstrip("/")
        self._client = client

    @property
    def available(self) -> bool:
        return self._token is not None

    async def self_info(self) -> dict[str, Any]:
        return _data(await self._request("GET", "/addons/self/info"))

    async def core_config(self) -> dict[str, Any]:
        return _object(await self._request("GET", "/core/api/config"))

    async def core_info(self) -> dict[str, Any]:
        return _data(await self._request("GET", "/core/info"))

    async def network_info(self) -> dict[str, Any]:
        return _data(await self._request("GET", "/network/info"))

    async def publish_discovery(self, config: dict[str, Any]) -> str:
        """Announce the App to Home Assistant; returns the discovery uuid."""
        body = {"service": DISCOVERY_SERVICE, "config": config}
        uuid = _data(await self._request("POST", "/discovery", body)).get("uuid")
        if not isinstance(uuid, str) or not uuid:
            raise SupervisorError("The Supervisor did not return a discovery uuid")
        return uuid

    async def delete_discovery(self, uuid: str) -> None:
        await self._request("DELETE", f"/discovery/{quote(uuid, safe='')}")

    async def fire_event(self, event_type: str, data: dict[str, Any]) -> None:
        await self._request("POST", f"/core/api/events/{quote(event_type, safe='')}", data)

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        path = f"/core/api/services/{quote(domain, safe='')}/{quote(service, safe='')}"
        await self._request("POST", path, data)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> httpx.Response:
        if self._token is None:
            raise SupervisorError("The Supervisor API is not available")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {self._token}"},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise SupervisorError(f"{method} {path} failed: {describe_error(exc)}") from exc
        if response.is_error:
            raise SupervisorError(
                f"{method} {path} returned {response.status_code}{_reason(response)}",
                status=response.status_code,
            )
        return response


def _reason(response: httpx.Response) -> str:
    """The Supervisor's error message, when the body carries one."""
    try:
        message = _object(response).get("message")
    except SupervisorError:
        return ""
    return f": {message}" if isinstance(message, str) and message else ""


def _object(response: httpx.Response) -> dict[str, Any]:
    try:
        body: object = response.json()
    except ValueError as exc:
        raise SupervisorError("The Supervisor returned a response that is not JSON") from exc
    if not isinstance(body, dict):
        raise SupervisorError("The Supervisor returned an unexpected response")
    return cast("dict[str, Any]", body)


def _data(response: httpx.Response) -> dict[str, Any]:
    data = _object(response).get("data")
    if not isinstance(data, dict):
        raise SupervisorError("The Supervisor response has no data")
    return cast("dict[str, Any]", data)
