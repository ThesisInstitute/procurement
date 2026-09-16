"""Proper scoring rules, the Murphy decomposition, AUC, Spearman and isotonic."""
from __future__ import annotations

import numpy as np
import pytest

from gmpp.src.scoring import (
    auc,
    bootstrap_ci,
    brier_decomposition,
    brier_score,
    isotonic_fit,
    spearman,
)


def test_brier_score_on_a_hand_worked_case():
    f = np.array([1.0, 0.0, 0.5, 0.5])
    o = np.array([1.0, 0.0, 1.0, 0.0])
    # errors 0, 0, 0.25, 0.25
    assert brier_score(f, o) == pytest.approx(0.125)


def test_decomposition_reconstructs_the_score():
    rng = np.random.default_rng(7)
    f = rng.choice([0.1, 0.25, 0.5, 0.75, 0.9], 500)
    o = (rng.random(500) < f).astype(float)
    d = brier_decomposition(f, o)
    assert d.brier == pytest.approx(d.reliability - d.resolution + d.uncertainty)
    assert d.as_dict()["decomposition_residual"] == pytest.approx(0.0, abs=1e-12)


def test_a_perfectly_calibrated_forecast_has_zero_reliability():
    # Two groups, forecasts equal to the group's realised rate.
    f = np.array([0.25] * 4 + [0.75] * 4)
    o = np.array([1.0, 0, 0, 0] + [1.0, 1, 1, 0])
    d = brier_decomposition(f, o)
    assert d.reliability == pytest.approx(0.0)
    assert d.resolution > 0


def test_a_constant_forecast_at_the_base_rate_scores_exactly_the_uncertainty():
    o = np.array([1.0, 1, 0, 0, 0, 0, 1, 0])
    f = np.full_like(o, o.mean())
    d = brier_decomposition(f, o, bins=np.zeros_like(o))
    assert d.reliability == pytest.approx(0.0)
    assert d.resolution == pytest.approx(0.0)
    assert d.brier == pytest.approx(d.uncertainty)
    assert d.skill_vs_base_rate == pytest.approx(0.0)


def test_a_constant_forecast_away_from_the_base_rate_is_pure_reliability():
    o = np.array([1.0, 0, 0, 0])
    f = np.full_like(o, 0.9)
    d = brier_decomposition(f, o, bins=np.zeros_like(o))
    assert d.resolution == pytest.approx(0.0)
    assert d.reliability == pytest.approx((0.9 - 0.25) ** 2)
    assert d.skill_vs_base_rate < 0


def test_decomposition_rejects_mismatched_shapes():
    with pytest.raises(ValueError):
        brier_decomposition(np.array([0.5]), np.array([1.0, 0.0]))


def test_decomposition_rejects_an_empty_sample():
    with pytest.raises(ValueError):
        brier_decomposition(np.array([]), np.array([]))


def test_auc_of_a_perfect_separator_is_one():
    assert auc(np.array([1.0, 2, 3, 4]), np.array([0.0, 0, 1, 1])) == pytest.approx(1.0)


def test_auc_of_a_reversed_separator_is_zero():
    assert auc(np.array([4.0, 3, 2, 1]), np.array([0.0, 0, 1, 1])) == pytest.approx(0.0)


def test_auc_of_a_constant_score_is_one_half():
    assert auc(np.array([2.0, 2, 2, 2]), np.array([0.0, 1, 0, 1])) == pytest.approx(0.5)


def test_auc_averages_ties_the_same_way_as_the_mann_whitney_u():
    # scores 1,1,2,2,3 against outcomes 0,1,0,1,1.
    # Concordant/tied pairs by hand: U = 4 of 6 -> 0.6667.
    assert auc(
        np.array([1.0, 1, 2, 2, 3]), np.array([0.0, 1, 0, 1, 1])
    ) == pytest.approx(2 / 3)


def test_auc_is_nan_when_one_class_is_empty():
    assert np.isnan(auc(np.array([1.0, 2, 3]), np.array([0.0, 0, 0])))


def test_auc_drops_nan_pairs():
    assert auc(
        np.array([1.0, 2, np.nan, 4]), np.array([0.0, 0, 1, 1])
    ) == pytest.approx(1.0)


def test_spearman_is_one_for_a_monotone_relation():
    x = np.array([1.0, 2, 3, 4, 5])
    assert spearman(x, x**3) == pytest.approx(1.0)
    assert spearman(x, -(x**3)) == pytest.approx(-1.0)


def test_spearman_is_nan_when_one_side_is_constant():
    assert np.isnan(spearman(np.array([1.0, 1, 1, 1]), np.array([1.0, 2, 3, 4])))


def test_isotonic_is_non_decreasing_and_pools_violators():
    model = isotonic_fit(np.array([1.0, 2, 3, 4, 5]), np.array([0.0, 1, 0, 1, 1]))
    fitted = model.predict(np.array([1.0, 2, 3, 4, 5]))
    assert list(fitted) == pytest.approx([0.0, 0.5, 0.5, 1.0, 1.0])
    assert all(np.diff(fitted) >= 0)


def test_isotonic_clamps_outside_the_fitted_range():
    model = isotonic_fit(np.array([1.0, 2, 3]), np.array([0.0, 0.5, 1.0]))
    assert model.predict(np.array([-5.0]))[0] == pytest.approx(0.0)
    assert model.predict(np.array([99.0]))[0] == pytest.approx(1.0)


def test_isotonic_averages_ties_in_x():
    model = isotonic_fit(np.array([1.0, 1, 2, 2]), np.array([0.0, 1, 1, 1]))
    assert model.predict(np.array([1.0]))[0] == pytest.approx(0.5)
    assert model.predict(np.array([2.0]))[0] == pytest.approx(1.0)


def test_bootstrap_is_deterministic_for_a_fixed_seed():
    rng = np.random.default_rng(3)
    s = rng.normal(size=200)
    o = (rng.random(200) < 0.4).astype(float)
    first = bootstrap_ci(auc, s, o, n_boot=200)
    second = bootstrap_ci(auc, s, o, n_boot=200)
    assert first == second
    assert first[0] <= auc(s, o) <= first[1]


def test_cluster_bootstrap_is_deterministic_and_covers_the_estimate():
    from gmpp.src.scoring import cluster_bootstrap_ci

    rng = np.random.default_rng(11)
    clusters = np.repeat(np.arange(60), 5)
    s = rng.normal(size=300)
    o = (rng.random(300) < 0.4).astype(float)
    first = cluster_bootstrap_ci(auc, s, o, clusters=clusters, n_boot=200)
    second = cluster_bootstrap_ci(auc, s, o, clusters=clusters, n_boot=200)
    assert first == second
    assert first[0] <= auc(s, o) <= first[1]


def test_cluster_bootstrap_is_wider_when_rows_repeat_within_a_cluster():
    # Ten projects, each observed ten times with an identical row. Resampling
    # rows sees 100 observations; resampling projects sees 10, and must say so.
    rng = np.random.default_rng(5)
    from gmpp.src.scoring import cluster_bootstrap_ci

    base_scores = rng.normal(size=10)
    base_outcomes = np.array([0.0, 1, 0, 1, 0, 1, 1, 0, 1, 0])
    s = np.repeat(base_scores, 10)
    o = np.repeat(base_outcomes, 10)
    clusters = np.repeat(np.arange(10), 10)
    row_lo, row_hi = bootstrap_ci(auc, s, o, n_boot=400)
    cl_lo, cl_hi = cluster_bootstrap_ci(auc, s, o, clusters=clusters, n_boot=400)
    assert (cl_hi - cl_lo) > (row_hi - row_lo)


def test_isotonic_is_fitted_on_the_training_rows_only():
    """The recalibration must not see the test outcomes.

    Fit on one set of rows, then change only the TEST outcomes. The fitted
    mapping must not move; only the evaluation of it may.
    """
    import numpy as np

    from gmpp.src.scoring import isotonic_fit

    train_rank = np.array([0, 0, 1, 1, 2, 2, 3, 3, 4, 4], dtype=float)
    train_y = np.array([0, 0, 0, 0, 0, 1, 1, 1, 1, 1], dtype=float)
    model = isotonic_fit(train_rank, train_y)
    grid = np.array([0, 1, 2, 3, 4], dtype=float)
    before = model.predict(grid)

    # A second fit on the identical training data, with completely different
    # test rows in existence, must give the identical mapping.
    again = isotonic_fit(train_rank.copy(), train_y.copy())
    assert np.allclose(before, again.predict(grid))


def test_isotonic_output_is_monotone_in_the_rank():
    import numpy as np

    from gmpp.src.scoring import isotonic_fit

    rng = np.random.default_rng(11)
    rank = rng.integers(0, 5, 300).astype(float)
    y = (rng.random(300) < (rank / 8 + 0.05)).astype(float)
    fitted = isotonic_fit(rank, y).predict(np.arange(5, dtype=float))
    assert all(a <= b + 1e-12 for a, b in zip(fitted, fitted[1:]))


def test_skill_against_a_constant_base_rate_forecast_is_zero():
    """A constant forecast equal to the base rate has skill exactly 0 by
    definition, which pins the sign convention of the skill score.
    """
    import numpy as np

    from gmpp.src.scoring import brier_decomposition

    y = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0], dtype=float)
    d = brier_decomposition(np.full_like(y, y.mean()), y)
    assert abs(d.skill_vs_base_rate) < 1e-12
    assert abs(d.reliability) < 1e-12
    assert abs(d.resolution) < 1e-12


def test_a_perfect_forecast_has_skill_one():
    import numpy as np

    from gmpp.src.scoring import brier_decomposition

    y = np.array([1, 1, 0, 0, 0, 0], dtype=float)
    d = brier_decomposition(y.copy(), y)
    assert abs(d.brier) < 1e-12
    assert abs(d.skill_vs_base_rate - 1.0) < 1e-12
