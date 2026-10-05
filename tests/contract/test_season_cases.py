import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from custom_components.cinema_studio.seasons import resolve_calendar_season

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
def test_integration_calendar(case: dict[str, Any]) -> None:
    assert (
        resolve_calendar_season(
            [_Season(**s) for s in case["seasons"]], date.fromisoformat(case["date"])
        )
        == case["expected"]
    )
