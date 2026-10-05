from pathlib import Path

import yaml
from openapi_spec_validator import validate

CONTRACT = Path(__file__).resolve().parents[2] / "contract" / "openapi-v1.yaml"


def test_contract_is_valid_openapi() -> None:
    validate(yaml.safe_load(CONTRACT.read_text(encoding="utf-8")))


def test_contract_declares_v1_paths() -> None:
    document = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert set(document["paths"]) == {
        "/api/v1/health",
        "/api/v1/catalog",
        "/api/v1/selections",
        "/api/v1/import/legacy",
    }


def test_every_operation_requires_consumer_header() -> None:
    document = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    header = document["components"]["parameters"]["ConsumerHeader"]
    assert header["name"] == "X-Cinema-Consumer"
    assert header["in"] == "header"
    assert header["required"] is True
    for path, item in document["paths"].items():
        for method, operation in item.items():
            refs = [p.get("$ref") for p in operation["parameters"]]
            assert "#/components/parameters/ConsumerHeader" in refs, f"{method} {path}"


def test_contract_declares_expected_schemas() -> None:
    document = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert {
        "Health",
        "Catalog",
        "CatalogSeason",
        "CatalogCollection",
        "CatalogClip",
        "Render",
        "SelectionEvent",
        "SelectionBatch",
        "LegacyManifest",
        "LegacyStageRequest",
        "LegacyStageResponse",
        "LegacyCommitRequest",
        "LegacyReport",
        "Error",
    } <= set(document["components"]["schemas"])


def test_object_schemas_require_every_property() -> None:
    document = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))

    def walk(name: str, node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if node.get("type") == "object" and isinstance(properties, dict):
                assert set(node.get("required", [])) == set(properties), name
                for key, child in properties.items():
                    walk(f"{name}.{key}", child)
            elif node.get("type") == "array":
                walk(f"{name}[]", node.get("items"))

    for name, schema in document["components"]["schemas"].items():
        walk(name, schema)
