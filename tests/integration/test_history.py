import random
from datetime import UTC, datetime, time

import pytest

from custom_components.cinema_studio.catalog import ClipDef, CollectionDef
from custom_components.cinema_studio.history import HistoryState, order_candidates

pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 27, 20, tzinfo=UTC)


def test_round_rollover_and_sequential_custom_order() -> None:
    history = HistoryState()
    a = history.pick(
        "c",
        ["a", "b"],
        "sequential",
        random.Random(),
        now=NOW,
        reset_mode="exhaustion",
        reset_time=time(),
    )
    history.commit("c", a[3])
    b = history.pick(
        "c",
        ["a", "b"],
        "sequential",
        random.Random(),
        now=NOW,
        reset_mode="exhaustion",
        reset_time=time(),
    )
    history.commit("c", b[3])
    again = history.pick(
        "c",
        ["a", "b"],
        "sequential",
        random.Random(),
        now=NOW,
        reset_mode="exhaustion",
        reset_time=time(),
    )
    assert (a[0], b[0], again[0], again[1], again[2]) == ("a", "b", "a", 2, True)


def test_random_round_is_no_repeat_and_collections_are_independent() -> None:
    history = HistoryState()
    rng = random.Random(10)
    draws: list[str] = []
    for _ in range(3):
        picked = history.pick(
            "films",
            ["a", "b", "c"],
            "random",
            rng,
            now=NOW,
            reset_mode="exhaustion",
            reset_time=time(),
        )
        assert picked[0] is not None
        draws.append(picked[0])
        assert picked[3] is not None
        history.commit("films", picked[3])
    assert len(set(draws)) == 3
    other = history.pick(
        "trailers",
        ["a"],
        "sequential",
        rng,
        now=NOW,
        reset_mode="exhaustion",
        reset_time=time(),
    )
    assert other[0] == "a" and other[1] == 1


def test_removed_clip_does_not_end_round_and_reappearing_clip_joins() -> None:
    history = HistoryState()
    first = history.pick(
        "c",
        ["a", "b"],
        "sequential",
        random.Random(),
        now=NOW,
        reset_mode="exhaustion",
        reset_time=time(),
    )
    assert first[3] is not None
    history.commit("c", first[3])
    next_pick = history.pick(
        "c",
        ["a", "c"],
        "sequential",
        random.Random(),
        now=NOW,
        reset_mode="exhaustion",
        reset_time=time(),
    )
    assert next_pick[0] == "c" and next_pick[1] == 1 and not next_pick[2]


def test_daily_reconcile_and_legacy_unknown_ids() -> None:
    state = HistoryState(
        {
            "collections": {
                "c": {
                    "period_start": "2026-08-26",
                    "round_number": 1,
                    "played_clip_ids": ["gone"],
                    "last_selected_clip_id": None,
                    "last_reset_at": None,
                }
            }
        }
    )
    pick = state.pick(
        "c", ["a"], "random", random.Random(0), now=NOW, reset_mode="daily", reset_time=time()
    )
    assert pick[2] is True
    legacy = HistoryState.from_legacy(state.to_dict(), {"a"})
    assert legacy.to_dict()["collections"]["c"]["played_clip_ids"] == []


def test_order_candidates_custom_keeps_rest_sequential() -> None:
    collection = CollectionDef("c", "C", "", "", "custom", ("b",), True)
    clips = [ClipDef(x, "c", x, "", True, x, False, None) for x in ("z", "b", "a")]
    assert order_candidates(clips, collection) == ["b", "a", "z"]
