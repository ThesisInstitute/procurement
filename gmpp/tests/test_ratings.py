"""Harmonising published Delivery Confidence Assessment strings."""
from __future__ import annotations

import pytest

from gmpp.src.ratings import (
    FIVE_POINT,
    THREE_POINT,
    harmonise,
    implied_p_adverse,
    normalised_rank,
    rank,
    scale_for_year,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Green", "Green"),
        ("GREEN", "Green"),
        ("Amber", "Amber"),
        ("AMBER", "Amber"),
        ("Red", "Red"),
        ("RED", "Red"),
        ("Amber/Green", "Amber/Green"),
        ("Amber/ Green", "Amber/Green"),
        ("Amber/Red", "Amber/Red"),
        ("Amber/ Red", "Amber/Red"),
        ("Amber/red", "Amber/Red"),
        ("Amber - Red", "Amber/Red"),
    ],
)
def test_rating_spellings(text, expected):
    assert harmonise(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Exempt under Section 43 of the Freedom of Information Act (2000)",
        "Data exempt under Section 35 of the Freedom of Information Act (2000)",
        "Section 24 - National security",
        "Exempt under Sections 24 and 31(1) of the Freedom of Information Act (2000)",
    ],
)
def test_exempt_is_its_own_category(text):
    assert harmonise(text) == "EXEMPT"


@pytest.mark.parametrize(
    "text",
    [
        "No DCA",
        "Not Applicable",
        "The project is not in a position to provide this information",
        "The project is still at the planning stage and is not yet in a position to "
        "provide this information",
        "Early planning GMPP project \r\n\r\n(The project has not yet passed SOC, or "
        "its programme equivalent)",
    ],
)
def test_unrated_is_its_own_category(text):
    assert harmonise(text) == "NOT_RATED"


def test_reset_is_its_own_category():
    assert harmonise("Reset") == "RESET"


@pytest.mark.parametrize("text", ["", "   ", None, float("nan"), "nan"])
def test_blank_is_missing(text):
    assert harmonise(text) == "MISSING"


def test_scale_in_force_follows_the_published_headers():
    # Every publication from 2013 to 2021 states a five-point scale in its DCA
    # header; 2022 onward state three-point.
    for year in range(2013, 2022):
        assert scale_for_year(year) == "five_point"
    for year in range(2022, 2027):
        assert scale_for_year(year) == "three_point"


def test_rank_is_green_best_and_scale_specific():
    assert rank("Green", "five_point") == 0
    assert rank("Red", "five_point") == 4
    assert rank("Green", "three_point") == 0
    assert rank("Red", "three_point") == 2
    # Amber sits at the same ordinal position on both scales but means something
    # different, which is why the two eras are never pooled.
    assert rank("Amber", "five_point") == 2
    assert rank("Amber", "three_point") == 1


def test_rank_is_none_for_non_ratings():
    for label in ("EXEMPT", "RESET", "NOT_RATED", "MISSING", "UNPARSED"):
        assert rank(label, "five_point") is None
        assert rank(label, "three_point") is None


def test_normalised_rank_spans_zero_to_one():
    assert normalised_rank("Green", "five_point") == 0.0
    assert normalised_rank("Red", "five_point") == 1.0
    assert normalised_rank("Amber", "three_point") == pytest.approx(0.5)


def test_implied_probability_is_monotone_in_the_rank():
    for scale, order in (("five_point", FIVE_POINT), ("three_point", THREE_POINT)):
        probabilities = [implied_p_adverse(r, scale) for r in order]
        assert probabilities == sorted(probabilities)
        assert all(0.0 <= p <= 1.0 for p in probabilities)
