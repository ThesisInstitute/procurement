"""Resolve what happened to each project-year from the later snapshots.

For a project-year t the outcomes are read from the snapshots after t. Nothing
from t+1 or later is ever used as an input: the only thing carried forward is
the outcome itself. The year-t commentary is deliberately not used as a model
input either, even though it is contemporaneous with the rating.

Outcomes, all defined over the SNAPSHOT sequence rather than the calendar. The
portfolio moved from a September to a March reporting date between the
September 2019 and March 2021 snapshots, so that one step is 18 months and every
other is 12. `interval_months_1` records the true gap on every row and the
scoring restricts to 12-month steps where stated.

  wlc_growth_1y      baseline whole-life cost at t+1 over t, minus 1
  wlc_growth_2y      the same over two snapshots
  wlc_growth_vs_first  against the project's first observed baseline
  slip_1y_months     latest approved end date at t+1 minus at t, in months
  slip_2y_months     the same over two snapshots
  red_next           the published DCA at t+1 is Red
  red_or_amberred_next  Red or Amber/Red at t+1 (five-point snapshots only)
  worsened_next      the DCA at t+1 is a worse rating than at t, same scale
  absent_next        no row for the project in the t+1 snapshot
  permanent_exit_next  absent at t+1 and in every later snapshot

Run: .venv/bin/python -m gmpp.src.outcomes
"""
from __future__ import annotations

import re
import sys

import numpy as np
import pandas as pd

from .calendar_map import REAL_PRICE_SNAPSHOTS, interval_months, ordered_snapshots
from .paths import RESULTS_DIR
from .ratings import FIVE_POINT, THREE_POINT, rank

PANEL_PATH = RESULTS_DIR / "panel.csv"
OUT_PATH = RESULTS_DIR / "panel_outcomes.csv"

RATINGS = set(FIVE_POINT) | set(THREE_POINT)

# Growth and slip flags, as the workstream brief specifies.
WLC_GROWTH_FLAGS = (0.10, 0.25)
SLIP_FLAG_MONTHS = (6, 12)

_REBASELINE_RE = re.compile(r"rebaselin|re-baselin|re baselin|rebasing", re.I)


def months_between(a: pd.Timestamp, b: pd.Timestamp) -> float | None:
    """Whole-month difference b - a, using a 30.4375-day month.

    A calendar-month count would round a 29-day slip to one month and a 32-day
    slip to one month too; the average month length keeps the scale linear,
    which is what the 6-month and 12-month flags need.
    """
    if pd.isna(a) or pd.isna(b):
        return None
    return (b - a).days / 30.4375


def add_outcomes(panel: pd.DataFrame) -> pd.DataFrame:
    work = panel.copy()
    work["snapshot_date"] = pd.to_datetime(work["snapshot_date"])
    for col in ("start_date", "end_date"):
        work[col] = pd.to_datetime(work[col], errors="coerce")

    # Computed before the forward-looking index is built so it can be read
    # forward like any other field.
    narrative = (
        work["wlc_narrative"].fillna("").astype(str)
        + " || "
        + work["budget_narrative"].fillna("").astype(str)
        + " || "
        + work["schedule_narrative"].fillna("").astype(str)
    )
    work["rebaseline_mentioned_t"] = narrative.map(
        lambda s: bool(_REBASELINE_RE.search(s))
    )

    order = ordered_snapshots()
    index_of = {pd.Timestamp(d): i for i, d in enumerate(order)}
    work["snapshot_index"] = work["snapshot_date"].map(index_of)

    # Lookup of (project, snapshot index) -> row, for reading forward.
    keyed = work.set_index(["project_key", "snapshot_index"], drop=False)
    keyed = keyed[~keyed.index.duplicated(keep="first")]

    def forward(field: str, steps: int) -> pd.Series:
        idx = pd.MultiIndex.from_arrays(
            [work["project_key"], work["snapshot_index"] + steps]
        )
        return pd.Series(
            keyed[field].reindex(idx).to_numpy(), index=work.index, name=field
        )

    work["wlc_next"] = forward("wlc_baseline_gbp_m", 1)
    work["wlc_next2"] = forward("wlc_baseline_gbp_m", 2)
    work["end_date_next"] = pd.to_datetime(forward("end_date", 1), errors="coerce")
    work["end_date_next2"] = pd.to_datetime(forward("end_date", 2), errors="coerce")
    work["dca_next"] = forward("dca_published", 1)
    work["dca_next_rank"] = forward("dca_published_rank", 1)
    work["scale_next"] = forward("scale", 1)
    work["wlc_next_kind"] = forward("wlc_baseline_gbp_m_kind", 1)

    # Presence at later snapshots.
    #
    # A project is only observably absent if something covering its department
    # was published at that snapshot. Where a department published nothing, its
    # projects are unobservable rather than departed, and counting them as exits
    # invents departures out of a publication gap. The FCO is the clear case:
    # its 2020 publication is missing from the gov.uk collection, and before it
    # was recovered by searching gov.uk directly, four FCO projects looked as
    # though they had left the portfolio in September 2018.
    present = set(zip(work["project_key"], work["snapshot_index"]))
    last_index = len(order) - 1
    dept_published = set(zip(work["department_norm"], work["snapshot_index"]))

    def _covered(dept: object, index: int) -> bool:
        return (dept, index) in dept_published

    work["department_published_next"] = [
        None if i >= last_index else _covered(d, i + 1)
        for d, i in zip(work["department_norm"], work["snapshot_index"])
    ]
    def _absent_next(key: object, dept: object, i: int) -> bool | None:
        if i >= last_index:
            return None
        if (key, i + 1) in present:
            # Present, wherever it is reported. A project that moved department
            # has not left, and it is the project key that says so.
            return False
        # Genuinely not there. Only an absence from a snapshot the department
        # actually published is evidence of leaving.
        return None if not _covered(dept, i + 1) else True

    def _permanent_exit(key: object, dept: object, i: int) -> bool | None:
        if i >= last_index:
            return None
        later = range(i + 1, last_index + 1)
        if any((key, j) in present for j in later):
            return False
        if not any(_covered(dept, j) for j in later):
            return None
        return True

    work["absent_next"] = [
        _absent_next(k, d, i)
        for k, d, i in zip(
            work["project_key"], work["department_norm"], work["snapshot_index"]
        )
    ]
    work["permanent_exit_next"] = [
        _permanent_exit(k, d, i)
        for k, d, i in zip(
            work["project_key"], work["department_norm"], work["snapshot_index"]
        )
    ]

    # Snapshot spacing.
    work["interval_months_1"] = [
        None
        if i is None or i >= last_index
        else interval_months(order[int(i)], order[int(i) + 1])
        for i in work["snapshot_index"]
    ]
    work["interval_months_2"] = [
        None
        if i is None or i >= last_index - 1
        else interval_months(order[int(i)], order[int(i) + 2])
        for i in work["snapshot_index"]
    ]

    # --- whole-life cost growth ---------------------------------------------
    # Two kinds of published value cannot carry a growth ratio.
    #
    # Sign. Two project-years publish a NEGATIVE baseline whole-life cost, both
    # DfT rail franchising, where the narrative explains the figure is net of
    # the premium train operators pay the department. A ratio across a sign
    # change is not a growth rate, so a pair is used only when both ends are
    # strictly positive.
    #
    # Magnitude. One project-year, the September 2012 HM Treasury Equitable Life
    # Payment Scheme, publishes 59,173,700 in a column headed "Total budgeted
    # whole life costs (£million)". That is the figure in pounds, not millions:
    # the same row's own narrative says the scheme distributes "up to £1bi" and
    # its in-year budget cell reads 19,853,558 in a "(£million)" column. It is a
    # publisher units error, and the only one in the panel. The published value
    # is kept in the panel unaltered; it is flagged here and excluded from the
    # cost outcomes. The largest credible whole-life cost published anywhere in
    # the panel is 72,079 (Home Office asylum accommodation, March 2025), so the
    # threshold below separates the one bad row from every real one by a factor
    # of 2.8 on one side and 296 on the other.
    IMPLAUSIBLE_WLC_GBP_M = 200_000

    def usable_wlc(values: pd.Series) -> pd.Series:
        v = pd.to_numeric(values, errors="coerce")
        return v.where((v > 0) & (v < IMPLAUSIBLE_WLC_GBP_M))

    work["wlc_implausible"] = (
        pd.to_numeric(work["wlc_baseline_gbp_m"], errors="coerce")
        >= IMPLAUSIBLE_WLC_GBP_M
    )

    def growth(now: pd.Series, later: pd.Series) -> pd.Series:
        now_v = usable_wlc(now)
        later_v = usable_wlc(later)
        return later_v / now_v - 1.0

    work["wlc_growth_1y"] = growth(work["wlc_baseline_gbp_m"], work["wlc_next"])
    work["wlc_growth_2y"] = growth(work["wlc_baseline_gbp_m"], work["wlc_next2"])

    first_wlc = (
        work.sort_values("snapshot_index")
        .groupby("project_key")["wlc_baseline_gbp_m"]
        .transform("first")
    )
    work["wlc_first_observed"] = first_wlc
    work["wlc_growth_vs_first"] = growth(first_wlc, work["wlc_baseline_gbp_m"])

    # The March 2026 file is published in 2024/25 real prices while every other
    # file is nominal, so any step that lands on it mixes price bases and its
    # ratio is not a growth rate. One flag per horizon: the one-year step from
    # March 2025, the two-year step from March 2024, and the growth of the
    # March 2026 row itself against the project's first observed baseline.
    def _crosses_price_base(steps: int) -> pd.Series:
        return work["snapshot_index"].map(
            lambda i: (
                False
                if i is None or i + steps > last_index
                else order[int(i) + steps] in REAL_PRICE_SNAPSHOTS
            )
        )

    work["wlc_growth_price_base_break"] = _crosses_price_base(1)
    work["wlc_growth_2y_price_base_break"] = _crosses_price_base(2)
    work["wlc_growth_vs_first_price_base_break"] = work["snapshot_date"].dt.date.isin(
        REAL_PRICE_SNAPSHOTS
    )

    for threshold in WLC_GROWTH_FLAGS:
        name = f"wlc_growth_1y_gt_{int(threshold * 100)}"
        work[name] = np.where(
            work["wlc_growth_1y"].notna(), work["wlc_growth_1y"] > threshold, None
        )
        name2 = f"wlc_growth_2y_gt_{int(threshold * 100)}"
        work[name2] = np.where(
            work["wlc_growth_2y"].notna(), work["wlc_growth_2y"] > threshold, None
        )

    # --- schedule slip -------------------------------------------------------
    work["slip_1y_months"] = [
        months_between(a, b) for a, b in zip(work["end_date"], work["end_date_next"])
    ]
    work["slip_2y_months"] = [
        months_between(a, b) for a, b in zip(work["end_date"], work["end_date_next2"])
    ]
    for threshold in SLIP_FLAG_MONTHS:
        work[f"slip_1y_gt_{threshold}m"] = np.where(
            work["slip_1y_months"].notna(), work["slip_1y_months"] > threshold, None
        )
        work[f"slip_2y_gt_{threshold}m"] = np.where(
            work["slip_2y_months"].notna(), work["slip_2y_months"] > threshold, None
        )

    # --- next rating ---------------------------------------------------------
    next_is_rating = work["dca_next"].isin(RATINGS)
    five_next = work["scale_next"] == "five_point"
    same_scale = (work["scale"] == work["scale_next"]) & next_is_rating
    work["same_scale_next"] = same_scale
    # "Red at the next snapshot" only means the same thing when the next
    # snapshot uses the same scale. The March 2021 to March 2022 step crosses
    # the five-point to three-point change, where three-point Red absorbs part
    # of what used to be Amber/Red, so it is excluded from the rating outcomes.
    work["red_next"] = np.where(same_scale, work["dca_next"] == "Red", None)
    work["red_or_amberred_next"] = np.where(
        same_scale & five_next, work["dca_next"].isin(["Red", "Amber/Red"]), None
    )
    work["worsened_next"] = np.where(
        same_scale & work["dca_published_rank"].notna(),
        pd.to_numeric(work["dca_next_rank"], errors="coerce")
        > pd.to_numeric(work["dca_published_rank"], errors="coerce"),
        None,
    )
    # A project already on the worst rating cannot worsen, so including those
    # rows guarantees a sub-0.5 AUC for any ranking that puts them last. The
    # restricted version drops them and is the one to read.
    worst_rank = work["scale"].map({"five_point": 4.0, "three_point": 2.0})
    can_worsen = pd.to_numeric(work["dca_published_rank"], errors="coerce") < worst_rank
    work["worsened_next_excl_worst"] = np.where(
        same_scale & can_worsen & work["dca_published_rank"].notna(),
        pd.to_numeric(work["dca_next_rank"], errors="coerce")
        > pd.to_numeric(work["dca_published_rank"], errors="coerce"),
        None,
    )

    work["rebaseline_mentioned_next"] = forward("rebaseline_mentioned_t", 1)
    work["dca_reset_next"] = np.where(
        work["dca_next"].notna(), work["dca_next"] == "RESET", None
    )

    return work


def main() -> int:
    panel = pd.read_csv(PANEL_PATH)
    out = add_outcomes(panel)
    out.to_csv(OUT_PATH, index=False)
    print(f"{len(out)} project-years -> {OUT_PATH}")

    rated = out[out["dca_published"].isin(RATINGS)]
    cols = [
        "wlc_growth_1y_gt_10",
        "wlc_growth_1y_gt_25",
        "slip_1y_gt_6m",
        "slip_1y_gt_12m",
        "red_next",
        "worsened_next",
        "worsened_next_excl_worst",
        "absent_next",
        "permanent_exit_next",
    ]
    print("\nresolvable project-years and base rate, rated rows only:")
    rows = []
    for c in cols:
        s = pd.to_numeric(rated[c], errors="coerce")
        rows.append(
            {
                "outcome": c,
                "n_resolved": int(s.notna().sum()),
                "base_rate": round(float(s.mean()), 4) if s.notna().any() else None,
            }
        )
    print(pd.DataFrame(rows).to_string(index=False))

    print("\ncontinuous outcomes:")
    for c in ("wlc_growth_1y", "slip_1y_months"):
        s = pd.to_numeric(rated[c], errors="coerce").dropna()
        print(
            f"  {c}: n={len(s)} median={s.median():.4f} mean={s.mean():.4f} "
            f"p90={s.quantile(0.9):.4f}"
        )
    print("\nresolvable rows by snapshot (wlc_growth_1y):")
    print(
        rated.groupby(rated["snapshot_date"].astype(str).str[:10])
        .agg(
            n=("project_key", "size"),
            wlc_1y=("wlc_growth_1y", lambda s: int(s.notna().sum())),
            slip_1y=("slip_1y_months", lambda s: int(s.notna().sum())),
            red_next=("red_next", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
        )
        .to_string()
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
