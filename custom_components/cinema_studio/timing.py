"""Timing invariants shared by the Cinema Studio App and integration (kept identical in both)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

TOLERANCE = 0.001
_EPSILON = 1e-9  # absorbs float error so a difference of exactly TOLERANCE is accepted
_LIMIT = TOLERANCE + _EPSILON
MAX_DURATION = 7200.0


@dataclass(frozen=True)
class Timing:
    duration: float
    content_start: float
    content_end: float
    lead_in: float
    tail_out: float
    content_duration: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def round_timing(timing: Timing) -> Timing:
    return Timing(**{key: round(value, 3) for key, value in asdict(timing).items()})


def timing_problems(timing: Timing) -> list[str]:
    values = asdict(timing)
    problems = [f"{key} is not finite" for key, value in values.items() if not math.isfinite(value)]
    if problems:
        return problems
    if not 0 < timing.duration <= MAX_DURATION:
        problems.append("duration out of range")
    if abs(timing.content_start - timing.lead_in) > _LIMIT:
        problems.append("content_start differs from lead_in")
    if not 0 <= timing.content_start < timing.content_end <= timing.duration + _LIMIT:
        problems.append("content bounds out of order")
    if abs(timing.content_duration - (timing.content_end - timing.content_start)) > _LIMIT:
        problems.append("content_duration mismatch")
    if abs(timing.tail_out - (timing.duration - timing.content_end)) > _LIMIT:
        problems.append("tail_out mismatch")
    if timing.lead_in < 0 or timing.tail_out < -_LIMIT:
        problems.append("negative margin")
    return problems
