"""Publish-time timing check; `timing.py` itself stays identical to the integration copy."""

from __future__ import annotations

from .errors import InvalidError
from .timing import Timing, round_timing, timing_problems


def validate_timing(t: Timing) -> Timing:
    """Round to the millisecond grid, then raise InvalidError listing every violated invariant."""
    rounded = round_timing(t)
    problems = timing_problems(rounded)
    if problems:
        raise InvalidError("; ".join(problems))
    return rounded
