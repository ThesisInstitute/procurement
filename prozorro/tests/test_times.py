"""Mixed-precision ISO timestamps must all parse, not just the first spelling.

This is a regression test for a silent failure found on the real sample:
`pd.to_datetime` infers one format from the first element, so a column that
starts with a whole-second stamp coerced every microsecond stamp to NaT, which
in turn zeroed every as-of history feature for those rows.
"""

import numpy as np
import pandas as pd
import pytest

from src.features import AsOfHistory, _ts, build_history, lot_block
from src.labels import days_between, days_between_columns
from src.times import to_kyiv_date, to_seconds, to_utc

MIXED = pd.Series(
    [
        "2021-12-24T14:21:59+02:00",          # no microseconds, winter offset
        "2020-11-12T16:54:16.166801+02:00",   # microseconds, winter offset
        "2022-08-11T10:30:18.805993+03:00",   # microseconds, summer offset
        "2019-07-01T09:00:00+03:00",          # no microseconds, summer offset
        None,
    ]
)


def test_every_spelling_parses():
    out = to_utc(MIXED)
    assert out.notna().sum() == 4
    assert out.isna().sum() == 1
    assert out.iloc[0] == pd.Timestamp("2021-12-24T12:21:59Z")
    assert out.iloc[2] == pd.Timestamp("2022-08-11T07:30:18.805993Z")


def test_the_naive_call_is_what_used_to_break():
    """Documents the failure mode, so the fix cannot be quietly reverted."""
    naive = pd.to_datetime(MIXED, utc=True, errors="coerce")
    assert naive.isna().sum() > to_utc(MIXED).isna().sum()


def test_to_seconds_is_finite_for_every_parsed_stamp():
    secs = to_seconds(MIXED)
    assert np.isfinite(secs[:4]).all()
    assert not np.isfinite(secs[4])
    assert secs[3] < secs[1] < secs[0] < secs[2]


def test_kyiv_date_uses_local_time_not_utc():
    # 00:30 Kyiv time on 1 March is still 22:30 UTC on 28 February.
    s = pd.Series(["2021-03-01T00:30:00+02:00"])
    assert to_kyiv_date(s).iloc[0] == "2021-03-01"
    assert to_utc(s).dt.strftime("%Y-%m-%d").iloc[0] == "2021-02-28"


def test_days_between_agrees_scalar_and_vectorised():
    later = pd.Series(["2022-06-30T00:00:00+03:00", "2021-12-31T00:00:00+02:00"])
    earlier = pd.Series(["2021-12-31T00:00:00+02:00", "2021-12-31T00:00:00+02:00"])
    vec = days_between_columns(later, earlier)
    for i in range(2):
        assert vec[i] == pytest.approx(days_between(later[i], earlier[i]))
    assert vec[0] == pytest.approx(180.958, abs=0.01)
    assert vec[1] == 0.0


def test_as_of_history_survives_mixed_precision_columns():
    lots = pd.DataFrame(
        {
            "tender_id": ["T1", "T2"],
            "buyer_id": ["B", "B"],
            "winner_id": ["W", "W"],
            "winner_discount": [0.2, 0.1],
            "tender_start": [
                "2019-05-01T00:00:00+03:00",
                "2021-02-01T10:00:00.123456+02:00",
            ],
            "tc_dateSigned": [
                "2019-06-01T00:00:00.999999+03:00",
                "2021-03-05T00:00:00+02:00",
            ],
            "award_end": [None, None],
            "first_duration_change_date": ["2019-09-01T00:00:00+03:00", None],
            "lot_expected_value": [1.0, 2.0],
            "n_bids_lot": [2, 2],
            "n_lots": [1, 1],
            "bid_cv": [0.1, 0.1],
            "bid_spread": [0.2, 0.2],
            "method": ["aboveThreshold"] * 2,
            "cpv_division": ["45", "45"],
            "region": ["r", "r"],
            "main_category": ["works", "works"],
            "buyer_kind": ["general", "general"],
        }
    )
    bids = pd.DataFrame({"tender_id": ["T1", "T2"], "bidder_id": ["W", "W"],
                         "discount": [0.2, 0.1]})
    hist = build_history(lots, bids)
    assert np.isfinite(_ts(lots["tc_dateSigned"])).all()
    # The 2019 win and its 2019 extension are both visible by the 2021 tender.
    cut = to_seconds(pd.Series(["2021-02-01T10:00:00.123456+02:00"]))[0]
    assert hist["winner_wins"].count("W", cut) == 1
    assert hist["winner_ext"].count("W", cut) == 1
    blk = lot_block(lots, hist)
    assert blk["buyer_prior_lots_log"].iloc[1] > 0
    # Kyiv local month, so 2019-05-01T00:00+03:00 is May and not April.
    assert blk["start_month"].tolist() == [5.0, 2.0]


def test_asof_history_ignores_unparseable_dates_without_crashing():
    h = AsOfHistory()
    h.add("a", float("nan"))
    h.add("a", to_seconds(pd.Series(["2020-01-01T00:00:00+02:00"]))[0])
    h.finalise()
    assert h.count("a", to_seconds(pd.Series(["2021-01-01T00:00:00+02:00"]))[0]) == 1
