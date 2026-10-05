import json
from pathlib import Path
from types import ModuleType

import pytest

from cinema_studio import timing as app_timing
from custom_components.cinema_studio import timing as integration_timing

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "contract" / "timing_cases.json").read_text(encoding="utf-8"))
MODULES: list[ModuleType] = [app_timing, integration_timing]


@pytest.mark.parametrize("module", MODULES, ids=["app", "integration"])
@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_timing_cases(module: ModuleType, case: dict) -> None:
    problems = module.timing_problems(module.Timing(**case["timing"]))
    assert (problems == []) == case["valid"], problems


def test_timing_modules_identical() -> None:
    app = (ROOT / "app/src/cinema_studio/timing.py").read_text(encoding="utf-8").splitlines()
    integration = (
        (ROOT / "custom_components/cinema_studio/timing.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert app[1:] == integration[1:]


def test_round_timing_rounds_to_three_decimals() -> None:
    rounded = app_timing.round_timing(app_timing.Timing(10.00049, 1.0004, 9.0004, 1.0004, 1.0, 8.0))
    assert rounded.duration == 10.0
    assert rounded.content_start == 1.0
