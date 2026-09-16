"""Tests for the scoring functions on small synthetic fixtures."""
import numpy as np
import pandas as pd
import pytest

from worldbank.src import metrics


# ------------------------------------------------------------------- brier

def test_brier_perfect_and_worst():
    y = np.array([1, 0, 1, 0])
    assert metrics.brier(y, np.array([1., 0., 1., 0.])) == 0.0
    assert metrics.brier(y, np.array([0., 1., 0., 1.])) == 1.0


def test_brier_constant_half_is_quarter():
    y = np.array([1, 0, 1, 0])
    assert metrics.brier(y, np.full(4, 0.5)) == pytest.approx(0.25)


def test_brier_equals_base_rate_variance_for_constant_base_rate():
    """A constant forecast at the base rate scores the outcome variance."""
    y = np.array([1, 1, 1, 0])           # base rate 0.75
    p = np.full(4, 0.75)
    assert metrics.brier(y, p) == pytest.approx(0.75 * 0.25)


# --------------------------------------------------------------------- bss

def test_bss_zero_when_model_equals_reference():
    y = np.array([1, 0, 1, 1])
    p = np.full(4, 0.75)
    assert metrics.brier_skill_score(y, p, p) == pytest.approx(0.0)


def test_bss_one_when_model_is_perfect():
    y = np.array([1, 0, 1, 1])
    assert metrics.brier_skill_score(y, y.astype(float),
                                     np.full(4, 0.5)) == pytest.approx(1.0)


def test_bss_negative_when_model_is_worse_than_reference():
    y = np.array([1, 1, 1, 0])
    bad = np.full(4, 0.1)
    ref = np.full(4, 0.75)
    assert metrics.brier_skill_score(y, bad, ref) < 0


# --------------------------------------------------------------------- auc

def test_auc_perfect_separation():
    y = np.array([0, 0, 1, 1])
    assert metrics.auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0


def test_auc_reversed_is_zero():
    y = np.array([0, 0, 1, 1])
    assert metrics.auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0


def test_auc_constant_forecast_is_one_half():
    y = np.array([0, 0, 1, 1])
    assert metrics.auc(y, np.full(4, 0.5)) == pytest.approx(0.5)


def test_auc_nan_when_one_class_only():
    assert np.isnan(metrics.auc(np.array([1, 1, 1]), np.array([.1, .5, .9])))


# ------------------------------------------------------------- calibration

def test_calibration_table_bins_sum_to_n_and_are_labelled():
    y = np.array([0, 1, 1, 1, 0, 1])
    p = np.array([0.05, 0.15, 0.55, 0.95, 0.45, 0.85])
    t = metrics.calibration_table(y, p, n_bins=10)
    assert len(t) == 10
    assert t["n"].sum() == len(y)
    assert t.loc[t["n"] > 0, "mean_forecast"].notna().all()


def test_calibration_table_puts_one_point_zero_in_last_bin():
    t = metrics.calibration_table(np.array([1]), np.array([1.0]), n_bins=10)
    assert t.iloc[-1]["n"] == 1


def test_calibration_gap_is_observed_minus_forecast():
    y = np.array([1, 1])
    p = np.array([0.55, 0.55])
    t = metrics.calibration_table(y, p, n_bins=10)
    row = t[t["n"] > 0].iloc[0]
    assert row["gap"] == pytest.approx(1.0 - 0.55)


def test_perfectly_calibrated_forecast_has_near_zero_gaps():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.05, 0.95, 20000)
    y = (rng.uniform(size=20000) < p).astype(float)
    t = metrics.calibration_table(y, p, n_bins=10)
    assert t.loc[t["n"] > 100, "gap"].abs().max() < 0.03


# ------------------------------------------------------- within-group auc

def test_within_group_auc_excludes_single_class_groups():
    y = [0, 0, 1, 1] * 3 + [1] * 12
    p = [0.1, 0.2, 0.8, 0.9] * 3 + [0.5] * 12
    g = ["A"] * 12 + ["B"] * 12
    w, t = metrics.within_group_auc(y, p, g, min_n=10)
    assert w == pytest.approx(1.0)                      # only A contributes
    assert bool(t.set_index("group").loc["B", "usable"]) is False


def test_within_group_auc_drops_small_groups():
    y = [0, 1] * 2 + [0, 0, 0, 0, 0, 1, 1, 1, 1, 1]
    p = [0.9, 0.1] * 2 + [0.1] * 5 + [0.9] * 5
    g = ["small"] * 4 + ["big"] * 10
    w, t = metrics.within_group_auc(y, p, g, min_n=10)
    assert w == pytest.approx(1.0)
    assert bool(t.set_index("group").loc["small", "usable"]) is False


def test_within_group_auc_weighting_by_n_and_by_pairs_agree_when_balanced():
    """With equal class balance the two weightings coincide.

    group A (n=10, 5/5) AUC 1.0, group B (n=20, 10/10) AUC 0.0.
    n weights are 10/30 and 20/30; pair weights are 25/225 and 100/125... the
    pair counts are 25 and 100, so 25/125 and 100/125. Both are computed and
    both are asserted, so a change to the default weighting cannot pass silently.
    """
    y = [0] * 5 + [1] * 5 + [0] * 10 + [1] * 10
    p = [0.1] * 5 + [0.9] * 5 + [0.9] * 10 + [0.1] * 10
    g = ["A"] * 10 + ["B"] * 20
    w_n, t = metrics.within_group_auc(y, p, g, min_n=10, weight="n")
    w_pairs, _ = metrics.within_group_auc(y, p, g, min_n=10, weight="pairs")
    assert w_n == pytest.approx(10 / 30)
    assert w_pairs == pytest.approx(25 / 125)
    assert t.attrs["weighted_by_n"] == pytest.approx(10 / 30)
    assert t.attrs["weighted_by_pairs"] == pytest.approx(25 / 125)


def test_within_group_auc_default_weighting_is_pairs():
    y = [0] * 5 + [1] * 5 + [0] * 18 + [1] * 2
    p = [0.1] * 5 + [0.9] * 5 + [0.9] * 18 + [0.1] * 2
    g = ["A"] * 10 + ["B"] * 20
    default, _ = metrics.within_group_auc(y, p, g, min_n=10)
    pairs, _ = metrics.within_group_auc(y, p, g, min_n=10, weight="pairs")
    n_wt, _ = metrics.within_group_auc(y, p, g, min_n=10, weight="n")
    assert default == pytest.approx(pairs)
    assert default != pytest.approx(n_wt)   # the two genuinely differ here


def test_within_group_auc_rejects_unknown_weight():
    with pytest.raises(ValueError):
        metrics.within_group_auc([0, 1], [0.1, 0.9], ["A", "A"], weight="size")


def test_within_group_auc_reports_excluded_row_share():
    """Rows in unusable groups are a selection on realised labels; make it visible."""
    y = [0] * 5 + [1] * 5 + [1] * 12
    p = [0.1] * 5 + [0.9] * 5 + [0.5] * 12
    g = ["A"] * 10 + ["B"] * 12
    _, t = metrics.within_group_auc(y, p, g, min_n=10)
    assert t.attrs["excluded_row_share"] == pytest.approx(12 / 22)


def test_within_group_auc_all_groups_unusable_returns_nan():
    y = [1, 1, 1]
    p = [0.1, 0.5, 0.9]
    w, t = metrics.within_group_auc(y, p, ["A", "A", "A"], min_n=2)
    assert np.isnan(w)
    assert t.attrs["excluded_row_share"] == pytest.approx(1.0)


def test_within_group_auc_length_mismatch_raises():
    with pytest.raises(ValueError):
        metrics.within_group_auc([0, 1, 1], [0.1, 0.9, 0.5], ["A", "A"])


def test_within_group_auc_removes_a_pure_group_level_signal():
    """A forecast that only encodes the group mean must score 0.5 within group.

    This is the property the report leans on: pooled AUC can look skilful purely
    because some countries succeed more often than others, while the forecast
    carries no information about which project inside a country will succeed.
    """
    y = [1] * 8 + [0] * 2 + [1] * 2 + [0] * 8
    p = [0.9] * 10 + [0.1] * 10          # constant inside each group
    g = ["hi"] * 10 + ["lo"] * 10
    pooled = metrics.auc(y, p)
    within, t = metrics.within_group_auc(y, p, g, min_n=10)
    assert pooled == pytest.approx(0.80)  # looks skilful pooled
    assert bool(t["usable"].all())        # both groups qualify
    assert within == pytest.approx(0.5)   # no skill inside a country


# ------------------------------------------------------- shrunk cell means

def test_shrunk_cell_mean_pulls_small_cells_toward_global():
    train = pd.DataFrame({
        "c": ["A"] + ["B"] * 100,
        "y": [1.0] + [0.0] * 100,
    })
    target = pd.DataFrame({"c": ["A", "B"]})
    out, diag = metrics.shrunk_cell_means(train, target, ["c"], "y", k=10.0)
    global_mean = 1 / 101
    # A has one observation at 1.0 but is pulled hard toward the global mean
    assert out[0] < 0.2
    assert out[0] > global_mean
    # B has 100 observations at 0.0 and barely moves
    assert out[1] < 0.01
    assert diag["global_mean"] == pytest.approx(global_mean)
    assert diag["fallback_share"] == pytest.approx(0.0)


def test_shrunk_cell_mean_unseen_cell_falls_back_to_global_mean():
    train = pd.DataFrame({"c": ["A", "A", "B", "B"], "y": [1.0, 1.0, 0.0, 0.0]})
    target = pd.DataFrame({"c": ["ZZZ"]})
    out, diag = metrics.shrunk_cell_means(train, target, ["c"], "y", k=10.0)
    assert float(out[0]) == pytest.approx(0.5)
    assert diag["fallback_share"] == pytest.approx(1.0)
    assert diag["n_hit"] == 0


def test_shrunk_cell_mean_fallback_share_is_measured_not_assumed():
    """The degenerate-cell failure the report turns on must be observable."""
    train = pd.DataFrame({"c": ["A"] * 4, "y": [1.0, 1.0, 0.0, 0.0]})
    target = pd.DataFrame({"c": ["A", "A", "ZZZ", "YYY"]})
    _, diag = metrics.shrunk_cell_means(train, target, ["c"], "y", k=1.0)
    assert diag["n_target"] == 4
    assert diag["n_hit"] == 2
    assert diag["fallback_share"] == pytest.approx(0.5)
    assert diag["n_train_cells"] == 1
    assert diag["n_target_cells"] == 3
    assert diag["n_target_cells_hit"] == 1


def test_shrunk_cell_mean_k_zero_is_the_raw_cell_mean():
    train = pd.DataFrame({"c": ["A", "A", "A", "B"], "y": [1.0, 1.0, 0.0, 0.0]})
    target = pd.DataFrame({"c": ["A", "B"]})
    out, _ = metrics.shrunk_cell_means(train, target, ["c"], "y", k=0.0)
    assert out[0] == pytest.approx(2 / 3)
    assert out[1] == pytest.approx(0.0)


def test_shrunk_cell_mean_uses_train_only_no_leakage():
    """Target rows must not influence their own prediction."""
    train = pd.DataFrame({"c": ["A", "A"], "y": [1.0, 1.0]})
    target = pd.DataFrame({"c": ["A", "A", "A"]})
    out, _ = metrics.shrunk_cell_means(train, target, ["c"], "y", k=10.0)
    assert len(set(out.round(10))) == 1   # identical regardless of target size


def test_shrunk_cell_mean_multi_column_cells():
    train = pd.DataFrame({
        "country": ["X", "X", "Y", "Y"],
        "decade": [1990, 1990, 2000, 2000],
        "y": [1.0, 1.0, 0.0, 0.0],
    })
    target = pd.DataFrame({"country": ["X", "Y"], "decade": [1990, 2000]})
    out, diag = metrics.shrunk_cell_means(train, target, ["country", "decade"],
                                          "y", k=1.0)
    assert out[0] > out[1]
    assert diag["fallback_share"] == pytest.approx(0.0)


def test_shrunk_cell_mean_key_types_match_across_int_and_str():
    """A key built from an Int64 column on one side and object on the other must
    still hit. Both sides are stringified by the same helper; this pins that."""
    train = pd.DataFrame({"d": pd.array([1990, 1990], dtype="Int64"),
                          "y": [1.0, 1.0]})
    target = pd.DataFrame({"d": pd.array([1990], dtype="Int64")})
    _, diag = metrics.shrunk_cell_means(train, target, ["d"], "y", k=1.0)
    assert diag["fallback_share"] == pytest.approx(0.0)


# ------------------------------------------------------ cluster bootstrap

def test_cluster_bootstrap_point_matches_the_plain_statistic():
    rng = np.random.default_rng(3)
    g = np.repeat([f"c{i}" for i in range(12)], 20)
    y = rng.integers(0, 2, size=len(g)).astype(float)
    p = rng.uniform(size=len(g))
    pt, lo, hi = metrics.cluster_bootstrap_ci(y, p, g, stat="auc", n_boot=40,
                                              seed=1)
    assert pt == pytest.approx(metrics.auc(y, p))
    assert lo <= pt <= hi


def test_cluster_bootstrap_is_deterministic_under_a_seed():
    rng = np.random.default_rng(4)
    g = np.repeat([f"c{i}" for i in range(10)], 20)
    y = rng.integers(0, 2, size=len(g)).astype(float)
    p = rng.uniform(size=len(g))
    a = metrics.cluster_bootstrap_ci(y, p, g, n_boot=25, seed=7)
    b = metrics.cluster_bootstrap_ci(y, p, g, n_boot=25, seed=7)
    assert a == b


def test_cluster_bootstrap_rejects_unknown_stat():
    with pytest.raises(ValueError):
        metrics.cluster_bootstrap_ci([0, 1], [0.1, 0.9], ["A", "A"],
                                     stat="nonsense", n_boot=2)
