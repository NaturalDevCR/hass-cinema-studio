from datetime import date

import pytest

from custom_components.cinema_studio.catalog import parse_catalog
from custom_components.cinema_studio.seasons import UnknownSeasonError, resolve_effective_season

pytestmark = pytest.mark.integration


def test_effective_season_precedence_and_entity_name(catalog_payload: dict) -> None:
    data = catalog_payload.copy()
    data["seasons"] = list(data["seasons"])
    data["seasons"].append(
        {
            "id": "halloween",
            "name": "Halloween",
            "color": "",
            "icon": "",
            "start": "10-01",
            "end": "10-31",
            "priority": 10,
            "collection_id": "regular",
        }
    )
    catalog = parse_catalog(data)
    base = dict(catalog=catalog, day=date(2026, 10, 15), override=None, entity_state=None)
    assert resolve_effective_season(**(base | {"action_season": "regular"})) == (
        "regular",
        "action",
    )
    assert resolve_effective_season(
        **(base | {"action_season": None, "override": "halloween"})
    ) == ("halloween", "override")
    assert resolve_effective_season(
        **(base | {"action_season": None, "entity_state": "Halloween"})
    ) == ("halloween", "entity")
    assert resolve_effective_season(**(base | {"action_season": None})) == ("halloween", "calendar")
    with pytest.raises(UnknownSeasonError):
        resolve_effective_season(**(base | {"action_season": "missing"}))
