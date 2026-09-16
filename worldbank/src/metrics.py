"""Scoring functions. Pure, tested in tests/test_metrics.py."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


def _clean(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    ok = np.isfinite(y) & np.isfinite(p)
    return y[ok], p[ok], int((~ok).sum())


def brier(y, p) -> float:
    y, p, _ = _clean(y, p)
    return float(np.mean((p - y) ** 2))


def brier_skill_score(y, p, p_ref) -> float:
    """BSS = 1 - Brier(model) / Brier(reference). 0 = no skill over reference."""
    b = brier(y, p)
    b_ref = brier(y, p_ref)
    if b_ref == 0:
        return float("nan")
    return float(1.0 - b / b_ref)


def auc(y, p) -> float:
    y, p, _ = _clean(y, p)
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, p))


def calibration_table(y, p, n_bins: int = 10) -> pd.DataFrame:
    """Fixed-width probability bins on [0, 1].

    Bins are [0, 0.1), [0.1, 0.2), ..., [0.9, 1.0] with the TOP bin closed so a
    forecast of exactly 1.0 lands in it. Boundary assignment uses a rounded bin
    index rather than raw floating-point comparison, because 0.3, 0.6 and 0.7
    are not exactly representable and np.digitize places them one bin too low.
    Non-finite forecasts are excluded and counted in `n_dropped_non_finite`
    rather than silently swept into the last bin.
    """
    y, p, dropped = _clean(y, p)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    # round to 9 decimals so 0.30000000000000004 lands in [0.3, 0.4)
    idx = np.clip(np.floor(np.round(p * n_bins, 9)).astype(int), 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        closing = "]" if b == n_bins - 1 else ")"
        rows.append({
            "bin": f"[{edges[b]:.1f}, {edges[b + 1]:.1f}{closing}",
            "n": int(m.sum()),
            "mean_forecast": float(p[m].mean()) if m.any() else np.nan,
            "observed_rate": float(y[m].mean()) if m.any() else np.nan,
        })
    t = pd.DataFrame(rows)
    t["gap"] = t["observed_rate"] - t["mean_forecast"]
    t.attrs["n_dropped_non_finite"] = dropped
    return t


def within_group_auc(y, p, groups, min_n: int = 10, min_per_class: int = 2,
                     weight: str = "pairs") -> tuple[float, pd.DataFrame]:
    """Mean per-group AUC, weighted by group size or by comparable pairs.

    `weight="pairs"` weights each group by n_pos * n_neg, the number of
    positive-negative comparisons the AUC is actually an average over. That is
    the weighting under which the pooled and within-group quantities are
    commensurable. `weight="n"` weights by group row count instead; the two can
    differ materially when class balance varies across groups, so `summary`
    reports both.

    Only groups with at least `min_n` rows and `min_per_class` of each class can
    yield an AUC. Excluded groups are kept in the returned table with
    usable=False, and the share of rows they account for is recorded in
    `table.attrs["excluded_row_share"]`, because that exclusion is a selection
    on realised labels and must be visible.
    """
    if weight not in ("pairs", "n"):
        raise ValueError("weight must be 'pairs' or 'n'")
    yv, pv, _ = _clean(y, p)
    g = pd.Series(groups).astype(str).values
    if len(g) != len(np.asarray(y, dtype=float)):
        raise ValueError("groups must be the same length as y")
    ok = np.isfinite(np.asarray(y, dtype=float)) & np.isfinite(
        np.asarray(p, dtype=float))
    df = pd.DataFrame({"y": yv, "p": pv, "g": g[ok]})
    rows = []
    for grp, sub in df.groupby("g"):
        n = len(sub)
        pos = int(sub["y"].sum())
        neg = n - pos
        usable = (n >= min_n and pos >= min_per_class and neg >= min_per_class)
        rows.append({"group": grp, "n": n, "n_pos": pos, "n_neg": neg,
                     "pairs": pos * neg, "usable": usable,
                     "auc": auc(sub["y"], sub["p"]) if usable else np.nan})
    t = pd.DataFrame(rows).sort_values("n", ascending=False)
    u = t[t["usable"] & t["auc"].notna()]
    if not len(u):
        t.attrs["excluded_row_share"] = 1.0
        t.attrs["weighted_by_n"] = float("nan")
        t.attrs["weighted_by_pairs"] = float("nan")
        return float("nan"), t
    w_n = float((u["auc"] * u["n"]).sum() / u["n"].sum())
    w_p = (float((u["auc"] * u["pairs"]).sum() / u["pairs"].sum())
           if u["pairs"].sum() else float("nan"))
    t.attrs["excluded_row_share"] = float(
        1.0 - u["n"].sum() / max(int(t["n"].sum()), 1))
    t.attrs["weighted_by_n"] = w_n
    t.attrs["weighted_by_pairs"] = w_p
    return (w_p if weight == "pairs" else w_n), t


def cluster_bootstrap_ci(y, p, groups, stat="within_group_auc",
                         n_boot: int = 500, seed: int = 0,
                         weight: str = "pairs", alpha: float = 0.05):
    """Percentile CI, resampling GROUPS (not rows) with replacement.

    Projects in the same country are not independent, so a row bootstrap would
    understate the interval. Each drawn group is given a fresh identity, so a
    country drawn twice contributes twice as two separate groups rather than
    being merged into one larger one. Returns (point, lo, hi).

    Row indices per group are precomputed once; a draw then concatenates index
    arrays instead of rebuilding a frame per group, which is what makes running
    this for every rung of the ladder affordable.
    """
    if stat not in ("within_group_auc", "auc"):
        raise ValueError(stat)
    yv = np.asarray(y, dtype=float)
    pv = np.asarray(p, dtype=float)
    gv = pd.Series(groups).astype(str).values
    if not (len(yv) == len(pv) == len(gv)):
        raise ValueError("y, p and groups must be the same length")

    if stat == "within_group_auc":
        point, _ = within_group_auc(yv, pv, gv, weight=weight)
    else:
        point = auc(yv, pv)

    uniq, inverse = np.unique(gv, return_inverse=True)
    idx_by_group = [np.flatnonzero(inverse == i) for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(uniq), size=len(uniq))
        parts = [idx_by_group[i] for i in pick]
        rows = np.concatenate(parts) if parts else np.array([], dtype=int)
        if not len(rows):
            continue
        if stat == "within_group_auc":
            gids = np.repeat(np.arange(len(parts)), [len(q) for q in parts])
            v, _ = within_group_auc(yv[rows], pv[rows], gids, weight=weight)
        else:
            v = auc(yv[rows], pv[rows])
        if np.isfinite(v):
            draws.append(v)
    if not draws:
        return point, float("nan"), float("nan")
    lo, hi = np.percentile(draws, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(point), float(lo), float(hi)


def shrunk_cell_means(train: pd.DataFrame, target: pd.DataFrame,
                      cell_cols: list[str], y_col: str,
                      k: float = 10.0) -> tuple[np.ndarray, dict]:
    """Empirical-Bayes cell means: (n*cell_mean + k*global_mean) / (n + k).

    k is the prior weight in units of observations. Computed from TRAIN ONLY.
    Returns (predictions, diagnostics). The diagnostics distinguish a genuine
    unseen cell from a key-construction mismatch: both sides are stringified by
    the same helper, and `train_keys` / `target_keys` are reported so a silent
    all-fallback (which would make the baseline a constant without saying so) is
    visible instead of invisible.
    """
    global_mean = float(train[y_col].mean())

    def keys(df: pd.DataFrame) -> list[tuple]:
        return [tuple(str(v) for v in row)
                for row in df[cell_cols].astype(object).values]

    agg = train.groupby(cell_cols, dropna=False)[y_col].agg(["sum", "count"])
    agg["shrunk"] = (agg["sum"] + k * global_mean) / (agg["count"] + k)
    lookup = {}
    for idx, v in agg["shrunk"].items():
        idx = idx if isinstance(idx, tuple) else (idx,)
        lookup[tuple(str(x) for x in idx)] = float(v)

    tk = keys(target)
    hit = [kk in lookup for kk in tk]
    out = np.array([lookup.get(kk, global_mean) for kk in tk], dtype=float)
    diag = {
        "global_mean": global_mean,
        "n_target": len(tk),
        "n_hit": int(sum(hit)),
        "fallback_share": float(1.0 - (sum(hit) / len(tk))) if tk else float("nan"),
        "n_train_cells": int(len(lookup)),
        "n_target_cells": int(len(set(tk))),
        "n_target_cells_hit": int(len({kk for kk in tk if kk in lookup})),
    }
    return out, diag
