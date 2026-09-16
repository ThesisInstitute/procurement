"""Residual persistence, decomposition and pairing on hand-computed fixtures."""
import numpy as np
import pandas as pd
import pytest

from bidders_us.src import persistence as P


def _frame():
    # two contractors in one office; A slips more than forecast in both periods
    rows = []
    for split, n in (("train", 6), ("test", 4)):
        for i in range(n):
            rows.append({"uei": "A", "office": "O1", "split": split,
                         "y": 1.0 if i % 2 == 0 else 1.0, "p": 0.5})
            rows.append({"uei": "B", "office": "O1", "split": split,
                         "y": 0.0, "p": 0.5})
    return pd.DataFrame(rows)


def test_group_table_means_and_thresholds():
    t = P.group_table(_frame(), "uei", min_train=5, min_test=3)
    assert set(t.index) == {"A", "B"}
    assert t.loc["A", "resid_train"] == pytest.approx(0.5)
    assert t.loc["A", "resid_test"] == pytest.approx(0.5)
    assert t.loc["B", "resid_train"] == pytest.approx(-0.5)
    assert t.loc["B", "n_train"] == 6 and t.loc["B", "n_test"] == 4
    strict = P.group_table(_frame(), "uei", min_train=7, min_test=3)
    assert strict.empty


def test_group_table_drops_null_keys():
    d = _frame()
    d.loc[d.index[:3], "uei"] = None
    t = P.group_table(d, "uei", min_train=1, min_test=1)
    assert None not in t.index and pd.NA not in t.index


def test_shrink_toward_zero():
    out = P.shrink_toward_zero(np.array([0.4, 0.4]), np.array([10, 90]), k=10.0)
    assert out[0] == pytest.approx(0.2)
    assert out[1] == pytest.approx(0.36)


def test_pearson_weighted_and_unweighted():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    y = np.array([2.0, 4.0, 6.0, 8.0])
    assert P.pearson(x, y) == pytest.approx(1.0)
    y2 = np.array([1.0, 0.0, 0.0, 10.0])
    # weighting the last point to dominance pulls the correlation toward +1
    assert P.pearson(x, y2, np.array([1, 1, 1, 100])) > P.pearson(x, y2)
    assert np.isnan(P.pearson(x, np.ones(4)))


def test_spearman_is_rank_based():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    y = np.array([1.0, 10.0, 100.0, 1000.0])
    assert P.spearman(x, y) == pytest.approx(1.0)
    assert P.spearman(x, -y) == pytest.approx(-1.0)


def test_bootstrap_corr_interval_contains_point_on_clean_signal():
    rng = np.random.default_rng(1)
    x = rng.normal(size=200)
    t = pd.DataFrame({"a": x, "b": x + rng.normal(scale=0.5, size=200), "w": rng.integers(1, 5, 200)})
    r = P.bootstrap_corr(t, "a", "b", None, n_boot=200, seed=0)
    assert r["lo"] <= r["r"] <= r["hi"]
    assert r["r"] > 0.8
    rw = P.bootstrap_corr(t, "a", "b", "w", n_boot=200, seed=0)
    assert rw["weighted"] is True


def test_signal_on_test_auc_of_persistent_residual():
    d = _frame()
    tab = P.group_table(d, "uei", 5, 3)
    r = P.signal_on_test(d, "uei", tab, k_shrink=1.0)
    # A always slips in test, B never; A's training residual is higher -> AUC 1
    assert r["auc_train_residual_alone"] == pytest.approx(1.0)
    assert r["auc_model"] == pytest.approx(0.5)  # constant forecast: all ties
    assert r["brier_model_plus_shrunk_residual"] < r["brier_model"]
    assert r["n"] == 8


def test_choose_shrink_k_uses_validation_not_test():
    # validation rows continue the training pattern (A slips, B does not), so
    # on validation the least shrinkage (k=1) scores best
    d = _frame()
    d.loc[d.index[-8:], "split"] = "val"
    out = P.choose_shrink_k(d, "uei", min_train=5, min_val=3, grid=(1, 100))
    assert out["k"] == 1.0
    assert set(out["grid"]) == {"1", "100"}
    assert out["n_val_rows"] == 8
    # now add test rows where the pattern REVERSES (A never slips, B always):
    # if test outcomes leaked into the choice, heavy shrinkage would win
    rows = []
    for i in range(20):
        rows.append({"uei": "A", "office": "O1", "split": "test", "y": 0.0, "p": 0.5})
        rows.append({"uei": "B", "office": "O1", "split": "test", "y": 1.0, "p": 0.5})
    d2 = pd.concat([d, pd.DataFrame(rows)], ignore_index=True)
    out2 = P.choose_shrink_k(d2, "uei", min_train=5, min_val=3, grid=(1, 100))
    assert out2["k"] == 1.0
    assert out2["grid"] == out["grid"]
    assert out2["n_val_rows"] == 8


def test_anova_between_variance_balanced_hand_computed():
    # two groups of three: means 1 and 3, within deviations +-1
    r = np.array([0.0, 1.0, 2.0, 2.0, 3.0, 4.0])
    g = np.array(["a", "a", "a", "b", "b", "b"])
    out = P.anova_between_variance(r, g)
    # SSB = 3*(1-2)^2 + 3*(3-2)^2 = 6, MSB = 6; SSW = 2 + 2 = 4, MSW = 1; n0 = 3
    assert out["sigma2_within"] == pytest.approx(1.0)
    assert out["sigma2_between"] == pytest.approx((6.0 - 1.0) / 3.0)
    assert out["share"] == pytest.approx((5 / 3) / (5 / 3 + 1))


def test_anova_between_variance_floors_at_zero():
    rng = np.random.default_rng(0)
    r = rng.normal(size=300)
    g = np.repeat(np.arange(30), 10)
    out = P.anova_between_variance(r, g)
    assert out["sigma2_between"] >= 0.0
    assert out["share"] < 0.1


def test_fe_r2_single_set_equals_between_share_of_sst():
    r = np.array([0.0, 1.0, 2.0, 2.0, 3.0, 4.0])
    g = ["a", "a", "a", "b", "b", "b"]
    out = P.fe_r2(r, [g])
    assert out["r2"] == pytest.approx(6.0 / 10.0)
    assert out["k"] == 1
    assert out["adj_r2"] == pytest.approx(1 - (1 - 0.6) * 5 / 4)


def test_fe_r2_two_sets_recovers_additive_effects():
    rng = np.random.default_rng(0)
    a = rng.integers(0, 5, 400)
    b = rng.integers(0, 4, 400)
    eff_a = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    eff_b = np.array([0.0, -1.0, 1.0, 0.5])
    r = eff_a[a] + eff_b[b]
    out = P.fe_r2(r, [a, b])
    assert out["r2"] == pytest.approx(1.0, abs=1e-6)
    assert out["k"] == 4 + 3


def test_within_cell_pairs_hand_computed():
    d = pd.DataFrame({
        "office": ["O"] * 4, "psc1": ["D"] * 4, "fy": [2020] * 4,
        "uei": ["A", "B", "A", "C"], "sig": [0.3, -0.2, 0.3, 0.0],
        "y": [1.0, 0.0, 0.0, 1.0], "dec": [5, 5, 6, 8],
    })
    out = P.within_cell_pairs(d, ["office", "psc1", "fy"], "uei", "sig", "y",
                              decile_col="dec", max_decile_gap=1)
    # pairs across groups within one decile: (A1,B), (B,A2); A1-A2 same group;
    # C is 2+ deciles from everyone else -> excluded
    assert out["n_pairs"] == 2
    # discordant: (A1,B): y 1 vs 0, B lower signal and B did not slip -> correct
    # (B,A2): y 0 vs 0 -> not discordant
    assert out["n_discordant_pairs"] == 1
    assert out["accuracy"] == pytest.approx(1.0)


def test_within_cell_pairs_tie_counts_half():
    d = pd.DataFrame({"office": ["O", "O"], "uei": ["A", "B"], "sig": [0.1, 0.1],
                      "y": [1.0, 0.0]})
    out = P.within_cell_pairs(d, ["office"], "uei", "sig", "y")
    assert out["n_discordant_pairs"] == 1
    assert out["accuracy"] == pytest.approx(0.5)


def test_permute_within_keeps_multiset_per_block():
    labels = pd.Series(["a", "b", "c", "d", "e", "f"])
    within = pd.Series(["x", "x", "x", "y", "y", "z"])
    rng = np.random.default_rng(3)
    out = P.permute_within(labels, within, rng)
    assert sorted(out[within == "x"]) == ["a", "b", "c"]
    assert sorted(out[within == "y"]) == ["d", "e"]
    assert out[within == "z"].tolist() == ["f"]
    assert out.index.equals(labels.index)


def test_permute_within_actually_shuffles():
    labels = pd.Series(list("abcdefghij"))
    within = pd.Series(["x"] * 10)
    moved = 0
    for seed in range(5):
        out = P.permute_within(labels, within, np.random.default_rng(seed))
        moved += int((out != labels).sum())
    assert moved > 0


def test_split_half_between_variance_recovers_group_effect():
    rng = np.random.default_rng(0)
    g = np.repeat(np.arange(300), 6)
    eff = rng.normal(scale=0.3, size=300)
    r = eff[g] + rng.normal(scale=0.5, size=len(g))
    d = pd.DataFrame({"g": g, "r": r})
    out = P.split_half_between_variance(d, "g", "r", np.random.default_rng(1), n_splits=10)
    assert out["cov_unweighted"] == pytest.approx(0.09, abs=0.03)
    assert out["n_groups"] == 300


def test_split_half_between_variance_near_zero_without_effect():
    rng = np.random.default_rng(0)
    g = np.repeat(np.arange(300), 6)
    r = rng.normal(scale=0.5, size=len(g))
    out = P.split_half_between_variance(pd.DataFrame({"g": g, "r": r}), "g", "r",
                                        np.random.default_rng(1), n_splits=10)
    assert abs(out["cov_unweighted"]) < 0.02


def test_split_half_drops_singletons():
    d = pd.DataFrame({"g": ["a", "a", "b", "b", "c", "c", "d"], "r": [1, 1, 2, 2, 3, 3, 9]})
    out = P.split_half_between_variance(d, "g", "r", np.random.default_rng(0), n_splits=1)
    assert out["n"] == 6 and out["n_groups"] == 3


def test_cross_period_covariance_hand_computed():
    t = pd.DataFrame({"resid_train": [1.0, 2.0, 3.0], "resid_test": [2.0, 4.0, 6.0],
                      "n_test": [1, 1, 2]})
    out = P.cross_period_covariance(t, n_boot=50)
    # means 2 and 4; sum of products of deviations = 1*2 + 0 + 1*2 = 4; / 3
    assert out["cov"] == pytest.approx(4.0 / 3.0)
    assert out["lo"] <= out["cov"] <= out["hi"]
    w = P.cross_period_covariance(t, "n_test", n_boot=50)
    # weighted means: (1+2+6)/4 = 2.25, (2+4+12)/4 = 4.5
    dev = [(1 - 2.25) * (2 - 4.5), (2 - 2.25) * (4 - 4.5), (3 - 2.25) * (6 - 4.5)]
    assert w["cov"] == pytest.approx((dev[0] + dev[1] + 2 * dev[2]) / 4)


def test_fe_r2_two_sets_counts_components_in_parameter_count():
    # two disconnected blocks: contractors a,b in office X; c,d in office Y
    r = np.array([1.0, 2.0, 1.5, 2.5, 5.0, 6.0, 5.5, 6.5])
    c = ["a", "b", "a", "b", "c", "d", "c", "d"]
    o = ["X", "X", "X", "X", "Y", "Y", "Y", "Y"]
    out = P.fe_r2(r, [c, o])
    assert out["components"] == 2
    # rank beyond the constant: 4 contractors + 2 offices - 2 components - 1 = 3
    assert out["k"] == 3
    assert out["converged"] is True
