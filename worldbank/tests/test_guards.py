"""Tests for the loud-failure guards.

These exist because of one specific bug, reproduced below as
`test_reproduces_the_abbreviation_bug_that_emptied_route_one`: the GovTech
workbook's abbreviated ratings were mapped with a function that refuses
abbreviations, every value became None, and the report published
"n = 0, exact agreement nan%" under a heading claiming a verified result.

The guards do not check that numbers are correct. They check that a computation
which must produce rows produced some, so a hole can never be formatted into a
deliverable.
"""
import numpy as np
import pandas as pd
import pytest

from worldbank.src import govtech, guards, scales


# -- require_rows ---------------------------------------------------------

def test_require_rows_passes_a_populated_frame():
    df = pd.DataFrame({"a": [1, 2, 3]})
    assert guards.require_rows(df, "x") is df


def test_require_rows_raises_on_empty():
    with pytest.raises(guards.EmptyResultError, match="got 0"):
        guards.require_rows(pd.DataFrame({"a": []}), "disagreement table")


def test_require_rows_raises_on_none():
    with pytest.raises(guards.EmptyResultError):
        guards.require_rows(None, "missing frame")


def test_require_rows_enforces_a_minimum_above_one():
    df = pd.DataFrame({"a": [1, 2]})
    guards.require_rows(df, "x", minimum=2)
    with pytest.raises(guards.EmptyResultError, match="at least 3"):
        guards.require_rows(df, "x", minimum=3)


def test_require_rows_message_names_the_stage_and_the_hint():
    with pytest.raises(guards.EmptyResultError) as e:
        guards.require_rows(pd.DataFrame(), "route 1", hint="check the join key")
    assert "route 1" in str(e.value)
    assert "check the join key" in str(e.value)


# -- require_finite -------------------------------------------------------

def test_require_finite_passes_a_real_number():
    assert guards.require_finite(0.25, "rate") == 0.25


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_require_finite_raises_on_non_finite(bad):
    with pytest.raises(guards.EmptyResultError):
        guards.require_finite(bad, "agreement rate")


def test_require_finite_catches_the_mean_of_an_empty_series():
    """This is the exact shape the published `nan%` took."""
    empty = pd.Series([], dtype=float)
    with pytest.raises(guards.EmptyResultError, match="finite"):
        guards.require_finite(empty.mean(), "agreement rate")


# -- require_mapped -------------------------------------------------------

def test_require_mapped_passes_when_the_mapping_works():
    orig = pd.Series(["Satisfactory", "Unsatisfactory", None])
    mapped = orig.map(scales.to_six_point)
    out = guards.require_mapped(orig, mapped, "outcome", min_share=0.5)
    assert out.notna().sum() == 2


def test_require_mapped_raises_when_everything_maps_to_null():
    orig = pd.Series(["S", "MS", "HS"])
    mapped = orig.map(scales.to_six_point)          # refuses abbreviations
    with pytest.raises(guards.EmptyResultError, match="0 of 3"):
        guards.require_mapped(orig, mapped, "govtech outcome")


def test_require_mapped_raises_on_an_all_null_source_column():
    orig = pd.Series([None, None], dtype=object)
    with pytest.raises(guards.EmptyResultError, match="entirely null"):
        guards.require_mapped(orig, orig, "outcome")


def test_require_mapped_tolerates_a_minority_of_sentinels():
    """The real workbook column carries "-", "?" and 0 alongside ratings."""
    orig = pd.Series(["S", "MS", "-", "?", "S", "0"])
    mapped = orig.map(govtech.six_point)
    out = guards.require_mapped(orig, mapped, "govtech outcome", min_share=0.5)
    assert out.notna().sum() == 3


def test_require_mapped_reports_a_sample_of_what_failed():
    orig = pd.Series(["S", "MS", "HS"])
    with pytest.raises(guards.EmptyResultError) as e:
        guards.require_mapped(orig, orig.map(scales.to_six_point), "outcome")
    msg = str(e.value)
    assert "'S'" in msg and "'MS'" in msg


def test_reproduces_the_abbreviation_bug_that_emptied_route_one():
    """End to end, on a fixture shaped like the workbook.

    Without the guard this sequence yields an empty frame and a NaN rate, which
    is what shipped. With the guard it raises at the mapping step.
    """
    workbook = pd.DataFrame({
        "projectid": ["P1", "P2", "P3", "P4"],
        "gt_icr_outcome": ["S", "MS", "U", "-"],
    })
    ratings = pd.DataFrame({
        "projectid": ["P1", "P2", "P3", "P4"],
        "ieg_outcome": ["Satisfactory", "Moderately Unsatisfactory",
                        "Unsatisfactory", "Satisfactory"],
    })

    # the buggy path: abbreviations refused, everything becomes null
    bad = workbook["gt_icr_outcome"].map(scales.to_six_point)
    merged = workbook.assign(bank=bad).merge(ratings, on="projectid")
    merged["ieg"] = merged["ieg_outcome"].map(scales.to_six_point)
    collapsed = merged.dropna(subset=["bank", "ieg"])
    assert len(collapsed) == 0
    assert np.isnan((collapsed["bank"] == collapsed["ieg"]).mean())

    with pytest.raises(guards.EmptyResultError):
        guards.require_mapped(workbook["gt_icr_outcome"], bad, "route 1")

    # the fixed path: abbreviations expanded by the opt-in wrapper
    good = workbook["gt_icr_outcome"].map(govtech.six_point)
    guards.require_mapped(workbook["gt_icr_outcome"], good, "route 1",
                          min_share=0.5)
    merged = workbook.assign(bank=good).merge(ratings, on="projectid")
    merged["ieg"] = merged["ieg_outcome"].map(scales.to_six_point)
    kept = merged.dropna(subset=["bank", "ieg"])
    assert len(kept) == 3
    # P1 S vs Satisfactory agree; P2 MS above MU; P3 U vs U agree
    assert float((kept["bank"] == kept["ieg"]).mean()) == pytest.approx(2 / 3)


# -- require_overlap ------------------------------------------------------

def test_require_overlap_counts_shared_keys():
    assert guards.require_overlap(["P1", "P2"], ["P2", "P3"], "join") == 1


def test_require_overlap_raises_when_an_inner_join_would_be_empty():
    with pytest.raises(guards.EmptyResultError, match="got 0"):
        guards.require_overlap(["P1"], ["P2"], "join")


def test_require_overlap_catches_a_case_normalisation_mismatch():
    """Upper vs lower P-numbers is the classic silent-empty join."""
    with pytest.raises(guards.EmptyResultError):
        guards.require_overlap(["p123", "p456"], ["P123", "P456"], "join")
