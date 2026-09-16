"""Tests for the forward-chained fold construction.

This is the guarantee the whole backtest rests on: a model is never trained on a
project approved later than one it is scored on. The audit noted these functions
had no direct coverage, and they are the wrong functions to leave untested.
"""
import pandas as pd
import pytest

from worldbank.src import model


def _frame(years):
    return pd.DataFrame({"approval_year": years,
                         "y_satisfactory": [1.0] * len(years)})


def test_preregistered_cut_points_are_used_when_the_test_fold_is_big_enough():
    df = _frame(list(range(1996, 2006)) * 50 + list(range(2006, 2011)) * 50
                + list(range(2011, 2020)) * 100)
    cuts = model.choose_splits(df, min_test=800)
    assert (cuts["train_end"], cuts["valid_end"]) == (2005, 2010)
    assert cuts["moved_from_preregistered"] is False


def test_the_boundary_only_ever_moves_earlier_never_later():
    """A too-small test fold is grown by taking years FROM validation."""
    df = _frame(list(range(1996, 2006)) * 50 + list(range(2006, 2011)) * 50
                + [2011] * 10)
    cuts = model.choose_splits(df, min_test=800)
    assert cuts["valid_end"] <= 2010
    assert cuts["train_end"] == 2005
    assert cuts["moved_from_preregistered"] is True


def test_moving_the_boundary_is_recorded_not_silent():
    df = _frame(list(range(1996, 2006)) * 50 + list(range(2006, 2011)) * 50
                + [2011] * 10)
    cuts = model.choose_splits(df, min_test=800)
    assert "moved_from_preregistered" in cuts
    assert cuts["moved_from_preregistered"] is True


def test_the_loop_terminates_even_when_the_test_fold_can_never_be_filled():
    df = _frame([1996] * 5 + [2011] * 3)
    cuts = model.choose_splits(df, min_test=10_000)
    assert cuts["valid_end"] <= cuts["train_end"] + 1
    assert cuts["n_test"] >= 0


def test_the_three_folds_partition_the_frame_exactly():
    years = list(range(1996, 2024)) * 7
    df = _frame(years)
    cuts = model.choose_splits(df)
    tr, va, te = model.split(df, cuts)
    assert len(tr) + len(va) + len(te) == len(df)
    assert cuts["n_train"] == len(tr)
    assert cuts["n_valid"] == len(va)
    assert cuts["n_test"] == len(te)


def test_no_training_project_is_approved_later_than_a_test_project():
    """The forward-chaining guarantee, stated as an assertion."""
    df = _frame(list(range(1996, 2024)) * 7)
    cuts = model.choose_splits(df)
    tr, va, te = model.split(df, cuts)
    assert tr["approval_year"].max() < va["approval_year"].min()
    assert va["approval_year"].max() < te["approval_year"].min()
    fit = pd.concat([tr, va])
    assert fit["approval_year"].max() < te["approval_year"].min()


def test_folds_are_disjoint_on_row_identity():
    df = _frame(list(range(1996, 2024)) * 7)
    cuts = model.choose_splits(df)
    tr, va, te = model.split(df, cuts)
    idx = set(tr.index) | set(va.index) | set(te.index)
    assert len(idx) == len(df)
    assert not (set(tr.index) & set(te.index))
    assert not (set(va.index) & set(te.index))


def test_an_empty_frame_does_not_raise():
    cuts = model.choose_splits(_frame([]), min_test=0)
    assert cuts["n_train"] == cuts["n_valid"] == cuts["n_test"] == 0


@pytest.mark.parametrize("min_test", [1, 100, 800])
def test_the_test_fold_meets_the_requested_size_when_the_data_allows(min_test):
    df = _frame(list(range(1996, 2006)) * 50 + list(range(2006, 2011)) * 50
                + list(range(2011, 2020)) * 100)
    cuts = model.choose_splits(df, min_test=min_test)
    assert cuts["n_test"] >= min_test
