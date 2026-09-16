import numpy as np
import pytest

import scoring as S


def test_brier_perfect_and_worst():
    y = np.array([1.0, 0.0, 1.0, 0.0])
    assert S.brier_score(y, y) == 0.0
    assert S.brier_score(y, 1 - y) == 1.0


def test_brier_constant_forecast_equals_variance_form():
    y = np.array([1.0, 1.0, 0.0, 0.0, 0.0])
    p = 0.4
    expected = np.mean((p - y) ** 2)
    assert S.brier_score(y, np.full_like(y, p)) == pytest.approx(expected)


def test_brier_skill_score_zero_against_itself():
    y = np.array([1.0, 0.0, 1.0, 1.0])
    base = float(y.mean())
    assert S.brier_skill_score(y, np.full_like(y, base), base) == pytest.approx(0.0)


def test_brier_skill_score_one_for_perfect_forecast():
    y = np.array([1.0, 0.0, 1.0, 0.0])
    assert S.brier_skill_score(y, y, 0.5) == pytest.approx(1.0)


def test_brier_skill_score_negative_when_worse_than_base_rate():
    y = np.array([1.0, 0.0, 0.0, 0.0])
    assert S.brier_skill_score(y, np.full_like(y, 0.9), 0.25) < 0


def test_auc_perfect_separation():
    y = np.array([0.0, 0.0, 1.0, 1.0])
    p = np.array([0.1, 0.2, 0.8, 0.9])
    assert S.auc(y, p) == pytest.approx(1.0)


def test_auc_reversed_is_zero():
    y = np.array([0.0, 0.0, 1.0, 1.0])
    p = np.array([0.9, 0.8, 0.2, 0.1])
    assert S.auc(y, p) == pytest.approx(0.0)


def test_auc_all_ties_is_half():
    y = np.array([0.0, 1.0, 0.0, 1.0])
    p = np.full(4, 0.5)
    assert S.auc(y, p) == pytest.approx(0.5)


def test_auc_known_value_with_partial_tie():
    # one positive above both negatives, one positive tied with a negative
    y = np.array([0.0, 0.0, 1.0, 1.0])
    p = np.array([0.1, 0.5, 0.5, 0.9])
    # pairs: (0.5 vs 0.1)=1, (0.5 vs 0.5)=0.5, (0.9 vs 0.1)=1, (0.9 vs 0.5)=1
    assert S.auc(y, p) == pytest.approx(3.5 / 4)


def test_auc_single_class_is_nan():
    assert np.isnan(S.auc(np.ones(5), np.linspace(0, 1, 5)))


def test_calibration_table_bins_and_rates():
    y = np.array([1.0, 1.0, 0.0, 0.0, 1.0, 0.0])
    p = np.array([0.95, 0.91, 0.05, 0.02, 0.55, 0.51])
    tab = S.calibration_table(y, p, n_bins=10)
    assert int(tab.loc[tab["bin"] == "[0.9,1.0)", "n"].iloc[0]) == 2
    assert float(tab.loc[tab["bin"] == "[0.9,1.0)", "observed_rate"].iloc[0]) == 1.0
    assert int(tab.loc[tab["bin"] == "[0.0,0.1)", "n"].iloc[0]) == 2
    assert float(tab.loc[tab["bin"] == "[0.0,0.1)", "observed_rate"].iloc[0]) == 0.0
    assert int(tab.loc[tab["bin"] == "[0.5,0.6)", "n"].iloc[0]) == 2
    assert tab["n"].sum() == 6


def test_calibration_table_includes_probability_one():
    tab = S.calibration_table(np.array([1.0]), np.array([1.0]), n_bins=10)
    assert int(tab.loc[tab["bin"] == "[0.9,1.0)", "n"].iloc[0]) == 1


def test_calibration_error_zero_for_perfect_calibration():
    y = np.array([1.0, 0.0] * 50)
    p = np.full(100, 0.5)
    assert S.calibration_error(y, p) == pytest.approx(0.0, abs=1e-12)


def test_murphy_decomposition_sums_to_brier():
    rng = np.random.RandomState(0)
    p = rng.uniform(0, 1, 5000)
    y = (rng.uniform(0, 1, 5000) < p).astype(float)
    d = S.murphy_decomposition(y, p, n_bins=10)
    # the identity holds for the binned forecast, so compare against the
    # Brier score of the bin-mean forecast
    edges = np.linspace(0, 1, 11)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, 9)
    pb = np.array([p[idx == b].mean() if (idx == b).any() else 0.0 for b in range(10)])
    binned = pb[idx]
    assert (d["reliability"] - d["resolution"] + d["uncertainty"]) == pytest.approx(
        S.brier_score(y, binned), abs=1e-3)


def test_pinball_loss_median_is_half_mae():
    y = np.array([1.0, 2.0, 3.0, 10.0])
    q = np.full(4, 2.0)
    assert S.pinball_loss(y, q, 0.5) == pytest.approx(0.5 * S.mae(y, q))


def test_pinball_loss_asymmetry():
    y = np.array([10.0])
    low = S.pinball_loss(y, np.array([0.0]), 0.9)
    high = S.pinball_loss(y, np.array([0.0]), 0.1)
    assert low == pytest.approx(9.0)
    assert high == pytest.approx(1.0)


def test_empty_inputs_return_nan():
    e = np.array([])
    assert np.isnan(S.brier_score(e, e))
    assert np.isnan(S.mae(e, e))
    assert np.isnan(S.pinball_loss(e, e, 0.5))
