"""Contract-shape gradient boosting for schedule slip, with no contractor identity.

Experiment 1, step 1. Two feature variants, both derived from the usaspending
`gbm_no_history` feature set (usaspending/src/features.py):

  shape_office  gbm_no_history minus every column keyed to the recipient:
                recipient_is_aggregate (a flag on the recipient) and
                contracting_officers_determination_of_business_size_code (the
                contracting officer's size determination of the recipient).
                Office identity stays in, as the brief specifies.
  shape_only    shape_office minus awarding_office_code and
                awarding_sub_agency_code, so that the contractor and the office
                can be compared as residual effects on equal footing. The
                top-tier awarding_agency_code stays in as contract shape.

Fitting follows usaspending/src/models.py exactly (same HistGradientBoosting
settings, iteration count chosen by Brier score on the validation years, refit
on the training years). Predictions:

  train rows  5-fold cross-fitted within the training years: each fold model is
              fit on the other four fifths at the iteration count chosen above
              and predicts the held-out fifth. Folds are drawn at random over
              awards within the training window only; the time split between
              training and test is untouched. In-sample predictions would have
              understated the training-period residuals of every office the
              model can see, which is the quantity Experiment 1 compares.
  val rows    from the full-training-years model. The iteration count was
              chosen on these rows, so their Brier score is mildly optimistic;
              they are reported but nothing is concluded from them.
  test rows   from the full-training-years model, never seen before scoring.

Writes data/raw/bidders_us/exp1_predictions.parquet (one row per panel award,
one column per variant, label and horizon) and results/exp1_model_metrics.json.
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from bidders_us.src.common import (CELLS, PANEL, RAW, RESULTS, make_logger,
                                   record_timing, split_of, write_json)

sys.path.insert(0, str(__import__("bidders_us.src.common", fromlist=["USA_SRC"]).USA_SRC))
import features as F  # noqa: E402
import models as UM  # noqa: E402
import scoring as S  # noqa: E402

RECIPIENT_KEYED = [
    "recipient_is_aggregate",
    "contracting_officers_determination_of_business_size_code",
]
OFFICE_KEYED = ["awarding_office_code", "awarding_sub_agency_code"]

VARIANTS = {
    "shape_office": {"drop": RECIPIENT_KEYED},
    "shape_only": {"drop": RECIPIENT_KEYED + OFFICE_KEYED},
}
N_FOLDS = 5


def variant_columns(variant: str) -> tuple[list, list]:
    cat, num = F.feature_columns(use_history=False)
    drop = set(VARIANTS[variant]["drop"])
    return [c for c in cat if c not in drop], [c for c in num if c not in drop]


def prepare(df: pd.DataFrame, maps: dict, cat: list, num: list) -> pd.DataFrame:
    d = F.apply_category_maps(df[cat], {c: maps[c] for c in cat})
    for c in num:
        d[c] = pd.to_numeric(df[c], errors="coerce")
    return d[cat + num]


def fit_cell(panel: pd.DataFrame, label: str, h: int, variant: str, log) -> tuple[pd.Series, dict]:
    col = f"{label}_{h}"
    ok = panel[f"qualifies_{h}"].astype(bool) & panel[col].notna()
    d = panel[ok]
    y = d[col].to_numpy(dtype=float)
    split = split_of(d["base_fy"])
    tr = (split == "train").to_numpy()
    va = (split == "val").to_numpy()
    te = (split == "test").to_numpy()

    cat, num = variant_columns(variant)
    maps = F.fit_category_maps(d[tr], cat)
    X = prepare(d, maps, cat, num)

    t0 = time.time()
    clf, best_iter, best_val_brier = UM.fit_gbm(X[tr], y[tr], X[va], y[va], set(cat))
    log(f"{variant} {col}: full fit, best_iter={best_iter} val_brier={best_val_brier:.5f} "
        f"({time.time()-t0:.0f}s)")

    p = pd.Series(np.nan, index=d.index, dtype=float)
    p[va] = clf.predict_proba(X[va])[:, 1]
    p[te] = clf.predict_proba(X[te])[:, 1]

    # cross-fitted training predictions
    tr_idx = np.where(tr)[0]
    kf = KFold(n_splits=N_FOLDS, shuffle=True, random_state=0)
    Xtr, ytr = X.iloc[tr_idx], y[tr_idx]
    p_tr = np.full(len(tr_idx), np.nan)
    for k, (fit_i, hold_i) in enumerate(kf.split(tr_idx)):
        m = UM.HistGradientBoostingClassifier(
            categorical_features=[c in set(cat) for c in X.columns],
            max_iter=int(best_iter), **UM.GBM_KW)
        m.fit(Xtr.iloc[fit_i], ytr[fit_i])
        p_tr[hold_i] = m.predict_proba(Xtr.iloc[hold_i])[:, 1]
        log(f"{variant} {col}: fold {k+1}/{N_FOLDS} done ({time.time()-t0:.0f}s)")
    p.iloc[tr_idx] = p_tr

    base_rate = float(y[tr].mean())
    metrics = {
        "label": label, "horizon": h, "variant": variant,
        "n_train": int(tr.sum()), "n_val": int(va.sum()), "n_test": int(te.sum()),
        "features_categorical": cat, "features_numeric": num,
        "n_iter": int(best_iter), "train_base_rate": base_rate,
        "test_base_rate": float(y[te].mean()),
        "train_crossfit": {"brier": S.brier_score(y[tr], p_tr),
                           "bss_vs_train_base_rate": S.brier_skill_score(y[tr], p_tr, base_rate),
                           "auc": S.auc(y[tr], p_tr)},
        "val": {"brier": S.brier_score(y[va], p[va].to_numpy()),
                "auc": S.auc(y[va], p[va].to_numpy())},
        "test": {"brier": S.brier_score(y[te], p[te].to_numpy()),
                 "bss_vs_train_base_rate": S.brier_skill_score(y[te], p[te].to_numpy(), base_rate),
                 "auc": S.auc(y[te], p[te].to_numpy()),
                 "ece": S.calibration_error(y[te], p[te].to_numpy())},
        "seconds": round(time.time() - t0, 1),
    }
    log(f"{variant} {col}: test auc={metrics['test']['auc']:.4f} "
        f"bss={metrics['test']['bss_vs_train_base_rate']:.4f}; "
        f"train crossfit auc={metrics['train_crossfit']['auc']:.4f}")
    return p, metrics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default=str(PANEL))
    ap.add_argument("--out", default=str(RAW / "exp1_predictions.parquet"))
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--cells", default="all",
                    help="comma list like schedule_slip_gt90:24, or all")
    a = ap.parse_args()
    log = make_logger("shape_model")
    t0 = time.time()

    panel = pd.read_parquet(a.panel)
    log(f"panel rows {len(panel)}")
    cells = CELLS if a.cells == "all" else [
        (c.split(":")[0], int(c.split(":")[1])) for c in a.cells.split(",")]

    out = panel[["contract_award_unique_key", "base_fy", "recipient_uei",
                 "recipient_parent_uei", "recipient_name", "awarding_office_code",
                 "awarding_agency_code", "awarding_sub_agency_code", "psc1",
                 "log_base_obligation", "recipient_is_aggregate"]].copy()
    out["split"] = split_of(out["base_fy"])
    metrics = []
    for label, h in cells:
        out[f"y_{label}_{h}"] = panel[f"{label}_{h}"]
        for variant in a.variants.split(","):
            p, m = fit_cell(panel, label, h, variant, log)
            out[f"p_{variant}_{label}_{h}"] = p.reindex(out.index)
            metrics.append(m)
            write_json(RESULTS / "exp1_model_metrics.json", metrics)
    RAW.mkdir(parents=True, exist_ok=True)
    out.to_parquet(a.out, index=False, compression="zstd")
    record_timing("shape_model", time.time() - t0, {"cells": len(metrics)})
    log(f"predictions -> {a.out} in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
