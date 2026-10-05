from __future__ import annotations

import pytest
from pydantic import ValidationError

from cinema_studio.errors import InvalidError
from cinema_studio.models import (
    Crop,
    OriginalInfo,
    Recipe,
    SelectionBatch,
    SelectionEvent,
    default_sort_key,
    slugify,
)

pytestmark = pytest.mark.studio

ORIGINAL = OriginalInfo(
    filename="m.mp4",
    size=1,
    sha256="x",
    duration=60.0,
    width=1920,
    height=1080,
    fps=24.0,
    has_audio=True,
    video_codec="h264",
)


def test_recipe_defaults_keep_the_whole_clip_with_default_margins() -> None:
    recipe = Recipe()
    assert (recipe.trim_start, recipe.trim_end, recipe.crop) == (0.0, None, None)
    assert (recipe.fade_in, recipe.fade_out, recipe.gain_db) == (None, None, 0.0)
    assert (recipe.profile_id, recipe.lead_in, recipe.tail_out) == (None, 2.0, 2.0)
    recipe.validate_for(ORIGINAL)


@pytest.mark.parametrize(
    ("recipe", "message"),
    [
        (Recipe(trim_start=10.0, trim_end=5.0), "before trim end"),
        (Recipe(trim_end=61.0), "past the end"),
        (Recipe(trim_start=60.0), "at or past the end"),
        (Recipe(crop=Crop(x=1000, y=0, w=1000, h=100)), "crop"),
        (Recipe(crop=Crop(x=0, y=1000, w=100, h=100)), "crop"),
        (Recipe(trim_start=0.0, trim_end=3.0, fade_in=2.0, fade_out=2.0), "Fade"),
    ],
)
def test_recipe_validate_for_rejects(recipe: Recipe, message: str) -> None:
    with pytest.raises(InvalidError, match=message):
        recipe.validate_for(ORIGINAL)


def test_recipe_accepts_a_crop_inside_the_frame_and_small_trim_overshoot() -> None:
    Recipe(crop=Crop(x=10, y=10, w=1910, h=1070), trim_end=60.04).validate_for(ORIGINAL)


def test_recipe_rejects_nonfinite_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Recipe.model_validate({"lead_in": float("inf")})
    with pytest.raises(ValidationError):
        Recipe.model_validate({"nope": 1})


def test_selection_batch_is_capped_and_timestamps_normalised() -> None:
    event = {
        "selection_id": "s",
        "clip_id": "c",
        "render_id": "r",
        "catalog_revision": 1,
        "selected_at": "2026-10-05T10:00:00-06:00",
    }
    batch = SelectionBatch.model_validate({"events": [event]})
    assert batch.events[0].selected_at == "2026-10-05T16:00:00Z"
    with pytest.raises(ValidationError):
        SelectionBatch.model_validate({"events": [event] * 501})
    with pytest.raises(ValidationError):
        SelectionEvent.model_validate({**event, "selected_at": "yesterday"})


def test_helpers() -> None:
    assert slugify("Películas Épicas!") == "peliculas_epicas"
    assert default_sort_key("Regular", "ABC-1") == "regular/abc-1.mp4"
