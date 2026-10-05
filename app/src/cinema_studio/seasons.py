"""Yearly season calendar shared (by copy) with the sound_effects integration."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol

REGULAR = "regular"


class SeasonLike(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def start(self) -> str | None: ...
    @property
    def end(self) -> str | None: ...
    @property
    def priority(self) -> int: ...


def season_matches(start: str | None, end: str | None, mmdd: str) -> bool:
    """Return True when MM-DD falls inside an inclusive, possibly year-wrapping range."""
    if not start or not end:
        return False
    if start <= end:
        return start <= mmdd <= end
    return mmdd >= start or mmdd <= end


def resolve_calendar_season(seasons: Iterable[SeasonLike], day: date) -> str:
    """Pick the highest-priority season whose range contains the day, else regular."""
    mmdd = day.strftime("%m-%d")
    matches = [
        season
        for season in seasons
        if season.id != REGULAR and season_matches(season.start, season.end, mmdd)
    ]
    if not matches:
        return REGULAR
    matches.sort(key=lambda season: (-season.priority, season.id))
    return matches[0].id
