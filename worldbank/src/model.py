"""Forward-chained baselines for IEG outcome >= Moderately Satisfactory.

Splits are by BOARD APPROVAL YEAR, never random, so every model is trained only
on projects approved before the projects it is scored on.

Model ladder:
  (a) base_rate        constant at the train-set base rate
  (b) cell_shrunk      country x approval-decade x sector cell means, shrunk
  (c) text_structured  TF-IDF of PAD text (1-2 grams, min_df=5) + structured
  (d) text_only        TF-IDF of PAD text alone
  (e) structured_only  reported as an ablation so the text contribution is visible

Run:  .venv/bin/python -m worldbank.src.model
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from . import metrics
from .paths import PAD_TEXT, RESULTS

# The pre-registered cell is country x approval-decade x practice group. Under
# forward chaining that cell DEGENERATES: the test fold's decade is, by
# construction, almost absent from the training fold, so most test rows fall back
# to the global mean and the "baseline" stops being a country-sector baseline at
# all. Measured on this data: 904 of 1,522 test rows (59.4%) land in a cell that
# training never saw. Both cells are therefore fitted and both are reported.
CELL_COLS = ["ieg_country", "approval_decade", "ieg_practice_group"]
CELL_COLS_NO_DECADE = ["ieg_country", "ieg_practice_group"]

# EX-ANTE ONLY. Every field here has to have existed at board approval, because
# the whole claim of the backtest is that its inputs predate the outcome. Both
# source tables are 2026 snapshots, so which vintage a field carries is a
# measurement, not an assumption; src/feature_vintage.py makes it and writes
# results/feature_vintage.csv.
#
# EXCLUDED, with the measurement that excluded it:
#   ieg_country_fcs_status. Fragile-state status varies WITHIN a country across
#   projects in 51 of 187 countries, and the variation tracks the project's
#   CLOSING period rather than its approval period. Reproducing the field from a
#   single fiscal-year threshold scores 0.923 from Final Closing FY against
#   0.878 from Approval FY; the closing threshold is exact in 22 countries
#   against 7; and it beats the approval threshold in 29 of 50 countries while
#   the approval threshold beats it in NONE. Burkina Faso is the clean case:
#   every non-FCS project closes 1995-2019 and every FCS project closes
#   2020-2025, while the two groups' approval years overlap almost entirely. A
#   status carried at closing is post-treatment and cannot be an ex-ante input.
#   LIMIT OF THE CLAIM: no World Bank dictionary stating the field's as-of date
#   was found or read, so the cause is not claimed. The field is excluded
#   because its ex-ante status could not be ESTABLISHED, not because a mechanism
#   was proven.
#
# KEPT, WITH THE CAVEAT STATED IN THE REPORT:
#   ieg_country_lending_group takes one value per country in this snapshot (it
#   varies within only 4 of 187 countries), so it is a 2026 country attribute
#   stamped on projects of every vintage. Being country-constant is exactly what
#   the within-country statistic neutralises.
#   ieg_practice_group is the post-2014 Global Practice vocabulary applied to
#   projects of every vintage. The underlying sector is ex ante; the vocabulary
#   is not. The vintage test puts it on the approval side (approval threshold
#   better in 54 of 134 countries against 30 for closing).
CAT_FEATURES = ["ieg_region", "ieg_country_lending_group",
                "ieg_practice_group",
                "ieg_agreement_type", "ieg_lending_instrument_type",
                "prodline_exact", "envassesmentcategorycode"]
# Added back only by the sensitivity rung in src/analysis.py, so the report can
# show what the exclusion changed instead of asserting it did not matter.
EXCLUDED_POST_TREATMENT_FEATURES = ["ieg_country_fcs_status"]
# `log_commitment` has UNKNOWN VINTAGE and is used anyway, with that stated.
# An earlier comment here claimed the `curr_` prefix distinguishes current from
# approval-time amounts. It does not: lendprojectcost equals curr_project_cost
# on 100% of 27,477 rows and idacommamt equals curr_ida_commitment on 100% of
# 13,650, so the two names serve the same number (see src/dataset.py for the
# full measurement and the withdrawal). Nothing establishes any amount field as
# an approval-time value.
#
# It is kept because the Board does approve an amount, so a commitment is the
# most natural ex-ante structured input, and because dropping every field whose
# vintage is merely unestablished (rather than measured as post-treatment, as
# ieg_country_fcs_status was) would leave no structured rung at all.
# src/analysis.py scores the structured rungs without it so the report can show
# what rests on it rather than assert it is harmless.
NUM_FEATURES = ["log_commitment", "approval_year", "pad_lead_days"]
UNKNOWN_VINTAGE_FEATURES = ["log_commitment"]

MAX_TEXT_CHARS = 200_000


def load_text(projectid: str) -> str:
    f = PAD_TEXT / f"{projectid}.txt"
    if not f.exists():
        return ""
    try:
        return f.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_CHARS]
    except OSError:
        return ""


def attach_text(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["pad_text"] = [load_text(p) for p in df["projectid"]]
    df["pad_text_chars"] = df["pad_text"].str.len()
    return df


def choose_splits(df: pd.DataFrame, min_test: int = 800) -> dict:
    """Forward-chained cut points, widened only if the test fold is too small.

    Starts at the pre-registered cuts (train <= 2005, validate 2006-2010,
    test >= 2011) and walks the test boundary EARLIER one year at a time until
    the test fold has at least `min_test` rows. Never moves the boundary later,
    and never reorders the folds.
    """
    train_end, valid_end = 2005, 2010
    while True:
        n_test = int((df["approval_year"] > valid_end).sum())
        n_train = int((df["approval_year"] <= train_end).sum())
        n_valid = int(((df["approval_year"] > train_end)
                       & (df["approval_year"] <= valid_end)).sum())
        if n_test >= min_test or valid_end <= train_end + 1:
            return {"train_end": train_end, "valid_end": valid_end,
                    "n_train": n_train, "n_valid": n_valid, "n_test": n_test,
                    "moved_from_preregistered": (train_end, valid_end) != (2005, 2010)}
        valid_end -= 1


def split(df: pd.DataFrame, cuts: dict):
    tr = df[df["approval_year"] <= cuts["train_end"]]
    va = df[(df["approval_year"] > cuts["train_end"])
            & (df["approval_year"] <= cuts["valid_end"])]
    te = df[df["approval_year"] > cuts["valid_end"]]
    return tr, va, te


def _struct_pipe() -> ColumnTransformer:
    return ColumnTransformer([
        ("cat", Pipeline([
            ("imp", SimpleImputer(strategy="constant", fill_value="__missing__")),
            ("oh", OneHotEncoder(handle_unknown="ignore", min_frequency=5)),
        ]), CAT_FEATURES),
        ("num", Pipeline([
            ("imp", SimpleImputer(strategy="median")),
            ("sc", StandardScaler()),
        ]), NUM_FEATURES),
    ])


def _text_vec() -> TfidfVectorizer:
    return TfidfVectorizer(ngram_range=(1, 2), min_df=5, max_features=300_000,
                           sublinear_tf=True, strip_accents="unicode",
                           lowercase=True, stop_words="english")


def _preprocessor(kind: str):
    """Build the feature transformer for one rung of the ladder."""
    txt = ("txt", _text_vec(), "pad_text")
    cat = ("cat", Pipeline([
        ("imp", SimpleImputer(strategy="constant", fill_value="__missing__")),
        ("oh", OneHotEncoder(handle_unknown="ignore", min_frequency=5)),
    ]), CAT_FEATURES)
    num = ("num", Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("sc", StandardScaler()),
    ]), NUM_FEATURES)
    if kind == "text_only":
        return ColumnTransformer([txt])
    if kind == "structured_only":
        return ColumnTransformer([cat, num])
    if kind == "text_structured":
        return ColumnTransformer([txt, cat, num])
    raise ValueError(kind)


def fit_transform_once(kind: str, tr: pd.DataFrame, te: pd.DataFrame):
    """Fit the transformer on TRAIN ONLY, then transform both folds.

    Fitting once and reusing the matrices across regularisation strengths is
    what makes the C sweep affordable. Crucially the transformer, including the
    TF-IDF vocabulary and the scaler statistics, never sees the fold it is
    scored on.
    """
    pre = _preprocessor(kind)
    Xtr = pre.fit_transform(tr)
    Xte = pre.transform(te)
    return Xtr, Xte


def fit_predict_matrix(Xtr, y, Xte, C: float = 1.0) -> np.ndarray:
    clf = LogisticRegression(max_iter=3000, C=C, solver="liblinear")
    clf.fit(Xtr, y)
    return clf.predict_proba(Xte)[:, 1]


def fit_predict(kind: str, tr: pd.DataFrame, te: pd.DataFrame,
                C: float = 1.0) -> np.ndarray:
    Xtr, Xte = fit_transform_once(kind, tr, te)
    return fit_predict_matrix(Xtr, tr["y_satisfactory"].astype(float).values,
                              Xte, C=C)


def evaluate(name: str, y, p, p_base, p_cell, countries, p_testbase) -> dict:
    """Metrics for one rung.

    Two Brier skill references are reported on purpose. `bss_vs_train_base_rate`
    uses a constant at the TRAINING base rate, which is the only constant a
    forecaster could actually have registered before seeing the test period.
    `bss_vs_test_base_rate` uses a constant at the realised TEST base rate,
    which no forecaster could know but which is the correct zero-information
    benchmark: a model that beats the training constant only because the base
    rate drifted upward scores positive on the first and zero on the second.
    """
    wauc_pairs, t = metrics.within_group_auc(y, p, countries, weight="pairs")
    wauc_n = t.attrs.get("weighted_by_n", float("nan"))
    return {
        "model": name,
        "n": int(len(y)),
        "auc": metrics.auc(y, p),
        "brier": metrics.brier(y, p),
        "bss_vs_train_base_rate": metrics.brier_skill_score(y, p, p_base),
        "bss_vs_test_base_rate": metrics.brier_skill_score(y, p, p_testbase),
        "bss_vs_cell": metrics.brier_skill_score(y, p, p_cell),
        "within_country_auc_pairwt": wauc_pairs,
        "within_country_auc_nwt": wauc_n,
        "within_country_rows_excluded": t.attrs.get("excluded_row_share",
                                                    float("nan")),
    }


def run(min_test: int = 800, cell_k: float = 10.0) -> dict:
    df = pd.read_parquet(RESULTS / "pad_ieg_join.parquet")
    df = df[df["y_satisfactory"].notna() & df["approval_year"].notna()].copy()
    df = attach_text(df)
    df["has_text"] = df["pad_text_chars"] > 0

    cuts = choose_splits(df, min_test=min_test)
    tr, va, te = split(df, cuts)

    # Tune C on the validation fold only. The transformer is fitted on TRAIN and
    # reused across every C, so the validation fold never influences the
    # vocabulary or the scaler.
    best_C, tuning = {}, []
    y_tr = tr["y_satisfactory"].astype(float).values
    y_va = va["y_satisfactory"].astype(float).values
    for kind in ("text_structured", "text_only", "structured_only"):
        Xtr, Xva = fit_transform_once(kind, tr, va)
        scores = {}
        for C in (0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0):
            p = fit_predict_matrix(Xtr, y_tr, Xva, C=C)
            scores[C] = metrics.auc(y_va, p)
            tuning.append({"model": kind, "C": C, "validation_auc": scores[C]})
        best_C[kind] = max(scores,
                           key=lambda c: (scores[c] if not np.isnan(scores[c])
                                          else -1))
        grid = sorted(scores)
        edge = best_C[kind] in (grid[0], grid[-1])
        print(f"[tune] {kind}: "
              f"{({k: round(v, 4) for k, v in scores.items()})} "
              f"-> C={best_C[kind]}"
              f"{'  [WARNING: on grid boundary]' if edge else ''}", flush=True)
    pd.DataFrame(tuning).to_csv(RESULTS / "tuning.csv", index=False)

    # final fit on train + validation, scored on test
    fit = pd.concat([tr, va], ignore_index=True)
    y_te = te["y_satisfactory"].astype(float).values
    countries = te["ieg_country"].values

    base = float(fit["y_satisfactory"].mean())
    p_base = np.full(len(te), base)
    p_cell_decade, diag_decade = metrics.shrunk_cell_means(
        fit, te, CELL_COLS, "y_satisfactory", k=cell_k)
    p_cell, diag_cell = metrics.shrunk_cell_means(
        fit, te, CELL_COLS_NO_DECADE, "y_satisfactory", k=cell_k)
    fallback = {
        "cell_with_decade": diag_decade,
        "cell_no_decade": diag_cell,
        "cell_with_decade_fallback_share": diag_decade["fallback_share"],
        "cell_no_decade_fallback_share": diag_cell["fallback_share"],
    }
    # The zero-information benchmark that no forecaster could have registered.
    p_testbase = np.full(len(te), float(np.mean(y_te)))

    rows = [
        evaluate("(a) base rate (constant, train)", y_te, p_base, p_base,
                 p_cell, countries, p_testbase),
        evaluate("(b) country x decade x practice cell means, shrunk "
                 "(pre-registered; degenerates)",
                 y_te, p_cell_decade, p_base, p_cell, countries, p_testbase),
        evaluate("(b2) country x practice cell means, shrunk (reference class)",
                 y_te, p_cell, p_base, p_cell, countries, p_testbase),
    ]
    preds = {"base_rate": p_base, "cell_shrunk_with_decade": p_cell_decade,
             "cell_shrunk": p_cell}
    label = {"structured_only": "(e) structured fields only (ablation)",
             "text_only": "(d) PAD text only (TF-IDF)",
             "text_structured": "(c) PAD text + structured fields"}
    y_fit = fit["y_satisfactory"].astype(float).values
    for kind in ("text_structured", "text_only", "structured_only"):
        Xf, Xt = fit_transform_once(kind, fit, te)
        p = fit_predict_matrix(Xf, y_fit, Xt, C=best_C[kind])
        preds[kind] = p
        rows.append(evaluate(label[kind], y_te, p, p_base, p_cell, countries,
                             p_testbase))
        print(f"[fit] {kind} done, features={Xf.shape[1]:,}", flush=True)

    table = pd.DataFrame(rows)
    table.to_csv(RESULTS / "model_table.csv", index=False)

    # Calibration for the reference-class baseline and BOTH text rungs. The
    # text-only rung is included because it is the one that beats the
    # zero-information benchmark on Brier, and a forecast that is going to be
    # published has to be judged on its calibration, not only its ranking.
    cal_cell = metrics.calibration_table(y_te, preds["cell_shrunk"])
    cal_cell["model"] = "(b2) cell means, shrunk"
    cal_text = metrics.calibration_table(y_te, preds["text_structured"])
    cal_text["model"] = "(c) PAD text + structured fields"
    cal_only = metrics.calibration_table(y_te, preds["text_only"])
    cal_only["model"] = "(d) PAD text only (TF-IDF)"
    cal = pd.concat([cal_cell, cal_text, cal_only], ignore_index=True)
    cal.to_csv(RESULTS / "calibration.csv", index=False)

    _, wtab = metrics.within_group_auc(y_te, preds["text_structured"], countries)
    wtab.to_csv(RESULTS / "within_country_auc.csv", index=False)

    # Cluster bootstrap over countries. A point estimate near 0.5 with an
    # interval spanning 0.5 is the honest headline, so it is computed and
    # reported rather than left to the reader.
    ci_rows = []
    for name in ("text_structured", "text_only", "cell_shrunk"):
        pt, lo, hi = metrics.cluster_bootstrap_ci(
            y_te, preds[name], countries, stat="within_group_auc", n_boot=400)
        pa, la, ha = metrics.cluster_bootstrap_ci(
            y_te, preds[name], countries, stat="auc", n_boot=400)
        ci_rows.append({"model": name, "within_country_auc": pt,
                        "within_lo": lo, "within_hi": hi,
                        "pooled_auc": pa, "pooled_lo": la, "pooled_hi": ha})
    pd.DataFrame(ci_rows).to_csv(RESULTS / "bootstrap_ci.csv", index=False)
    print(pd.DataFrame(ci_rows).to_string(index=False), flush=True)

    # How much of the "country" control is actually a multi-country aggregate.
    agg_mask = te["ieg_country"].astype(str).str.contains(
        "Africa|Asia|Europe|America|World|Region|Caribbean|Pacific|Eastern|"
        "Western|Southern|Central|Other", case=False, regex=True)
    meta_country = {
        "test_rows_with_aggregate_country_label": int(agg_mask.sum()),
        "share": float(agg_mask.mean()),
    }

    out_pred = te[["projectid", "ieg_country", "approval_year",
                   "y_satisfactory"]].copy()
    for k, v in preds.items():
        out_pred[f"p_{k}"] = v
    out_pred.to_csv(RESULTS / "test_predictions.csv", index=False)

    meta = {
        "cuts": cuts, "best_C": best_C, "cell_k": cell_k,
        "train_base_rate": base,
        "test_base_rate": float(np.mean(y_te)),
        "n_fit": int(len(fit)), "n_test": int(len(te)),
        "test_with_text": int(te["has_text"].sum()),
        "fit_with_text": int(fit["has_text"].sum()),
        **fallback,
        **meta_country,
    }
    (RESULTS / "model_meta.json").write_text(json.dumps(meta, indent=2,
                                                        default=str))
    print(table.to_string(index=False))
    print(json.dumps(meta, indent=2, default=str))
    return {"table": table, "meta": meta}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-test", type=int, default=800)
    ap.add_argument("--cell-k", type=float, default=10.0)
    args = ap.parse_args()
    run(min_test=args.min_test, cell_k=args.cell_k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
