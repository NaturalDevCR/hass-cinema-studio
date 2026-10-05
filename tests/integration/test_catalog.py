from __future__ import annotations

import copy
import math

import pytest

from custom_components.cinema_studio.catalog import parse_catalog

pytestmark = pytest.mark.integration


def test_parse_catalog_and_find_collection(catalog_payload: dict) -> None:
    catalog = parse_catalog(catalog_payload)
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
        lambda c: c["clips"][0]["render"].update(tail_out=99),
        lambda c: c["clips"][0]["render"].update(media_path="elsewhere"),
        lambda c: c["clips"][0]["render"].update(
            relative_path="cinema-studio\\renders\\clip-a\\x.mp4"
        ),
    ],
)
def test_bad_contract_fails_or_bad_clip_is_dropped(mutate, catalog_payload: dict) -> None:
    data = copy.deepcopy(catalog_payload)
    mutate(data)
    if data["contract_version"] != 1:
        with pytest.raises(ValueError):
            parse_catalog(data)
    else:
        catalog = parse_catalog(data)
        assert catalog.invalid_clip_ids == ("clip-a",)
        assert catalog.clips == ()
