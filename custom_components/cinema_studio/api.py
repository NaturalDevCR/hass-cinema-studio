"""Authenticated client for the Cinema Studio v1 API."""

from dataclasses import dataclass
from typing import Any, cast

import aiohttp
from yarl import URL


class StudioConnectionError(Exception):
    """Studio could not be reached or returned an invalid response."""


class StudioAuthError(StudioConnectionError):
    """Studio rejected the API token."""


class StudioRequestError(StudioConnectionError):
    """Studio rejected the request with a 4xx status and a JSON ``detail``."""

    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(f"Studio rejected the request (HTTP {status})")
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class CatalogResponse:
    data: dict[str, Any] | None
    etag: str | None


class StudioClient:
    """Use Home Assistant's shared session for all Studio requests."""

    def __init__(
        self, session: aiohttp.ClientSession, host: str, port: int, token: str, consumer_id: str
    ) -> None:
        self._session = session
        self._base_url = URL.build(scheme="http", host=host, port=port) / "api/v1"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "X-Cinema-Consumer": consumer_id,
        }
        self._timeout = aiohttp.ClientTimeout(total=10)
        self._legacy_timeout = aiohttp.ClientTimeout(total=1800)

    async def health(self) -> dict[str, Any]:
        result = await self._request("GET", "health")
        data = result.data
        if (
            data is None
            or data.get("status") != "ok"
            or data.get("api_version") != 1
            or not isinstance(data.get("instance_id"), str)
            or not data["instance_id"]
            or not isinstance(data.get("version"), str)
        ):
            raise StudioConnectionError("Invalid Studio health response")
        return data

    async def catalog(self, etag: str | None = None) -> CatalogResponse:
        return await self._request("GET", "catalog", etag=etag, allow_not_modified=True)

    async def post_selections(self, events: list[dict[str, Any]]) -> None:
        await self._request("POST", "selections", json_body={"events": events}, expected=204)

    async def legacy_stage(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._legacy(body)

    async def legacy_commit(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._legacy(body)

    async def _legacy(self, body: dict[str, Any]) -> dict[str, Any]:
        result = await self._request(
            "POST", "import/legacy", json_body=body, timeout=self._legacy_timeout
        )
        return result.data or {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        expected: int = 200,
        allow_not_modified: bool = False,
        etag: str | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> CatalogResponse:
        headers = self._headers.copy()
        if etag is not None:
            headers["If-None-Match"] = etag
        try:
            async with self._session.request(
                method,
                self._base_url / path,
                headers=headers,
                json=json_body,
                timeout=timeout or self._timeout,
                allow_redirects=False,
            ) as response:
                status = response.status
                if status in (401, 403):
                    raise StudioAuthError("Studio rejected the API token")
                if status == 304 and allow_not_modified:
                    return CatalogResponse(None, response.headers.get("ETag", etag))
                if status != expected:
                    if 400 <= status < 500:
                        await _raise_for_detail(response, status)
                    raise StudioConnectionError(f"Studio returned HTTP {status}")
                if status == 204:
                    return CatalogResponse(None, None)
                data: Any = await response.json()
                if not isinstance(data, dict):
                    raise StudioConnectionError("Studio response must be an object")
                return CatalogResponse(cast(dict[str, Any], data), response.headers.get("ETag"))
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise StudioConnectionError("Unable to contact Studio") from err


async def _raise_for_detail(response: aiohttp.ClientResponse, status: int) -> None:
    """Raise StudioRequestError when a 4xx body is a JSON object with a detail."""
    try:
        body: Any = await response.json()
    except (aiohttp.ClientError, ValueError):
        return
    if isinstance(body, dict) and "detail" in body:
        raise StudioRequestError(status, cast(dict[str, Any], body)["detail"])
