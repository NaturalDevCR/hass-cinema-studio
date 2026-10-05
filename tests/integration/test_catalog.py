from __future__ import annotations

import copy
import math

import pytest

from custom_components.cinema_studio.catalog import parse_catalog

pytestmark = pytest.mark.integration


def payload() -> dict:
    return {
        "contract_version": 1,
        "revision": 4,
        "instance_id": "abc",
        "seasons": [
            {
                "id": "regular",
                "name": "Regular",
                "color": "",
                "icon": "",
                "start": None,
                "end": None,
                "priority": 0,
                "collection_id": "regular",
            }
        ],
        "collections": [
            {
                "id": "regular",
                "name": "Regular",
                "color": "",
                "icon": "",
                "playback_mode": "random",
                "order": [],
                "enabled": True,
            }
        ],
        "clips": [
            {
                "id": "clip-a",
                "collection_id": "regular",
                "title": "Film",
                "source_name": "film.mp4",
                "enabled": True,
                "sort_key": "Film",
                "render_pending": False,
                "render": {
                    "id": "r1",
                    "n": 1,
                    "relative_path": "cinema-studio/renders/clip-a/a.mp4",
                    "media_path": "cinema-studio/renders/clip-a/a.mp4",
                    "size": 5,
                    "sha256": "abc",
                    "duration": 8.0,
                    "content_start": 2.0,
                    "content_end": 6.0,
                    "lead_in": 2.0,
                    "tail_out": 2.0,
                    "content_duration": 4.0,
                    "timing_source": "measured",
                    "profile_fingerprint": "fp",
                    "integrated_lufs": None,
                },
            }
        ],
    }


def test_parse_catalog_and_find_collection() -> None:
    catalog = parse_catalog(payload())
    assert catalog.revision == 4 and catalog.clips[0].id == "clip-a"
    assert catalog.find_collection("Regular") == catalog.collections[0]
    assert catalog.render_ids() == frozenset({"r1"})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(contract_version=2),
        lambda c: c["clips"][0]["render"].update(duration=math.nan),
        lambda c: c["clips"][0]["render"].update(relative_path="cinema-studio/renders/other/x.mp4"),
        lambda c: c["clips"][0]["render"].update(
            relative_path="cinema-studio/renders/clip-a/../x.mp4"
        ),
    ],
)
def test_bad_contract_fails_or_bad_clip_is_dropped(mutate) -> None:
    data = copy.deepcopy(payload())
    mutate(data)
    if data["contract_version"] != 1:
        with pytest.raises(ValueError):
            parse_catalog(data)
    else:
        catalog = parse_catalog(data)
        assert catalog.invalid_clip_ids == ("clip-a",)
        assert catalog.clips == ()
