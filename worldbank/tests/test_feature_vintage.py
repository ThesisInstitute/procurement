"""Tests for the ex-ante / post-treatment field test, on synthetic fixtures.

The measurement in src/feature_vintage.py is what removed
`ieg_country_fcs_status` from the model's feature set, so the discriminating
power of the test itself needs to be demonstrated rather than assumed: it has to
say "approval" for a field constructed to track approval, and "closing" for one
constructed to track closing, on data where the answer is known by construction.
"""
import numpy as np
import pandas as pd
import pytest

from worldbank.src import feature_vintage as fv


def _frame(rule, n_per_country=40, n_countries=4, seed=0):
    """Projects whose field value is decided by `rule(approval, closing)`.

    Approval and closing years are deliberately correlated but not identical,
    which is the situation on the real data: both fiscal years carry signal, so
    the test has to pick the better one rather than the only one.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(n_countries):
        for _i in range(n_per_country):
            appr = int(rng.integers(1995, 2016))
            closing = appr + int(rng.integers(3, 12))
            rows.append({
                "Country / Economy": f"C{c}",
                "Approval FY": appr,
                "Final Closing FY": closing,
                "F": rule(appr, closing),
            })
    return pd.DataFrame(rows)


def test_a_field_keyed_to_approval_is_reported_as_approval_keyed():
    df = _frame(lambda a, c: "early" if a < 2005 else "late", seed=1)
    r = fv.field_report(df, "F")
    assert r["mean_approval_fy_accuracy"] == pytest.approx(1.0)
    assert r["mean_approval_fy_accuracy"] > r["mean_closing_fy_accuracy"]
    assert r["approval_better_in"] > r["closing_better_in"]


def test_a_field_keyed_to_closing_is_reported_as_closing_keyed():
    """The shape that disqualified FCS status."""
    df = _frame(lambda a, c: "pre" if c < 2015 else "post", seed=2)
    r = fv.field_report(df, "F")
    assert r["mean_closing_fy_accuracy"] == pytest.approx(1.0)
    assert r["mean_closing_fy_accuracy"] > r["mean_approval_fy_accuracy"]
    assert r["closing_better_in"] > r["approval_better_in"]


def test_a_constant_field_is_not_tested_at_all():
    df = _frame(lambda a, c: "same")
    r = fv.field_report(df, "F")
    assert r["countries_varying"] == 0
    assert r["countries_tested"] == 0
    assert np.isnan(r["mean_approval_fy_accuracy"])


def test_a_country_constant_field_is_not_tested():
    """`ieg_country_lending_group` has this shape: one value per country."""
    df = _frame(lambda a, c: "x")
    df["F"] = df["Country / Economy"].map({"C0": "IDA", "C1": "IBRD",
                                           "C2": "BLEND", "C3": "IDA"})
    r = fv.field_report(df, "F")
    assert r["countries_varying"] == 0
    assert r["countries_tested"] == 0


def test_small_countries_are_excluded_from_the_test():
    df = _frame(lambda a, c: "early" if a < 2005 else "late",
                n_per_country=fv.MIN_ROWS - 1, n_countries=3, seed=3)
    r = fv.field_report(df, "F")
    assert r["countries_tested"] == 0


def test_threshold_accuracy_is_symmetric_in_the_target_coding():
    """Both directions of the threshold are tried, so coding cannot flip it."""
    years = np.array([2000, 2001, 2002, 2003])
    up = np.array([False, False, True, True])
    assert fv._best_threshold_accuracy(years, up) == pytest.approx(1.0)
    assert fv._best_threshold_accuracy(years, ~up) == pytest.approx(1.0)


def test_threshold_accuracy_is_bounded_by_a_half_on_noise():
    rng = np.random.default_rng(0)
    years = rng.integers(1990, 2020, size=200)
    target = rng.random(200) < 0.5
    acc = fv._best_threshold_accuracy(years, target)
    assert 0.5 <= acc <= 1.0


def test_run_writes_the_table_and_a_verdict_for_every_field(results_dir,
                                                            monkeypatch):
    monkeypatch.setattr(fv, "RESULTS", results_dir)
    out = fv.run()
    assert (results_dir / "feature_vintage.csv").exists()
    assert out["verdict"].notna().all()
    assert set(out["field"]) <= set(fv.FIELDS)


def test_the_real_fcs_field_is_classified_as_not_ex_ante(results_dir,
                                                         monkeypatch):
    """A regression guard on the decision that shapes the feature set.

    If a future IEG snapshot changes this field's behaviour, the exclusion in
    model.CAT_FEATURES needs revisiting, and this test is what says so.
    """
    monkeypatch.setattr(fv, "RESULTS", results_dir)
    out = fv.run()
    row = out[out["field"].eq("Country / Economy FCS Status")].iloc[0]
    assert row["mean_closing_fy_accuracy"] > row["mean_approval_fy_accuracy"]
    assert "NOT established as ex ante" in row["verdict"]
