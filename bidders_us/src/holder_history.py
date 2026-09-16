"""As-of history of a holder, a vehicle, or a holder within a vehicle.

The as-of rule is the one in usaspending/src/panel.py add_history_features:
the count of prior events uses events whose base date is strictly before the
query date, and the outcome mean uses only events whose horizon had already
closed by the query date, that is base_date + h months <= query date. The
binary-search implementation is copied from usaspending/src/panel.py
_asof_group_stats with one addition, as the brief allows for a variant: it
also returns the number of resolved events with a non-null value, so that a
holder with three prior orders none of which had resolved is distinguishable
from one with none.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def asof_group_stats(event_group: pd.Series, event_date: pd.Series, event_value: pd.Series,
                     q_group: pd.Series, q_date: pd.Series, strict: bool
                     ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-group count, valid count and mean of events dated before each query date.

    strict=True uses event_date < q_date; strict=False uses event_date <= q_date.
    Returns (count_of_events, count_of_events_with_a_value, mean_of_values).
    """
    ev = pd.DataFrame({"g": event_group.to_numpy(),
                       "d": pd.to_datetime(event_date).to_numpy(),
                       "v": pd.to_numeric(event_value, errors="coerce").to_numpy(dtype=float)})
    ev = ev[pd.notna(ev["d"]) & pd.notna(ev["g"])].sort_values(["g", "d"], kind="mergesort")
    n_q = len(q_group)
    counts = np.zeros(n_q, dtype=float)
    ns = np.zeros(n_q, dtype=float)
    sums = np.full(n_q, np.nan, dtype=float)
    by_group = {}
    for g, blk in ev.groupby("g", sort=False):
        d = blk["d"].to_numpy()
        v = blk["v"].to_numpy(dtype=float)
        valid = ~np.isnan(v)
        cum_v = np.concatenate([[0.0], np.cumsum(np.where(valid, v, 0.0))])
        cum_n = np.concatenate([[0.0], np.cumsum(valid.astype(float))])
        by_group[g] = (d, cum_v, cum_n)
    qg = q_group.to_numpy()
    qd = pd.to_datetime(q_date).to_numpy()
    side = "left" if strict else "right"
    for i in range(n_q):
        entry = by_group.get(qg[i])
        if entry is None or pd.isna(qd[i]) or pd.isna(qg[i]):
            continue
        d, cum_v, cum_n = entry
        j = int(np.searchsorted(d, qd[i], side=side))
        counts[i] = j
        ns[i] = cum_n[j]
        sums[i] = cum_v[j]
    with np.errstate(invalid="ignore", divide="ignore"):
        means = np.where(ns > 0, sums / np.where(ns > 0, ns, 1.0), np.nan)
    return counts, ns, means


def asof_history(events: pd.DataFrame, queries: pd.DataFrame, h_months: int,
                 group_col: str = "group", event_date_col: str = "base_date",
                 value_col: str = "value", q_date_col: str = "date") -> pd.DataFrame:
    """Prior count, resolved count and resolved mean for every query row.

    events: one row per prior award with its group, base date and outcome at
    h_months (null when the outcome is unknown). queries: one row per award to
    describe, with its group and base date. A query award that is itself in
    `events` is never counted for itself: its base date is not strictly before
    itself, and its own resolution date is after its own base date.
    """
    resolved = pd.to_datetime(events[event_date_col]) + pd.DateOffset(months=h_months)
    ones = pd.Series(np.ones(len(events)), index=events.index)
    prior, _, _ = asof_group_stats(events[group_col], events[event_date_col], ones,
                                   queries[group_col], queries[q_date_col], strict=True)
    _, n_res, mean = asof_group_stats(events[group_col], resolved, events[value_col],
                                      queries[group_col], queries[q_date_col], strict=False)
    return pd.DataFrame({"prior_count": prior, "resolved_count": n_res,
                         "resolved_rate": mean}, index=queries.index)
