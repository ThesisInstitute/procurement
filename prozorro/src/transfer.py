"""Experiment 2: does a bidder's forecast transfer from lots it lost to lots it won?

A losing bid never produces a contract, so its forecast can never be resolved
directly.  The transfer test is the way round that.  For every bidder on every
test lot we score the lot *as if that bidder had won it*: the lot block is held
fixed and the bidder block is swapped for that bidder's own price on that lot
and that bidder's own as-of record.  The bidder's mean forecast over the lots
it LOST is then compared with the extension rate it actually realised on the
lots it WON, in the same test window and the same CPV division.

Four forecasts are transferred, which is the point of the design:

* `full` - the with-history model (price and identity);
* `price only` - lot block plus the bidder's price, no bidder history;
* `prior extension rate` - the bidder's as-of extension rate on its own;
* `lot only` - a placebo.  The lot-block model knows nothing about the bidder,
  so if its mean over a bidder's lost lots also correlates with that bidder's
  realised rate, the correlation is about which lots the bidder competes for,
  not about the bidder.

The null shuffles bidder identity within CPV division, which holds the division
mix and both marginal distributions fixed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features import BIDDER_HISTORY, bidder_block
from src.labels import live_bids
from src.models import fit_gbm
from scipy.stats import rankdata

from src.scoring import auc, spearman


def counterfactual_frame(lots: pd.DataFrame, bids: pd.DataFrame) -> pd.DataFrame:
    """One row per (lot, bidder) with that bidder's price and rank on the lot."""
    live = live_bids(bids)
    keys = ["tender_id", "lot_id"]
    cols = keys + [
        "tender_start",
        "n_bids_lot",
        "cpv_division",
        "winner_id",
        "created_date",
        "year",
        "invasion",
    ]
    cf = live.merge(lots[cols], on=keys, how="inner")
    cf["bidder_is_lowest"] = cf["rank_in_lot"].eq(1.0)
    cf["rank_frac"] = np.where(
        cf["n_bids_lot"] > 1, (cf["rank_in_lot"] - 1.0) / (cf["n_bids_lot"] - 1.0), 0.0
    )
    cf["won"] = cf["bidder_id"].eq(cf["winner_id"])
    return cf.reset_index(drop=True)


def score_counterfactuals(
    cf: pd.DataFrame,
    lots: pd.DataFrame,
    hist: dict[str, object],
    models: dict[str, object],
    lotX_all: pd.DataFrame,
    history_cutoff: str | None = None,
) -> pd.DataFrame:
    """Forecast each lot as if each of its bidders had won it.

    `lots` and `lotX_all` must be row-aligned; `lots` supplies the lot keys.

    `history_cutoff` matters for the transfer test and is the reason this
    argument exists.  With the default (history as of each tender's own start)
    a bidder's forecast on a lot it lost in late 2021 already contains the
    outcome of a lot it won in early 2021 - and that same early win is on the
    realised side of the comparison.  Passing the first day of the test window
    freezes every bidder-history feature there, so nothing that happens inside
    the resolution window can reach the forecast.  The price features still
    come from the lot's own auction, because that is what a forecaster
    registering at award time would have.
    """
    """Attach each model's forecast for `this bidder wins this lot`."""
    keys = ["tender_id", "lot_id"]
    lot_index = lots[keys].reset_index(drop=True).copy()
    lot_index["_row"] = np.arange(len(lots))
    pos = cf[keys].merge(lot_index, on=keys, how="left")["_row"].to_numpy()
    if np.isnan(pos.astype(float)).any():
        raise ValueError("counterfactual rows without a matching lot")
    lotX = lotX_all.iloc[pos.astype(int)].reset_index(drop=True)

    cutoff_iso = (
        pd.Series([history_cutoff] * len(cf), index=cf.index)
        if history_cutoff is not None
        else cf["tender_start"]
    )
    bidX = bidder_block(
        cf["bidder_id"],
        cutoff_iso,
        cf["discount"],
        cf["bidder_is_lowest"],
        cf["rank_frac"],
        hist,
    )
    out = cf.copy()
    out["p_lot_only"] = models["lot"].predict_proba(
        _aligned(models["lot"], lotX)
    )[:, 1]
    price_cols = [c for c in bidX.columns if not c.startswith("bidder_prior")]
    out["p_price_only"] = models["price"].predict_proba(
        _aligned(models["price"], pd.concat([lotX, bidX[price_cols]], axis=1))
    )[:, 1]
    out["p_full"] = models["full"].predict_proba(
        _aligned(models["full"], pd.concat([lotX, bidX], axis=1))
    )[:, 1]
    out["p_prior_ext"] = bidX["bidder_prior_ext_rate"].to_numpy()
    return out


def _aligned(model, X: pd.DataFrame) -> pd.DataFrame:
    """Re-apply the exact column order and category sets the model was fitted with.

    A category the fit never saw becomes NaN here, which is how
    HistGradientBoostingClassifier already treats an unseen level, rather than
    being silently mapped onto some other level's code.
    """
    X = X.copy()
    for col, values in (getattr(model, "_fit_categories", None) or {}).items():
        X[col] = pd.Categorical(X[col].astype(str), categories=[str(v) for v in values])
    cols = getattr(model, "_fit_columns", None)
    return X[cols] if cols else X


def fit_transfer_models(
    lotX: pd.DataFrame,
    bidX: pd.DataFrame,
    y: np.ndarray,
    train: np.ndarray,
) -> dict[str, object]:
    """Fit the three scorable rungs on the training window only."""
    price_cols = [c for c in bidX.columns if c not in BIDDER_HISTORY]
    specs = {
        "lot": lotX,
        "price": pd.concat([lotX, bidX[price_cols]], axis=1),
        "full": pd.concat([lotX, bidX], axis=1),
    }
    models: dict[str, object] = {}
    for name, X in specs.items():
        # The whole frame is passed as the "test" side only so that every
        # category present anywhere is in the fitted encoding.
        _, model = fit_gbm(X.loc[train], y[train], X)
        models[name] = model
    return models


def transfer_cells(
    scored: pd.DataFrame,
    lots: pd.DataFrame,
    label: str = "duration_extension",
    min_wins: int = 3,
    min_lost: int = 1,
) -> pd.DataFrame:
    """(bidder, CPV division) cells: mean lost-lot forecast vs realised won rate."""
    realised = lots[lots[label].notna() & lots["winner_id"].notna()].copy()
    won = (
        realised.groupby(["winner_id", "cpv_division"], observed=True)[label]
        .agg(["mean", "size"])
        .rename(columns={"mean": "realised_rate", "size": "n_won"})
        .reset_index()
        .rename(columns={"winner_id": "bidder_id"})
    )
    lost = scored[~scored["won"]].copy()
    agg = (
        lost.groupby(["bidder_id", "cpv_division"], observed=True)
        .agg(
            f_full=("p_full", "mean"),
            f_price=("p_price_only", "mean"),
            f_prior=("p_prior_ext", "mean"),
            f_lot=("p_lot_only", "mean"),
            n_lost=("p_full", "size"),
        )
        .reset_index()
    )
    cells = agg.merge(won, on=["bidder_id", "cpv_division"], how="inner")
    return cells[(cells["n_won"] >= min_wins) & (cells["n_lost"] >= min_lost)].reset_index(
        drop=True
    )


def permutation_null(
    cells: pd.DataFrame, forecast_col: str, n_perm: int = 2000, seed: int = 20260916
) -> dict[str, float]:
    """Shuffle bidder identity within CPV division and re-score the correlation.

    Spearman's rho is Pearson's r on ranks, and permuting the forecast values
    within a group permutes their ranks the same way (average ranks for ties
    move with their values).  So the ranks are computed once and only the rank
    vector is permuted, which makes a two-thousand-draw null cheap enough to
    run for every label.
    """
    ok = cells[forecast_col].notna() & cells["realised_rate"].notna()
    sub = cells[ok]
    f = sub[forecast_col].to_numpy(dtype=float)
    r = sub["realised_rate"].to_numpy(dtype=float)
    observed = spearman(f, r)
    rf = rankdata(f)
    rr = rankdata(r)
    rr_c = rr - rr.mean()
    rr_ss = float(np.sqrt(np.sum(rr_c**2)))
    groups = [
        np.flatnonzero(sub["cpv_division"].to_numpy() == d)
        for d in pd.unique(sub["cpv_division"])
    ]
    groups = [g for g in groups if len(g) > 1]
    rng = np.random.default_rng(seed)
    null = np.empty(n_perm, dtype=float)
    shuffled = rf.copy()
    if rr_ss == 0 or not len(groups):
        null = np.array([], dtype=float)
    else:
        for i in range(n_perm):
            for idx in groups:
                shuffled[idx] = rf[rng.permutation(idx)]
            sc = shuffled - shuffled.mean()
            ss = float(np.sqrt(np.sum(sc**2)))
            null[i] = float(np.dot(sc, rr_c) / (ss * rr_ss)) if ss > 0 else np.nan
    null = null[np.isfinite(null)]
    if not len(null) or not np.isfinite(observed):
        return {
            "observed": observed,
            "null_mean": float("nan"),
            "null_sd": float("nan"),
            "null_q95": float("nan"),
            "excess_over_null": float("nan"),
            "p_greater": float("nan"),
            "p_two_sided": float("nan"),
            "n_perm": int(len(null)),
        }
    mu = float(np.mean(null))
    # Shuffling *within* division leaves the between-division association
    # intact, so this null is not centred on zero: its mean is the correlation
    # that CPV composition alone produces.  The headline test is therefore the
    # right-tail probability, and the two-sided version is taken about the
    # null's own centre rather than about zero.
    p_greater = float((np.sum(null >= observed) + 1) / (len(null) + 1))
    p_two = float((np.sum(np.abs(null - mu) >= abs(observed - mu)) + 1) / (len(null) + 1))
    return {
        "observed": float(observed),
        "null_mean": mu,
        "null_sd": float(np.std(null)),
        "null_q95": float(np.quantile(null, 0.95)),
        "excess_over_null": float(observed - mu),
        "p_greater": p_greater,
        "p_two_sided": p_two,
        "n_perm": int(len(null)),
    }


def identity_persistence(
    lots: pd.DataFrame,
    label: str,
    train_mask: np.ndarray,
    test_mask: np.ndarray,
    min_wins: int = 3,
    n_perm: int = 2000,
    seed: int = 20260916,
) -> dict[str, float]:
    """Does a bidder's own record persist from the training years into the test ones?

    This is the plainest form of "bidder identity carries slip information": it
    uses only lots the bidder WON on both sides, so nothing counterfactual is
    involved.  If this does not hold, the transfer test in this module has
    nothing to transfer.  The null shuffles the test-window rate among bidders
    that share a modal CPV division, so a correlation driven purely by which
    sector a bidder works in is inside the null and not in the result.
    """
    ok = lots[label].notna().to_numpy()
    tr = lots[train_mask & ok]
    te = lots[test_mask & ok]
    a = tr.groupby("winner_id", observed=True)[label].agg(["mean", "size"])
    b = te.groupby("winner_id", observed=True)[label].agg(["mean", "size"])
    j = a.join(b, lsuffix="_train", rsuffix="_test", how="inner")
    j = j[(j["size_train"] >= min_wins) & (j["size_test"] >= min_wins)]
    if len(j) < 10:
        return {"n_bidders": int(len(j)), "observed": float("nan")}
    modal = (
        te.groupby("winner_id", observed=True)["cpv_division"]
        .agg(lambda x: x.mode().iloc[0] if len(x.mode()) else "")
        .reindex(j.index)
        .fillna("")
    )
    cells = pd.DataFrame(
        {
            "bidder_id": j.index,
            "cpv_division": modal.to_numpy(),
            "train_rate": j["mean_train"].to_numpy(),
            "realised_rate": j["mean_test"].to_numpy(),
            "n_train": j["size_train"].to_numpy(),
            "n_test": j["size_test"].to_numpy(),
        }
    ).reset_index(drop=True)
    out = permutation_null(cells, "train_rate", n_perm=n_perm, seed=seed)
    out.update(
        {
            "n_bidders": int(len(cells)),
            "n_train_lots": int(cells["n_train"].sum()),
            "n_test_lots": int(cells["n_test"].sum()),
            "min_wins_each_side": min_wins,
        }
    )
    return out


def within_lot_test(
    scored: pd.DataFrame,
    lots: pd.DataFrame,
    label: str = "duration_extension",
    n_perm: int = 1000,
    seed: int = 20260916,
    **kwargs,
) -> pd.DataFrame:
    """Hold the lot fixed and ask whether the winner stood out among its rivals.

    Everything that makes a lot slip-prone - the buyer, the sector, the size,
    the year, the number of bidders - is identical for every bidder on that
    lot, so ranking the bidders against each other removes all of it by
    construction.  For each test lot the winner's percentile rank among the
    bidders on that lot is taken under each forecast, and the AUC of that
    percentile against the winner's realised outcome is reported.

    The null replaces the winner with a uniformly random bidder from the same
    lot and recomputes the AUC.  Under that null the percentile carries no
    information about the winner's outcome, so the null centres on 0.5 without
    assuming the winner's own percentile is uniform (it is not: winners are
    chosen largely on price).

    The first row is the model-free version: the winner's own price rank among
    the bids on its lot, with no model between the price and the statistic.
    `p_lot_only` is the other end of the range: it is constant within a lot, so
    its percentile is 0.5 everywhere and it is reported as a degenerate control.
    """
    keys = ["tender_id", "lot_id"]
    y = lots.loc[lots[label].notna(), keys + [label, "winner_id"]]
    df = scored.merge(y, on=keys, how="inner", suffixes=("", "_lot"))
    sizes = df.groupby(keys, observed=True)["bidder_id"].transform("size")
    df = df[sizes >= 2].copy()
    if not len(df):
        return pd.DataFrame()

    rng = np.random.default_rng(seed)
    rows = []
    sample_name = kwargs.get("sample", "all test lots")
    for col, name in [
        ("rank_frac", "raw price rank on the lot, no model"),
        ("p_full", "full model (price and identity)"),
        ("p_price_only", "price only"),
        ("p_prior_ext", "prior extension rate only"),
        ("p_lot_only", "lot only (degenerate control)"),
    ]:
        if col not in df.columns:
            continue
        g = df.groupby(keys, observed=True)[col]
        n = g.transform("size").to_numpy(dtype=float)
        rank = g.rank(method="average").to_numpy(dtype=float)
        pctl = np.where(n > 1, (rank - 1.0) / (n - 1.0), 0.5)
        df["_pctl"] = pctl
        winner_rows = df[df["bidder_id"] == df["winner_id"]]
        per_lot = winner_rows.drop_duplicates(keys)
        obs = auc(per_lot[label].to_numpy(dtype=float), per_lot["_pctl"].to_numpy())
        # Null: a uniformly random bidder from the same lot stands in for the winner.
        lot_key = df[keys].astype(str).agg("|".join, axis=1).to_numpy()
        order = np.argsort(lot_key, kind="stable")
        sorted_keys = lot_key[order]
        starts = np.flatnonzero(np.r_[True, sorted_keys[1:] != sorted_keys[:-1]])
        counts = np.diff(np.r_[starts, len(sorted_keys)])
        pct_sorted = df["_pctl"].to_numpy()[order]
        lab_sorted = df[label].to_numpy(dtype=float)[order]
        lab_lot = lab_sorted[starts]
        null = np.empty(n_perm, dtype=float)
        for i in range(n_perm):
            pick = starts + rng.integers(0, counts)
            null[i] = auc(lab_lot, pct_sorted[pick])
        null = null[np.isfinite(null)]
        rows.append(
            {
                "label": label,
                "sample": sample_name,
                "forecast": name,
                "n_lots": int(len(per_lot)),
                "n_bidders_scored": int(len(df)),
                "mean_percentile_outcome_1": float(
                    per_lot.loc[per_lot[label] == 1, "_pctl"].mean()
                ),
                "mean_percentile_outcome_0": float(
                    per_lot.loc[per_lot[label] == 0, "_pctl"].mean()
                ),
                "auc": obs,
                "null_mean": float(np.mean(null)) if len(null) else float("nan"),
                "null_sd": float(np.std(null)) if len(null) else float("nan"),
                "p_two_sided": float(
                    (np.sum(np.abs(null - 0.5) >= abs(obs - 0.5)) + 1) / (len(null) + 1)
                )
                if len(null) and np.isfinite(obs)
                else float("nan"),
                "n_perm": int(len(null)),
            }
        )
    return pd.DataFrame(rows)
