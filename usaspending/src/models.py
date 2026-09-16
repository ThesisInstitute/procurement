"""The model ladder, forward chained by base fiscal year.

Ladder per (label, horizon):
  0 base rate          the unconditional training-period mean
  1 reference class    shrunk cell means over (agency, NAICS2, pricing, value quintile)
  2 GBM                HistGradientBoostingClassifier on all base-row features
                       plus the as-of recipient and office history
  3 GBM no history     model 2 with the history block removed

Split by base action_date fiscal year: train FY2010-FY2017, validate
FY2018-FY2019, test FY2020-FY2022. The GBM early-stops on the validation split;
nothing is selected on test.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as F  # noqa: E402
import scoring as S  # noqa: E402
from reference_class import ReferenceClassModel  # noqa: E402

TRAIN_FY = (2010, 2017)
VAL_FY = (2018, 2019)
TEST_FY = (2020, 2022)
HORIZONS = (12, 24, 36)

BINARY_LABELS = [
    "ceiling_growth_gt10",
    "ceiling_growth_gt25",
    "ceiling_growth_gt50",
    "schedule_slip_gt90",
    "schedule_slip_gt365",
    "terminated",
    "terminated_default",
    "any_change_order",
]

CONTINUOUS_LABELS = [
    "ceiling_growth",
    "schedule_slip_days",
    "unplanned_growth",
]

MAX_ITER = 300

GBM_KW = dict(
    learning_rate=0.06,
    max_leaf_nodes=31,
    min_samples_leaf=50,
    l2_regularization=1.0,
    early_stopping=False,
    random_state=0,
)


def split_masks(df: pd.DataFrame) -> dict:
    fy = df["base_fy"].astype("Int64")
    return {
        "train": ((fy >= TRAIN_FY[0]) & (fy <= TRAIN_FY[1])).to_numpy(dtype=bool),
        "val": ((fy >= VAL_FY[0]) & (fy <= VAL_FY[1])).to_numpy(dtype=bool),
        "test": ((fy >= TEST_FY[0]) & (fy <= TEST_FY[1])).to_numpy(dtype=bool),
    }


def prepare_matrix(df: pd.DataFrame, maps: dict, use_history: bool) -> pd.DataFrame:
    cat, num = F.feature_columns(use_history)
    d = F.apply_category_maps(df[[c for c in cat if c in df.columns]], maps)
    for c in num:
        d[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    return d[[c for c in cat if c in d.columns] + num]


def fit_gbm(X_tr, y_tr, X_va, y_va, cat_cols):
    """Fit on train only; choose the number of boosting iterations on val.

    HistGradientBoostingClassifier has no `shuffle` parameter and its built-in
    early stopping carves its own validation split out of the training data at
    random (checked against sklearn 1.9.1 this session), which would break the
    forward-chained design. So the model is fitted on the training years with
    early stopping off, the iteration count is chosen by Brier score on the
    validation years using staged_predict_proba, and the model is refitted on
    the training years at exactly that many iterations. Test-period rows are
    never seen before scoring.
    """
    clf = HistGradientBoostingClassifier(
        categorical_features=[c in cat_cols for c in X_tr.columns],
        max_iter=MAX_ITER, **GBM_KW)
    clf.fit(X_tr, y_tr)

    best_iter, best_brier = 1, float("inf")
    for i, p in enumerate(clf.staged_predict_proba(X_va), start=1):
        b = S.brier_score(y_va, p[:, 1])
        if b < best_brier:
            best_brier, best_iter = b, i
    if best_iter < MAX_ITER:
        clf = HistGradientBoostingClassifier(
            categorical_features=[c in cat_cols for c in X_tr.columns],
            max_iter=best_iter, **GBM_KW)
        clf.fit(X_tr, y_tr)
    return clf, best_iter, best_brier


def binary_metrics(y, p, base_rate_train) -> dict:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    m = {
        "n": int(len(y)),
        "observed_rate": float(np.mean(y)) if len(y) else float("nan"),
        "brier": S.brier_score(y, p),
        "bss_vs_train_base_rate": S.brier_skill_score(y, p, base_rate_train),
        "auc": S.auc(y, p),
        "ece": S.calibration_error(y, p),
    }
    m.update({f"murphy_{k}": v for k, v in S.murphy_decomposition(y, p).items()})
    return m


def run_cell(panel: pd.DataFrame, label: str, h: int, maps: dict,
             perm_sample: int, perm_repeats: int, log) -> dict:
    col = f"{label}_{h}"
    qual = panel[f"qualifies_{h}"].astype(bool) & panel[col].notna()
    d = panel[qual].copy()
    if d.empty:
        return {"label": label, "horizon": h, "error": "no qualifying rows"}
    y = d[col].to_numpy(dtype=float)
    masks = split_masks(d)
    n_tr, n_va, n_te = (int(masks[k].sum()) for k in ("train", "val", "test"))
    if min(n_tr, n_va, n_te) == 0:
        return {"label": label, "horizon": h, "error": "empty split"}
    if len(np.unique(y[masks["train"]])) < 2 or len(np.unique(y[masks["test"]])) < 2:
        return {"label": label, "horizon": h, "error": "single-class split",
                "n_train": n_tr, "n_val": n_va, "n_test": n_te}

    base_rate = float(np.mean(y[masks["train"]]))
    res = {"label": label, "horizon": h, "n_train": n_tr, "n_val": n_va,
           "n_test": n_te, "train_base_rate": base_rate,
           "test_base_rate": float(np.mean(y[masks["test"]])), "models": {}}

    # model 0: base rate
    p0_te = np.full(n_te, base_rate)
    res["models"]["base_rate"] = binary_metrics(y[masks["test"]], p0_te, base_rate)

    # model 1: reference class
    rc = ReferenceClassModel().fit(d[masks["train"]], pd.Series(y[masks["train"]]))
    p1_te = np.clip(rc.predict(d[masks["test"]]), 1e-6, 1 - 1e-6)
    p1_va = np.clip(rc.predict(d[masks["val"]]), 1e-6, 1 - 1e-6)
    res["models"]["reference_class"] = binary_metrics(y[masks["test"]], p1_te, base_rate)
    res["models"]["reference_class"]["val_brier"] = S.brier_score(y[masks["val"]], p1_va)

    cat_cols, _ = F.feature_columns(True)
    for name, use_hist in (("gbm", True), ("gbm_no_history", False)):
        X = prepare_matrix(d, maps, use_hist)
        clf, best_iter, best_val_brier = fit_gbm(
            X[masks["train"]], y[masks["train"]],
            X[masks["val"]], y[masks["val"]], set(cat_cols))
        p_te = clf.predict_proba(X[masks["test"]])[:, 1]
        p_va = clf.predict_proba(X[masks["val"]])[:, 1]
        m = binary_metrics(y[masks["test"]], p_te, base_rate)
        m["val_brier"] = S.brier_score(y[masks["val"]], p_va)
        m["val_brier_at_selected_iter"] = best_val_brier
        m["n_iter"] = int(best_iter)
        res["models"][name] = m
        if name == "gbm":
            res["calibration_test"] = S.calibration_table(
                y[masks["test"]], p_te).to_dict("records")
            res["calibration_test_reference_class"] = S.calibration_table(
                y[masks["test"]], p1_te).to_dict("records")
            # unseen-recipient slice
            train_uei = set(d.loc[masks["train"], "recipient_uei"].dropna().unique())
            te = d[masks["test"]]
            unseen = ~te["recipient_uei"].isin(train_uei).to_numpy()
            if unseen.sum() > 50 and len(np.unique(y[masks["test"]][unseen])) > 1:
                res["unseen_recipient_test"] = {
                    "n": int(unseen.sum()),
                    "share_of_test": float(unseen.mean()),
                    "base_rate": binary_metrics(
                        y[masks["test"]][unseen],
                        np.full(int(unseen.sum()), base_rate), base_rate),
                    "reference_class": binary_metrics(
                        y[masks["test"]][unseen], p1_te[unseen], base_rate),
                    "gbm": binary_metrics(
                        y[masks["test"]][unseen], p_te[unseen], base_rate),
                }
            else:
                res["unseen_recipient_test"] = {
                    "n": int(unseen.sum()),
                    "note": "too few unseen-recipient test rows or single class",
                }
            # permutation importance on validation
            Xv = X[masks["val"]]
            yv = y[masks["val"]]
            if len(Xv) > perm_sample:
                idx = np.random.RandomState(0).choice(len(Xv), perm_sample,
                                                      replace=False)
                Xv, yv = Xv.iloc[idx], yv[idx]

            def neg_brier(est, Xa, ya):
                return -S.brier_score(ya, est.predict_proba(Xa)[:, 1])

            # permutation_importance reports baseline_score minus permuted_score
            # for a higher-is-better scorer. With the negative Brier score that
            # difference is exactly the increase in Brier caused by shuffling the
            # feature, so it is reported as it stands.
            pi = permutation_importance(clf, Xv, yv, scoring=neg_brier,
                                        n_repeats=perm_repeats, random_state=0,
                                        n_jobs=1)
            order = np.argsort(pi.importances_mean)[::-1][:15]
            res["permutation_importance_val"] = [
                {"feature": Xv.columns[i],
                 "mean_brier_increase": float(pi.importances_mean[i]),
                 "std": float(pi.importances_std[i])}
                for i in order
            ]
    log(f"{label} H={h}: n_test={n_te} base={base_rate:.4f} "
        f"rc_bss={res['models']['reference_class']['bss_vs_train_base_rate']:.4f} "
        f"gbm_bss={res['models']['gbm']['bss_vs_train_base_rate']:.4f} "
        f"gbm_nohist_bss={res['models']['gbm_no_history']['bss_vs_train_base_rate']:.4f}")
    return res


def base_rates_table(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for h in HORIZONS:
        q = panel[f"qualifies_{h}"].astype(bool)
        for label in BINARY_LABELS:
            col = f"{label}_{h}"
            sub = panel[q & panel[col].notna()]
            for fy, blk in sub.groupby("base_fy"):
                rows.append({"label": label, "horizon_months": h,
                             "base_fy": int(fy), "n": int(len(blk)),
                             "base_rate": float(blk[col].mean())})
            rows.append({"label": label, "horizon_months": h, "base_fy": "ALL",
                         "n": int(len(sub)),
                         "base_rate": float(sub[col].mean()) if len(sub) else np.nan})
    return pd.DataFrame(rows)


def leak_comparison_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Base rates of the same label under both readings of the ceiling.

    The reconstructed reading uses per-action deltas up to the horizon. The
    award-level reading takes potential_total_value_of_award off the row, which
    carries the award's end state whatever the horizon.
    """
    rows = []
    for h in HORIZONS:
        q = panel[f"qualifies_{h}"].astype(bool)
        rec = panel.loc[q, f"ceiling_growth_gt25_{h}"]
        leak = panel.loc[q, f"ceiling_growth_awardlevel_gt25_diagnostic_{h}"]
        both = q & panel[f"ceiling_growth_gt25_{h}"].notna() &             panel[f"ceiling_growth_awardlevel_gt25_diagnostic_{h}"].notna()
        rows.append({
            "horizon_months": h,
            "n_qualifying": int(q.sum()),
            "n_reconstructed_label": int(rec.notna().sum()),
            "n_award_level_label": int(leak.notna().sum()),
            "rate_reconstructed": float(rec.mean()),
            "rate_award_level": float(leak.mean()),
            "n_both_available": int(both.sum()),
            "rate_reconstructed_on_common_rows": float(
                panel.loc[both, f"ceiling_growth_gt25_{h}"].mean()),
            "rate_award_level_on_common_rows": float(
                panel.loc[both,
                          f"ceiling_growth_awardlevel_gt25_diagnostic_{h}"].mean()),
        })
    return pd.DataFrame(rows)


def continuous_summary(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for h in HORIZONS:
        q = panel[f"qualifies_{h}"].astype(bool)
        for label in CONTINUOUS_LABELS:
            col = f"{label}_{h}"
            s = pd.to_numeric(panel.loc[q, col], errors="coerce").dropna()
            if s.empty:
                continue
            rows.append({
                "label": label, "horizon_months": h, "n": int(len(s)),
                "mean": float(s.mean()), "sd": float(s.std()),
                "p10": float(s.quantile(0.10)), "p25": float(s.quantile(0.25)),
                "median": float(s.median()), "p75": float(s.quantile(0.75)),
                "p90": float(s.quantile(0.90)), "p99": float(s.quantile(0.99)),
                "share_zero": float((s == 0).mean()),
            })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=Path,
                    default=Path("data/raw/usaspending/panel.parquet"))
    ap.add_argument("--out", type=Path, default=Path("usaspending/results"))
    ap.add_argument("--log", type=Path, default=Path("usaspending/logs/models.log"))
    ap.add_argument("--perm-sample", type=int, default=40_000)
    ap.add_argument("--perm-repeats", type=int, default=3)
    ap.add_argument("--labels", type=str, default=",".join(BINARY_LABELS))
    ap.add_argument("--horizons", type=str, default="12,24,36")
    a = ap.parse_args()

    a.log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(a.log, "a")

    def log(msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}"
        print(line, flush=True)
        handle.write(line + "\n")
        handle.flush()

    t0 = time.time()
    panel = pd.read_parquet(a.panel)
    log(f"panel rows {len(panel)}")
    a.out.mkdir(parents=True, exist_ok=True)

    base_rates_table(panel).to_csv(a.out / "base_rates.csv", index=False)
    leak_comparison_table(panel).to_csv(a.out / "leak_comparison.csv", index=False)
    continuous_summary(panel).to_csv(a.out / "continuous_label_summary.csv", index=False)
    log("wrote base_rates.csv and continuous_label_summary.csv")

    masks = split_masks(panel)
    maps = F.fit_category_maps(panel[masks["train"]])
    (a.out / "category_cardinality.json").write_text(json.dumps(
        {c: len(v) for c, v in maps.items()}, indent=1))

    # published reference-class table: ceiling growth over 25 percent at 36 months
    rc_panel = panel[panel["qualifies_36"].astype(bool)
                     & panel["ceiling_growth_gt25_36"].notna()]
    rc_masks = split_masks(rc_panel)
    rc = ReferenceClassModel().fit(
        rc_panel[rc_masks["train"]],
        pd.Series(rc_panel.loc[rc_masks["train"], "ceiling_growth_gt25_36"].to_numpy()))
    tab = rc.cell_table()
    tab.insert(0, "label", "ceiling_growth_gt25")
    tab.insert(1, "horizon_months", 36)
    tab.to_csv(a.out / "reference_class_table.csv", index=False)
    log(f"wrote reference_class_table.csv rows={len(tab)}")

    labels = [x for x in a.labels.split(",") if x]
    horizons = [int(x) for x in a.horizons.split(",") if x]
    results = []
    for label in labels:
        for h in horizons:
            try:
                results.append(run_cell(panel, label, h, maps, a.perm_sample,
                                        a.perm_repeats, log))
            except Exception as exc:  # noqa: BLE001
                log(f"ERROR {label} H={h}: {exc}")
                results.append({"label": label, "horizon": h, "error": str(exc)})
            (a.out / "model_results.json").write_text(json.dumps(results, indent=1))
    log(f"done in {time.time()-t0:.0f}s -> {a.out/'model_results.json'}")
    handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
