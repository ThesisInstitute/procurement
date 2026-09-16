"""Award-time features, including strictly as-of buyer and bidder history.

Every history feature is evaluated at the tender's own `tenderPeriod.startDate`
and counts only events *dated before* that moment.  A contract signed before
the cutoff that is extended after it therefore lands in the denominator and not
the numerator, which is exactly what a forecaster standing at the cutoff would
see.  Rates are shrunk toward the as-of global rate so that a bidder with one
prior win does not enter the model at 0 or 1.

The feature matrix is deliberately split in two: a lot block that does not
depend on who won, and a bidder block (price and history).  Experiment 2 keeps
the lot block fixed and swaps the bidder block, which is what "score this lot
as if that bidder had won" means.
"""

from __future__ import annotations

import bisect
from collections import defaultdict

import numpy as np
import pandas as pd

from src.times import to_seconds, to_utc

SHRINK_K = 5.0

LOT_CATEGORICAL = ["method", "cpv_division", "region", "main_category", "buyer_kind"]
BUYER_HISTORY = ["buyer_prior_lots_log", "buyer_prior_ext_rate"]
LOT_NUMERIC = [
    "log_value",
    "n_bids_lot",
    "n_lots",
    "bid_cv",
    "bid_spread",
    "start_month",
] + BUYER_HISTORY
# The bidder block splits in two on purpose: what the bidder bid on this lot,
# and who the bidder is. Separating them is the whole question.
BIDDER_PRICE = [
    "bidder_discount",
    "bidder_is_lowest",
    "bidder_rank_frac",
]
BIDDER_HISTORY = [
    "bidder_prior_bids_log",
    "bidder_prior_wins_log",
    "bidder_prior_win_rate",
    "bidder_prior_ext_rate",
    "bidder_prior_mean_discount",
]
BIDDER_NUMERIC = BIDDER_PRICE + BIDDER_HISTORY


def _ts(series: pd.Series) -> np.ndarray:
    """ISO strings to float seconds since the epoch, NaN when missing."""
    return to_seconds(series)


class AsOfHistory:
    """Counts of dated events per entity, queryable strictly before a cutoff."""

    def __init__(self) -> None:
        self._events: dict[str, list[float]] = defaultdict(list)
        self._all: list[float] = []
        self._sorted = False

    def add(self, key: str | None, when: float) -> None:
        if key is None or not np.isfinite(when):
            return
        self._events[key].append(when)
        self._all.append(when)

    def finalise(self) -> None:
        for v in self._events.values():
            v.sort()
        self._all.sort()
        self._sorted = True

    def count(self, key: str | None, cutoff: float) -> int:
        if not self._sorted:
            raise RuntimeError("call finalise() first")
        if key is None or not np.isfinite(cutoff):
            return 0
        v = self._events.get(key)
        return 0 if v is None else bisect.bisect_left(v, cutoff)

    def total(self, cutoff: float) -> int:
        if not np.isfinite(cutoff):
            return 0
        return bisect.bisect_left(self._all, cutoff)


class SumHistory(AsOfHistory):
    """Like AsOfHistory but also accumulates a value per event (for means)."""

    def __init__(self) -> None:
        super().__init__()
        self._vals: dict[str, list[float]] = defaultdict(list)

    def add_value(self, key: str | None, when: float, value: float) -> None:
        if key is None or not np.isfinite(when) or not np.isfinite(value):
            return
        self._events[key].append(when)
        self._vals[key].append(value)
        self._all.append(when)

    def finalise(self) -> None:
        for key, v in self._events.items():
            order = np.argsort(np.asarray(v), kind="stable")
            self._events[key] = list(np.asarray(v)[order])
            self._vals[key] = list(np.asarray(self._vals[key])[order])
        self._all.sort()
        self._sorted = True

    def mean(self, key: str | None, cutoff: float) -> float:
        n = self.count(key, cutoff)
        if n == 0:
            return float("nan")
        return float(np.mean(self._vals[key][:n]))


def shrink(num: np.ndarray, den: np.ndarray, prior: np.ndarray, k: float = SHRINK_K) -> np.ndarray:
    prior = np.where(np.isfinite(prior), prior, 0.0)
    return (num + k * prior) / (den + k)


def build_history(lots: pd.DataFrame, bids: pd.DataFrame) -> dict[str, object]:
    """Index every dated event the as-of features need."""
    signed = _ts(lots["tc_dateSigned"].where(lots["tc_dateSigned"].notna(), lots["award_end"]))
    ext = _ts(lots["first_duration_change_date"])
    start = _ts(lots["tender_start"])

    buyer_lots = AsOfHistory()
    buyer_ext = AsOfHistory()
    winner_wins = SumHistory()
    winner_ext = AsOfHistory()
    buyer_ids = lots["buyer_id"].to_numpy(dtype=object)
    winner_ids = lots["winner_id"].to_numpy(dtype=object)
    win_disc = pd.to_numeric(lots["winner_discount"], errors="coerce").to_numpy(dtype=float)
    for i in range(len(lots)):
        buyer_lots.add(buyer_ids[i], signed[i])
        winner_wins.add_value(winner_ids[i], signed[i], win_disc[i])
        if np.isfinite(ext[i]):
            buyer_ext.add(buyer_ids[i], ext[i])
            winner_ext.add(winner_ids[i], ext[i])
    for h in (buyer_lots, buyer_ext, winner_wins, winner_ext):
        h.finalise()

    bidder_bids = SumHistory()
    start_by_tender = dict(zip(lots["tender_id"], start))
    bt = np.array([start_by_tender.get(t, np.nan) for t in bids["tender_id"]])
    b_ids = bids["bidder_id"].to_numpy(dtype=object)
    b_disc = pd.to_numeric(bids["discount"], errors="coerce").to_numpy(dtype=float)
    for i in range(len(bids)):
        bidder_bids.add_value(b_ids[i], bt[i], b_disc[i])
    bidder_bids.finalise()

    return {
        "buyer_lots": buyer_lots,
        "buyer_ext": buyer_ext,
        "winner_wins": winner_wins,
        "winner_ext": winner_ext,
        "bidder_bids": bidder_bids,
    }


def lot_block(lots: pd.DataFrame, hist: dict[str, object]) -> pd.DataFrame:
    cutoff = _ts(lots["tender_start"])
    bl, be = hist["buyer_lots"], hist["buyer_ext"]
    n_prior = np.array([bl.count(b, c) for b, c in zip(lots["buyer_id"], cutoff)], dtype=float)
    n_ext = np.array([be.count(b, c) for b, c in zip(lots["buyer_id"], cutoff)], dtype=float)
    glob_den = np.array([bl.total(c) for c in cutoff], dtype=float)
    glob_num = np.array([be.total(c) for c in cutoff], dtype=float)
    glob = np.where(glob_den > 0, glob_num / np.maximum(glob_den, 1), np.nan)

    out = pd.DataFrame(index=lots.index)
    for c in LOT_CATEGORICAL:
        out[c] = lots[c].astype("string").fillna("missing").astype("category")
    out["log_value"] = np.log1p(lots["lot_expected_value"].clip(lower=0))
    out["n_bids_lot"] = lots["n_bids_lot"].astype(float)
    out["n_lots"] = lots["n_lots"].astype(float)
    out["bid_cv"] = lots["bid_cv"].astype(float)
    out["bid_spread"] = lots["bid_spread"].astype(float)
    # Local month, not UTC: a tender opening just after midnight Kyiv time
    # belongs to that day's month, and this feature is about seasonality.
    out["start_month"] = (
        to_utc(lots["tender_start"]).dt.tz_convert("Europe/Kyiv").dt.month.astype(float)
    )
    out["buyer_prior_lots_log"] = np.log1p(n_prior)
    out["buyer_prior_ext_rate"] = shrink(n_ext, n_prior, glob)
    return out


def bidder_block(
    bidder_ids: pd.Series,
    cutoff_iso: pd.Series,
    discount: pd.Series,
    is_lowest: pd.Series,
    rank_frac: pd.Series,
    hist: dict[str, object],
) -> pd.DataFrame:
    cutoff = _ts(cutoff_iso)
    ww, we, bb = hist["winner_wins"], hist["winner_ext"], hist["bidder_bids"]
    wins = np.array([ww.count(b, c) for b, c in zip(bidder_ids, cutoff)], dtype=float)
    exts = np.array([we.count(b, c) for b, c in zip(bidder_ids, cutoff)], dtype=float)
    subs = np.array([bb.count(b, c) for b, c in zip(bidder_ids, cutoff)], dtype=float)
    mdis = np.array([bb.mean(b, c) for b, c in zip(bidder_ids, cutoff)], dtype=float)
    g_den = np.array([ww.total(c) for c in cutoff], dtype=float)
    g_num = np.array([we.total(c) for c in cutoff], dtype=float)
    glob = np.where(g_den > 0, g_num / np.maximum(g_den, 1), np.nan)
    g_wr_den = np.array([bb.total(c) for c in cutoff], dtype=float)
    glob_wr = np.where(g_wr_den > 0, g_den / np.maximum(g_wr_den, 1), np.nan)

    out = pd.DataFrame(index=bidder_ids.index)
    out["bidder_discount"] = discount.astype(float).to_numpy()
    out["bidder_is_lowest"] = is_lowest.astype(float).to_numpy()
    out["bidder_rank_frac"] = rank_frac.astype(float).to_numpy()
    out["bidder_prior_bids_log"] = np.log1p(subs)
    out["bidder_prior_wins_log"] = np.log1p(wins)
    out["bidder_prior_win_rate"] = shrink(wins, subs, glob_wr)
    out["bidder_prior_ext_rate"] = shrink(exts, wins, glob)
    out["bidder_prior_mean_discount"] = mdis
    return out


def winner_bidder_block(lots: pd.DataFrame, hist: dict[str, object]) -> pd.DataFrame:
    rank_frac = np.where(
        lots["n_bids_lot"].to_numpy() > 1,
        (lots["winner_rank"].to_numpy() - 1.0) / (lots["n_bids_lot"].to_numpy() - 1.0),
        0.0,
    )
    return bidder_block(
        lots["winner_id"],
        lots["tender_start"],
        lots["winner_discount"],
        lots["winner_is_lowest"],
        pd.Series(rank_frac, index=lots.index),
        hist,
    )


def assemble(lot: pd.DataFrame, bidder: pd.DataFrame | None) -> pd.DataFrame:
    if bidder is None:
        return lot.copy()
    return pd.concat([lot, bidder], axis=1)
