"""Quantile ladder for the continuous labels.

For each continuous label and horizon: a constant forecast at the training-period
quantile, and a HistGradientBoostingRegressor with the pinball loss at the same
quantile. Iterations are chosen on the validation years, exactly as in models.py.
Scored with pinball loss at 0.1, 0.5 and 0.9, plus MAE of the median forecast.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as F  # noqa: E402
import scoring as S  # noqa: E402
from models import (CONTINUOUS_LABELS, HORIZONS, MAX_ITER, prepare_matrix,  # noqa: E402
                    split_masks)

QUANTILES = (0.10, 0.50, 0.90)
REG_KW = dict(learning_rate=0.06, max_leaf_nodes=31, min_samples_leaf=50,
              l2_regularization=1.0, early_stopping=False, random_state=0)


def fit_quantile_gbm(X_tr, y_tr, X_va, y_va, cat_mask, q):
    reg = HistGradientBoostingRegressor(loss="quantile", quantile=q,
                                        categorical_features=cat_mask,
                                        max_iter=MAX_ITER, **REG_KW)
    reg.fit(X_tr, y_tr)
    best_iter, best_loss = 1, float("inf")
    for i, pred in enumerate(reg.staged_predict(X_va), start=1):
        loss = S.pinball_loss(y_va, pred, q)
        if loss < best_loss:
            best_loss, best_iter = loss, i
    if best_iter < MAX_ITER:
        reg = HistGradientBoostingRegressor(loss="quantile", quantile=q,
                                            categorical_features=cat_mask,
                                            max_iter=best_iter, **REG_KW)
        reg.fit(X_tr, y_tr)
    return reg, best_iter, best_loss


def run_cell(panel, label, h, maps, log) -> dict:
    col = f"{label}_{h}"
    qual = panel[f"qualifies_{h}"].astype(bool) & panel[col].notna()
    d = panel[qual].copy()
    if d.empty:
        return {"label": label, "horizon": h, "error": "no qualifying rows"}
    y = pd.to_numeric(d[col], errors="coerce").to_numpy(dtype=float)
    masks = split_masks(d)
    if min(masks[k].sum() for k in ("train", "val", "test")) < 100:
        return {"label": label, "horizon": h, "error": "split too small"}

    lo, hi = np.quantile(y[masks["train"]], [0.01, 0.99])
    yw = np.clip(y, lo, hi)

    X = prepare_matrix(d, maps, use_history=True)
    cat_cols, _ = F.feature_columns(True)
    cat_mask = [c in set(cat_cols) for c in X.columns]

    res = {"label": label, "horizon": h,
           "n_train": int(masks["train"].sum()), "n_val": int(masks["val"].sum()),
           "n_test": int(masks["test"].sum()),
           "train_winsor_low": float(lo), "train_winsor_high": float(hi),
           "quantiles": {}}

    for q in QUANTILES:
        const = float(np.quantile(yw[masks["train"]], q))
        p_const = np.full(int(masks["test"].sum()), const)
        reg, best_iter, best_val = fit_quantile_gbm(
            X[masks["train"]], yw[masks["train"]],
            X[masks["val"]], yw[masks["val"]], cat_mask, q)
        p_gbm = reg.predict(X[masks["test"]])
        yt = yw[masks["test"]]
        entry = {
            "train_constant": const,
            "pinball_constant": S.pinball_loss(yt, p_const, q),
            "pinball_gbm": S.pinball_loss(yt, p_gbm, q),
            "n_iter": int(best_iter),
            "val_pinball_at_selected_iter": float(best_val),
        }
        entry["pinball_skill_vs_constant"] = (
            1.0 - entry["pinball_gbm"] / entry["pinball_constant"]
            if entry["pinball_constant"] > 0 else float("nan"))
        if q == 0.50:
            entry["mae_constant"] = S.mae(yt, p_const)
            entry["mae_gbm"] = S.mae(yt, p_gbm)
            entry["coverage_note"] = "median forecast, so MAE is reported here"
        res["quantiles"][f"{q:.2f}"] = entry
        log(f"{label} H={h} q={q}: pinball const={entry['pinball_constant']:.5f} "
            f"gbm={entry['pinball_gbm']:.5f} "
            f"skill={entry['pinball_skill_vs_constant']:.4f}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=Path,
                    default=Path("data/raw/usaspending/panel.parquet"))
    ap.add_argument("--out", type=Path, default=Path("usaspending/results"))
    ap.add_argument("--log", type=Path,
                    default=Path("usaspending/logs/quantile_models.log"))
    a = ap.parse_args()
    a.log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(a.log, "a")

    def log(msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}"
        print(line, flush=True)
        handle.write(line + "\n")
        handle.flush()

    panel = pd.read_parquet(a.panel)
    masks = split_masks(panel)
    maps = F.fit_category_maps(panel[masks["train"]])
    out = []
    for label in CONTINUOUS_LABELS:
        for h in HORIZONS:
            try:
                out.append(run_cell(panel, label, h, maps, log))
            except Exception as exc:  # noqa: BLE001
                log(f"ERROR {label} H={h}: {exc}")
                out.append({"label": label, "horizon": h, "error": str(exc)})
            (a.out / "quantile_results.json").write_text(json.dumps(out, indent=1))
    log("done")
    handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
