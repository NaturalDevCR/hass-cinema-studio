"""Authenticated client for the Cinema Studio v1 API."""

from dataclasses import dataclass
from typing import Any, cast

import aiohttp
from yarl import URL


class StudioConnectionError(Exception):
    """Studio could not be reached or returned an invalid response."""


class StudioAuthError(StudioConnectionError):
    """Studio rejected the API token."""


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
        return await self._request("GET", "catalog", etag=etag)

    async def post_selections(self, events: list[dict[str, Any]]) -> None:
        await self._request("POST", "selections", json_body={"events": events})

    async def legacy_stage(self, body: dict[str, Any]) -> dict[str, Any]:
        result = await self._request("POST", "import/legacy", json_body=body, legacy=True)
        return result.data or {}

    async def legacy_commit(self, body: dict[str, Any]) -> dict[str, Any]:
        result = await self._request("POST", "import/legacy", json_body=body, legacy=True)
        return result.data or {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        etag: str | None = None,
        json_body: dict[str, Any] | None = None,
        legacy: bool = False,
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
                timeout=self._legacy_timeout if legacy else self._timeout,
                allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise StudioAuthError("Studio rejected the API token")
                if response.status == 304 and path == "catalog":
                    return CatalogResponse(None, response.headers.get("ETag", etag))
                expected_status = 204 if path == "selections" else 200
                if response.status != expected_status:
                    raise StudioConnectionError(f"Studio returned HTTP {response.status}")
                if response.status == 204:
                    return CatalogResponse(None, None)
                data: Any = await response.json()
                if not isinstance(data, dict):
                    raise StudioConnectionError("Studio response must be an object")
                return CatalogResponse(cast(dict[str, Any], data), response.headers.get("ETag"))
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise StudioConnectionError("Unable to contact Studio") from err
