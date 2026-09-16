"""Scoring functions for orders grouped by vehicle and holder. Pure, tested.

within_vehicle_cross_holder_auc: the probability that a slipped test order
under a vehicle is ranked above a non-slipped test order under the SAME
vehicle from a DIFFERENT holder. Computed with the rank-sum identity: the
numerator and denominator of the ordinary AUC over a vehicle's orders, minus
the same quantities over each holder's own orders, pooled across vehicles.
Restricting the ranking to a subset does not change any pairwise comparison
inside it, so the subtraction is exact, including for ties.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import rankdata


def rank_numerator(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """Sum over (positive, negative) pairs of [p_pos > p_neg] + 0.5[tie], and the pair count."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    n_pos = float(np.sum(y == 1))
    n_neg = float(np.sum(y == 0))
    if n_pos == 0 or n_neg == 0:
        return 0.0, 0.0
    r = rankdata(p, method="average")
    return float(r[y == 1].sum() - n_pos * (n_pos + 1) / 2.0), n_pos * n_neg


def within_vehicle_cross_holder_auc(df: pd.DataFrame, y_col: str, p_col: str,
                                    vehicle_col: str = "vehicle", holder_col: str = "holder") -> dict:
    d = df.dropna(subset=[y_col, p_col, vehicle_col, holder_col])
    num = den = 0.0
    n_vehicles = 0
    for _, blk in d.groupby(vehicle_col, sort=False):
        n_v, d_v = rank_numerator(blk[y_col].to_numpy(), blk[p_col].to_numpy())
        if d_v == 0:
            continue
        for _, hb in blk.groupby(holder_col, sort=False):
            n_h, d_h = rank_numerator(hb[y_col].to_numpy(), hb[p_col].to_numpy())
            n_v -= n_h
            d_v -= d_h
        if d_v > 0:
            num += n_v
            den += d_v
            n_vehicles += 1
    return {"auc": num / den if den > 0 else float("nan"), "n_pairs": float(den),
            "n_vehicles": int(n_vehicles), "n_orders": int(len(d))}


def holder_rate_table(df: pd.DataFrame, y_col: str, split_col: str = "split",
                      vehicle_col: str = "vehicle", holder_col: str = "holder",
                      min_train: int = 3, min_test: int = 3, resid_col: str | None = None) -> pd.DataFrame:
    """Per (vehicle, holder): slip rate in train and in test, with counts.

    If resid_col is given, its mean is carried too (the residual against a
    contract-shape forecast, the "given the contract" version of the rate).
    """
    d = df.dropna(subset=[y_col, vehicle_col, holder_col])
    agg = {"n": (y_col, "size"), "rate": (y_col, "mean")}
    if resid_col:
        agg["resid"] = (resid_col, "mean")
    tr = d[d[split_col] == "train"].groupby([vehicle_col, holder_col]).agg(**agg)
    te = d[d[split_col] == "test"].groupby([vehicle_col, holder_col]).agg(**agg)
    t = tr.join(te, lsuffix="_train", rsuffix="_test", how="inner")
    return t[(t["n_train"] >= min_train) & (t["n_test"] >= min_test)]


def _spearman(x, y) -> float:
    x = pd.Series(np.asarray(x, dtype=float)).rank()
    y = pd.Series(np.asarray(y, dtype=float)).rank()
    if x.nunique() < 2 or y.nunique() < 2:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def within_vehicle_spearman(table: pd.DataFrame, xcol: str, ycol: str, wcol: str = "n_test",
                            min_holders: int = 3) -> dict:
    """Spearman between x and y across holders, per vehicle, averaged with weights.

    Vehicles with fewer than min_holders holders in the table are skipped. The
    average is weighted by the vehicle's total of wcol (test orders of the
    holders in the table). A pooled version demeans x and y within vehicle and
    takes the wcol-weighted Pearson correlation of the demeaned values.
    """
    rows = []
    for v, blk in table.groupby(level=0, sort=False):
        if len(blk) < min_holders:
            continue
        rho = _spearman(blk[xcol], blk[ycol])
        if np.isfinite(rho):
            rows.append((v, rho, float(blk[wcol].sum()), len(blk)))
    if not rows:
        return {"n_vehicles": 0, "weighted_mean": float("nan"), "unweighted_mean": float("nan")}
    r = pd.DataFrame(rows, columns=["vehicle", "rho", "w", "n_holders"])
    keep = table.index.get_level_values(0).isin(r["vehicle"])
    t = table[keep]
    w = t[wcol].to_numpy(dtype=float)
    # Demean within vehicle with the SAME weights the correlation uses, so the
    # demeaned values have weighted mean zero and the uncentred formula below
    # is the weighted Pearson correlation of the within-vehicle deviations.
    wx = (t[xcol] * t[wcol]).groupby(level=0).transform("sum") / t[wcol].groupby(level=0).transform("sum")
    wy = (t[ycol] * t[wcol]).groupby(level=0).transform("sum") / t[wcol].groupby(level=0).transform("sum")
    xw, yw = (t[xcol] - wx).to_numpy(), (t[ycol] - wy).to_numpy()
    pooled = float(np.sum(w * xw * yw) / np.sqrt(np.sum(w * xw ** 2) * np.sum(w * yw ** 2))) \
        if np.sum(w * xw ** 2) > 0 and np.sum(w * yw ** 2) > 0 else float("nan")
    return {"n_vehicles": int(len(r)), "n_holder_rows": int(len(t)),
            "weighted_mean": float(np.average(r["rho"], weights=r["w"])),
            "unweighted_mean": float(r["rho"].mean()),
            "share_positive": float((r["rho"] > 0).mean()),
            "pooled_within_vehicle_weighted_pearson": pooled}


def holder_gaps(table: pd.DataFrame) -> pd.DataFrame:
    """Per vehicle: realised best-minus-worst test gap, and the gap recovered by ranking on train.

    oracle_gap     max minus min of rate_test across the vehicle's holders.
    recovered_gap  rate_test of the holder with the highest rate_train minus
                   rate_test of the holder with the lowest rate_train. At
                   either end a tie in rate_train goes to the holder with the
                   larger n_train (the better-established record), then to
                   the holder label, so the result is deterministic.
    """
    rows = []
    for v, blk in table.groupby(level=0, sort=False):
        if len(blk) < 2:
            continue
        b = blk.reset_index()
        hcol = b.columns[1]
        low = b.sort_values(["rate_train", "n_train", hcol], ascending=[True, False, True]).iloc[0]
        high = b.sort_values(["rate_train", "n_train", hcol], ascending=[False, False, True]).iloc[0]
        rows.append({"vehicle": v, "n_holders": int(len(b)),
                     "oracle_gap": float(b["rate_test"].max() - b["rate_test"].min()),
                     "recovered_gap": float(high["rate_test"] - low["rate_test"]),
                     "train_gap": float(high["rate_train"] - low["rate_train"]),
                     "n_test_orders": int(b["n_test"].sum())})
    return pd.DataFrame(rows)


def permute_holders_within_vehicle(df: pd.DataFrame, holder_col: str, vehicle_col: str,
                                   mask: np.ndarray, rng: np.random.Generator) -> pd.Series:
    """Shuffle holder labels among the rows selected by mask, within each vehicle."""
    out = df[holder_col].copy()
    sub = df.loc[mask, [holder_col, vehicle_col]]
    lab = sub[holder_col].to_numpy(dtype=object)
    for _, idx in sub.groupby(vehicle_col, sort=False).indices.items():
        if len(idx) > 1:
            lab[idx] = lab[idx][rng.permutation(len(idx))]
    out.loc[mask] = lab
    return out
