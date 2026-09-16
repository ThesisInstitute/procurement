"""Proper scoring rules and skill statistics.

Pure functions over arrays so they can be tested on synthetic fixtures without
touching the panel. Nothing here knows about GMPP.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np


@dataclass(frozen=True)
class BrierDecomposition:
    """Murphy's three-term decomposition of the Brier score.

    With forecasts grouped into K bins of distinct forecast values,

        BS = reliability - resolution + uncertainty

    reliability  mean squared gap between a bin's forecast and the outcome rate
                 observed in that bin. Lower is better; 0 is perfect calibration.
    resolution   mean squared gap between a bin's observed rate and the overall
                 base rate. Higher is better; 0 means the forecast separates
                 nothing.
    uncertainty  the base rate's own variance, o(1-o). A property of the
                 outcome, not of the forecaster.
    """

    brier: float
    reliability: float
    resolution: float
    uncertainty: float
    base_rate: float
    n: int
    n_bins: int

    @property
    def skill_vs_base_rate(self) -> float:
        """Brier skill score against always forecasting the base rate.

        The base-rate forecast scores exactly `uncertainty`, so this is
        1 - BS/UNC, i.e. (resolution - reliability) / uncertainty.
        """
        if self.uncertainty == 0:
            return float("nan")
        return 1.0 - self.brier / self.uncertainty

    def as_dict(self) -> dict:
        out = asdict(self)
        out["skill_vs_base_rate"] = self.skill_vs_base_rate
        # Identity check: the three terms must reconstruct the score.
        out["decomposition_residual"] = (
            self.brier - (self.reliability - self.resolution + self.uncertainty)
        )
        return out


def brier_score(forecasts: np.ndarray, outcomes: np.ndarray) -> float:
    f = np.asarray(forecasts, dtype=float)
    o = np.asarray(outcomes, dtype=float)
    return float(np.mean((f - o) ** 2))


def brier_decomposition(
    forecasts: np.ndarray, outcomes: np.ndarray, bins: np.ndarray | None = None
) -> BrierDecomposition:
    """Decompose the Brier score.

    `bins` labels the grouping. When omitted the distinct forecast values are
    used, which is exact for a forecast that takes a handful of values, as a
    rating-implied probability does. With continuous forecasts pass explicit
    bins, because one observation per bin drives reliability to zero and
    resolution to the uncertainty by construction.
    """
    f = np.asarray(forecasts, dtype=float)
    o = np.asarray(outcomes, dtype=float)
    if f.shape != o.shape:
        raise ValueError("forecasts and outcomes must have the same shape")
    if f.size == 0:
        raise ValueError("no observations")
    keys = np.asarray(f if bins is None else bins)

    n = f.size
    base = float(np.mean(o))
    reliability = resolution = 0.0
    unique = np.unique(keys)
    for key in unique:
        mask = keys == key
        n_k = int(mask.sum())
        f_k = float(np.mean(f[mask]))
        o_k = float(np.mean(o[mask]))
        reliability += n_k * (f_k - o_k) ** 2
        resolution += n_k * (o_k - base) ** 2
    reliability /= n
    resolution /= n
    uncertainty = base * (1.0 - base)

    return BrierDecomposition(
        brier=brier_score(f, o),
        reliability=reliability,
        resolution=resolution,
        uncertainty=uncertainty,
        base_rate=base,
        n=n,
        n_bins=int(unique.size),
    )


def auc(scores: np.ndarray, outcomes: np.ndarray) -> float:
    """Area under the ROC curve, computed from ranks with ties averaged.

    `scores` should increase with the probability of the outcome. Returns NaN
    when either class is empty. Equivalent to the normalised Mann-Whitney U.
    """
    s = np.asarray(scores, dtype=float)
    o = np.asarray(outcomes, dtype=float)
    keep = ~(np.isnan(s) | np.isnan(o))
    s, o = s[keep], o[keep]
    n_pos = int((o == 1).sum())
    n_neg = int((o == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = _average_ranks(s)
    return float((ranks[o == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    sorted_values = values[order]
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and sorted_values[j + 1] == sorted_values[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rank correlation, ties averaged. NaN pairs are dropped."""
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    keep = ~(np.isnan(a) | np.isnan(b))
    a, b = a[keep], b[keep]
    if a.size < 3:
        return float("nan")
    ra, rb = _average_ranks(a), _average_ranks(b)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    denom = np.sqrt((ra**2).sum() * (rb**2).sum())
    if denom == 0:
        return float("nan")
    return float((ra * rb).sum() / denom)


def isotonic_fit(x: np.ndarray, y: np.ndarray) -> "IsotonicMap":
    """Pool-adjacent-violators isotonic regression of y on x, non-decreasing."""
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    keep = ~(np.isnan(a) | np.isnan(b))
    a, b = a[keep], b[keep]
    order = np.argsort(a, kind="mergesort")
    a, b = a[order], b[order]

    # Collapse ties in x first: the fitted value must be a function of x.
    xs: list[float] = []
    ys: list[float] = []
    ws: list[float] = []
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and a[j + 1] == a[i]:
            j += 1
        xs.append(float(a[i]))
        ys.append(float(np.mean(b[i : j + 1])))
        ws.append(float(j - i + 1))
        i = j + 1

    # Pool adjacent violators.
    k = 0
    while k < len(ys) - 1:
        if ys[k] <= ys[k + 1]:
            k += 1
            continue
        total_w = ws[k] + ws[k + 1]
        pooled = (ys[k] * ws[k] + ys[k + 1] * ws[k + 1]) / total_w
        ys[k] = pooled
        ws[k] = total_w
        del ys[k + 1], ws[k + 1], xs[k + 1]
        k = max(k - 1, 0)
    return IsotonicMap(np.array(xs), np.array(ys))


@dataclass(frozen=True)
class IsotonicMap:
    x: np.ndarray
    y: np.ndarray

    def predict(self, values: np.ndarray) -> np.ndarray:
        """Step-function prediction, clamped at the fitted range's ends."""
        v = np.asarray(values, dtype=float)
        idx = np.searchsorted(self.x, v, side="right") - 1
        idx = np.clip(idx, 0, len(self.y) - 1)
        out = self.y[idx]
        return np.where(np.isnan(v), np.nan, out)


def cluster_bootstrap_ci(
    statistic,
    *arrays,
    clusters,
    n_boot: int = 2000,
    seed: int = 20260915,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap that resamples CLUSTERS, not rows.

    Project-years of the same project across snapshots are not independent: the
    same project carries a similar rating and a similar trajectory year after
    year. Resampling rows treats each project-year as fresh information and
    produces intervals that are too narrow. This resamples whole projects with
    replacement and keeps every row of a drawn project, which is the standard
    correction.
    """
    rng = np.random.default_rng(seed)
    arrays = [np.asarray(a) for a in arrays]
    clusters = np.asarray(clusters)
    keys = np.unique(clusters)
    index_for = {k: np.flatnonzero(clusters == k) for k in keys}
    if keys.size == 0:
        return float("nan"), float("nan")
    draws = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        drawn = rng.choice(keys, size=keys.size, replace=True)
        idx = np.concatenate([index_for[k] for k in drawn])
        try:
            draws[i] = statistic(*[a[idx] for a in arrays])
        except Exception:  # noqa: BLE001 - a resample can be degenerate
            draws[i] = np.nan
    draws = draws[~np.isnan(draws)]
    if draws.size == 0:
        return float("nan"), float("nan")
    return (
        float(np.quantile(draws, alpha / 2)),
        float(np.quantile(draws, 1 - alpha / 2)),
    )


def bootstrap_ci(
    statistic, *arrays, n_boot: int = 2000, seed: int = 20260915, alpha: float = 0.05
) -> tuple[float, float]:
    """Percentile bootstrap interval for a statistic over paired arrays.

    The seed is fixed so every number in the report is reproducible.
    """
    rng = np.random.default_rng(seed)
    arrays = [np.asarray(a) for a in arrays]
    n = len(arrays[0])
    if n == 0:
        return float("nan"), float("nan")
    draws = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        try:
            draws[i] = statistic(*[a[idx] for a in arrays])
        except Exception:  # noqa: BLE001 - a resample can be degenerate
            draws[i] = np.nan
    draws = draws[~np.isnan(draws)]
    if draws.size == 0:
        return float("nan"), float("nan")
    return (
        float(np.quantile(draws, alpha / 2)),
        float(np.quantile(draws, 1 - alpha / 2)),
    )
