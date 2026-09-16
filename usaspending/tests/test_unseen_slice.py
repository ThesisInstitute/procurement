"""The unseen-recipient slice must be a statement about contractors.

An award booked to an aggregate placeholder recipient has no identifiable
contractor, so it is neither a contractor seen in training nor one unseen in
training. Letting the bucket code into the training set of UEIs would mark a
test award as "seen" because the bucket appears in both periods rather than
because any contractor does.
"""
import numpy as np
import pandas as pd
import pytest

import models as M


def _slice(train_ueis, test_ueis, train_agg=None, test_agg=None):
    """Reproduce the slice logic on a tiny frame and return (unseen, excluded)."""
    n_tr, n_te = len(train_ueis), len(test_ueis)
    d = pd.DataFrame({
        "recipient_uei": list(train_ueis) + list(test_ueis),
        "recipient_is_aggregate": list(train_agg or [0] * n_tr)
                                  + list(test_agg or [0] * n_te),
    })
    masks = {"train": np.array([True] * n_tr + [False] * n_te),
             "test": np.array([False] * n_tr + [True] * n_te)}
    agg = d["recipient_is_aggregate"].astype(bool).to_numpy()
    train_uei = set(d.loc[masks["train"] & ~agg, "recipient_uei"].dropna().unique())
    te = d[masks["test"]]
    te_agg = agg[masks["test"]]
    unseen = (~te["recipient_uei"].isin(train_uei).to_numpy()) & ~te_agg
    return unseen, int(te_agg.sum())


def test_a_contractor_present_in_training_is_not_unseen():
    unseen, _ = _slice(["A", "B"], ["A", "C"])
    assert unseen.tolist() == [False, True]


def test_an_aggregate_bucket_in_both_periods_does_not_make_a_test_row_seen():
    """The bug: bucket AGG appears in train, so the test row counted as seen."""
    unseen, excluded = _slice(["A", "AGG"], ["AGG", "C"],
                              train_agg=[0, 1], test_agg=[1, 0])
    # the aggregate test row is excluded from the slice entirely, not called seen
    assert unseen.tolist() == [False, True]
    assert excluded == 1


def test_an_aggregate_bucket_only_in_test_is_still_excluded_not_called_unseen():
    """The mirror image: it must not inflate the slice either."""
    unseen, excluded = _slice(["A"], ["AGG", "C"], test_agg=[1, 0])
    assert unseen.tolist() == [False, True]
    assert excluded == 1


def test_a_real_contractor_is_unaffected_by_an_aggregate_row_beside_it():
    unseen, excluded = _slice(["A", "AGG"], ["A", "AGG", "D"],
                              train_agg=[0, 1], test_agg=[0, 1, 0])
    assert unseen.tolist() == [False, False, True]
    assert excluded == 1


def test_excluding_aggregates_from_train_ueis_cannot_mark_a_real_firm_unseen():
    """Removing buckets from train_uei must not disturb genuine contractors."""
    keep, _ = _slice(["A", "B", "AGG"], ["A", "B"], train_agg=[0, 0, 1])
    assert keep.tolist() == [False, False]


def test_run_cell_records_the_number_of_excluded_rows():
    """The exclusion count is published so the choice stays checkable."""
    import inspect
    src = inspect.getsource(M.run_cell)
    assert "test_rows_excluded_as_aggregate_recipient" in src
    assert 'd.loc[masks["train"] & ~agg, "recipient_uei"]' in src
