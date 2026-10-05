"""Pure activation transition rules."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActivationState:
    last_effective_season: str | None
    last_effective_collection: str | None


def evaluate_activation(
    state: ActivationState, *, season_id: str, collection_id: str, fallback: bool
) -> tuple[ActivationState, str | None]:
    new = ActivationState(season_id, collection_id)
    if state.last_effective_season is None:
        return new, None
    if state.last_effective_season == season_id:
        if state.last_effective_collection != collection_id and not fallback:
            return new, collection_id
        if fallback:
            return state, None
        return new, None
    return new, None if fallback else collection_id
