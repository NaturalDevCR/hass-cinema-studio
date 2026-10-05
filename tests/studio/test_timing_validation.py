from __future__ import annotations

import pytest

from cinema_studio.errors import InvalidError
from cinema_studio.timing import Timing
from cinema_studio.timing_validation import validate_timing

pytestmark = pytest.mark.studio


def test_rounds_to_three_decimals_before_checking() -> None:
    # 1.00049 only passes the content_start == lead_in check because both round to 1.0.
    raw = Timing(10.00049, 1.00049, 9.00049, 1.0, 1.0, 8.0)
    assert validate_timing(raw) == Timing(10.0, 1.0, 9.0, 1.0, 1.0, 8.0)


def test_valid_production_example_is_returned_rounded() -> None:
    timing = Timing(154.133, 2.0, 152.125, 2.0, 2.008, 150.125)
    assert validate_timing(timing) == timing


def test_raises_listing_every_problem() -> None:
    bad = Timing(30.0, 1.0, 28.0, 2.0, 1.5, 25.0)
    with pytest.raises(InvalidError) as caught:
        validate_timing(bad)
    message = str(caught.value)
    assert "content_start differs from lead_in" in message
    assert "content_duration mismatch" in message
    assert "tail_out mismatch" in message
    assert message.count("; ") == 2


def test_non_finite_values_are_rejected() -> None:
    with pytest.raises(InvalidError, match="not finite"):
        validate_timing(Timing(float("inf"), 0.0, 1.0, 0.0, 0.0, 1.0))
