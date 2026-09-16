"""Outcome construction on a small synthetic panel.

The fixture uses the real snapshot calendar, including the one 18-month step
between the September 2019 and March 2021 snapshots and the scale change between
March 2021 and March 2022, because both of those are where the construction can
go wrong.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gmpp.src.calendar_map import interval_months, next_snapshot, ordered_snapshots
from gmpp.src.outcomes import add_outcomes, months_between

SNAPSHOTS = ordered_snapshots()


def _row(project, snapshot, *, dca, scale, wlc=None, end=None, dept="MOD", narrative=""):
    return {
        "project_key": project,
        "project_name": project,
        "department_norm": dept,
        "snapshot_date": pd.Timestamp(snapshot),
        "report_year": pd.Timestamp(snapshot).year,
        "dca_published": dca,
        "dca_published_rank": {
            "five_point": {"Green": 0.0, "Amber/Green": 1.0, "Amber": 2.0,
                           "Amber/Red": 3.0, "Red": 4.0},
            "three_point": {"Green": 0.0, "Amber": 1.0, "Red": 2.0},
        }[scale].get(dca, np.nan),
        "scale": scale,
        "wlc_baseline_gbp_m": wlc,
        "wlc_baseline_gbp_m_kind": "value" if wlc is not None else "missing",
        "end_date": pd.Timestamp(end) if end else pd.NaT,
        "start_date": pd.NaT,
        "wlc_narrative": narrative,
        "budget_narrative": "",
        "schedule_narrative": "",
    }


@pytest.fixture
def panel() -> pd.DataFrame:
    rows = [
        # Runs the whole five-point era with a clean 20 per cent cost rise and a
        # 12-month slip between the first two snapshots.
        _row("P_GROW", "2012-09-30", dca="Amber", scale="five_point",
             wlc=100.0, end="2020-03-31"),
        _row("P_GROW", "2013-09-30", dca="Amber", scale="five_point",
             wlc=120.0, end="2021-03-31"),
        _row("P_GROW", "2014-09-30", dca="Red", scale="five_point",
             wlc=126.0, end="2021-03-31"),
        # Absent at the next snapshot, then back: a gap, not an exit.
        _row("P_GAP", "2012-09-30", dca="Green", scale="five_point", wlc=50.0),
        _row("P_GAP", "2014-09-30", dca="Green", scale="five_point", wlc=55.0),
        # Leaves after the first snapshot and never returns.
        _row("P_EXIT", "2012-09-30", dca="Amber/Red", scale="five_point", wlc=10.0),
        # Straddles the scale change: five-point at March 2021, three-point at
        # March 2022.
        _row("P_SCALE", "2021-03-31", dca="Amber/Red", scale="five_point", wlc=200.0),
        _row("P_SCALE", "2022-03-31", dca="Red", scale="three_point", wlc=200.0),
        _row("P_SCALE", "2023-03-31", dca="Red", scale="three_point", wlc=200.0),
        # Already on the worst rating, so it cannot worsen.
        _row("P_WORST", "2022-03-31", dca="Red", scale="three_point", wlc=5.0),
        _row("P_WORST", "2023-03-31", dca="Red", scale="three_point", wlc=5.0),
        # Zero baseline: a growth ratio is undefined.
        _row("P_ZERO", "2022-03-31", dca="Amber", scale="three_point", wlc=0.0),
        _row("P_ZERO", "2023-03-31", dca="Amber", scale="three_point", wlc=40.0),
        # Narrative naming a rebaseline.
        _row("P_REBASE", "2022-03-31", dca="Amber", scale="three_point", wlc=90.0,
             narrative="The programme was rebaselined in year."),
        _row("P_REBASE", "2023-03-31", dca="Amber", scale="three_point", wlc=180.0),
    ]
    return pd.DataFrame(rows)


def test_snapshot_calendar_has_one_eighteen_month_step():
    gaps = [interval_months(a, b) for a, b in zip(SNAPSHOTS, SNAPSHOTS[1:])]
    assert gaps.count(18) == 1
    assert set(gaps) == {12, 18}
    assert str(next_snapshot(SNAPSHOTS[7])) == "2021-03-31"


def test_months_between_is_linear_and_signed():
    assert months_between(
        pd.Timestamp("2020-01-31"), pd.Timestamp("2021-01-31")
    ) == pytest.approx(12.0, abs=0.05)
    assert months_between(
        pd.Timestamp("2021-01-31"), pd.Timestamp("2020-01-31")
    ) == pytest.approx(-12.0, abs=0.05)
    assert months_between(pd.NaT, pd.Timestamp("2020-01-31")) is None


def test_growth_uses_the_next_snapshot_not_the_next_calendar_year(panel):
    out = add_outcomes(panel).set_index(["project_key", "snapshot_date"])
    row = out.loc[("P_GROW", pd.Timestamp("2012-09-30"))]
    assert row["wlc_growth_1y"] == pytest.approx(0.20)
    assert bool(row["wlc_growth_1y_gt_10"]) is True
    assert bool(row["wlc_growth_1y_gt_25"]) is False
    assert row["interval_months_1"] == 12


def test_two_step_growth_uses_two_snapshots_ahead(panel):
    out = add_outcomes(panel).set_index(["project_key", "snapshot_date"])
    row = out.loc[("P_GROW", pd.Timestamp("2012-09-30"))]
    assert row["wlc_growth_2y"] == pytest.approx(0.26)
    assert row["interval_months_2"] == 24


def test_a_gap_snapshot_does_not_borrow_a_later_value(panel):
    # P_GAP has no September 2013 row, so its September 2012 row has no next.
    out = add_outcomes(panel).set_index(["project_key", "snapshot_date"])
    row = out.loc[("P_GAP", pd.Timestamp("2012-09-30"))]
    assert pd.isna(row["wlc_growth_1y"])
    assert bool(row["absent_next"]) is True
    # It came back, so it is not a permanent exit.
    assert bool(row["permanent_exit_next"]) is False


def test_a_project_that_never_returns_is_a_permanent_exit(panel):
    out = add_outcomes(panel).set_index(["project_key", "snapshot_date"])
    row = out.loc[("P_EXIT", pd.Timestamp("2012-09-30"))]
    assert bool(row["absent_next"]) is True
    assert bool(row["permanent_exit_next"]) is True


def test_the_last_snapshot_has_no_resolvable_outcome(panel):
    last = pd.Timestamp(SNAPSHOTS[-1])
    extra = panel.copy()
    extra.loc[len(extra)] = {
        **{c: None for c in extra.columns},
        "project_key": "P_LAST",
        "project_name": "P_LAST",
        "department_norm": "MOD",
        "snapshot_date": last,
        "report_year": last.year,
        "dca_published": "Amber",
        "dca_published_rank": 1.0,
        "scale": "three_point",
        "wlc_baseline_gbp_m": 10.0,
        "end_date": pd.NaT,
        "start_date": pd.NaT,
        "wlc_narrative": "",
        "budget_narrative": "",
        "schedule_narrative": "",
    }
    out = add_outcomes(extra).set_index(["project_key", "snapshot_date"])
    row = out.loc[("P_LAST", last)]
    assert row["absent_next"] is None
    assert row["permanent_exit_next"] is None
    assert pd.isna(row["wlc_growth_1y"])


def test_rating_outcomes_are_null_across_the_scale_change(panel):
    out = add_outcomes(panel).set_index(["project_key", "snapshot_date"])
    crossing = out.loc[("P_SCALE", pd.Timestamp("2021-03-31"))]
    # March 2021 is five-point and March 2022 is three-point, so "Red next"
    # would be comparing two different events.
    assert crossing["red_next"] is None
    assert crossing["worsened_next"] is None
    within = out.loc[("P_SCALE", pd.Timestamp("2022-03-31"))]
    assert bool(within["red_next"]) is True
    assert bool(within["worsened_next"]) is False


def test_a_project_already_on_the_worst_rating_is_excluded_from_worsening(panel):
    out = add_outcomes(panel).set_index(["project_key", "snapshot_date"])
    row = out.loc[("P_WORST", pd.Timestamp("2022-03-31"))]
    assert bool(row["worsened_next"]) is False
    assert row["worsened_next_excl_worst"] is None


def test_a_zero_baseline_yields_no_growth_ratio(panel):
    out = add_outcomes(panel).set_index(["project_key", "snapshot_date"])
    row = out.loc[("P_ZERO", pd.Timestamp("2022-03-31"))]
    assert pd.isna(row["wlc_growth_1y"])


def test_slip_and_its_flags(panel):
    out = add_outcomes(panel).set_index(["project_key", "snapshot_date"])
    row = out.loc[("P_GROW", pd.Timestamp("2012-09-30"))]
    assert row["slip_1y_months"] == pytest.approx(12.0, abs=0.1)
    assert bool(row["slip_1y_gt_6m"]) is True
    assert bool(row["slip_1y_gt_12m"]) is False  # strict greater than
    later = out.loc[("P_GROW", pd.Timestamp("2013-09-30"))]
    assert later["slip_1y_months"] == pytest.approx(0.0)
    assert bool(later["slip_1y_gt_6m"]) is False


def test_rebaselining_is_flagged_from_the_year_t_narrative(panel):
    out = add_outcomes(panel).set_index(["project_key", "snapshot_date"])
    assert bool(out.loc[("P_REBASE", pd.Timestamp("2022-03-31"))]["rebaseline_mentioned_t"])
    assert not bool(out.loc[("P_GROW", pd.Timestamp("2012-09-30"))]["rebaseline_mentioned_t"])


def test_outcomes_never_read_the_year_t_row_of_another_project(panel):
    # Two projects share a snapshot; neither may pick up the other's value.
    out = add_outcomes(panel).set_index(["project_key", "snapshot_date"])
    assert out.loc[("P_GAP", pd.Timestamp("2012-09-30"))]["wlc_next"] is None or pd.isna(
        out.loc[("P_GAP", pd.Timestamp("2012-09-30"))]["wlc_next"]
    )
    assert out.loc[("P_GROW", pd.Timestamp("2012-09-30"))]["wlc_next"] == 120.0


def test_a_project_whose_department_published_nothing_has_no_exit_outcome():
    """A publication gap is not a departure. The FCO's 2020 publication is
    missing from the gov.uk collection, and counting its projects as exits
    invented four departures out of a missing file.
    """
    frame = pd.DataFrame(
        [
            _row("Atlas", "2018-09-30", dca="Amber", scale="five_point", dept="FCO"),
            # Another department publishes at the next snapshot, so the series
            # itself is fine; only the FCO is missing.
            _row("Other", "2018-09-30", dca="Amber", scale="five_point", dept="MOD"),
            _row("Other", "2019-09-30", dca="Amber", scale="five_point", dept="MOD"),
        ]
    )
    out = add_outcomes(frame).set_index(["project_key", "snapshot_date"])
    atlas = out.loc[("Atlas", pd.Timestamp("2018-09-30"))]
    assert pd.isna(atlas["absent_next"])
    assert pd.isna(atlas["permanent_exit_next"])
    assert atlas["department_published_next"] is False or not atlas[
        "department_published_next"
    ]


def test_a_project_absent_from_a_snapshot_its_department_did_publish_has_left():
    frame = pd.DataFrame(
        [
            _row("Gone", "2018-09-30", dca="Amber", scale="five_point", dept="MOD"),
            _row("Stays", "2018-09-30", dca="Amber", scale="five_point", dept="MOD"),
            _row("Stays", "2019-09-30", dca="Amber", scale="five_point", dept="MOD"),
        ]
    )
    out = add_outcomes(frame).set_index(["project_key", "snapshot_date"])
    gone = out.loc[("Gone", pd.Timestamp("2018-09-30"))]
    assert bool(gone["absent_next"]) is True
    assert bool(gone["permanent_exit_next"]) is True


def test_a_project_that_moved_department_has_not_left():
    """DECC was abolished in 2016 and published nothing afterwards. Its projects
    continued under BEIS, and presence is decided by the project key, not by
    whether the old department still exists.
    """
    frame = pd.DataFrame(
        [
            _row("Urenco", "2015-09-30", dca="Amber", scale="five_point",
                 dept="DECC/DESNZ"),
            _row("Urenco", "2016-09-30", dca="Amber", scale="five_point",
                 dept="BEIS/DBT"),
        ]
    )
    out = add_outcomes(frame).set_index(["project_key", "snapshot_date"])
    row = out.loc[("Urenco", pd.Timestamp("2015-09-30"))]
    assert bool(row["absent_next"]) is False
    assert bool(row["permanent_exit_next"]) is False


def test_the_price_base_break_is_flagged_on_every_horizon():
    """The March 2026 file is in 2024/25 real prices. A one-step flag left the
    two-year growth from March 2024 comparing a nominal figure with a real one.
    """
    frame = pd.DataFrame(
        [
            _row("P", "2024-03-31", dca="Amber", scale="three_point", wlc=100.0),
            _row("P", "2025-03-31", dca="Amber", scale="three_point", wlc=110.0),
            _row("P", "2026-03-31", dca="Amber", scale="three_point", wlc=120.0),
        ]
    )
    out = add_outcomes(frame).set_index(["project_key", "snapshot_date"])
    at_2024 = out.loc[("P", pd.Timestamp("2024-03-31"))]
    at_2025 = out.loc[("P", pd.Timestamp("2025-03-31"))]
    at_2026 = out.loc[("P", pd.Timestamp("2026-03-31"))]
    # One year from March 2025 lands on the real-prices file.
    assert bool(at_2025["wlc_growth_price_base_break"]) is True
    assert bool(at_2024["wlc_growth_price_base_break"]) is False
    # Two years from March 2024 lands on it too.
    assert bool(at_2024["wlc_growth_2y_price_base_break"]) is True
    # And the real-prices row itself, for growth against the first baseline.
    assert bool(at_2026["wlc_growth_vs_first_price_base_break"]) is True
    assert bool(at_2024["wlc_growth_vs_first_price_base_break"]) is False


def test_a_units_error_is_excluded_from_the_cost_outcomes():
    """HM Treasury published a whole-life cost of 59,173,700 in a column headed
    GBP million. It is flagged and kept out of the ratios, not corrected.
    """
    frame = pd.DataFrame(
        [
            _row("ELPS", "2012-09-30", dca="Amber/Red", scale="five_point",
                 wlc=59173700.0, dept="HMT"),
            _row("ELPS", "2013-09-30", dca="Amber/Red", scale="five_point",
                 wlc=58.0, dept="HMT"),
        ]
    )
    out = add_outcomes(frame).set_index(["project_key", "snapshot_date"])
    row = out.loc[("ELPS", pd.Timestamp("2012-09-30"))]
    assert bool(row["wlc_implausible"]) is True
    assert pd.isna(row["wlc_growth_1y"])


def test_a_growth_ratio_is_never_taken_across_a_sign_change():
    """Two DfT rail franchising rows publish a negative whole-life cost, net of
    the premium train operators pay. A ratio across that is not a growth rate.
    """
    frame = pd.DataFrame(
        [
            _row("Rail", "2015-09-30", dca="Amber", scale="five_point",
                 wlc=1036.3, dept="DFT"),
            _row("Rail", "2016-09-30", dca="Amber", scale="five_point",
                 wlc=-7169.2, dept="DFT"),
        ]
    )
    out = add_outcomes(frame).set_index(["project_key", "snapshot_date"])
    assert pd.isna(out.loc[("Rail", pd.Timestamp("2015-09-30"))]["wlc_growth_1y"])
