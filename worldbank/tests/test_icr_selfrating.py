"""Tests for the documented icr_ratings repair and the disagreement table."""
import numpy as np
import pandas as pd
import pytest

from worldbank.src import icr_selfrating as icr
from worldbank.src import scales


def test_substantial_is_read_as_satisfactory_inside_the_icr_block():
    assert icr.repair_icr_value("Substantial") == "Satisfactory"
    assert icr.repaired_six_point("Substantial") == 5


def test_repair_leaves_every_other_six_point_value_alone():
    for v in ["Highly Satisfactory", "Satisfactory", "Moderately Satisfactory",
              "Moderately Unsatisfactory", "Unsatisfactory",
              "Highly Unsatisfactory"]:
        assert icr.repair_icr_value(v) == v
        assert icr.repaired_six_point(v) == scales.to_six_point(v)


def test_repair_does_not_change_the_plain_scale_mapping():
    """The repair must not leak into the IEG side of the comparison."""
    assert scales.to_six_point("Substantial") is None
    assert scales.to_four_point("Substantial") == 3


def test_repair_is_idempotent():
    once = icr.repair_icr_value("Substantial")
    assert icr.repair_icr_value(once) == once


@pytest.mark.parametrize("v", ["Not Rated", None, "", "Modest", "Negligible"])
def test_repair_returns_none_for_non_outcome_values(v):
    assert icr.repaired_six_point(v) is None


def test_repair_frame_adds_columns_without_mutating_input():
    df = pd.DataFrame({"icr_outratingind": ["Substantial", "Moderately Satisfactory"],
                       "icr_borroverall": ["Substantial", "Unsatisfactory"]})
    before = df.copy()
    out = icr.repair_frame(df)
    pd.testing.assert_frame_equal(df, before)
    assert out["icr_outratingind_six_point"].tolist() == [5, 4]
    assert out["icr_borroverall_six_point"].tolist() == [5, 2]


def test_repair_frame_tolerates_missing_columns():
    out = icr.repair_frame(pd.DataFrame({"icr_outratingind": ["Substantial"]}))
    assert "icr_outratingind_six_point" in out.columns
    assert "icr_borroverall_six_point" not in out.columns


# --------------------------------------------------------- disagreement

def _frame():
    return pd.DataFrame({
        "bank": [5, 5, 4, 3, 6, 4],
        "ieg":  [5, 4, 4, 4, 4, 2],
        "year": [2010, 2010, 2011, 2011, 2011, 2011],
    })


def test_disagreement_rates_are_shares_within_year():
    t = icr.disagreement_table(_frame(), "bank", "ieg", "year").set_index("year")
    assert t.loc[2010, "n"] == 2
    assert t.loc[2010, "agree"] == pytest.approx(0.5)
    assert t.loc[2010, "bank_higher"] == pytest.approx(0.5)
    assert t.loc[2010, "bank_lower"] == pytest.approx(0.0)
    assert t.loc[2011, "n"] == 4
    assert t.loc[2011, "agree"] == pytest.approx(0.25)
    assert t.loc[2011, "bank_higher"] == pytest.approx(0.5)
    assert t.loc[2011, "bank_lower"] == pytest.approx(0.25)


def test_disagreement_shares_sum_to_one():
    t = icr.disagreement_table(_frame(), "bank", "ieg", "year")
    total = t["agree"] + t["bank_higher"] + t["bank_lower"]
    assert np.allclose(total.values, 1.0)


def test_disagreement_mean_gap_sign_is_bank_minus_ieg():
    df = pd.DataFrame({"bank": [5, 5], "ieg": [4, 4], "year": [2010, 2010]})
    t = icr.disagreement_table(df, "bank", "ieg", "year")
    assert t["mean_gap"].iloc[0] == pytest.approx(1.0)


def test_disagreement_drops_unrated_rows():
    df = pd.DataFrame({"bank": [5, np.nan, 4], "ieg": [4, 4, np.nan],
                       "year": [2010, 2010, 2010]})
    t = icr.disagreement_table(df, "bank", "ieg", "year")
    assert t["n"].iloc[0] == 1


def test_disagreement_empty_input_returns_empty_table():
    df = pd.DataFrame({"bank": [np.nan], "ieg": [np.nan], "year": [2010]})
    t = icr.disagreement_table(df, "bank", "ieg", "year")
    assert len(t) == 0
    assert list(t.columns) == ["year", "n", "agree", "bank_higher",
                               "bank_lower", "mean_gap"]
