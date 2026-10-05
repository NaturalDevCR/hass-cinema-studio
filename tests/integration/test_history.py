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


def test_daily_reset_respects_boundary_and_sets_reset_pending() -> None:
    state = HistoryState(
        {
            "collections": {
                "c": {"period_start": "2026-08-26", "round_number": 1, "played_clip_ids": ["a"]}
            }
        }
    )
    reset_at = datetime(2026, 8, 27, 2, tzinfo=UTC)
    assert state.reset("c", reset_at, reset_time=time(4)) == ["c"]
    record = state.to_dict()["collections"]["c"]
    assert record["period_start"] == "2026-08-26"
    assert record["last_reset_at"] == reset_at.isoformat()
    picked = state.pick(
        "c",
        ["a", "b"],
        "sequential",
        random.Random(),
        now=reset_at,
        reset_mode="daily",
        reset_time=time(4),
    )
    assert picked[1:3] == (2, True)


def test_pick_is_dry_run_and_normalizes_corrupt_records() -> None:
    state = HistoryState(
        {
            "collections": {
                "bad": {"round_number": "x", "played_clip_ids": None},
                "c": {"period_start": "2026-08-27", "round_number": 1, "played_clip_ids": ["a", 2]},
            }
        }
    )
    before = state.to_dict()
    result = state.pick(
        "c",
        ["a", "b"],
        "sequential",
        random.Random(),
        now=NOW,
        reset_mode="exhaustion",
        reset_time=time(),
    )
    assert result[0] == "a" and result[3] is not None
    assert state.to_dict() == before
    assert "bad" not in state.to_dict()["collections"]


def test_reset_supports_one_or_all_collections() -> None:
    state = HistoryState(
        {
            "collections": {
                key: {"period_start": "2026-08-27", "round_number": 1, "played_clip_ids": []}
                for key in ("a", "b")
            }
        }
    )
    assert state.reset("a", NOW) == ["a"]
    assert state.reset(None, NOW) == ["a", "b"]


def test_custom_order_is_used_by_pick() -> None:
    collection = CollectionDef("c", "C", "", "", "custom", ("b", "a"), True)
    clips = [ClipDef(x, "c", x, "", True, x, False, None) for x in ("a", "b", "c")]
    eligible = order_candidates(clips, collection)
    result = HistoryState().pick(
        "c",
        eligible,
        "sequential",
        random.Random(),
        now=NOW,
        reset_mode="exhaustion",
        reset_time=time(),
    )
    assert result[0] == "b"


def test_reappearing_clip_joins_existing_round() -> None:
    state = HistoryState(
        {
            "collections": {
                "c": {
                    "period_start": "2026-08-27",
                    "round_number": 3,
                    "played_clip_ids": ["a", "b"],
                }
            }
        }
    )
    result = state.pick(
        "c",
        ["a", "b", "c"],
        "sequential",
        random.Random(),
        now=NOW,
        reset_mode="exhaustion",
        reset_time=time(),
    )
    assert result[0] == "c" and result[1] == 3 and result[2] is False


def test_daily_reconcile_starts_new_round_and_marks_reset_time() -> None:
    previous = {
        "collections": {
            "c": {"period_start": "2026-08-26", "round_number": 2, "played_clip_ids": ["a"]}
        }
    }
    history = HistoryState(previous)
    picked = history.pick(
        "c",
        ["a", "b"],
        "sequential",
        random.Random(),
        now=NOW,
        reset_mode="daily",
        reset_time=time(4),
    )
    assert picked[0] == "a" and picked[1] == 3 and picked[2] is True
    assert picked[3] is not None and picked[3]["last_reset_at"] == NOW.isoformat()


def test_daily_reset_boundary_does_not_apply_in_exhaustion_mode() -> None:
    state = HistoryState(
        {"collections": {"c": {"period_start": "old", "round_number": 4, "played_clip_ids": ["a"]}}}
    )
    picked = state.pick(
        "c",
        ["a", "b"],
        "sequential",
        random.Random(),
        now=NOW,
        reset_mode="exhaustion",
        reset_time=time(4),
    )
    assert picked[0] == "b" and picked[1] == 4 and picked[2] is False


def test_reset_pending_is_reported_and_cleared_in_new_record() -> None:
    history = HistoryState(
        {
            "collections": {
                "c": {
                    "period_start": "2026-08-27",
                    "round_number": 2,
                    "played_clip_ids": [],
                    "reset_pending": True,
                }
            }
        }
    )
    picked = history.pick(
        "c",
        ["a"],
        "sequential",
        random.Random(),
        now=NOW,
        reset_mode="exhaustion",
        reset_time=time(),
    )
    assert picked[2] is True
    assert picked[3] is not None and picked[3]["reset_pending"] is False


def test_pick_mode_switch_does_not_reconcile_daily_record() -> None:
    history = HistoryState(
        {
            "collections": {
                "c": {"period_start": "yesterday", "round_number": 1, "played_clip_ids": ["a"]}
            }
        }
    )
    picked = history.pick(
        "c",
        ["a", "b"],
        "sequential",
        random.Random(),
        now=NOW,
        reset_mode="exhaustion",
        reset_time=time(4),
    )
    assert picked[0] == "b" and picked[1] == 1 and picked[2] is False
