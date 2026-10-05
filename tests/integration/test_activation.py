import pytest

from custom_components.cinema_studio.activation import ActivationState, evaluate_activation

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("old", "season", "collection", "fallback", "reset"),
    [
        (ActivationState(None, None), "s", "c", False, None),
        (ActivationState("s", "old"), "t", "c", False, "c"),
        (ActivationState("s", "old"), "t", "c", True, None),
        (ActivationState("s", "old"), "s", "c", False, "c"),
        (ActivationState("s", "c"), "s", "c", False, None),
    ],
)
def test_activation_rules(old, season, collection, fallback, reset) -> None:
    state, actual_reset = evaluate_activation(
        old, season_id=season, collection_id=collection, fallback=fallback
    )
    assert actual_reset == reset
    assert state == ActivationState(season, collection)
