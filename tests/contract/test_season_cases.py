import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from cinema_studio.seasons import resolve_calendar_season as studio_resolve
from custom_components.cinema_studio.seasons import (
    resolve_calendar_season as integration_resolve,
)

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).resolve().parents[2] / "contract" / "season_cases.json").read_text(
        encoding="utf-8"
    )
)


@dataclass
class _Season:
    id: str
    start: str | None
    end: str | None
    priority: int


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_studio_calendar(case: dict[str, Any]) -> None:
    seasons = [_Season(**season) for season in case["seasons"]]
    assert studio_resolve(seasons, date.fromisoformat(case["date"])) == case["expected"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_integration_calendar(case: dict[str, Any]) -> None:
    seasons = [_Season(**season) for season in case["seasons"]]
    assert integration_resolve(seasons, date.fromisoformat(case["date"])) == case["expected"]
