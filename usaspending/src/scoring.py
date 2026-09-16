"""Proper scoring rules and calibration diagnostics.

All functions are pure and take numpy arrays, so they are tested directly on
small synthetic fixtures in usaspending/tests/test_scoring.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def brier_score(y: np.ndarray, p: np.ndarray) -> float:
    """Mean squared error of a probability forecast against a 0/1 outcome."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    if y.size == 0:
        return float("nan")
    return float(np.mean((p - y) ** 2))


def brier_skill_score(y: np.ndarray, p: np.ndarray, p_ref: float | np.ndarray) -> float:
    """1 - BS(forecast) / BS(reference). Positive means better than reference.

    p_ref is normally the training-period base rate, supplied as a scalar so the
    reference forecast uses no test-period information.
    """
    y = np.asarray(y, dtype=float)
    bs = brier_score(y, p)
    ref = np.full_like(y, p_ref, dtype=float) if np.isscalar(p_ref) else np.asarray(p_ref, dtype=float)
    bs_ref = brier_score(y, ref)
    if bs_ref == 0:
        return float("nan")
    return float(1.0 - bs / bs_ref)


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Area under the ROC curve via the rank (Mann-Whitney) identity.

    Ties in p receive average ranks, which is the standard tie correction.
    Returns nan when the outcome has only one class.
    """
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    n_pos = float(np.sum(y == 1))
    n_neg = float(np.sum(y == 0))
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), dtype=float)
    sorted_p = p[order]
    i = 0
    while i < len(sorted_p):
        j = i
        while j + 1 < len(sorted_p) and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        ranks[order[i:j + 1]] = avg
        i = j + 1
    sum_pos = float(np.sum(ranks[y == 1]))
    return float((sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def calibration_table(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Reliability table on fixed-width probability bins [0,0.1),...,[0.9,1.0]."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        rows.append({
            "bin": f"[{edges[b]:.1f},{edges[b+1]:.1f})",
            "n": int(m.sum()),
            "mean_forecast": float(np.mean(p[m])) if m.any() else float("nan"),
            "observed_rate": float(np.mean(y[m])) if m.any() else float("nan"),
        })
    return pd.DataFrame(rows)


def calibration_error(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> float:
    """Expected calibration error: n-weighted mean |observed - forecast|."""
    tab = calibration_table(y, p, n_bins)
    tab = tab[tab["n"] > 0]
    if tab.empty:
        return float("nan")
    w = tab["n"].to_numpy(dtype=float)
    gap = np.abs(tab["observed_rate"].to_numpy() - tab["mean_forecast"].to_numpy())
    return float(np.sum(w * gap) / np.sum(w))


def murphy_decomposition(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> dict:
    """Brier = reliability - resolution + uncertainty, on binned forecasts."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    n = len(y)
    if n == 0:
        return {"reliability": float("nan"), "resolution": float("nan"),
                "uncertainty": float("nan")}
    ybar = float(np.mean(y))
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    rel = res = 0.0
    for b in range(n_bins):
        m = idx == b
        nb = int(m.sum())
        if nb == 0:
            continue
        pb = float(np.mean(p[m]))
        yb = float(np.mean(y[m]))
        rel += nb * (pb - yb) ** 2
        res += nb * (yb - ybar) ** 2
    return {"reliability": rel / n, "resolution": res / n,
            "uncertainty": ybar * (1 - ybar)}


def pinball_loss(y: np.ndarray, q: np.ndarray, tau: float) -> float:
    """Quantile (pinball) loss at level tau for a point prediction q."""
    y = np.asarray(y, dtype=float)
    q = np.asarray(q, dtype=float)
    if y.size == 0:
        return float("nan")
    d = y - q
    return float(np.mean(np.maximum(tau * d, (tau - 1.0) * d)))


def mae(y: np.ndarray, yhat: np.ndarray) -> float:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    if y.size == 0:
        return float("nan")
    return float(np.mean(np.abs(y - yhat)))
