import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_versions_agree() -> None:
    manifest = json.loads((ROOT / "custom_components/cinema_studio/manifest.json").read_text())
    app_config = yaml.safe_load((ROOT / "app/config.yaml").read_text())
    namespace: dict[str, str] = {}
    exec((ROOT / "app/src/cinema_studio/__init__.py").read_text(), namespace)
    assert manifest["version"] == app_config["version"] == namespace["__version__"]


def test_hacs_metadata() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["name"] == "Cinema Studio"
    assert hacs["content_in_root"] is False
    assert hacs["homeassistant"] == "2025.12.0"


def test_app_manifest_core_fields() -> None:
    app_config = yaml.safe_load((ROOT / "app/config.yaml").read_text())
    assert app_config["slug"] == "cinema_studio"
    assert app_config["ingress_port"] == 8099
    assert "media:rw" in app_config["map"]
    assert app_config["discovery"] == ["cinema_studio"]
    assert "image" not in app_config
