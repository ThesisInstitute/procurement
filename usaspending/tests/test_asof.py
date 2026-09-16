"""The as-of history features must never use information dated on or after the
base action date of the award they describe."""
import numpy as np
import pandas as pd
import pytest

import panel as P


def test_asof_group_stats_strict_excludes_same_day_events():
    g = pd.Series(["a", "a", "a"])
    d = pd.Series(pd.to_datetime(["2015-01-01", "2016-01-01", "2017-01-01"]))
    v = pd.Series([1.0, 1.0, 1.0])
    qg = pd.Series(["a", "a", "a"])
    qd = pd.Series(pd.to_datetime(["2015-01-01", "2016-01-01", "2018-01-01"]))
    counts, _ = P._asof_group_stats(g, d, v, qg, qd, strict=True)
    assert counts.tolist() == [0.0, 1.0, 3.0]


def test_asof_group_stats_non_strict_includes_same_day_events():
    g = pd.Series(["a", "a"])
    d = pd.Series(pd.to_datetime(["2015-01-01", "2016-01-01"]))
    v = pd.Series([1.0, 3.0])
    counts, means = P._asof_group_stats(
        g, d, v, pd.Series(["a", "a"]),
        pd.Series(pd.to_datetime(["2015-01-01", "2016-01-01"])), strict=False)
    assert counts.tolist() == [1.0, 2.0]
    assert means[0] == pytest.approx(1.0)
    assert means[1] == pytest.approx(2.0)


def test_asof_group_stats_does_not_mix_groups():
    g = pd.Series(["a", "b", "b"])
    d = pd.Series(pd.to_datetime(["2015-01-01", "2015-01-01", "2015-06-01"]))
    v = pd.Series([10.0, 20.0, 40.0])
    counts, means = P._asof_group_stats(
        g, d, v, pd.Series(["a", "b"]),
        pd.Series(pd.to_datetime(["2016-01-01", "2016-01-01"])), strict=False)
    assert counts.tolist() == [1.0, 2.0]
    assert means[0] == pytest.approx(10.0)
    assert means[1] == pytest.approx(30.0)


def test_asof_group_stats_unknown_group_gets_zero_and_nan():
    g = pd.Series(["a"])
    d = pd.Series(pd.to_datetime(["2015-01-01"]))
    v = pd.Series([1.0])
    counts, means = P._asof_group_stats(
        g, d, v, pd.Series(["zzz"]),
        pd.Series(pd.to_datetime(["2020-01-01"])), strict=False)
    assert counts.tolist() == [0.0]
    assert np.isnan(means[0])


def _panel_rows(rows):
    df = pd.DataFrame(rows)
    df["action_date"] = pd.to_datetime(df["action_date"])
    return df


def test_history_features_are_blind_to_later_and_unresolved_awards():
    """Three awards for one recipient.

    2010-01-01 growth 1.0 terminated 1   resolves 2013-01-01
    2012-01-01 growth 0.0 terminated 0   resolves 2015-01-01
    2014-01-01 is the award being described

    At the 2014 base date only the first award has resolved (2013-01-01 <=
    2014-01-01); the second resolves in 2015 and must not appear. The prior
    award count, which has no resolution requirement, sees both.
    """
    rows = _panel_rows([
        dict(action_date="2010-01-01", recipient_uei="U", awarding_office_code="O",
             ceiling_growth_36=1.0, terminated_36=1, schedule_slip_gt90_36=1.0),
        dict(action_date="2012-01-01", recipient_uei="U", awarding_office_code="O",
             ceiling_growth_36=0.0, terminated_36=0, schedule_slip_gt90_36=0.0),
        dict(action_date="2014-01-01", recipient_uei="U", awarding_office_code="O",
             ceiling_growth_36=0.0, terminated_36=0, schedule_slip_gt90_36=0.0),
    ])
    out = P.add_history_features(rows).set_index("action_date")
    last = out.loc[pd.Timestamp("2014-01-01")]
    assert last["recipient_prior_award_count"] == 2
    assert last["recipient_prior_mean_ceiling_growth_36"] == pytest.approx(1.0)
    assert last["recipient_prior_termination_rate_36"] == pytest.approx(1.0)
    assert last["office_prior_mean_ceiling_growth_36"] == pytest.approx(1.0)

    first = out.loc[pd.Timestamp("2010-01-01")]
    assert first["recipient_prior_award_count"] == 0
    assert np.isnan(first["recipient_prior_mean_ceiling_growth_36"])


def test_history_never_includes_the_award_itself():
    rows = _panel_rows([
        dict(action_date="2010-01-01", recipient_uei="U", awarding_office_code="O",
             ceiling_growth_36=5.0, terminated_36=1, schedule_slip_gt90_36=1.0),
    ])
    out = P.add_history_features(rows)
    assert out["recipient_prior_award_count"].iloc[0] == 0
    assert np.isnan(out["recipient_prior_mean_ceiling_growth_36"].iloc[0])
    assert np.isnan(out["recipient_prior_termination_rate_36"].iloc[0])


def test_history_of_a_second_recipient_is_independent():
    rows = _panel_rows([
        dict(action_date="2010-01-01", recipient_uei="U1", awarding_office_code="O1",
             ceiling_growth_36=2.0, terminated_36=1, schedule_slip_gt90_36=1.0),
        dict(action_date="2014-01-01", recipient_uei="U2", awarding_office_code="O1",
             ceiling_growth_36=0.0, terminated_36=0, schedule_slip_gt90_36=0.0),
    ])
    out = P.add_history_features(rows).set_index("recipient_uei")
    assert out.loc["U2", "recipient_prior_award_count"] == 0
    assert np.isnan(out.loc["U2", "recipient_prior_mean_ceiling_growth_36"])
    # same office though, and the 2010 award resolved by 2013
    assert out.loc["U2", "office_prior_award_count"] == 1
    assert out.loc["U2", "office_prior_mean_ceiling_growth_36"] == pytest.approx(2.0)


def test_history_is_invariant_to_input_row_order():
    rows = _panel_rows([
        dict(action_date="2014-01-01", recipient_uei="U", awarding_office_code="O",
             ceiling_growth_36=0.0, terminated_36=0, schedule_slip_gt90_36=0.0),
        dict(action_date="2010-01-01", recipient_uei="U", awarding_office_code="O",
             ceiling_growth_36=1.0, terminated_36=1, schedule_slip_gt90_36=1.0),
        dict(action_date="2012-01-01", recipient_uei="U", awarding_office_code="O",
             ceiling_growth_36=0.0, terminated_36=0, schedule_slip_gt90_36=0.0),
    ])
    a = P.add_history_features(rows).sort_values("action_date").reset_index(drop=True)
    b = P.add_history_features(rows.sort_values("action_date")).reset_index(drop=True)
    pd.testing.assert_series_equal(a["recipient_prior_award_count"],
                                   b["recipient_prior_award_count"])
    pd.testing.assert_series_equal(a["recipient_prior_mean_ceiling_growth_36"],
                                   b["recipient_prior_mean_ceiling_growth_36"])


def test_history_ignores_awards_whose_outcome_is_missing():
    rows = _panel_rows([
        dict(action_date="2010-01-01", recipient_uei="U", awarding_office_code="O",
             ceiling_growth_36=np.nan, terminated_36=0, schedule_slip_gt90_36=np.nan),
        dict(action_date="2011-01-01", recipient_uei="U", awarding_office_code="O",
             ceiling_growth_36=3.0, terminated_36=0, schedule_slip_gt90_36=0.0),
        dict(action_date="2015-01-01", recipient_uei="U", awarding_office_code="O",
             ceiling_growth_36=0.0, terminated_36=0, schedule_slip_gt90_36=0.0),
    ])
    out = P.add_history_features(rows).set_index("action_date")
    last = out.loc[pd.Timestamp("2015-01-01")]
    assert last["recipient_prior_award_count"] == 2
    # only the 2011 award contributes a growth value
    assert last["recipient_prior_mean_ceiling_growth_36"] == pytest.approx(3.0)
