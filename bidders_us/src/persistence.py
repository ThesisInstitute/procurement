"""Residual persistence, variance decomposition and within-cell pairing.

Pure functions on pandas frames and numpy arrays, so they are tested directly
on small fixtures in bidders_us/tests/test_persistence.py. Nothing here reads
a file.

Vocabulary. A "residual" is realised minus forecast, y - p, on one award, where
p is the contract-shape model's out-of-sample probability. A "group" is a
contractor (recipient_uei, recipient_parent_uei or recipient_name) or an
awarding office. "Train" and "test" are the forward-chained periods.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bidders_us.src.common import USA_SRC  # noqa: F401  (puts usaspending/src on the path)
import scoring as S  # noqa: E402


# ----------------------------------------------------------------------------
# group tables
# ----------------------------------------------------------------------------

def group_table(df: pd.DataFrame, key: str, min_train: int = 5, min_test: int = 3,
                split_col: str = "split", y_col: str = "y", p_col: str = "p") -> pd.DataFrame:
    """Per-group mean residual in train and in test, for groups with enough of both.

    Rows with a null key are dropped. The returned frame is indexed by the group
    key and carries n_train, n_test, resid_train, resid_test, y_test, p_test.
    """
    d = df[[key, split_col, y_col, p_col]].dropna(subset=[key, y_col, p_col]).copy()
    d["resid"] = d[y_col] - d[p_col]
    tr = d[d[split_col] == "train"].groupby(key).agg(
        n_train=("resid", "size"), resid_train=("resid", "mean"))
    te = d[d[split_col] == "test"].groupby(key).agg(
        n_test=("resid", "size"), resid_test=("resid", "mean"),
        y_test=(y_col, "mean"), p_test=(p_col, "mean"))
    t = tr.join(te, how="inner")
    t = t[(t["n_train"] >= min_train) & (t["n_test"] >= min_test)]
    return t


def shrink_toward_zero(mean: np.ndarray, n: np.ndarray, k: float) -> np.ndarray:
    """Empirical-Bayes style shrinkage of a group mean residual toward zero.

    (n * mean) / (n + k). The residual of a calibrated forecast has mean zero,
    so zero is the prior mean and k plays the role of the prior's weight in
    observations. k is chosen on the validation years (choose_shrink_k),
    never on test rows.
    """
    mean = np.asarray(mean, dtype=float)
    n = np.asarray(n, dtype=float)
    return n * mean / (n + k)


# ----------------------------------------------------------------------------
# correlations and bootstrap
# ----------------------------------------------------------------------------

def pearson(x, y, w=None) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if w is None:
        w = np.ones_like(x)
    w = np.asarray(w, dtype=float)
    if len(x) < 3 or w.sum() <= 0:
        return float("nan")
    mx = np.sum(w * x) / np.sum(w)
    my = np.sum(w * y) / np.sum(w)
    cov = np.sum(w * (x - mx) * (y - my))
    vx = np.sum(w * (x - mx) ** 2)
    vy = np.sum(w * (y - my) ** 2)
    if vx <= 0 or vy <= 0:
        return float("nan")
    return float(cov / np.sqrt(vx * vy))


def spearman(x, y) -> float:
    x = pd.Series(np.asarray(x, dtype=float)).rank()
    y = pd.Series(np.asarray(y, dtype=float)).rank()
    return pearson(x.to_numpy(), y.to_numpy())


def bootstrap_corr(table: pd.DataFrame, xcol: str, ycol: str, wcol: str | None,
                   n_boot: int = 2000, seed: int = 0) -> dict:
    """Point estimate and percentile interval, resampling GROUPS with replacement."""
    x = table[xcol].to_numpy(dtype=float)
    y = table[ycol].to_numpy(dtype=float)
    w = table[wcol].to_numpy(dtype=float) if wcol else None
    point = pearson(x, y, w)
    rng = np.random.default_rng(seed)
    n = len(x)
    draws = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        draws[b] = pearson(x[idx], y[idx], None if w is None else w[idx])
    draws = draws[~np.isnan(draws)]
    return {"r": point, "lo": float(np.quantile(draws, 0.025)) if len(draws) else float("nan"),
            "hi": float(np.quantile(draws, 0.975)) if len(draws) else float("nan"),
            "n_groups": int(n), "n_boot": int(n_boot), "weighted": wcol is not None}


# ----------------------------------------------------------------------------
# does the training-period group residual predict test outcomes?
# ----------------------------------------------------------------------------

def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def expit(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def signal_on_test(df: pd.DataFrame, key: str, table: pd.DataFrame, k_shrink: float,
                   split_col: str = "split", y_col: str = "y", p_col: str = "p") -> dict:
    """Score the training-period group residual as a predictor on test awards.

    Restricted to test awards whose group is in `table`. Reports the AUC of the
    raw training-period mean residual alone, the AUC of the model alone on the
    same rows, and the AUC and Brier score of the model with the shrunk group
    residual added to it on the probability scale, clipped to [1e-6, 1 - 1e-6].
    """
    te = df[(df[split_col] == "test") & df[key].isin(table.index)].dropna(subset=[y_col, p_col])
    if te.empty:
        return {"n": 0}
    y = te[y_col].to_numpy(dtype=float)
    p = te[p_col].to_numpy(dtype=float)
    raw = te[key].map(table["resid_train"]).to_numpy(dtype=float)
    shr = shrink_toward_zero(raw, te[key].map(table["n_train"]).to_numpy(), k_shrink)
    p_adj = np.clip(p + shr, 1e-6, 1 - 1e-6)
    base = float(df.loc[df[split_col] == "train", y_col].mean())
    return {
        "n": int(len(te)), "n_groups": int(te[key].nunique()),
        "observed_rate": float(y.mean()),
        "auc_train_residual_alone": S.auc(y, raw),
        "auc_model": S.auc(y, p),
        "auc_model_plus_shrunk_residual": S.auc(y, p_adj),
        "brier_model": S.brier_score(y, p),
        "brier_model_plus_shrunk_residual": S.brier_score(y, p_adj),
        "brier_base_rate": S.brier_score(y, np.full(len(y), base)),
        "bss_model": S.brier_skill_score(y, p, base),
        "bss_model_plus_shrunk_residual": S.brier_skill_score(y, p_adj, base),
        "k_shrink": float(k_shrink),
    }


def choose_shrink_k(df: pd.DataFrame, key: str, min_train: int, min_val: int,
                    grid=(1, 2, 5, 10, 20, 50, 100, 200), split_col: str = "split",
                    y_col: str = "y", p_col: str = "p") -> dict:
    """Pick k by Brier score of model-plus-shrunk-residual on the VALIDATION years.

    The group residual is computed on the training years only, exactly as it
    will be for the test years, and scored on validation. Nothing here touches
    test rows.
    """
    # The real test rows are removed BEFORE the validation rows are relabelled
    # as the scoring period. Relabelling alone would leave the test rows in
    # place under the same label, and k would then be chosen on validation
    # and test outcomes pooled; an audit of this module caught exactly that.
    d = df[df[split_col] != "test"].copy()
    d.loc[d[split_col] == "val", split_col] = "test"
    tab = group_table(d, key, min_train, min_val, split_col, y_col, p_col)
    if tab.empty:
        return {"k": float(grid[0]), "grid": {}}
    scores = {}
    for k in grid:
        r = signal_on_test(d, key, tab, float(k), split_col, y_col, p_col)
        scores[k] = r.get("brier_model_plus_shrunk_residual", float("nan"))
    best = min(scores, key=lambda k: (np.nan_to_num(scores[k], nan=np.inf), k))
    return {"k": float(best), "grid": {str(k): v for k, v in scores.items()},
            "n_val_rows": int(((d[split_col] == "test") & d[key].isin(tab.index)).sum())}


# ----------------------------------------------------------------------------
# variance decomposition
# ----------------------------------------------------------------------------

def anova_between_variance(resid, groups) -> dict:
    """One-way random-effects method-of-moments decomposition, unbalanced design.

    sigma2_between = (MSB - MSW) / n0 with n0 = (N - sum n_g^2 / N) / (G - 1),
    floored at zero; sigma2_within = MSW. `share` is the between part of the
    total. Groups with a null label are dropped first.
    """
    d = pd.DataFrame({"r": np.asarray(resid, dtype=float), "g": np.asarray(groups)})
    d = d[pd.notna(d["g"]) & pd.notna(d["r"])]
    N = len(d)
    G = d["g"].nunique()
    if N < 3 or G < 2 or G >= N:
        return {"n": int(N), "n_groups": int(G), "sigma2_between": float("nan"),
                "sigma2_within": float("nan"), "share": float("nan")}
    grand = d["r"].mean()
    stats = d.groupby("g")["r"].agg(["size", "mean"])
    ssb = float((stats["size"] * (stats["mean"] - grand) ** 2).sum())
    ssw = float(((d["r"] - d["g"].map(stats["mean"])) ** 2).sum())
    msb = ssb / (G - 1)
    msw = ssw / (N - G)
    n0 = (N - float((stats["size"] ** 2).sum()) / N) / (G - 1)
    s2b = max(0.0, (msb - msw) / n0)
    return {"n": int(N), "n_groups": int(G), "sigma2_between": s2b,
            "sigma2_within": msw, "share": s2b / (s2b + msw) if (s2b + msw) > 0 else float("nan"),
            "total_variance": float(d["r"].var(ddof=0))}


def fe_r2(resid, group_sets: list, max_iter: int = 2000, tol: float = 1e-12) -> dict:
    """R squared and adjusted R squared of a fixed-effects regression of the residual.

    One set of effects is exact (group means). Two sets are fitted by
    alternating demeaning, the within transformation, iterated until the sum
    of squared residuals stops changing; the number of iterations and whether
    it converged are returned. The parameter count for the adjustment is the
    rank of the dummy design beyond the constant: G - 1 for one set, and
    G1 + G2 - m - 1 for two sets, where m is the number of connected
    components of the bipartite group graph (a disconnected pair of groups
    costs one fewer parameter than the naive count).
    """
    r = pd.Series(np.asarray(resid, dtype=float))
    gs = [pd.Series(np.asarray(g)).astype("string") for g in group_sets]
    ok = r.notna()
    for g in gs:
        ok &= g.notna()
    r = r[ok].reset_index(drop=True)
    gs = [g[ok].reset_index(drop=True) for g in gs]
    n = len(r)
    sst = float(((r - r.mean()) ** 2).sum())
    if n < 3 or sst == 0:
        return {"n": int(n), "r2": float("nan"), "adj_r2": float("nan"), "k": 0}
    e = r - r.mean()
    converged, n_iter = len(gs) == 1, 0
    prev_sse = float((e ** 2).sum())
    for n_iter in range(1, max_iter + 1):
        for g in gs:
            e = e - e.groupby(g).transform("mean")
        sse_now = float((e ** 2).sum())
        if abs(prev_sse - sse_now) < tol * sst:
            converged = True
            break
        prev_sse = sse_now
    sse = float((e ** 2).sum())
    if len(gs) == 1:
        k = int(gs[0].nunique()) - 1
        m = int(gs[0].nunique())
    else:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        codes = [pd.Categorical(g).codes for g in gs]
        sizes = [int(c.max()) + 1 for c in codes]
        # bipartite graph over the first two sets; further sets are counted naively
        adj_m = coo_matrix((np.ones(n), (codes[0], codes[1] + sizes[0])),
                           shape=(sizes[0] + sizes[1], sizes[0] + sizes[1]))
        m = int(connected_components(adj_m, directed=False)[0])
        k = sizes[0] + sizes[1] - m - 1 + sum(sz - 1 for sz in sizes[2:])
    r2 = 1.0 - sse / sst
    adj = 1.0 - (1.0 - r2) * (n - 1) / max(n - k - 1, 1)
    return {"n": int(n), "r2": r2, "adj_r2": adj, "k": int(k),
            "n_groups": [int(g.nunique()) for g in gs], "components": m,
            "n_iter": int(n_iter), "converged": bool(converged)}


# ----------------------------------------------------------------------------
# within-cell pairs
# ----------------------------------------------------------------------------

def within_cell_pairs(df: pd.DataFrame, cell_cols: list, key: str, signal_col: str,
                      y_col: str, decile_col: str | None = None, max_decile_gap: int = 1) -> dict:
    """Pair awards inside a cell that come from different groups and differ in outcome.

    A pair is correct when the award whose group has the LOWER signal is the one
    that did not slip; an exact tie in signal counts one half. Only rows with a
    non-null signal and outcome enter. Cells are the distinct combinations of
    cell_cols; within a cell the pair must satisfy |decile_i - decile_j| <=
    max_decile_gap when decile_col is given.
    """
    d = df.dropna(subset=[key, signal_col, y_col] + cell_cols).copy()
    n_pairs = n_disc = 0
    correct = 0.0
    for _, blk in d.groupby(cell_cols, sort=False):
        if len(blk) < 2:
            continue
        g = blk[key].to_numpy()
        s = blk[signal_col].to_numpy(dtype=float)
        y = blk[y_col].to_numpy(dtype=float)
        iu, ju = np.triu_indices(len(blk), k=1)
        ok = g[iu] != g[ju]
        if decile_col is not None:
            dec = blk[decile_col].to_numpy(dtype=float)
            ok &= np.abs(dec[iu] - dec[ju]) <= max_decile_gap
        iu, ju = iu[ok], ju[ok]
        n_pairs += len(iu)
        disc = y[iu] != y[ju]
        iu, ju = iu[disc], ju[disc]
        n_disc += len(iu)
        lower_i = s[iu] < s[ju]
        tie = s[iu] == s[ju]
        # the award with the lower signal should be the one with y == 0
        win = np.where(lower_i, y[iu] == 0, y[ju] == 0)
        correct += float(np.sum(win[~tie])) + 0.5 * float(np.sum(tie))
    return {"n_pairs": int(n_pairs), "n_discordant_pairs": int(n_disc),
            "accuracy": correct / n_disc if n_disc else float("nan")}


def permute_within(labels: pd.Series, within: pd.Series, rng: np.random.Generator) -> pd.Series:
    """Shuffle `labels` among rows that share the same `within` value."""
    out = labels.copy()
    lab = labels.to_numpy(dtype=object)
    w = within.to_numpy(dtype=object)
    order = np.argsort(pd.Series(w).astype("string").fillna("__NA__").to_numpy(), kind="mergesort")
    w_sorted = pd.Series(w[order]).astype("string").fillna("__NA__").to_numpy()
    lab_sorted = lab[order].copy()
    starts = np.r_[0, np.where(w_sorted[1:] != w_sorted[:-1])[0] + 1, len(w_sorted)]
    for a, b in zip(starts[:-1], starts[1:]):
        if b - a > 1:
            lab_sorted[a:b] = lab_sorted[a:b][rng.permutation(b - a)]
    lab_out = np.empty_like(lab)
    lab_out[order] = lab_sorted
    out[:] = lab_out
    return out


# ----------------------------------------------------------------------------
# between-group variance estimators that do not assume equal within variance
# ----------------------------------------------------------------------------

def split_half_between_variance(df: pd.DataFrame, key: str, resid_col: str,
                                rng: np.random.Generator, n_splits: int = 5) -> dict:
    """Between-group variance from the covariance of two random half-means.

    Within each group with at least two rows, rows are shuffled and dealt
    alternately into two halves. Across groups, the covariance of the two
    half-means estimates the variance of the group effect: the noise in the two
    halves is independent, so unlike the one-way ANOVA estimator this does not
    lean on equal within-group variance, which a residual of a binary outcome
    does not have. Averaged over n_splits deals. Reported unweighted and
    weighted by group size.
    """
    d = df[[key, resid_col]].dropna()
    sizes = d.groupby(key)[resid_col].transform("size")
    d = d[sizes >= 2]
    if d[key].nunique() < 3:
        return {"n": int(len(d)), "n_groups": int(d[key].nunique()),
                "cov_unweighted": float("nan"), "cov_weighted": float("nan")}
    cu, cw = [], []
    for _ in range(n_splits):
        dd = d.sample(frac=1.0, random_state=int(rng.integers(0, 2 ** 31 - 1)))
        dd["half"] = dd.groupby(key).cumcount() % 2
        m = dd.groupby([key, "half"])[resid_col].mean().unstack("half")
        n = dd.groupby(key).size().reindex(m.index)
        m = m.dropna()
        n = n.reindex(m.index).to_numpy(dtype=float)
        a, b = m[0].to_numpy(), m[1].to_numpy()
        cu.append(float(np.mean((a - a.mean()) * (b - b.mean()))))
        wa, wb = np.average(a, weights=n), np.average(b, weights=n)
        cw.append(float(np.sum(n * (a - wa) * (b - wb)) / np.sum(n)))
    return {"n": int(len(d)), "n_groups": int(d[key].nunique()),
            "cov_unweighted": float(np.mean(cu)), "cov_weighted": float(np.mean(cw)),
            "n_splits": int(n_splits)}


def _wcov(a: np.ndarray, b: np.ndarray, w: np.ndarray | None) -> float:
    if w is None:
        return float(np.mean((a - a.mean()) * (b - b.mean())))
    wa, wb = np.average(a, weights=w), np.average(b, weights=w)
    return float(np.sum(w * (a - wa) * (b - wb)) / np.sum(w))


def cross_period_covariance(table: pd.DataFrame, wcol: str | None = None,
                            n_boot: int = 2000, seed: int = 0) -> dict:
    """Covariance across groups of the training-period and test-period mean residual.

    Under residual = group effect + noise, with the effect stable across the
    split and the noise independent between periods, this is the variance of
    the group effect that persists into the test years. Unweighted, every
    group counts once; weighted by wcol (the group's test awards), it is the
    persistent between-group variance per test AWARD, which is the quantity
    comparable with a per-award explained variance. A percentile bootstrap
    over groups gives the interval.
    """
    a = table["resid_train"].to_numpy(dtype=float)
    b = table["resid_test"].to_numpy(dtype=float)
    n = len(a)
    if n < 3:
        return {"n_groups": int(n), "cov": float("nan"), "lo": float("nan"), "hi": float("nan")}
    w = table[wcol].to_numpy(dtype=float) if wcol else None
    rng = np.random.default_rng(seed)
    draws = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        draws[i] = _wcov(a[idx], b[idx], None if w is None else w[idx])
    return {"n_groups": int(n), "cov": _wcov(a, b, w),
            "lo": float(np.quantile(draws, 0.025)), "hi": float(np.quantile(draws, 0.975)),
            "n_boot": int(n_boot), "weighted_by": wcol}
