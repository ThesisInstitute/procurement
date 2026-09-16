"""Shrunk cell means: the reference-class rung of the ladder."""
import numpy as np
import pandas as pd
import pytest

from reference_class import MIN_CELL_N, ReferenceClassModel, assign_quintile, value_quintiles


def _frame(n_per_cell, agencies=("A", "B"), naics=("11", "54")):
    rows = []
    rng = np.random.RandomState(0)
    for a in agencies:
        for nc in naics:
            for i in range(n_per_cell):
                rows.append({
                    "awarding_agency_code": a,
                    "naics2": nc,
                    "type_of_contract_pricing_code": "J",
                    "log_base_ceiling": 5.0 + rng.uniform(0, 2),
                })
    return pd.DataFrame(rows)


def test_value_quintiles_returns_four_interior_edges():
    s = pd.Series(np.arange(1000, dtype=float))
    e = value_quintiles(s)
    assert len(e) == 4
    assert e[0] < e[1] < e[2] < e[3]


def test_assign_quintile_puts_values_in_five_buckets():
    s = pd.Series(np.arange(100, dtype=float))
    e = value_quintiles(s)
    q = assign_quintile(s, e)
    assert set(q.unique()) <= {"0", "1", "2", "3", "4"}
    assert q.nunique() == 5


def test_assign_quintile_marks_missing_values():
    e = np.array([1.0, 2.0, 3.0, 4.0])
    q = assign_quintile(pd.Series([np.nan, 2.5]), e)
    assert q.iloc[0] == "NA"
    assert q.iloc[1] != "NA"


def test_prediction_equals_global_mean_when_nothing_matches():
    train = _frame(100)
    y = pd.Series(np.zeros(len(train)))
    y.iloc[:50] = 1.0
    m = ReferenceClassModel().fit(train, y)
    novel = pd.DataFrame([{
        "awarding_agency_code": "ZZZ", "naics2": "99",
        "type_of_contract_pricing_code": "Q", "log_base_ceiling": 6.0}])
    assert m.predict(novel)[0] == pytest.approx(m.global_mean_)


def test_large_homogeneous_cell_is_barely_shrunk():
    train = _frame(500, agencies=("A",), naics=("11",))
    y = pd.Series(np.ones(len(train)))
    y.iloc[: len(train) // 2] = 0.0  # global mean 0.5
    # make one quintile all ones
    train = train.sort_values("log_base_ceiling").reset_index(drop=True)
    y = pd.Series(np.where(train.index >= 400, 1.0, 0.0))
    m = ReferenceClassModel().fit(train, y)
    top = train.iloc[[450]]
    p = m.predict(top)[0]
    assert p > 0.7


def test_tiny_cell_is_pulled_towards_its_parent():
    """A cell with one observation must sit close to the parent, not at 0 or 1."""
    rows = []
    for i in range(400):
        rows.append({"awarding_agency_code": "A", "naics2": "54",
                     "type_of_contract_pricing_code": "J",
                     "log_base_ceiling": 5.0 + (i % 5) * 0.5})
    rows.append({"awarding_agency_code": "A", "naics2": "54",
                 "type_of_contract_pricing_code": "T",
                 "log_base_ceiling": 5.0})
    train = pd.DataFrame(rows)
    y = pd.Series([0.0] * 400 + [1.0])
    m = ReferenceClassModel().fit(train, y)
    p = m.predict(train.iloc[[400]])[0]
    # one observation with y = 1 against a parent near 0
    assert 0.0 < p < 0.5
    assert p == pytest.approx(1.0 / (1.0 + MIN_CELL_N), abs=0.05)


def test_predictions_stay_inside_the_unit_interval():
    train = _frame(60)
    rng = np.random.RandomState(1)
    y = pd.Series(rng.binomial(1, 0.3, len(train)).astype(float))
    m = ReferenceClassModel().fit(train, y)
    p = m.predict(train)
    assert p.min() >= 0.0 and p.max() <= 1.0


def test_quintile_edges_come_from_train_only():
    train = _frame(100)
    y = pd.Series(np.zeros(len(train)))
    m = ReferenceClassModel().fit(train, y)
    edges_after_fit = m.edges_.copy()
    huge = train.copy()
    huge["log_base_ceiling"] = huge["log_base_ceiling"] + 100.0
    m.predict(huge)
    assert np.allclose(m.edges_, edges_after_fit)


def test_missing_label_rows_are_dropped_before_fitting():
    train = _frame(40)
    y = pd.Series([np.nan] * len(train))
    y.iloc[:10] = 1.0
    m = ReferenceClassModel().fit(train, y)
    assert m.global_mean_ == pytest.approx(1.0)


def test_cell_table_has_one_row_per_finest_cell():
    train = _frame(40)
    y = pd.Series(np.zeros(len(train)))
    m = ReferenceClassModel().fit(train, y)
    tab = m.cell_table()
    assert {"awarding_agency_code", "naics2", "type_of_contract_pricing_code",
            "value_quintile", "n", "mean", "shrunk"} <= set(tab.columns)
    assert tab["n"].sum() == len(train)
