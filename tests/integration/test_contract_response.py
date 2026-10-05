"""Selection responses obey the public schema."""

import json
from pathlib import Path

import jsonschema
import pytest

from .test_manager import manager, select  # noqa: F401

pytestmark = pytest.mark.integration


async def test_response_contract(manager):  # noqa: F811
    response = await select(manager)
    schema = json.loads(Path("contract/selection_response.schema.json").read_text())
    jsonschema.validate(response, schema, format_checker=jsonschema.FormatChecker())
    assert response["clip_id"] in response["media_content_id"]
    assert response["duration"] == response["duration_seconds"]
