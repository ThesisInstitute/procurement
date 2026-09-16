"""Proper scoring rules and calibration, written so they can be unit tested.

Brier skill score is always quoted against a stated reference probability; in
this workstream that reference is the base rate observed in the training
window, never the test window, so the skill number is achievable in advance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import rankdata


def brier(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    return float(np.mean((p - y) ** 2))


def brier_skill(y: np.ndarray, p: np.ndarray, reference: float) -> float:
    """1 - Brier(forecast) / Brier(constant `reference`)."""
    y = np.asarray(y, dtype=float)
    ref = np.full_like(y, float(reference), dtype=float)
    denom = brier(y, ref)
    if denom <= 0:
        return float("nan")
    return 1.0 - brier(y, p) / denom


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Rank AUC via the Mann-Whitney statistic, with ties counted as half.

    This sits inside the permutation loops and is called thousands of times, so
    it ranks with `scipy.stats.rankdata` rather than building a pandas Series.
    """
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    pos_mask = y == 1
    n_pos = int(pos_mask.sum())
    n_neg = int((y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    keep = pos_mask | (y == 0)
    ranks = rankdata(p[keep])
    r_pos = float(ranks[pos_mask[keep]].sum())
    return float((r_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def log_loss(y: np.ndarray, p: np.ndarray, eps: float = 1e-9) -> float:
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Equal-count bins of the forecast, with the realised rate in each."""
    df = pd.DataFrame({"y": np.asarray(y, dtype=float), "p": np.asarray(p, dtype=float)})
    try:
        df["bin"] = pd.qcut(df["p"], bins, labels=False, duplicates="drop")
    except ValueError:
        df["bin"] = 0
    out = (
        df.groupby("bin")
        .agg(n=("y", "size"), mean_forecast=("p", "mean"), observed=("y", "mean"))
        .reset_index()
    )
    return out


def reliability_resolution(y: np.ndarray, p: np.ndarray, bins: int = 10) -> dict[str, float]:
    """Murphy decomposition of the Brier score on equal-count bins."""
    tab = calibration_table(y, p, bins)
    n = float(len(y))
    base = float(np.mean(y))
    rel = float(np.sum(tab["n"] * (tab["mean_forecast"] - tab["observed"]) ** 2) / n)
    res = float(np.sum(tab["n"] * (tab["observed"] - base) ** 2) / n)
    return {
        "reliability": rel,
        "resolution": res,
        "uncertainty": base * (1 - base),
        "brier": brier(y, p),
    }


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation of the ranks, NaN when either side is constant."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return float("nan")
    ra = rankdata(a[ok])
    rb = rankdata(b[ok])
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def summarise(y: np.ndarray, p: np.ndarray, reference: float) -> dict[str, float]:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    return {
        "n": int(len(y)),
        "base_rate": float(np.mean(y)) if len(y) else float("nan"),
        "mean_forecast": float(np.mean(p)) if len(p) else float("nan"),
        "brier": brier(y, p),
        "bss": brier_skill(y, p, reference),
        "auc": auc(y, p),
        "log_loss": log_loss(y, p),
    }


def stratified_auc(y: np.ndarray, p: np.ndarray, strata: np.ndarray) -> dict[str, float]:
    """Mann-Whitney AUC pooled across strata, never comparing across them.

    A predictor can rank outcomes well overall only because it tracks which
    stratum a row is in.  Computing the AUC inside each stratum and pooling by
    each stratum's number of discordant pairs removes that entirely: the
    statistic only ever compares two rows that share a stratum.  Strata with no
    positive or no negative contribute nothing and are counted separately.
    """
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    s = pd.Series(np.asarray(strata, dtype=object))
    ok = np.isfinite(y) & np.isfinite(p) & s.notna().to_numpy()
    y, p, s = y[ok], p[ok], s[ok].to_numpy()
    if len(y) == 0:
        return {"auc": float("nan"), "strata_used": 0, "pairs": 0.0, "n": 0}
    num = 0.0
    den = 0.0
    used = 0
    codes, uniques = pd.factorize(pd.Series(s))
    for k in range(len(uniques)):
        m = codes == k
        ys, ps = y[m], p[m]
        n_pos = float((ys == 1).sum())
        n_neg = float((ys == 0).sum())
        if n_pos == 0 or n_neg == 0:
            continue
        a = auc(ys, ps)
        if not np.isfinite(a):
            continue
        w = n_pos * n_neg
        num += a * w
        den += w
        used += 1
    return {
        "auc": float(num / den) if den > 0 else float("nan"),
        "strata_used": used,
        "strata_total": int(len(uniques)),
        "pairs": den,
        "n": int(len(y)),
    }
