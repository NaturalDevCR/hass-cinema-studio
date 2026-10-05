"""Pure playback history state transitions; callers own persistence."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from datetime import datetime, time, timedelta
from typing import Any, cast

from .catalog import ClipDef, CollectionDef


class HistoryState:
    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        raw: Mapping[object, object] = (
            data.get("collections", {}) if isinstance(data, Mapping) else {}
        )
        collections: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not key or not isinstance(value, Mapping):
                continue
            record = cast(Mapping[str, Any], value)
            period, round_number, played = (
                record.get("period_start"),
                record.get("round_number"),
                record.get("played_clip_ids"),
            )
            last_selected, last_reset = (
                record.get("last_selected_clip_id"),
                record.get("last_reset_at"),
            )
            if (
                not isinstance(period, str)
                or isinstance(round_number, bool)
                or not isinstance(round_number, int)
                or round_number < 1
                or not isinstance(played, list)
                or not all(isinstance(item, str) and item for item in cast(list[object], played))
                or (last_selected is not None and not isinstance(last_selected, str))
                or (last_reset is not None and not isinstance(last_reset, str))
            ):
                continue
            played_ids = cast(list[str], played)
            collections[key] = {
                "period_start": period,
                "round_number": round_number,
                "played_clip_ids": list(dict.fromkeys(played_ids)),
                "last_selected_clip_id": last_selected,
                "last_reset_at": last_reset,
                "reset_pending": bool(record.get("reset_pending", False)),
            }
        self._data: dict[str, Any] = {"collections": collections}

    def to_dict(self) -> dict[str, Any]:
        return {
            "collections": {
                k: {**v, "played_clip_ids": list(v.get("played_clip_ids", []))}
                for k, v in self._data["collections"].items()
            }
        }

    def pick(
        self,
        collection_id: str,
        eligible: Sequence[str],
        mode: str,
        rng: random.Random,
        *,
        now: datetime,
        reset_mode: str,
        reset_time: time,
    ) -> tuple[str | None, int, bool, dict[str, Any] | None]:
        """Pick without mutation; ``now`` must be local and aware (use ``dt_util.as_local``)."""
        if now.tzinfo is None:
            raise ValueError("history requires timezone-aware datetime")
        ids = list(dict.fromkeys(x for x in eligible if x))
        record = self._data["collections"].get(collection_id)
        period = _period_start(now, reset_time)
        reset = False
        daily_reset = False
        if record is None:
            round_number, played = 1, []
        else:
            round_number = int(record.get("round_number", 1))
            played = [x for x in record.get("played_clip_ids", []) if x in ids]
            if reset_mode == "daily" and record.get("period_start") != period:
                round_number += 1
                played = []
                reset = True
                daily_reset = True
            reset = reset or bool(record.get("reset_pending", False))
        remaining = [x for x in ids if x not in played]
        if ids and not remaining:
            round_number += 1
            remaining = ids
            played = []
            reset = True
        if not remaining:
            return None, round_number, reset, None
        clip_id = rng.choice(remaining) if mode == "random" else remaining[0]
        new = {
            "period_start": period,
            "round_number": round_number,
            "played_clip_ids": [*played, clip_id],
            "last_selected_clip_id": clip_id,
            "last_reset_at": now.isoformat()
            if daily_reset
            else (record.get("last_reset_at") if record else None),
            "reset_pending": False,
        }
        return clip_id, round_number, reset, new

    def commit(self, collection_id: str, record: dict[str, Any]) -> None:
        self._data["collections"][collection_id] = {
            **record,
            "played_clip_ids": list(record["played_clip_ids"]),
        }

    def reset(self, collection_id: str | None, now: datetime, *, reset_time: time) -> list[str]:
        ids = (
            sorted(self._data["collections"])
            if collection_id is None
            else ([collection_id] if collection_id in self._data["collections"] else [])
        )
        for key in ids:
            rec = self._data["collections"][key]
            self._data["collections"][key] = {
                "period_start": _period_start(now, reset_time),
                "round_number": int(rec.get("round_number", 1)) + 1,
                "played_clip_ids": [],
                "last_selected_clip_id": None,
                "last_reset_at": now.isoformat(),
                "reset_pending": True,
            }
        return ids

    @classmethod
    def from_legacy(cls, legacy: Mapping[str, Any], known_clip_ids: set[str]) -> HistoryState:
        result = cls(legacy)
        for rec in result._data["collections"].values():
            rec["played_clip_ids"] = [
                x for x in rec.get("played_clip_ids", []) if x in known_clip_ids
            ]
        return result


def _period_start(now: datetime, boundary: time) -> str:
    start = (
        now.date()
        if now.timetz().replace(tzinfo=None) >= boundary
        else now.date() - timedelta(days=1)
    )
    return start.isoformat()


def order_candidates(clips: Sequence[ClipDef], collection: CollectionDef) -> list[str]:
    sequential = sorted(
        (clip for clip in clips if clip.collection_id == collection.id),
        key=lambda c: (c.sort_key.casefold(), c.sort_key, c.id),
    )
    if collection.playback_mode == "custom":
        by_id = {clip.id: clip for clip in sequential}
        return list(
            dict.fromkeys([x for x in collection.order if x in by_id] + [c.id for c in sequential])
        )
    return (
        [c.id for c in sequential]
        if collection.playback_mode == "sequential"
        else [c.id for c in clips if c.collection_id == collection.id]
    )
