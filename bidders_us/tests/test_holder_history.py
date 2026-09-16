"""The holder history must only see orders resolved before the order it describes."""
import numpy as np
import pandas as pd
import pytest

from bidders_us.src import holder_history as H


def _events():
    return pd.DataFrame({
        "group": ["V1|A", "V1|A", "V1|A", "V1|B"],
        "base_date": pd.to_datetime(["2012-01-01", "2013-01-01", "2014-06-01", "2012-01-01"]),
        "value": [1.0, 0.0, 1.0, np.nan],
    })


def test_prior_count_is_strict_and_resolution_uses_horizon():
    q = pd.DataFrame({"group": ["V1|A", "V1|A", "V1|A"],
                      "date": pd.to_datetime(["2013-01-01", "2014-06-01", "2016-01-01"])})
    out = H.asof_history(_events(), q, h_months=24)
    # 2013-01-01: one prior order (2012); it resolves 2014-01-01, so no rate yet
    assert out.loc[0, "prior_count"] == 1
    assert out.loc[0, "resolved_count"] == 0
    assert np.isnan(out.loc[0, "resolved_rate"])
    # 2014-06-01: two prior orders; the 2012 one resolved 2014-01-01 (value 1)
    assert out.loc[1, "prior_count"] == 2
    assert out.loc[1, "resolved_count"] == 1
    assert out.loc[1, "resolved_rate"] == pytest.approx(1.0)
    # 2016-01-01: three prior; 2012 and 2013 resolved (1 and 0); 2014-06 resolves 2016-06
    assert out.loc[2, "prior_count"] == 3
    assert out.loc[2, "resolved_count"] == 2
    assert out.loc[2, "resolved_rate"] == pytest.approx(0.5)


def test_same_day_event_is_not_prior_and_resolution_on_the_day_counts():
    ev = pd.DataFrame({"group": ["g"], "base_date": pd.to_datetime(["2012-01-01"]), "value": [1.0]})
    q = pd.DataFrame({"group": ["g", "g"], "date": pd.to_datetime(["2012-01-01", "2013-01-01"])})
    out = H.asof_history(ev, q, h_months=12)
    assert out.loc[0, "prior_count"] == 0
    assert out.loc[1, "prior_count"] == 1
    assert out.loc[1, "resolved_count"] == 1  # base + 12 months == query date, included


def test_null_outcome_counts_as_prior_but_not_resolved():
    q = pd.DataFrame({"group": ["V1|B"], "date": pd.to_datetime(["2020-01-01"])})
    out = H.asof_history(_events(), q, h_months=12)
    assert out.loc[0, "prior_count"] == 1
    assert out.loc[0, "resolved_count"] == 0
    assert np.isnan(out.loc[0, "resolved_rate"])


def test_unknown_group_and_null_group():
    q = pd.DataFrame({"group": ["zzz", None], "date": pd.to_datetime(["2020-01-01", "2020-01-01"])})
    out = H.asof_history(_events(), q, h_months=12)
    assert out["prior_count"].tolist() == [0, 0]
    assert out["resolved_rate"].isna().all()


def test_groups_do_not_mix():
    ev = pd.DataFrame({"group": ["a", "b"], "base_date": pd.to_datetime(["2010-01-01", "2010-01-01"]),
                       "value": [1.0, 0.0]})
    q = pd.DataFrame({"group": ["a", "b"], "date": pd.to_datetime(["2015-01-01", "2015-01-01"])})
    out = H.asof_history(ev, q, h_months=12)
    assert out["resolved_rate"].tolist() == [1.0, 0.0]
