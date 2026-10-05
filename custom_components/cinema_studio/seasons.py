"""Calendar and precedence rules for effective seasons."""

from collections.abc import Iterable
from datetime import date
from typing import Protocol

from .catalog import Catalog
from .const import REGULAR


class SeasonLike(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def start(self) -> str | None: ...

    @property
    def end(self) -> str | None: ...

    @property
    def priority(self) -> int: ...


class UnknownSeasonError(ValueError):
    """An action explicitly named a season absent from the catalog."""


def season_matches(start: str | None, end: str | None, mmdd: str) -> bool:
    if not start or not end:
        return False
    return start <= mmdd <= end if start <= end else mmdd >= start or mmdd <= end


def resolve_calendar_season(seasons: Iterable[SeasonLike], day: date) -> str:
    matches = [
        s
        for s in seasons
        if s.id != REGULAR and season_matches(s.start, s.end, day.strftime("%m-%d"))
    ]
    return min(matches, key=lambda s: (-s.priority, s.id)).id if matches else REGULAR


def resolve_effective_season(
    catalog: Catalog,
    day: date,
    *,
    action_season: str | None,
    override: str | None,
    entity_state: str | None,
) -> tuple[str, str]:
    if action_season is not None:
        season = catalog.find_season(action_season)
        if season is None:
            raise UnknownSeasonError(action_season)
        return season.id, "action"
    for value, source in ((override, "override"), (entity_state, "entity")):
        if (
            value is None
            or source == "entity"
            and value.casefold() in {"", "unknown", "unavailable"}
        ):
            continue
        season = catalog.find_season(value)
        if season is not None:
            return season.id, source
    result = resolve_calendar_season(catalog.seasons, day)
    return result, "calendar" if result != REGULAR else "default"
