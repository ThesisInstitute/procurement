"""Experiment 3: the bid-side numbers a losing bidder would also have had.

On the definitive-contract panel, among competed awards (extent_competed_code
A or D, number_of_offers_received at least 2), two pre-award numbers describe
the winning bid without seeing the losing bids: how many offers were received,
and how large the award is relative to its reference class. This script asks
whether either predicts schedule slip.

Relative size is the award's log10 base ceiling minus the leave-one-out mean of
log10 base ceiling over the other awards in the same (awarding agency, full
PSC, base fiscal year) cell, for cells with at least five awards. The cell mean
is built from award-time fields only, but it includes awards made later in the
same fiscal year, so it is a reference class that a forecaster registering on
the award date would only have had in part. That is stated in the report.

Three things are reported per label and horizon:
  binned tables   slip rate by number-of-offers bin and by relative-size
                  quintile (quintile edges from the training years), on test
                  rows, next to the mean residual of the contract-shape model in
                  the same bin (what the shape model does not already capture);
  partial effects partial dependence of the gradient boosting model on
                  n_offers and on relative size, computed on validation rows;
  ablation        test AUC and Brier skill of the shape model without the offer
                  count, with it (the Experiment 1 model), and with relative
                  size added, all on the competed test rows.
"""
from __future__ import annotations

import argparse
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.inspection import partial_dependence  # noqa: E402

from bidders_us.src import shape_model as SM  # noqa: E402
from bidders_us.src.common import (CELLS, PANEL, RAW, RESULTS, USA_SRC,  # noqa: E402
                                   make_logger, record_timing, split_of, write_json)

sys.path.insert(0, str(USA_SRC))
import features as F  # noqa: E402
import models as UM  # noqa: E402
import scoring as S  # noqa: E402

OFFER_BINS = [(2, 2), (3, 3), (4, 5), (6, 10), (11, 20), (21, 10 ** 9)]
MIN_CELL = 5


def relative_size(panel: pd.DataFrame) -> pd.Series:
    """Leave-one-out residual of log10 base ceiling within agency x PSC x base FY."""
    key = (panel["awarding_agency_code"].astype("string").fillna("NA") + "|"
           + panel["psc_full"].astype("string").fillna("NA") + "|"
           + panel["base_fy"].astype("string"))
    v = pd.to_numeric(panel["log_base_ceiling"], errors="coerce")
    g = v.groupby(key)
    n = g.transform("count")
    s = g.transform("sum")
    loo = (s - v) / (n - 1)
    out = v - loo
    out[(n < MIN_CELL) | v.isna()] = np.nan
    return out


def competed_mask(panel: pd.DataFrame) -> pd.Series:
    return (panel["extent_competed_code"].astype("string").isin(["A", "D"])
            & (pd.to_numeric(panel["n_offers"], errors="coerce") >= 2))


def offer_bin(n: pd.Series) -> pd.Series:
    n = pd.to_numeric(n, errors="coerce")
    out = pd.Series(pd.NA, index=n.index, dtype="string")
    for lo, hi in OFFER_BINS:
        lab = f"{lo}" if lo == hi else (f"{lo}-{hi}" if hi < 10 ** 9 else f"{lo}+")
        out[(n >= lo) & (n <= hi)] = lab
    return out


def fit_variant(panel: pd.DataFrame, label: str, h: int, cat: list, num: list, log) -> tuple[pd.Series, object, pd.DataFrame, np.ndarray]:
    col = f"{label}_{h}"
    ok = panel[f"qualifies_{h}"].astype(bool) & panel[col].notna()
    d = panel[ok]
    y = d[col].to_numpy(dtype=float)
    split = split_of(d["base_fy"])
    tr, va, te = [(split == s).to_numpy() for s in ("train", "val", "test")]
    maps = F.fit_category_maps(d[tr], cat)
    X = SM.prepare(d, maps, cat, num)
    clf, best_iter, _ = UM.fit_gbm(X[tr], y[tr], X[va], y[va], set(cat))
    p = pd.Series(np.nan, index=d.index)
    p[va | te] = clf.predict_proba(X[va | te])[:, 1]
    log(f"{label} {h}: fitted with {len(cat) + len(num)} features, iter={best_iter}")
    return p, clf, X[va], y[va]


def binned(te: pd.DataFrame, by: str, ycol: str, pcol: str) -> list:
    rows = []
    for b, blk in te.groupby(by, observed=True):
        rows.append({"bin": str(b), "n": int(len(blk)),
                     "slip_rate": float(blk[ycol].mean()),
                     "mean_forecast_shape_model": float(blk[pcol].mean()),
                     "mean_residual": float((blk[ycol] - blk[pcol]).mean())})
    return rows


def metrics(y, p, base) -> dict:
    return {"n": int(len(y)), "auc": S.auc(y, p), "brier": S.brier_score(y, p),
            "bss_vs_train_base_rate": S.brier_skill_score(y, p, base)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default=str(PANEL))
    ap.add_argument("--pred", default=str(RAW / "exp1_predictions.parquet"))
    a = ap.parse_args()
    log = make_logger("exp3")
    t0 = time.time()
    panel = pd.read_parquet(a.panel)
    pred = pd.read_parquet(a.pred).set_index("contract_award_unique_key")
    panel["relative_size"] = relative_size(panel)
    panel["offer_bin"] = offer_bin(panel["n_offers"])
    panel["split"] = split_of(panel["base_fy"])
    comp = competed_mask(panel)
    log(f"panel {len(panel)}, competed with >=2 offers {int(comp.sum())}, "
        f"relative size defined on {int(panel['relative_size'].notna().sum())}")

    cat_o, num_o = SM.variant_columns("shape_office")
    num_no_offers = [c for c in num_o if c not in ("n_offers", "n_offers_missing")]
    num_rel = num_o + ["relative_size"]

    tr_rel = panel.loc[(panel["split"] == "train") & comp, "relative_size"].dropna()
    q_edges = np.quantile(tr_rel, [0.2, 0.4, 0.6, 0.8])
    panel["relative_size_quintile"] = pd.Series(
        np.digitize(panel["relative_size"].to_numpy(dtype=float), q_edges) + 1,
        index=panel.index).where(panel["relative_size"].notna())

    results = []
    for label, h in CELLS:
        col = f"{label}_{h}"
        base = float(panel.loc[panel["split"] == "train", col].mean())
        p_shape = pred[f"p_shape_office_{label}_{h}"].reindex(panel["contract_award_unique_key"]).to_numpy()
        panel["p_shape"] = p_shape
        p_no, _, _, _ = fit_variant(panel, label, h, cat_o, num_no_offers, log)
        p_rel, clf_rel, Xva, yva = fit_variant(panel, label, h, cat_o, num_rel, log)
        panel["p_no_offers"] = p_no.reindex(panel.index)
        panel["p_relative"] = p_rel.reindex(panel.index)

        te = panel[(panel["split"] == "test") & comp & panel[col].notna()
                   & panel[f"qualifies_{h}"].astype(bool)]
        y = te[col].to_numpy(dtype=float)
        res = {"label": label, "horizon": h, "n_competed_test": int(len(te)),
               "train_base_rate_all": base, "competed_test_rate": float(y.mean()),
               "univariate": {
                   "auc_n_offers": S.auc(y, te["n_offers"].to_numpy(dtype=float)),
                   "auc_neg_relative_size": S.auc(y[te["relative_size"].notna()],
                                                  -te["relative_size"].dropna().to_numpy()),
                   "auc_relative_size": S.auc(y[te["relative_size"].notna()],
                                              te["relative_size"].dropna().to_numpy()),
               },
               "by_offer_bin": binned(te, "offer_bin", col, "p_shape"),
               "by_relative_size_quintile": binned(te.dropna(subset=["relative_size_quintile"]),
                                                   "relative_size_quintile", col, "p_shape"),
               "relative_size_quintile_edges_train": q_edges.tolist(),
               "ablation_on_competed_test": {
                   "shape_without_offer_count": metrics(y, te["p_no_offers"].to_numpy(), base),
                   "shape_office_experiment1": metrics(y, te["p_shape"].to_numpy(), base),
                   "shape_plus_relative_size": metrics(y, te["p_relative"].to_numpy(), base),
               }}
        # partial dependence on validation rows, competed only
        Xv = Xva.copy()
        yv = yva
        va_mask = comp[panel.index.isin(Xv.index)].reindex(Xv.index).fillna(False).to_numpy(dtype=bool)
        Xv = Xv[va_mask]
        pd_rows = {}
        for feat, grid in (("n_offers", np.array([2, 3, 4, 5, 7, 10, 15, 20, 30], dtype=float)),
                           ("relative_size", np.array([-1.5, -1, -0.5, -0.25, 0, 0.25, 0.5, 1, 1.5]))):
            pdp = partial_dependence(clf_rel, Xv, [feat], grid_resolution=50,
                                     custom_values={feat: grid}, kind="average")
            pd_rows[feat] = [{"value": float(v), "partial_dependence": float(a_)}
                             for v, a_ in zip(pdp["grid_values"][0], pdp["average"][0])]
        res["partial_dependence_validation_competed"] = pd_rows
        results.append(res)
        write_json(RESULTS / "exp3_results.json", results)
        log(f"{label} {h}: auc no-offers={res['ablation_on_competed_test']['shape_without_offer_count']['auc']:.4f} "
            f"shape={res['ablation_on_competed_test']['shape_office_experiment1']['auc']:.4f} "
            f"+rel={res['ablation_on_competed_test']['shape_plus_relative_size']['auc']:.4f}")

    # chart: slip rate by offers bin and by relative-size quintile, 36 months
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    for r in results:
        if r["horizon"] != 36:
            continue
        ob = pd.DataFrame(r["by_offer_bin"])
        order = [f"{lo}" if lo == hi else (f"{lo}-{hi}" if hi < 10 ** 9 else f"{lo}+") for lo, hi in OFFER_BINS]
        ob = ob.set_index("bin").reindex(order).dropna()
        axes[0].plot(ob.index, ob["slip_rate"], marker="o", label=f"{r['label']} realised")
        axes[0].plot(ob.index, ob["mean_forecast_shape_model"], marker="x", ls="--",
                     label=f"{r['label']} shape forecast")
        rq = pd.DataFrame(r["by_relative_size_quintile"]).set_index("bin")
        axes[1].plot(rq.index, rq["slip_rate"], marker="o", label=f"{r['label']} realised")
        axes[1].plot(rq.index, rq["mean_forecast_shape_model"], marker="x", ls="--",
                     label=f"{r['label']} shape forecast")
    axes[0].set_xlabel("Number of offers received")
    axes[0].set_ylabel("Share slipping by 36 months, competed test awards")
    axes[1].set_xlabel("Relative size quintile (1 smallest for its cell)")
    for ax in axes:
        ax.legend(fontsize=7)
        ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(RESULTS / "exp3_bid_side_signals.png", dpi=130)
    record_timing("exp3", time.time() - t0, {"cells": len(results)})
    log(f"done in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
