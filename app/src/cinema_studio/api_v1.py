"""Integration API v1, used by the cinema_studio Home Assistant integration."""

from __future__ import annotations

import re
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from . import __version__
from .auth import require_bearer
from .legacy import LegacyImporter, LegacyStageRequest, legacy_request
from .models import SelectionBatch
from .repository import Repository

# ASCII digits only and bounded, so odd validators can never raise.
_REVISION_ETAG = re.compile(r'"rev-([0-9]{1,15})"')
_CONSUMER_ID = r"^[A-Za-z0-9_-]{1,128}$"


async def validate_consumer(
    consumer_id: Annotated[
        str, Header(alias="X-Cinema-Consumer", pattern=_CONSUMER_ID, description="Config entry id")
    ],
) -> str:
    """Require a well-formed consumer header on every route; it is not recorded here."""
    return consumer_id


def _record_consumer(request: Request, consumer_id: str) -> None:
    """Note that this consumer fetched the catalog, and which revision it says it holds.

    Only the catalog route registers a consumer: that is what makes the integration write a
    ``consumers/<id>.json`` fence file, so probes (the config flow's health check) must not
    register, or the garbage collector would wait for a file that is never written.

    The revision is the ``"rev-<n>"`` validator in ``If-None-Match``: it is what the integration
    has adopted, so the garbage collector can tell which retired renders are still referenced.
    """
    repo: Repository = request.app.state.repo
    revision = repo.catalog_revision()
    held = [r for r in _etag_revisions(request.headers.get("If-None-Match", "")) if r <= revision]
    repo.touch_consumer(consumer_id, max(held) if held else None)


# ``require_bearer`` is listed first so an unauthenticated request is answered 401 before the
# consumer header is validated.
router = APIRouter(
    prefix="/api/v1", dependencies=[Depends(require_bearer), Depends(validate_consumer)]
)


@router.get("/health")
async def health(request: Request) -> dict[str, str | int]:
    return {
        "status": "ok",
        "version": __version__,
        "api_version": 1,
        "instance_id": request.app.state.instance_id,
    }


@router.get("/catalog")
async def catalog(
    request: Request, consumer_id: Annotated[str, Depends(validate_consumer)]
) -> Response:
    repo: Repository = request.app.state.repo
    _record_consumer(request, consumer_id)
    current = _etag(repo.catalog_revision())
    if _etag_matches(request.headers.get("If-None-Match", ""), current):
        return Response(status_code=304, headers={"ETag": current})
    document = repo.catalog_document(request.app.state.instance_id)
    # Tag the body with the revision it was built from, not the one that is current by now.
    return JSONResponse(document, headers={"ETag": _etag(cast("int", document["revision"]))})


@router.post("/selections", status_code=204)
async def selections(request: Request) -> Response:
    # The body is parsed here rather than declared as a parameter: FastAPI parses declared bodies
    # before it runs dependencies, which would answer malformed JSON with 422 ahead of the 401.
    try:
        batch = SelectionBatch.model_validate_json(await request.body())
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_input=False)) from exc
    repo: Repository = request.app.state.repo
    repo.record_selections(batch.events)
    return Response(status_code=204)


@router.post("/import/legacy")
async def import_legacy(request: Request) -> Response:
    try:
        body = legacy_request.validate_json(await request.body())
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_input=False)) from exc
    importer: LegacyImporter = request.app.state.legacy
    if isinstance(body, LegacyStageRequest):
        result = await importer.stage(body.manifest)
    else:
        result = await importer.commit(body.run_id, body.clips)
    return JSONResponse(result.model_dump(mode="json"))


def _etag(revision: int) -> str:
    return f'"rev-{revision}"'


def _etag_revisions(header: str) -> list[int]:
    """Catalog revisions named by ``"rev-<n>"`` validators in an ``If-None-Match`` header."""
    revisions: list[int] = []
    for candidate in header.split(","):
        match = _REVISION_ETAG.fullmatch(candidate.strip().removeprefix("W/"))
        if match:
            revisions.append(int(match.group(1)))
    return revisions


def _etag_matches(header: str, etag: str) -> bool:
    """Whether an ``If-None-Match`` header lists ``etag`` (weak validators compare equal)."""
    return any(
        candidate.strip().removeprefix("W/") in ("*", etag) for candidate in header.split(",")
    )
