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
    assert int(tab.loc[tab["bin"] == "[0.9,1.0]", "n"].iloc[0]) == 2
    assert float(tab.loc[tab["bin"] == "[0.9,1.0]", "observed_rate"].iloc[0]) == 1.0
    assert int(tab.loc[tab["bin"] == "[0.0,0.1)", "n"].iloc[0]) == 2
    assert float(tab.loc[tab["bin"] == "[0.0,0.1)", "observed_rate"].iloc[0]) == 0.0
    assert int(tab.loc[tab["bin"] == "[0.5,0.6)", "n"].iloc[0]) == 2
    assert tab["n"].sum() == 6


def test_calibration_table_includes_probability_one():
    tab = S.calibration_table(np.array([1.0]), np.array([1.0]), n_bins=10)
    assert int(tab.loc[tab["bin"] == "[0.9,1.0]", "n"].iloc[0]) == 1


def test_top_bin_label_is_closed_on_the_right():
    """It contains p = 1.0, so labelling it "[0.9,1.0)" would be a false claim."""
    labels = S.bin_labels(10)
    assert labels[-1] == "[0.9,1.0]"
    assert labels[0] == "[0.0,0.1)"
    assert len(labels) == len(set(labels)) == 10


@pytest.mark.parametrize("p,expected_bin", [
    (0.0, "[0.0,0.1)"), (0.1, "[0.1,0.2)"), (0.2, "[0.2,0.3)"),
    (0.3, "[0.3,0.4)"), (0.4, "[0.4,0.5)"), (0.5, "[0.5,0.6)"),
    (0.6, "[0.6,0.7)"), (0.7, "[0.7,0.8)"), (0.8, "[0.8,0.9)"),
    (0.9, "[0.9,1.0]"), (1.0, "[0.9,1.0]"),
])
def test_a_forecast_exactly_on_a_bin_edge_lands_in_the_bin_it_is_labelled_with(
        p, expected_bin):
    """np.linspace(0, 1, 11) does not reproduce 0.3, 0.6 or 0.7.

    Its entries are 0.30000000000000004, 0.6000000000000001 and
    0.7000000000000001, each strictly greater than the float64 nearest to the
    decimal, so digitizing against those edges put a forecast of exactly 0.3,
    0.6 or 0.7 one bin too low and printed a row whose stated interval excluded
    its own mean forecast.
    """
    tab = S.calibration_table(np.array([1.0]), np.array([p]), n_bins=10)
    row = tab.loc[tab["n"] == 1]
    assert len(row) == 1
    assert row["bin"].iloc[0] == expected_bin
    assert row["mean_forecast"].iloc[0] == pytest.approx(p)


@pytest.mark.parametrize("n_bins", [2, 3, 4, 5, 8, 10, 20])
def test_bin_labels_stay_distinct_for_any_bin_count(n_bins):
    """Row lookup is by label, so two bins sharing a label would be ambiguous."""
    labels = S.bin_labels(n_bins)
    assert len(labels) == n_bins
    assert len(set(labels)) == n_bins
    tab = S.calibration_table(np.array([1.0] * n_bins),
                              np.linspace(0, 1, n_bins), n_bins=n_bins)
    assert list(tab["bin"]) == labels
    assert tab["n"].sum() == n_bins


def test_murphy_identity_holds_exactly_on_binned_forecasts():
    rng = np.random.default_rng(11)
    y = (rng.random(4000) < 0.35).astype(float)
    p = (S.bin_index(rng.random(4000)) + 0.5) / 10.0
    d = S.murphy_decomposition(y, p)
    assert S.brier_score(y, p) == pytest.approx(
        d["reliability"] - d["resolution"] + d["uncertainty"], abs=1e-12)


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
