"""Shrunk cell means: the reference-class rung of the ladder."""
import numpy as np
import pandas as pd
import pytest

from reference_class import MIN_CELL_N, ReferenceClassModel, assign_quintile, value_quintiles
from reference_class import SHRINK_K as REFK  # noqa: E402


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
    # One observation with y = 1 against a parent near 0, so the prediction is
    # pulled most of the way to the parent. The exact value is pinned to 1e-12 in
    # test_shrunk_prediction_matches_the_formula_compounded_over_four_levels; the
    # assertion here is only that shrinkage happened and happened in the right
    # direction. An earlier version of this test claimed the value was
    # 1/(1+MIN_CELL_N) with a tolerance of 0.05, which is wider than the quantity
    # it was checking and passed for any shrink_k between 30 and 100.
    assert 0.0 < p < 0.5
    raw_cell_mean = 1.0
    assert p < raw_cell_mean / 2


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


# ------------------------------------------------- exact shrinkage arithmetic

def _one_cell_frame(n_a: int, n_b: int) -> pd.DataFrame:
    """Two agencies, everything else constant, so all four levels see one cell each."""
    n = n_a + n_b
    return pd.DataFrame({
        "awarding_agency_code": ["A"] * n_a + ["B"] * n_b,
        "naics2": ["54"] * n,
        "type_of_contract_pricing_code": ["J"] * n,
        "log_base_ceiling": [6.0] * n,
    })


def test_shrunk_prediction_matches_the_formula_compounded_over_four_levels():
    """Hand-computed, to 1e-12, not to a tolerance wider than the answer.

    Agency A has 30 observations all equal to 1, agency B has a single
    observation equal to 0, and NAICS, pricing code and value quintile are
    constant, so each of the four levels of the hierarchy sees the same two
    cells. With k = 30 the recursion is, starting from the global mean:

        s_A(next) = (30 * 1 + k * s_A) / (30 + k)
        s_B(next) = ( 1 * 0 + k * s_B) / ( 1 + k)
    """
    k = float(REFK)
    n_a, n_b = 30, 1
    train = _one_cell_frame(n_a, n_b)
    y = pd.Series([1.0] * n_a + [0.0] * n_b)

    g = (n_a * 1.0 + n_b * 0.0) / (n_a + n_b)
    s_a, s_b = g, g
    for _ in range(4):                       # LEVELS has four entries
        s_a = (n_a * 1.0 + k * s_a) / (n_a + k)
        s_b = (n_b * 0.0 + k * s_b) / (n_b + k)

    p = ReferenceClassModel().fit(train, y).predict(train)
    assert p[0] == pytest.approx(s_a, abs=1e-12)
    assert p[-1] == pytest.approx(s_b, abs=1e-12)
    # and the direction is the point of shrinkage: the lone zero is pulled a
    # long way up towards the parent, the well populated cell barely moves
    assert p[-1] > 0.5
    assert p[0] > 0.95


@pytest.mark.parametrize("k", [1.0, 10.0, 30.0, 100.0])
def test_shrink_k_actually_changes_the_prediction(k):
    """Guard against a test that passes for any k, which is a test of nothing."""
    train = _one_cell_frame(30, 1)
    y = pd.Series([1.0] * 30 + [0.0])
    p = ReferenceClassModel(shrink_k=k).fit(train, y).predict(train)[-1]
    baseline = ReferenceClassModel(shrink_k=30.0).fit(train, y).predict(train)[-1]
    if k == 30.0:
        assert p == pytest.approx(baseline)
    else:
        assert abs(p - baseline) > 1e-6, f"k={k} produced the same answer as k=30"
    # more shrinkage always pulls the lone zero further towards the parent
    strong = ReferenceClassModel(shrink_k=200.0).fit(train, y).predict(train)[-1]
    weak = ReferenceClassModel(shrink_k=0.5).fit(train, y).predict(train)[-1]
    assert strong > weak


def test_fit_rejects_mismatched_lengths():
    train = _one_cell_frame(5, 5)
    with pytest.raises(ValueError, match="rows but y has"):
        ReferenceClassModel().fit(train, pd.Series([1.0] * 3))


def test_fit_pairs_rows_positionally_even_when_the_frame_index_is_gapped():
    """The production caller passes a 0..n-1 y against a panel-indexed frame.

    Those indexes coincide only while nothing upstream has been filtered. If fit
    aligned on label instead of position, this frame would pair the wrong
    outcome with the wrong award, or raise.
    """
    train = _one_cell_frame(40, 40)
    train.index = np.arange(1000, 1000 + 2 * len(train), 2)   # gapped, non-zero
    y = pd.Series([1.0] * 40 + [0.0] * 40)                    # plain 0..79 index
    p = ReferenceClassModel().fit(train, y).predict(train)
    assert p[:40].mean() > 0.7
    assert p[40:].mean() < 0.3


def test_there_is_no_dead_min_cell_n_argument():
    """A knob that silently does nothing is worse than no knob."""
    with pytest.raises(TypeError):
        ReferenceClassModel(min_cell_n=5)
