"""Tests for the second model pass, on small synthetic fixtures.

These cover the pieces of src/analysis.py that turn numbers into claims: the
per-year skill table, the within-country permutation null, and the censoring
restriction. The model fitting itself is not tested here (it is sklearn), but
everything that decides what a number means is.

Functions here write CSVs. conftest.py redirects every module's RESULTS at a
temporary directory for every test in the suite, so nothing below can reach
worldbank/results/; take `results_dir` as a fixture argument to read back what a
function wrote. That protection exists because a test in this very file once
wrote its synthetic fixture over the real results/skill_by_test_year.csv.
"""
import numpy as np
import pandas as pd
import pytest

from worldbank.src import analysis, metrics


def make_test_fold(n_per_country=12, countries=("A", "B", "C"), seed=0):
    """A fold with enough rows per country to be usable by within_group_auc.

    within_group_auc needs at least 10 rows and 2 of each class per group, so
    the fixture is built to clear that bar rather than to be minimal.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for ci, c in enumerate(countries):
        for i in range(n_per_country):
            y = 1.0 if i >= 3 else 0.0          # 3 negatives, rest positive
            rows.append({
                "projectid": f"P{ci}{i:03d}",
                "ieg_country": c,
                "approval_year": 2011 + (i % 3),
                "y_satisfactory": y,
                "ieg_outcome": "Satisfactory" if y else "Unsatisfactory",
                "outcome_six_point": 5.0 if y else 2.0,
            })
    df = pd.DataFrame(rows)
    df["noise"] = rng.normal(size=len(df))
    return df


# -- C. skill by test year ------------------------------------------------

def test_skill_by_test_year_counts_and_base_rates():
    te = make_test_fold()
    p = te["y_satisfactory"].values * 0.9 + 0.05      # a perfect ranker
    out = analysis.skill_by_test_year(te, p)
    assert list(out["approval_year"]) == [2011, 2012, 2013]
    assert out["n"].sum() == len(te)
    assert out["n_unsatisfactory"].sum() == int((te["y_satisfactory"] == 0).sum())
    # a perfect ranker scores 1.0 in every year that contains both classes
    for _, r in out.iterrows():
        if 0 < r["n_unsatisfactory"] < r["n"]:
            assert r["auc_within_year"] == pytest.approx(1.0)


def test_skill_by_test_year_returns_nan_for_a_single_class_year():
    te = make_test_fold()
    te.loc[te["approval_year"] == 2013, "y_satisfactory"] = 1.0
    out = analysis.skill_by_test_year(
        te, np.linspace(0, 1, len(te)))
    row = out[out["approval_year"] == 2013].iloc[0]
    assert row["base_rate"] == 1.0
    assert np.isnan(row["auc_within_year"])


def test_skill_by_test_year_writes_a_file(results_dir):
    te = make_test_fold()
    analysis.skill_by_test_year(te, np.full(len(te), 0.5))
    assert (results_dir / "skill_by_test_year.csv").exists()


# -- D1. the within-country permutation null ------------------------------

def test_permutation_null_is_centred_on_one_half():
    """With forecasts that carry no information, the null must sit at 0.5."""
    te = make_test_fold(seed=1)
    p = te["noise"].values                     # independent of the label
    observed, draws, p_value = analysis.placebo_permute_within_country(
        te, p, n_perm=400, seed=7)
    assert draws.mean() == pytest.approx(0.5, abs=0.03)
    assert 0.01 < p_value < 0.99
    assert len(draws) == 400


def test_permutation_null_rejects_a_perfect_within_country_forecast():
    te = make_test_fold(seed=2)
    p = te["y_satisfactory"].values * 0.8 + 0.1
    observed, draws, p_value = analysis.placebo_permute_within_country(
        te, p, n_perm=200, seed=7)
    assert observed == pytest.approx(1.0)
    # the smallest value the +1 correction can produce
    assert p_value == pytest.approx(1 / 201)


def test_permutation_preserves_class_counts_within_every_country():
    """The reason this null is exact: the usable-group set cannot move."""
    te = make_test_fold(seed=3)
    before = te.groupby("ieg_country")["y_satisfactory"].sum().to_dict()
    p = te["noise"].values
    _, draws, _ = analysis.placebo_permute_within_country(
        te, p, n_perm=5, seed=11)
    after = te.groupby("ieg_country")["y_satisfactory"].sum().to_dict()
    assert before == after            # the fixture itself is not mutated
    assert np.isfinite(draws).all()


def test_permutation_is_deterministic_for_a_fixed_seed():
    te = make_test_fold(seed=4)
    p = te["noise"].values
    a = analysis.placebo_permute_within_country(te, p, n_perm=50, seed=99)[1]
    b = analysis.placebo_permute_within_country(te, p, n_perm=50, seed=99)[1]
    assert np.allclose(a, b)


def test_permutation_observed_matches_the_metric_it_reports():
    te = make_test_fold(seed=5)
    p = te["noise"].values
    observed, _, _ = analysis.placebo_permute_within_country(
        te, p, n_perm=10, seed=1)
    direct, _ = metrics.within_group_auc(
        te["y_satisfactory"].values, p, te["ieg_country"].values,
        weight="pairs")
    assert observed == pytest.approx(direct)


# -- A. evaluate_pair -----------------------------------------------------

def test_evaluate_pair_reports_pooled_and_within_country_separately():
    """A forecast that only knows the country ranks countries, not projects."""
    te = make_test_fold(seed=6)
    # country A is mostly satisfactory, C least; give each a constant forecast
    const = {"A": 0.9, "B": 0.6, "C": 0.3}
    p = te["ieg_country"].map(const).values
    r = analysis.evaluate_pair(te["y_satisfactory"].values, p,
                               te["ieg_country"].values)
    # constant within a country means no within-country discrimination at all
    assert r["within_country_auc"] == pytest.approx(0.5)
    assert np.isfinite(r["pooled_auc"])


def test_evaluate_pair_brier_matches_the_metric():
    te = make_test_fold(seed=7)
    p = np.full(len(te), 0.75)
    r = analysis.evaluate_pair(te["y_satisfactory"].values, p,
                               te["ieg_country"].values)
    assert r["brier"] == pytest.approx(
        metrics.brier(te["y_satisfactory"].values, p))


# -- F. the censoring restriction ----------------------------------------

def test_censoring_restricted_drops_only_low_coverage_years():
    te = make_test_fold(seed=8)
    coverage = pd.DataFrame({
        "approval_year": [2011, 2012, 2013],
        "evaluated_share": [0.9, 0.8, 0.2],      # 2013 is mostly unevaluated
    })
    p = te["noise"].values
    out = analysis.censoring_restricted(te, {"m": p}, coverage, min_share=0.5)
    row = out.iloc[0]
    assert row["years_kept"] == "2011,2012"
    assert row["n_full"] == len(te)
    assert row["n_restricted"] == int((te["approval_year"] != 2013).sum())
    assert row["n_restricted"] < row["n_full"]


def test_censoring_restricted_keeps_everything_when_coverage_is_high():
    te = make_test_fold(seed=9)
    coverage = pd.DataFrame({"approval_year": [2011, 2012, 2013],
                             "evaluated_share": [0.9, 0.9, 0.9]})
    out = analysis.censoring_restricted(te, {"m": te["noise"].values},
                                        coverage, min_share=0.5)
    assert out.iloc[0]["n_restricted"] == len(te)
    assert out.iloc[0]["pooled_auc_full"] == pytest.approx(
        out.iloc[0]["pooled_auc_restricted"])


def test_censoring_restricted_treats_an_unlisted_year_as_zero_coverage():
    """A test year absent from the coverage table must be dropped, not kept."""
    te = make_test_fold(seed=10)
    coverage = pd.DataFrame({"approval_year": [2011, 2012],
                             "evaluated_share": [0.9, 0.9]})
    out = analysis.censoring_restricted(te, {"m": te["noise"].values},
                                        coverage, min_share=0.5)
    assert out.iloc[0]["years_kept"] == "2011,2012"


def test_censoring_restricted_scores_every_model_it_is_given():
    te = make_test_fold(seed=11)
    coverage = pd.DataFrame({"approval_year": [2011, 2012, 2013],
                             "evaluated_share": [0.9, 0.9, 0.9]})
    preds = {"a": te["noise"].values, "b": np.full(len(te), 0.5)}
    out = analysis.censoring_restricted(te, preds, coverage)
    assert list(out["model"]) == ["a", "b"]
