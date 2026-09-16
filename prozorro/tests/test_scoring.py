"""Scoring rules, calibration and the permutation machinery."""

import numpy as np
import pandas as pd
import pytest

from src.contrasts import decile_table, lowest_disqualified_contrast, standardised_difference
from src.scoring import (
    auc,
    brier,
    brier_skill,
    calibration_table,
    log_loss,
    reliability_resolution,
    spearman,
    summarise,
)
from src.transfer import permutation_null


def test_brier_and_skill_against_a_stated_reference():
    y = np.array([0.0, 0.0, 1.0, 1.0])
    assert brier(y, y) == 0.0
    assert brier(y, np.full(4, 0.5)) == pytest.approx(0.25)
    assert brier_skill(y, y, 0.5) == pytest.approx(1.0)
    assert brier_skill(y, np.full(4, 0.5), 0.5) == pytest.approx(0.0)
    # A forecast worse than the reference must score negative skill.
    assert brier_skill(y, 1 - y, 0.5) < 0
    # A degenerate reference has no skill to measure against.
    assert np.isnan(brier_skill(np.ones(3), np.ones(3), 1.0))


def test_auc_handles_perfect_reversed_and_tied_forecasts():
    y = np.array([0, 0, 1, 1])
    assert auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == pytest.approx(1.0)
    assert auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == pytest.approx(0.0)
    assert auc(y, np.full(4, 0.5)) == pytest.approx(0.5)
    # Half credit for ties against one clear separation.
    assert auc(np.array([0, 1, 1]), np.array([0.5, 0.5, 0.9])) == pytest.approx(0.75)
    assert np.isnan(auc(np.array([1, 1]), np.array([0.2, 0.8])))


def test_log_loss_and_calibration_bins():
    y = np.array([0.0, 1.0])
    assert log_loss(y, np.array([0.0, 1.0])) < 1e-6
    p = np.linspace(0.05, 0.95, 100)
    y = (np.arange(100) % 2).astype(float)
    tab = calibration_table(y, p, bins=5)
    assert len(tab) == 5
    assert tab["n"].sum() == 100
    assert tab["mean_forecast"].is_monotonic_increasing


def test_murphy_decomposition_adds_up():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.05, 0.95, 4000)
    y = (rng.uniform(size=4000) < p).astype(float)
    d = reliability_resolution(y, p, bins=20)
    # Brier = reliability - resolution + uncertainty, to binning error.
    assert d["brier"] == pytest.approx(
        d["reliability"] - d["resolution"] + d["uncertainty"], abs=0.01
    )
    assert d["reliability"] < 0.01


def test_spearman_is_rank_based_and_guards_degenerate_input():
    a = np.array([1.0, 2.0, 3.0, 4.0])
    assert spearman(a, a**3) == pytest.approx(1.0)
    assert spearman(a, -a) == pytest.approx(-1.0)
    assert np.isnan(spearman(a, np.ones(4)))
    assert np.isnan(spearman(np.array([1.0, 2.0]), np.array([1.0, 2.0])))


def test_summarise_reports_the_reference_it_was_given():
    y = np.array([0.0, 1.0, 1.0, 0.0])
    out = summarise(y, np.array([0.2, 0.8, 0.7, 0.3]), reference=0.5)
    assert out["n"] == 4
    assert out["base_rate"] == pytest.approx(0.5)
    assert out["bss"] > 0
    assert out["auc"] == pytest.approx(1.0)


def test_permutation_null_is_centred_on_zero_for_unrelated_columns():
    rng = np.random.default_rng(1)
    n = 120
    cells = pd.DataFrame(
        {
            "bidder_id": [f"b{i}" for i in range(n)],
            "cpv_division": rng.choice(["45", "33", "09"], n),
            "f_full": rng.uniform(size=n),
            "realised_rate": rng.uniform(size=n),
        }
    )
    out = permutation_null(cells, "f_full", n_perm=300, seed=7)
    assert abs(out["null_mean"]) < 0.08
    assert out["p_two_sided"] > 0.02
    assert out["p_greater"] > 0.02
    assert out["n_perm"] == 300


def test_permutation_null_detects_a_planted_association():
    rng = np.random.default_rng(2)
    n = 150
    f = rng.uniform(size=n)
    cells = pd.DataFrame(
        {
            "bidder_id": [f"b{i}" for i in range(n)],
            "cpv_division": rng.choice(["45", "33"], n),
            "f_full": f,
            "realised_rate": f + rng.normal(0, 0.05, n),
        }
    )
    out = permutation_null(cells, "f_full", n_perm=300, seed=7)
    assert out["observed"] > 0.8
    assert out["p_two_sided"] < 0.01
    assert out["p_greater"] < 0.01


def test_standardised_difference_removes_a_pure_composition_effect():
    """Identical within-cell rates, different cell mixes: the difference is zero."""
    rows = []
    for cell, rate in [("45", 0.6), ("33", 0.1)]:
        for grp, n in [("t", 100), ("c", 100)]:
            share = 0.8 if (cell == "45") == (grp == "t") else 0.2
            k = int(n * share)
            for i in range(k):
                rows.append(
                    {"grp": grp, "cpv_division": cell, "year": "2021",
                     "lab": 1.0 if i < rate * k else 0.0}
                )
    df = pd.DataFrame(rows)
    t = df[df.grp == "t"]
    c = df[df.grp == "c"]
    raw = t["lab"].mean() - c["lab"].mean()
    out = standardised_difference(t, c, "lab", ["cpv_division", "year"], n_boot=50)
    assert abs(raw) > 0.2
    assert out["difference"] == pytest.approx(0.0, abs=0.02)
    assert out["n_treated"] == len(t)


def test_lowest_disqualified_contrast_splits_the_groups_as_documented():
    lots = pd.DataFrame(
        {
            "n_bids_lot": [3, 3, 3, 1],
            "lowest_disqualified": [True, False, True, True],
            "winner_is_lowest": [False, True, True, False],
            "cpv_division": ["45", "45", "45", "45"],
            "year": ["2021", "2021", "2021", "2021"],
            "duration_extension": [1.0, 0.0, 1.0, 1.0],
        }
    )
    out = lowest_disqualified_contrast(lots, ["duration_extension"])
    # Row 0 is treated (cheapest disqualified, dearer bid won); row 1 is the
    # control (cheapest won, nothing disqualified); row 2 is neither, because
    # a bid at the minimum price won even though a cheapest bid was
    # disqualified; row 3 has a single bid and is not eligible at all.
    assert out.iloc[0]["n_treated"] == 1
    assert out.iloc[0]["n_control"] == 1


def test_decile_table_counts_every_row_once():
    df = pd.DataFrame({"x": np.arange(100.0), "lab": (np.arange(100) % 3 == 0).astype(float)})
    tab = decile_table(df, "x", ["lab"], q=5)
    assert tab["n_lots"].sum() == 100
    assert len(tab) == 5
    assert tab["x_min"].is_monotonic_increasing


def test_icc_is_near_zero_when_groups_carry_no_signal():
    from src.contrasts import icc_one_way

    rng = np.random.default_rng(3)
    n, k = 3000, 300
    groups = np.repeat(np.arange(k), n // k).astype(object)
    y = (rng.uniform(size=n) < 0.3).astype(float)
    out = icc_one_way(y, groups)
    assert out["groups"] == k
    assert abs(out["icc"]) < 0.05


def test_icc_rises_when_the_group_sets_the_rate():
    from src.contrasts import icc_one_way

    rng = np.random.default_rng(4)
    n, k = 3000, 300
    groups = np.repeat(np.arange(k), n // k).astype(object)
    theta = rng.beta(1, 1, k)
    y = (rng.uniform(size=n) < theta[np.repeat(np.arange(k), n // k)]).astype(float)
    out = icc_one_way(y, groups)
    assert out["icc"] > 0.3


def test_variance_decomposition_separates_two_groupings():
    """Outcomes clustered by buyer and not by bidder must come out that way."""
    from src.contrasts import variance_decomposition

    rng = np.random.default_rng(5)
    n = 4000
    buyers = [f"b{i % 200}" for i in range(n)]
    winners = [f"w{rng.integers(0, 200)}" for _ in range(n)]
    theta = {b: rng.beta(1, 1) for b in set(buyers)}
    y = np.array([1.0 if rng.uniform() < theta[b] else 0.0 for b in buyers])
    lots = pd.DataFrame(
        {"buyer_id": buyers, "winner_id": winners, "duration_extension": y,
         "cpv_division": ["45"] * n, "region": ["r"] * n}
    )
    out = variance_decomposition(lots, "duration_extension", n_perm=50).set_index("grouping")
    assert out.loc["buyer_id", "icc"] > 0.25
    assert out.loc["buyer_id", "p_greater"] < 0.05
    assert out.loc["winner_id", "icc"] < 0.1
    assert out.loc["winner_id", "p_greater"] > 0.05


def test_conditional_icc_attributes_clustering_to_the_right_entity():
    """Outcomes set by the buyer must not survive holding the buyer fixed."""
    from src.contrasts import conditional_icc

    rng = np.random.default_rng(6)
    n = 5000
    buyers = np.array([f"b{i % 150}" for i in range(n)], dtype=object)
    # Each bidder works mostly with one buyer, which is what creates the
    # spurious bidder clustering this test has to see through.
    winners = np.array([f"w{(i % 150) * 3 + rng.integers(0, 3)}" for i in range(n)], dtype=object)
    theta = {b: rng.beta(1, 1) for b in set(buyers.tolist())}
    y = np.array([1.0 if rng.uniform() < theta[b] else 0.0 for b in buyers])
    lots = pd.DataFrame(
        {"buyer_id": buyers, "winner_id": winners, "duration_extension": y,
         "cpv_division": ["45"] * n}
    )
    from src.contrasts import icc_one_way

    # Unconditionally the bidder looks like it clusters the outcome, because
    # each bidder works with one buyer and the buyer is what sets the rate.
    raw = icc_one_way(y, winners)
    assert raw["icc"] > 0.2
    # Holding the buyer fixed, that apparent bidder effect disappears: the
    # null reproduces it, so the excess is not separable from zero.
    w = conditional_icc(lots, "duration_extension", "winner_id", "buyer_id", n_perm=100)
    assert w["p_greater"] > 0.05, w
    assert w["excess"] < 0.05, w
    assert w["null_mean"] > 0.15, w


def test_conditional_icc_finds_a_real_bidder_effect():
    from src.contrasts import conditional_icc

    rng = np.random.default_rng(7)
    n = 5000
    buyers = np.array([f"b{i % 150}" for i in range(n)], dtype=object)
    winners = np.array([f"w{rng.integers(0, 150)}" for _ in range(n)], dtype=object)
    theta = {w: rng.beta(1, 1) for w in set(winners.tolist())}
    y = np.array([1.0 if rng.uniform() < theta[w] else 0.0 for w in winners])
    lots = pd.DataFrame(
        {"buyer_id": buyers, "winner_id": winners, "duration_extension": y,
         "cpv_division": ["45"] * n}
    )
    out = conditional_icc(lots, "duration_extension", "winner_id", "buyer_id", n_perm=100)
    assert out["p_greater"] < 0.05, out
    assert out["excess"] > 0.2


def test_auc_matches_sklearn_including_heavy_ties():
    """The hand-rolled AUC is in every permutation loop, so pin it to a reference."""
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(11)
    y = (rng.uniform(size=5000) < 0.12).astype(float)
    p = rng.uniform(size=5000)
    assert auc(y, p) == pytest.approx(roc_auc_score(y, p), abs=1e-12)
    # A third of the forecasts collapsed onto one value.
    tied = np.where(rng.uniform(size=5000) < 0.33, 0.5, p)
    assert auc(y, tied) == pytest.approx(roc_auc_score(y, tied), abs=1e-12)
    # All tied: exactly chance.
    assert auc(y, np.full(5000, 0.3)) == pytest.approx(0.5, abs=1e-12)


def test_spearman_matches_scipy():
    from scipy.stats import spearmanr

    rng = np.random.default_rng(12)
    a = rng.uniform(size=400)
    b = a * 0.5 + rng.normal(0, 0.5, 400)
    assert spearman(a, b) == pytest.approx(spearmanr(a, b).statistic, abs=1e-12)
    # With ties on both sides.
    a2 = np.round(a, 1)
    b2 = np.round(b, 1)
    assert spearman(a2, b2) == pytest.approx(spearmanr(a2, b2).statistic, abs=1e-12)


def test_stratified_auc_ignores_a_predictor_that_only_knows_the_stratum():
    """A predictor that is constant inside each stratum carries no within-stratum
    information, however well it ranks pooled."""
    from src.scoring import stratified_auc

    rng = np.random.default_rng(21)
    n, k = 4000, 80
    strata = np.repeat(np.arange(k), n // k).astype(object)
    theta = rng.uniform(0.05, 0.95, k)
    y = (rng.uniform(size=n) < theta[np.repeat(np.arange(k), n // k)]).astype(float)
    # The predictor is the stratum's own rate: perfect between strata, useless
    # within them.
    p = theta[np.repeat(np.arange(k), n // k)]
    assert auc(y, p) > 0.75
    out = stratified_auc(y, p, strata)
    assert out["auc"] == pytest.approx(0.5, abs=1e-9)
    assert out["strata_used"] > 50
    assert out["n"] == n


def test_stratified_auc_keeps_a_real_within_stratum_signal():
    from src.scoring import stratified_auc

    rng = np.random.default_rng(22)
    n, k = 4000, 80
    strata = np.repeat(np.arange(k), n // k).astype(object)
    x = rng.uniform(size=n)
    y = (rng.uniform(size=n) < x).astype(float)
    out = stratified_auc(y, x, strata)
    assert out["auc"] > 0.7
    # Adding a large stratum offset changes the pooled AUC but not this one.
    offset = np.repeat(rng.uniform(0, 100, k), n // k)
    out2 = stratified_auc(y, x + offset, strata)
    assert out2["auc"] == pytest.approx(out["auc"], abs=1e-9)


def test_stratified_auc_handles_degenerate_strata():
    from src.scoring import stratified_auc

    y = np.array([1.0, 1.0, 0.0, 1.0])
    p = np.array([0.2, 0.8, 0.1, 0.9])
    strata = np.array(["a", "a", "b", "b"], dtype=object)
    out = stratified_auc(y, p, strata)
    # Stratum "a" is all positives and contributes nothing.
    assert out["strata_used"] == 1
    assert out["auc"] == pytest.approx(1.0)
    assert np.isnan(stratified_auc(np.array([]), np.array([]), np.array([]))["auc"])
