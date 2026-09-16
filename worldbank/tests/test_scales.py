"""Tests for the observed rating scale mapping."""
import pandas as pd
import pytest

from worldbank.src import scales


@pytest.mark.parametrize("value,expected", [
    ("Highly Unsatisfactory", 1),
    ("Unsatisfactory", 2),
    ("Moderately Unsatisfactory", 3),
    ("Moderately Satisfactory", 4),
    ("Satisfactory", 5),
    ("Highly Satisfactory", 6),
])
def test_six_point_is_ordered(value, expected):
    assert scales.to_six_point(value) == expected


def test_six_point_strictly_increasing():
    order = ["Highly Unsatisfactory", "Unsatisfactory", "Moderately Unsatisfactory",
             "Moderately Satisfactory", "Satisfactory", "Highly Satisfactory"]
    vals = [scales.to_six_point(v) for v in order]
    assert vals == sorted(vals)
    assert len(set(vals)) == 6


@pytest.mark.parametrize("value", ["Not Rated", "", None, float("nan"), "Weird"])
def test_not_rated_and_unknown_map_to_none(value):
    assert scales.to_six_point(value) is None


def test_whitespace_and_case_tolerated():
    assert scales.to_six_point("  satisfactory ") == 5
    assert scales.to_six_point("MODERATELY SATISFACTORY") == 4


@pytest.mark.parametrize("value,expected", [
    ("Highly Unsatisfactory", 0.0),
    ("Unsatisfactory", 0.0),
    ("Moderately Unsatisfactory", 0.0),
    ("Moderately Satisfactory", 1.0),
    ("Satisfactory", 1.0),
    ("Highly Satisfactory", 1.0),
])
def test_satisfactory_label_cut_is_at_moderately_satisfactory(value, expected):
    assert scales.satisfactory_label(value) == expected


def test_satisfactory_label_none_for_not_rated():
    assert scales.satisfactory_label("Not Rated") is None


def test_four_point_scale_is_separate_from_six_point():
    assert scales.to_four_point("Negligible") == 1
    assert scales.to_four_point("Modest") == 2
    assert scales.to_four_point("Substantial") == 3
    assert scales.to_four_point("High") == 4
    # A four-point value must not silently land on the six-point scale.
    assert scales.to_six_point("Substantial") is None
    assert scales.to_six_point("Modest") is None
    # ...and a six-point value must not land on the four-point scale.
    assert scales.to_four_point("Moderately Satisfactory") is None


def test_series_helpers_preserve_length_and_nulls():
    s = pd.Series(["Satisfactory", "Not Rated", "Unsatisfactory", None])
    six = scales.series_six_point(s)
    lab = scales.series_satisfactory(s)
    assert len(six) == 4 and len(lab) == 4
    assert six.tolist()[0] == 5
    assert pd.isna(six.tolist()[1])
    assert lab.tolist()[0] == 1.0 and lab.tolist()[2] == 0.0
    assert pd.isna(lab.tolist()[3])


# ------ abbreviations and sentinels observed in the GovTech workbook --------

@pytest.mark.parametrize("value,expected", [
    ("HS", 6), ("S", 5), ("MS", 4), ("MU", 3), ("U", 2), ("HU", 1),
    ("hs", 6), (" ms ", 4),
])
def test_abbreviations_expand_only_when_requested(value, expected):
    assert scales.to_six_point(value, allow_abbrev=True) == expected


@pytest.mark.parametrize("value", ["HS", "S", "MS", "MU", "U", "HU"])
def test_abbreviations_are_off_by_default(value):
    """Off by default because these letters collide with other WB code sets."""
    assert scales.to_six_point(value) is None
    assert scales.satisfactory_label(value) is None
    assert scales.canonicalise(value) is None


def test_the_specific_collisions_that_motivate_the_default():
    # esrc_ovrl_risk_rate uses "S" for Substantial, not Satisfactory
    assert scales.to_six_point("S") is None
    # envassesmentcategorycode uses "U"
    assert scales.to_six_point("U") is None
    # ISO country codes include MU (Mauritius) and HU (Hungary)
    assert scales.to_six_point("MU") is None
    assert scales.to_six_point("HU") is None


@pytest.mark.parametrize("value", ["-", "?", "#", "#MULTIVALUE", "NV", "NR",
                                   "0", 0, "N/A"])
def test_govtech_sentinels_are_not_ratings(value):
    assert scales.to_six_point(value, allow_abbrev=True) is None
    assert scales.satisfactory_label(value, allow_abbrev=True) is None


def test_abbreviation_and_long_form_agree_when_expansion_is_allowed():
    pairs = [("HS", "Highly Satisfactory"), ("S", "Satisfactory"),
             ("MS", "Moderately Satisfactory"),
             ("MU", "Moderately Unsatisfactory"), ("U", "Unsatisfactory"),
             ("HU", "Highly Unsatisfactory")]
    for short, long in pairs:
        assert (scales.to_six_point(short, allow_abbrev=True)
                == scales.to_six_point(long))
        assert scales.canonicalise(short, allow_abbrev=True) == long


def test_substantial_is_never_an_outcome_even_with_abbrev_on():
    assert scales.to_six_point("Substantial", allow_abbrev=True) is None
    assert scales.to_four_point("Substantial") == 3


# ------------------ the two four-point risk-scale vintages ------------------

@pytest.mark.parametrize("value,expected,vintage", [
    ("Negligible", 1, "new"), ("Modest", 2, "new"),
    ("Substantial", 3, "new"), ("High", 4, "both"),
    ("Negligible To Low", 1, "old"), ("Moderate", 2, "old"),
    ("Significant", 3, "old"),
])
def test_both_risk_vocabularies_map_and_report_their_vintage(value, expected,
                                                            vintage):
    assert scales.to_four_point(value) == expected
    assert scales.risk_vintage(value) == vintage


def test_risk_vocabularies_are_ordinally_aligned():
    new = ["Negligible", "Modest", "Substantial", "High"]
    old = ["Negligible To Low", "Moderate", "Significant", "High"]
    assert ([scales.to_four_point(v) for v in new]
            == [scales.to_four_point(v) for v in old] == [1, 2, 3, 4])


def test_risk_vintage_is_none_for_a_six_point_value():
    assert scales.risk_vintage("Moderately Satisfactory") is None


def test_series_helpers_take_the_abbrev_flag():
    s = pd.Series(["S", "MS", "-"])
    assert scales.series_six_point(s).isna().all()
    assert scales.series_six_point(s, allow_abbrev=True).tolist()[:2] == [5, 4]


# -- the two label cuts ---------------------------------------------------
# The pre-registered label is outcome >= Moderately Satisfactory; the
# robustness check in src/analysis.py uses outcome >= Satisfactory. Both go
# through label_at_least so there is one tested code path for a cut.

@pytest.mark.parametrize("value,at_ms,at_s", [
    ("Highly Unsatisfactory", 0.0, 0.0),
    ("Unsatisfactory", 0.0, 0.0),
    ("Moderately Unsatisfactory", 0.0, 0.0),
    ("Moderately Satisfactory", 1.0, 0.0),
    ("Satisfactory", 1.0, 1.0),
    ("Highly Satisfactory", 1.0, 1.0),
])
def test_both_cut_points_on_the_observed_scale(value, at_ms, at_s):
    assert scales.label_at_least(value, scales.MS_OR_BETTER) == at_ms
    assert scales.label_at_least(value, scales.S_OR_BETTER) == at_s


def test_the_second_cut_is_strictly_tighter_than_the_first():
    """Moderately Satisfactory is the only rating the two cuts disagree on."""
    order = ["Highly Unsatisfactory", "Unsatisfactory",
             "Moderately Unsatisfactory", "Moderately Satisfactory",
             "Satisfactory", "Highly Satisfactory"]
    ms = [scales.label_at_least(v, scales.MS_OR_BETTER) for v in order]
    s = [scales.label_at_least(v, scales.S_OR_BETTER) for v in order]
    assert all(a >= b for a, b in zip(ms, s))
    assert [a != b for a, b in zip(ms, s)] == [False, False, False,
                                               True, False, False]


def test_satisfactory_label_is_the_ms_cut():
    for v in ["Highly Unsatisfactory", "Moderately Satisfactory",
              "Satisfactory", "Not Rated", "nonsense"]:
        assert scales.satisfactory_label(v) == scales.label_at_least(
            v, scales.MS_OR_BETTER)


@pytest.mark.parametrize("value", ["Not Rated", "", None, float("nan")])
def test_unrated_values_have_no_label_at_either_cut(value):
    assert scales.label_at_least(value, scales.MS_OR_BETTER) is None
    assert scales.label_at_least(value, scales.S_OR_BETTER) is None


@pytest.mark.parametrize("value", ["Substantial", "Modest", "Negligible",
                                   "Significant", "Moderate"])
def test_a_four_point_value_never_produces_a_label(value):
    """The scales are kept separate precisely so this cannot silently score."""
    assert scales.to_four_point(value) is not None
    assert scales.label_at_least(value, scales.MS_OR_BETTER) is None
    assert scales.label_at_least(value, scales.S_OR_BETTER) is None


def test_high_is_four_point_only_and_is_not_a_satisfactory_label():
    assert scales.to_four_point("High") == 4
    assert scales.label_at_least("High", scales.MS_OR_BETTER) is None


@pytest.mark.parametrize("bad", [0, 7, -1, 10])
def test_an_off_scale_cut_point_is_refused(bad):
    with pytest.raises(ValueError, match="six-point"):
        scales.label_at_least("Satisfactory", bad)


def test_label_at_least_respects_the_abbrev_flag():
    assert scales.label_at_least("S", scales.S_OR_BETTER) is None
    assert scales.label_at_least("S", scales.S_OR_BETTER,
                                 allow_abbrev=True) == 1.0
    assert scales.label_at_least("MS", scales.S_OR_BETTER,
                                 allow_abbrev=True) == 0.0


def test_series_label_at_least_matches_the_scalar_function():
    s = pd.Series(["Satisfactory", "Moderately Satisfactory", "Not Rated"])
    out = scales.series_label_at_least(s, scales.S_OR_BETTER)
    assert out.tolist()[:2] == [1.0, 0.0]
    assert pd.isna(out.tolist()[2])
