"""The quantile ladder, on a synthetic panel small enough to reason about."""
import numpy as np
import pandas as pd
import pytest

import features as F
import quantile_models as Q
import scoring as S


def noop(_msg):
    return None


TEST_MAX_ITER = 40


@pytest.fixture(autouse=True)
def _small_models(monkeypatch):
    """Fit short models in the tests.

    The logic under test is the ladder, the winsorisation and the
    iteration-selection plumbing, none of which depends on the tree count. The
    production setting fits 300 iterations three times per quantile, which turns
    this file into a seven minute test run for no extra coverage.
    """
    monkeypatch.setattr(Q, "MAX_ITER", TEST_MAX_ITER)


def test_the_production_iteration_cap_is_what_the_report_describes():
    """The fixture above shrinks it, so assert the real value separately."""
    import models as M
    assert M.MAX_ITER == 300


def _panel(n_per_year=200, seed=0):
    """A panel whose continuous outcome depends on one feature, plus noise.

    Thirteen base fiscal years so the FY2010-2017 / FY2018-2019 / FY2020-2022
    split has enough rows in every part.
    """
    rng = np.random.RandomState(seed)
    years = list(range(2010, 2023))
    n = len(years) * n_per_year
    log_ceiling = rng.uniform(5.0, 8.0, n)
    rows = pd.DataFrame({
        "base_fy": np.repeat(years, n_per_year),
        "base_month": rng.randint(1, 13, n),
        "log_base_obligation": log_ceiling - 0.3,
        "log_base_ceiling": log_ceiling,
        "option_heaviness": rng.uniform(1.0, 3.0, n),
        "planned_duration_days": rng.randint(30, 1500, n),
        "potential_extra_duration_days": rng.randint(0, 900, n),
        "n_offers": rng.randint(1, 10, n),
        "n_offers_missing": 0,
        "recipient_is_aggregate": 0,
        "awarding_agency_code": rng.choice(["097", "070", "012"], n),
        "naics2": rng.choice(["54", "33", "23"], n),
        "naics6": rng.choice(["541512", "336411", "236220"], n),
        "psc1": rng.choice(["D", "R", "Y"], n),
        "psc_full": rng.choice(["D302", "R425", "Y1AA"], n),
        "type_of_contract_pricing_code": rng.choice(["J", "U", "R"], n),
        "extent_competed_code": rng.choice(["A", "C", "D"], n),
        "solicitation_procedures_code": rng.choice(["NP", "SP1"], n),
        "type_of_set_aside_code": rng.choice(["NONE", "SBA"], n),
        "awarding_sub_agency_code": rng.choice(["2100", "7008"], n),
        "awarding_office_code": rng.choice(["OFF1", "OFF2", "OFF3"], n),
        "contracting_officers_determination_of_business_size_code":
            rng.choice(["S", "O"], n),
        "performance_based_service_acquisition_code": rng.choice(["Y", "N"], n),
        "multi_year_contract_code": rng.choice(["Y", "N"], n),
        "cost_or_pricing_data_code": rng.choice(["Y", "N"], n),
        "fed_biz_opps_code": rng.choice(["Y", "N"], n),
        "primary_place_of_performance_state_code": rng.choice(["VA", "CA"], n),
    })
    for c in F.HISTORY:
        rows[c] = rng.uniform(0, 1, n)
    # the outcome is a real function of log_base_ceiling, so a model that learns
    # anything at all must beat the constant forecast
    signal = (log_ceiling - 6.5) * 0.8
    for h in (12, 24, 36):
        rows[f"ceiling_growth_{h}"] = signal + rng.normal(0, 0.3, n)
        rows[f"schedule_slip_days_{h}"] = signal * 100 + rng.normal(0, 40, n)
        rows[f"unplanned_growth_{h}"] = np.abs(signal) * 0.2 + rng.normal(0, 0.05, n)
        rows[f"qualifies_{h}"] = True
    return rows


def _maps(panel):
    masks = Q.split_masks(panel)
    return F.fit_category_maps(panel[masks["train"]])


def test_quantile_cell_returns_all_three_quantiles():
    panel = _panel()
    res = Q.run_cell(panel, "ceiling_growth", 36, _maps(panel), noop)
    assert set(res["quantiles"]) == {"0.10", "0.50", "0.90"}
    assert res["n_train"] > 0 and res["n_val"] > 0 and res["n_test"] > 0
    for q, e in res["quantiles"].items():
        assert e["pinball_constant"] > 0
        assert e["pinball_gbm"] > 0
        assert 1 <= e["n_iter"] <= TEST_MAX_ITER


def test_quantile_gbm_beats_a_constant_when_the_outcome_has_real_signal():
    """The outcome is a function of log_base_ceiling, so skill must be positive."""
    panel = _panel()
    res = Q.run_cell(panel, "ceiling_growth", 36, _maps(panel), noop)
    for q in ("0.10", "0.50", "0.90"):
        assert res["quantiles"][q]["pinball_skill_vs_constant"] > 0, q


def test_quantile_gbm_has_no_skill_when_the_outcome_is_pure_noise():
    """Guard against a harness that manufactures skill out of nothing."""
    panel = _panel()
    rng = np.random.RandomState(7)
    panel["ceiling_growth_36"] = rng.normal(0, 1, len(panel))
    res = Q.run_cell(panel, "ceiling_growth", 36, _maps(panel), noop)
    # a little either way is sampling noise; a large positive number would mean
    # the split is leaking
    assert res["quantiles"]["0.50"]["pinball_skill_vs_constant"] < 0.05


def test_median_cell_reports_mean_absolute_error():
    panel = _panel()
    res = Q.run_cell(panel, "ceiling_growth", 36, _maps(panel), noop)
    med = res["quantiles"]["0.50"]
    assert "mae_constant" in med and "mae_gbm" in med
    assert med["mae_gbm"] < med["mae_constant"]
    assert "mae_constant" not in res["quantiles"]["0.10"]


def test_winsorisation_cut_points_come_from_the_training_years_only():
    panel = _panel()
    y = pd.to_numeric(panel["ceiling_growth_36"]).to_numpy(dtype=float)
    masks = Q.split_masks(panel)
    lo, hi = np.quantile(y[masks["train"]], [0.01, 0.99])
    res = Q.run_cell(panel, "ceiling_growth", 36, _maps(panel), noop)
    assert res["train_winsor_low"] == pytest.approx(lo)
    assert res["train_winsor_high"] == pytest.approx(hi)
    # and they really are train-only: the full-sample cut points differ
    lo_all, hi_all = np.quantile(y, [0.01, 0.99])
    assert (lo, hi) != (lo_all, hi_all)


def test_a_split_that_is_too_small_is_reported_not_silently_skipped():
    panel = _panel(n_per_year=5)
    res = Q.run_cell(panel, "ceiling_growth", 36, _maps(panel), noop)
    assert res["error"] == "split too small"


def test_pinball_loss_at_the_median_is_half_the_mean_absolute_error():
    y = np.array([1.0, 2.0, 3.0, 10.0])
    q = np.full(4, 2.5)
    assert S.pinball_loss(y, q, 0.5) == pytest.approx(S.mae(y, q) / 2)
