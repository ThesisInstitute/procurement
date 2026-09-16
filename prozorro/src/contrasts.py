"""Experiments 3 and 4: price-position contrasts and bid dispersion.

Experiment 3 contrasts lots where the cheapest live bid was disqualified and a
dearer bid won against lots where the cheapest bid won.  The two groups are not
comparable as they stand (disqualification is commoner in some sectors and
years), so the control group is reweighted onto the treated group's
CPV-division by year cell distribution before the difference is taken.  Cells
with no control lot are dropped and reported, because a standardised
difference that quietly discards treated rows is not a difference.

Experiment 4 bins the within-lot dispersion of bids and reads the winner's
extension rate off each bin.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rate_table(df: pd.DataFrame, by: str, labels: list[str]) -> pd.DataFrame:
    """Rate of each label within each level of `by`, with counts."""
    rows = []
    for level, g in df.groupby(by, observed=True, dropna=False):
        row = {by: level, "n_lots": len(g)}
        for lab in labels:
            s = g[lab]
            row[f"{lab}_n"] = int(s.notna().sum())
            row[f"{lab}_rate"] = float(s.mean()) if s.notna().any() else float("nan")
        rows.append(row)
    return pd.DataFrame(rows).sort_values(by).reset_index(drop=True)


def standardised_difference(
    treated: pd.DataFrame,
    control: pd.DataFrame,
    label: str,
    cell_keys: list[str],
    n_boot: int = 1000,
    seed: int = 20260916,
) -> dict[str, float]:
    """Treated rate minus control rate reweighted onto the treated cell mix."""
    t = treated[treated[label].notna()]
    c = control[control[label].notna()]
    if not len(t) or not len(c):
        return {"n_treated": len(t), "n_control": len(c)}

    def _stat(tt: pd.DataFrame, cc: pd.DataFrame) -> tuple[float, float, float, int, int]:
        tw = tt.groupby(cell_keys, observed=True)[label].agg(["mean", "size"])
        cw = cc.groupby(cell_keys, observed=True)[label].agg(["mean", "size"])
        joined = tw.join(cw, how="inner", lsuffix="_t", rsuffix="_c")
        if not len(joined):
            return float("nan"), float("nan"), float("nan"), 0, 0
        w = joined["size_t"] / joined["size_t"].sum()
        t_rate = float((joined["mean_t"] * w).sum())
        c_rate = float((joined["mean_c"] * w).sum())
        matched_t = int(joined["size_t"].sum())
        matched_c = int(joined["size_c"].sum())
        return t_rate, c_rate, t_rate - c_rate, matched_t, matched_c

    t_rate, c_rate, diff, matched_t, matched_c = _stat(t, c)
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    t_idx = np.arange(len(t))
    c_idx = np.arange(len(c))
    for i in range(n_boot):
        bt = t.iloc[rng.choice(t_idx, len(t), replace=True)]
        bc = c.iloc[rng.choice(c_idx, len(c), replace=True)]
        boots[i] = _stat(bt, bc)[2]
    boots = boots[np.isfinite(boots)]
    return {
        "label": label,
        "n_treated": int(len(t)),
        "n_control": int(len(c)),
        "n_treated_matched": matched_t,
        "n_control_matched": matched_c,
        "treated_rate_raw": float(t.mean(numeric_only=True)[label]),
        "control_rate_raw": float(c.mean(numeric_only=True)[label]),
        "treated_rate_matched": t_rate,
        "control_rate_standardised": c_rate,
        "difference": diff,
        "ci_lo": float(np.quantile(boots, 0.025)) if len(boots) else float("nan"),
        "ci_hi": float(np.quantile(boots, 0.975)) if len(boots) else float("nan"),
    }


def lowest_disqualified_contrast(
    lots: pd.DataFrame, labels: list[str], cell_keys: list[str] | None = None
) -> pd.DataFrame:
    """Lowest bid disqualified and a dearer bid won, versus lowest bid won."""
    cell_keys = cell_keys or ["cpv_division", "year"]
    eligible = lots[lots["n_bids_lot"] >= 2].copy()
    treated = eligible[
        eligible["lowest_disqualified"].fillna(False) & ~eligible["winner_is_lowest"].fillna(False)
    ]
    # The control is a clean "cheapest bid won" lot: if the cheapest bid was
    # also disqualified (a price tie at the minimum) the lot belongs to
    # neither group, because it is both treated and untreated at once.
    control = eligible[
        eligible["winner_is_lowest"].fillna(False) & ~eligible["lowest_disqualified"].fillna(False)
    ]
    rows = [standardised_difference(treated, control, lab, cell_keys) for lab in labels]
    return pd.DataFrame(rows)


def decile_table(lots: pd.DataFrame, value_col: str, labels: list[str], q: int = 10) -> pd.DataFrame:
    """Equal-count bins of `value_col` with the realised rate of each label."""
    df = lots[lots[value_col].notna()].copy()
    try:
        df["_bin"] = pd.qcut(df[value_col], q, labels=False, duplicates="drop")
    except ValueError:
        df["_bin"] = 0
    rows = []
    for b, g in df.groupby("_bin", observed=True):
        row = {
            "bin": int(b),
            "n_lots": len(g),
            f"{value_col}_min": float(g[value_col].min()),
            f"{value_col}_median": float(g[value_col].median()),
            f"{value_col}_max": float(g[value_col].max()),
        }
        for lab in labels:
            s = g[lab]
            row[f"{lab}_n"] = int(s.notna().sum())
            row[f"{lab}_rate"] = float(s.mean()) if s.notna().any() else float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


def dispersion_table(lots: pd.DataFrame, labels: list[str], bins: int = 6) -> pd.DataFrame:
    """Winner's outcome rates by within-lot bid dispersion (coefficient of variation)."""
    df = lots[lots["bid_cv"].notna() & (lots["n_bids_lot"] >= 2)]
    return decile_table(df, "bid_cv", labels, q=bins)


def icc_one_way(y: np.ndarray, groups: np.ndarray) -> dict[str, float]:
    """One-way random-effects intraclass correlation of `y` within `groups`.

    Model free, so it does not inherit any assumption from the gradient
    booster: it simply asks how much of the variance in the outcome sits
    between groups rather than within them.  With a binary outcome the ICC is
    still the ratio of between-group variance to total variance; it is bounded
    below by a small negative number rather than by zero, which is why a
    negative value is reported as it comes out rather than clipped.
    """
    y = np.asarray(y, dtype=float)
    g = pd.Series(np.asarray(groups, dtype=object))
    ok = np.isfinite(y) & g.notna().to_numpy()
    y, g = y[ok], g[ok]
    if len(y) < 10:
        return {"n": int(len(y)), "groups": 0, "icc": float("nan")}
    codes, _ = pd.factorize(g)
    k = int(codes.max()) + 1
    n_total = len(y)
    if k < 2 or n_total <= k:
        return {"n": n_total, "groups": k, "icc": float("nan")}
    counts = np.bincount(codes, minlength=k).astype(float)
    sums = np.bincount(codes, weights=y, minlength=k)
    means = sums / counts
    grand = y.mean()
    ss_between = float(np.sum(counts * (means - grand) ** 2))
    ss_within = float(np.sum((y - means[codes]) ** 2))
    ms_between = ss_between / (k - 1)
    ms_within = ss_within / (n_total - k)
    n0 = (n_total - np.sum(counts**2) / n_total) / (k - 1)
    denom = ms_between + (n0 - 1) * ms_within
    icc = (ms_between - ms_within) / denom if denom > 0 else float("nan")
    return {
        "n": n_total,
        "groups": k,
        "mean_group_size": float(n_total / k),
        "icc": float(icc),
    }


def variance_decomposition(
    lots: pd.DataFrame,
    label: str,
    keys: tuple[str, ...] = ("buyer_id", "winner_id", "cpv_division", "region"),
    min_group: int = 3,
    n_perm: int = 500,
    seed: int = 20260916,
) -> pd.DataFrame:
    """ICC of one label within each grouping, with a label-shuffling null.

    Groups smaller than `min_group` are dropped, because a group of one
    contributes no within-group variance and inflates the statistic.  The null
    shuffles the outcome across all retained rows, which destroys any real
    clustering while keeping the group sizes and the base rate.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for key in keys:
        if key not in lots.columns:
            continue
        sub = lots[lots[label].notna() & lots[key].notna()]
        sizes = sub.groupby(key, observed=True)[label].transform("size")
        sub = sub[sizes >= min_group]
        if len(sub) < 50:
            continue
        y = sub[label].to_numpy(dtype=float)
        g = sub[key].to_numpy(dtype=object)
        obs = icc_one_way(y, g)
        null = np.empty(n_perm, dtype=float)
        for i in range(n_perm):
            null[i] = icc_one_way(rng.permutation(y), g)["icc"]
        null = null[np.isfinite(null)]
        rows.append(
            {
                "label": label,
                "grouping": key,
                "lots": obs["n"],
                "groups": obs["groups"],
                "mean_group_size": obs.get("mean_group_size", float("nan")),
                "icc": obs["icc"],
                "null_mean": float(np.mean(null)) if len(null) else float("nan"),
                "null_sd": float(np.std(null)) if len(null) else float("nan"),
                "p_greater": float((np.sum(null >= obs["icc"]) + 1) / (len(null) + 1))
                if len(null)
                else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def conditional_icc(
    lots: pd.DataFrame,
    label: str,
    group: str,
    block: str,
    min_group: int = 3,
    n_perm: int = 500,
    seed: int = 20260916,
) -> dict[str, float]:
    """Does `group` cluster the outcome once `block` is held fixed?

    A bidder usually wins repeatedly from the same handful of buyers, so a raw
    intraclass correlation by bidder partly restates the buyer's.  Here the
    null permutes the `group` label among lots that share the same `block`
    value, which keeps every group's size exactly and keeps each block's mix of
    groups, and destroys only the pairing between a particular group and a
    particular outcome.  An observed ICC above that null is clustering the
    block cannot account for.
    """
    sub = lots[lots[label].notna() & lots[group].notna() & lots[block].notna()].copy()
    sizes = sub.groupby(group, observed=True)[label].transform("size")
    sub = sub[sizes >= min_group]
    if len(sub) < 50:
        return {"group": group, "block": block, "lots": int(len(sub)), "icc": float("nan")}
    y = sub[label].to_numpy(dtype=float)
    g = sub[group].to_numpy(dtype=object)
    b = sub[block].to_numpy(dtype=object)
    obs = icc_one_way(y, g)
    rng = np.random.default_rng(seed)
    order = np.argsort(b.astype(str), kind="stable")
    keys = b.astype(str)[order]
    starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    bounds = np.r_[starts, len(keys)]
    null = np.empty(n_perm, dtype=float)
    shuffled = g.copy()
    for i in range(n_perm):
        perm = g[order].copy()
        for a, z in zip(bounds[:-1], bounds[1:]):
            if z - a > 1:
                perm[a:z] = rng.permutation(perm[a:z])
        shuffled[order] = perm
        null[i] = icc_one_way(y, shuffled)["icc"]
    null = null[np.isfinite(null)]
    return {
        "label": label,
        "group": group,
        "block": block,
        "lots": obs["n"],
        "groups": obs["groups"],
        "blocks": int(len(bounds) - 1),
        "icc": obs["icc"],
        "null_mean": float(np.mean(null)) if len(null) else float("nan"),
        "null_sd": float(np.std(null)) if len(null) else float("nan"),
        "excess": float(obs["icc"] - np.mean(null)) if len(null) else float("nan"),
        "p_greater": float((np.sum(null >= obs["icc"]) + 1) / (len(null) + 1))
        if len(null)
        else float("nan"),
    }
