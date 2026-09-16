"""Dating each publication to the portfolio position it carries."""
from __future__ import annotations

import datetime as dt

import pytest

from gmpp.src.calendar_map import (
    REPORTING_MONTHS,
    interval_months,
    next_snapshot,
    ordered_snapshots,
    snapshot_from_financial_year,
)


def test_a_money_column_financial_year_dates_the_september_snapshot():
    assert snapshot_from_financial_year(
        ["2018/19 TOTAL Baseline £m\n(including Non-Government costs)"]
    ) == dt.date(2018, 9, 30)
    assert snapshot_from_financial_year(["2013/2014 Budget"]) == dt.date(2013, 9, 30)


def test_a_narrative_column_never_dates_a_snapshot():
    """The September 2019 files head their money columns "Financial Year
    Baseline (GBPm)" with no year, and carry this narrative header left over
    from the previous year's template. Reading a financial year out of it dated
    all 120 September 2019 project-years to September 2018.
    """
    headers = [
        "Financial Year Baseline (£m) (including Non-Government Costs)",
        "Financial Year Forecast (£m) (including Non-Government Costs)",
        "Financial Year Variance (%)",
        "Departmental narrative on  budget/forecast variance for 2018/19\n"
        "(if variance is more than 5%)",
    ]
    assert snapshot_from_financial_year(headers) is None


def test_a_real_price_base_is_not_a_reporting_year():
    """The March 2026 NISTA file states its price base in the money header."""
    assert snapshot_from_financial_year(
        ["Financial Year Baseline (GBPm, Presented in 2024/25 Real Prices)"]
    ) is None


def test_every_snapshot_falls_in_a_reporting_month():
    for date in ordered_snapshots():
        assert date.month in REPORTING_MONTHS


def test_the_snapshot_series_is_the_fourteen_published_positions():
    order = ordered_snapshots()
    assert len(order) == 14
    assert order[0] == dt.date(2012, 9, 30)
    assert order[-1] == dt.date(2026, 3, 31)
    # September through 2019, then the move to March.
    assert order[7] == dt.date(2019, 9, 30)
    assert order[8] == dt.date(2021, 3, 31)


def test_the_gap_across_the_reporting_move_is_eighteen_months():
    """Every other step is twelve months. Scoring must not treat this one as a
    year, so `interval_months` reports the true gap.
    """
    order = ordered_snapshots()
    gaps = [
        interval_months(a, b) for a, b in zip(order, order[1:])
    ]
    assert gaps.count(18) == 1
    assert set(gaps) == {12, 18}
    assert interval_months(dt.date(2019, 9, 30), dt.date(2021, 3, 31)) == 18


@pytest.mark.parametrize(
    "date,expected",
    [
        (dt.date(2018, 9, 30), dt.date(2019, 9, 30)),
        (dt.date(2019, 9, 30), dt.date(2021, 3, 31)),
        (dt.date(2026, 3, 31), None),
    ],
)
def test_next_snapshot(date, expected):
    assert next_snapshot(date) == expected
