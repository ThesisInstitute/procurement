"""Second model pass: what the headline number survives.

`model.py` produces the ladder. This module asks the questions that decide
whether the one positive result in it (PAD text alone reaches within-country
AUC 0.573 on the test fold) is real.

Six analyses, each writing its own CSV under results/:

  A  country ablation        country_ablation.csv
     Is the pooled AUC just "which country is this?" Fit a country-only model
     and a text-plus-country model next to the text-only one. A country-only
     model is CONSTANT within a country, so its within-country AUC must come
     out at exactly 0.5; that is the arithmetic check that the within-country
     statistic is doing what it claims.

  B  text coefficients       text_coefficients.csv
     The highest and lowest weighted TF-IDF terms. Descriptive only. These are
     the terms one linear model leans on in one fold, not causes.

  C  skill by test year      skill_by_test_year.csv
     One AUC per test approval year. A skill estimate that lives in one or two
     years is a different claim from one that holds across the fold.

  D  label placebo           placebo_null.csv, placebo_refit.csv
     Two nulls. D1 permutes the test labels WITHIN country and recomputes the
     within-country AUC of the real forecasts, 2,000 times; that is the exact
     null for "the forecast carries no information about outcome beyond
     country", and it gives an empirical p-value rather than a bootstrap
     interval. D2 permutes the FIT-fold labels and refits the text model, which
     tests the whole pipeline: if the pipeline can manufacture skill from noise,
     D2 lands above 0.5.

  E  second label cut        second_label_cut.csv
     The pre-registered cut is outcome >= Moderately Satisfactory. The other
     natural cut on the same six-point scale is outcome >= Satisfactory, which
     is much closer to balanced. If skill exists at only one cut point, say so.

  G  vintage sensitivity     vintage_sensitivity.csv
     src/feature_vintage.py measures `ieg_country_fcs_status` as tracking the
     project's closing period, so model.CAT_FEATURES excludes it. Excluding a
     field on a vintage argument is a judgement, so this refits the two rungs
     that use structured features with the field added back and shows both.

  F  evaluation lag          censoring_by_year.csv, censoring_restricted.csv
     A project enters the IEG ratings table only after it closes and is
     evaluated, a median of eight years after approval. The recent approval
     years in the test fold are therefore not a sample of projects approved in
     those years; they are the subset that finished fast enough to be rated by
     the 2026 snapshot. This measures that and re-scores the model without them.

COST NOTE. Fitting the TF-IDF vocabulary over the corpus takes about two
minutes; fitting a logistic regression on the resulting matrix takes four
seconds. Every analysis here that needs the text matrix therefore reuses one
fit, and the country block is appended with a sparse hstack rather than by
refitting a combined ColumnTransformer. That is an exact equivalence, not an
approximation: the TF-IDF vocabulary is unsupervised and is fitted on the FIT
fold in both constructions.

Run:  .venv/bin/python -m worldbank.src.analysis
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from . import join, metrics, model, scales
from .paths import PROJECTS, RESULTS, WDS

# Reuse the ladder's tuned regularisation strengths rather than tuning again.
# Every extra pass over the validation fold is another researcher degree of
# freedom, and the point of this module is to stress the existing result, not to
# search for a better one. They are read from model_meta.json so the two cannot
# drift apart.
SECOND_CUT = scales.S_OR_BETTER   # outcome >= Satisfactory on the six-point scale
N_PERMUTATIONS = 2000         # D1, permuting test labels within country
N_REFIT_PLACEBO = 20          # D2, refitting on permuted fit-fold labels
PLACEBO_SEED = 20260915
MIN_EVALUATED_SHARE = 0.5     # F, the cohort-coverage floor


# --------------------------------------------------------------------------
# shared setup
# --------------------------------------------------------------------------

def load_folds():
    """The same frame and the same forward-chained folds model.py uses."""
    df = pd.read_parquet(RESULTS / "pad_ieg_join.parquet")
    df = df[df["y_satisfactory"].notna() & df["approval_year"].notna()].copy()
    df = model.attach_text(df)
    df["has_text"] = df["pad_text_chars"] > 0
    cuts = model.choose_splits(df)
    tr, va, te = model.split(df, cuts)
    fit = pd.concat([tr, va], ignore_index=True)
    return df, fit, te, cuts


def text_matrices(fit: pd.DataFrame, te: pd.DataFrame):
    """TF-IDF fitted on the FIT fold only. The single expensive call."""
    pre = ColumnTransformer([("txt", model._text_vec(), "pad_text")])
    return pre.fit_transform(fit), pre.transform(te), pre


def country_matrices(fit: pd.DataFrame, te: pd.DataFrame):
    """One-hot of `ieg_country`, fitted on the FIT fold only.

    `ieg_country` is deliberately NOT in model.CAT_FEATURES; the ladder never
    hands a model the country identity. This block exists only to measure what
    that identity is worth.
    """
    enc = Pipeline([
        ("imp", SimpleImputer(strategy="constant", fill_value="__missing__")),
        ("oh", OneHotEncoder(handle_unknown="ignore")),
    ])
    Xf = enc.fit_transform(fit[["ieg_country"]])
    return sp.csr_matrix(Xf), sp.csr_matrix(enc.transform(te[["ieg_country"]]))


def structured_matrices(fit: pd.DataFrame, te: pd.DataFrame):
    pre = ColumnTransformer([
        ("cat", Pipeline([
            ("imp", SimpleImputer(strategy="constant", fill_value="__missing__")),
            ("oh", OneHotEncoder(handle_unknown="ignore", min_frequency=5)),
        ]), model.CAT_FEATURES),
        ("num", Pipeline([
            ("imp", SimpleImputer(strategy="median")),
            ("sc", StandardScaler()),
        ]), model.NUM_FEATURES),
    ])
    return sp.csr_matrix(pre.fit_transform(fit)), sp.csr_matrix(pre.transform(te))


def evaluate_pair(y, p, countries) -> dict:
    wauc, tab = metrics.within_group_auc(y, p, countries, weight="pairs")
    return {
        "pooled_auc": metrics.auc(y, p),
        "within_country_auc": wauc,
        "brier": metrics.brier(y, p),
        "within_country_rows_excluded": tab.attrs.get("excluded_row_share",
                                                      float("nan")),
    }


# --------------------------------------------------------------------------
# A. country ablation
# --------------------------------------------------------------------------

def country_ablation(fit, te, best_C, Xt_f, Xt_t) -> pd.DataFrame:
    """What the country identity alone is worth, and what text adds to it."""
    y_fit = fit["y_satisfactory"].astype(float).values
    y_te = te["y_satisfactory"].astype(float).values
    countries = te["ieg_country"].values

    Xc_f, Xc_t = country_matrices(fit, te)
    Xs_f, Xs_t = structured_matrices(fit, te)

    variants = {
        "country identity only": (Xc_f, Xc_t, 1.0),
        "PAD text only": (Xt_f, Xt_t, best_C["text_only"]),
        "PAD text + country identity": (sp.hstack([Xt_f, Xc_f]).tocsr(),
                                        sp.hstack([Xt_t, Xc_t]).tocsr(),
                                        best_C["text_only"]),
        "structured + country identity": (sp.hstack([Xs_f, Xc_f]).tocsr(),
                                          sp.hstack([Xs_t, Xc_t]).tocsr(),
                                          best_C.get("structured_only", 3.0)),
    }
    rows = []
    for name, (Xf, Xt, C) in variants.items():
        p = model.fit_predict_matrix(Xf, y_fit, Xt, C=C)
        r = {"model": name, "C": C, "n_features": int(Xf.shape[1])}
        r.update(evaluate_pair(y_te, p, countries))
        rows.append(r)
        print(f"[ablation] {name}: pooled {r['pooled_auc']:.4f} "
              f"within {r['within_country_auc']:.4f}", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "country_ablation.csv", index=False)
    return out


# --------------------------------------------------------------------------
# B. top text coefficients
# --------------------------------------------------------------------------

def text_coefficients(fit, pre, Xt_f, best_C, top: int = 40) -> pd.DataFrame:
    clf = LogisticRegression(max_iter=3000, C=best_C["text_only"],
                             solver="liblinear")
    clf.fit(Xt_f, fit["y_satisfactory"].astype(float).values)
    terms = np.asarray(pre.named_transformers_["txt"].get_feature_names_out())
    coef = clf.coef_.ravel()
    order = np.argsort(coef)
    rows = []
    for rank, i in enumerate(order[::-1][:top], start=1):
        rows.append({"direction": "toward satisfactory", "rank": rank,
                     "term": terms[i], "coefficient": float(coef[i])})
    for rank, i in enumerate(order[:top], start=1):
        rows.append({"direction": "toward unsatisfactory", "rank": rank,
                     "term": terms[i], "coefficient": float(coef[i])})
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "text_coefficients.csv", index=False)
    return out


# --------------------------------------------------------------------------
# C. skill by test year
# --------------------------------------------------------------------------

def skill_by_test_year(te: pd.DataFrame, p: np.ndarray) -> pd.DataFrame:
    d = pd.DataFrame({"year": te["approval_year"].astype(int).values,
                      "y": te["y_satisfactory"].astype(float).values,
                      "p": np.asarray(p)})
    rows = []
    for yr, sub in d.groupby("year"):
        rows.append({
            "approval_year": int(yr), "n": int(len(sub)),
            "n_unsatisfactory": int((sub["y"] == 0).sum()),
            "base_rate": float(sub["y"].mean()),
            "auc_within_year": metrics.auc(sub["y"], sub["p"]),
            "mean_forecast": float(sub["p"].mean()),
        })
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "skill_by_test_year.csv", index=False)
    return out


# --------------------------------------------------------------------------
# D. label placebo
# --------------------------------------------------------------------------

def placebo_permute_within_country(te, p, n_perm=N_PERMUTATIONS,
                                   seed=PLACEBO_SEED):
    """D1. Exact null for "no information beyond country".

    Permuting labels WITHIN each country leaves every country's class counts
    unchanged, so the set of countries usable for a within-country AUC is
    identical in every draw and the null is clean. The observed statistic is
    compared against that null directly.
    """
    y = te["y_satisfactory"].astype(float).values
    g = te["ieg_country"].astype(str).values
    p = np.asarray(p, dtype=float)
    observed, _ = metrics.within_group_auc(y, p, g, weight="pairs")
    rng = np.random.default_rng(seed)
    idx_by_group = [np.flatnonzero(g == k) for k in np.unique(g)]
    idx_by_group = [i for i in idx_by_group if len(i) > 1]
    draws = []
    for _ in range(n_perm):
        yp = y.copy()
        for idx in idx_by_group:
            yp[idx] = rng.permutation(y[idx])
        v, _ = metrics.within_group_auc(yp, p, g, weight="pairs")
        if np.isfinite(v):
            draws.append(v)
    draws = np.asarray(draws)
    # +1 in numerator and denominator is the standard finite-sample correction,
    # so a p-value of exactly zero is never reported from a finite permutation
    # set.
    p_value = float((1 + int((draws >= observed).sum())) / (1 + len(draws)))
    return observed, draws, p_value


def placebo_refit(Xf, Xt, fit, te, C, n_repeats=N_REFIT_PLACEBO,
                  seed=PLACEBO_SEED):
    """D2. Permute the FIT-fold labels, refit, score against the real test labels.

    The TF-IDF vocabulary is unsupervised, so a label permutation cannot change
    the transformer and it is reused. Only the logistic regression is refitted.
    If the pipeline leaks, these land above 0.5.
    """
    y_fit = fit["y_satisfactory"].astype(float).values
    y_te = te["y_satisfactory"].astype(float).values
    g = te["ieg_country"].astype(str).values
    rng = np.random.default_rng(seed + 1)
    rows = []
    for r in range(n_repeats):
        yp = rng.permutation(y_fit)
        p = model.fit_predict_matrix(Xf, yp, Xt, C=C)
        w, _ = metrics.within_group_auc(y_te, p, g, weight="pairs")
        rows.append({"repeat": r, "pooled_auc": metrics.auc(y_te, p),
                     "within_country_auc": w})
        print(f"[placebo-refit] {r + 1}/{n_repeats} within={w:.4f}", flush=True)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# E. second label cut
# --------------------------------------------------------------------------

def second_label_cut(fit, te, best_C, Xt_f, Xt_t, cell_k=10.0) -> pd.DataFrame:
    """outcome >= Satisfactory instead of >= Moderately Satisfactory.

    The regularisation strength is NOT re-tuned for this cut. Reusing the value
    chosen for the pre-registered label keeps this a robustness check rather
    than a second search.
    """
    f, t = fit.copy(), te.copy()
    # Built from the raw rating string through the tested label function, not by
    # thresholding a numeric column, so both cuts go through one code path.
    for d in (f, t):
        d["y2"] = scales.series_label_at_least(
            d["ieg_outcome"], SECOND_CUT).astype(float)
    if f["y2"].isna().any() or t["y2"].isna().any():
        raise RuntimeError("second cut produced null labels on rows that "
                           "already carry a usable primary label")
    y_fit, y_te = f["y2"].values, t["y2"].values
    countries = t["ieg_country"].values

    base = float(y_fit.mean())
    p_base = np.full(len(t), base)
    p_cell, diag = metrics.shrunk_cell_means(f, t, model.CELL_COLS_NO_DECADE,
                                             "y2", k=cell_k)
    rows = [{"model": "(a) base rate (constant, fit fold)",
             **evaluate_pair(y_te, p_base, countries)},
            {"model": "(b2) country x practice cell means, shrunk",
             **evaluate_pair(y_te, p_cell, countries)}]

    p = model.fit_predict_matrix(Xt_f, y_fit, Xt_t, C=best_C["text_only"])
    rows.append({"model": "(d) PAD text only (TF-IDF)",
                 **evaluate_pair(y_te, p, countries)})

    Xs_f, Xs_t = structured_matrices(f, t)
    p = model.fit_predict_matrix(sp.hstack([Xt_f, Xs_f]).tocsr(), y_fit,
                                 sp.hstack([Xt_t, Xs_t]).tocsr(),
                                 C=best_C["text_structured"])
    rows.append({"model": "(c) PAD text + structured fields",
                 **evaluate_pair(y_te, p, countries)})

    out = pd.DataFrame(rows)
    out["fit_base_rate"] = base
    out["test_base_rate"] = float(y_te.mean())
    out["n_test"] = int(len(t))
    out["cell_fallback_share"] = diag["fallback_share"]
    out.to_csv(RESULTS / "second_label_cut.csv", index=False)
    return out


# --------------------------------------------------------------------------
# F. evaluation lag and right-censoring
# --------------------------------------------------------------------------

def censoring_by_year() -> pd.DataFrame:
    """How much of each approval cohort has been evaluated yet.

    Denominator: every project with a QUALIFYING PAD and a board approval date,
    rated or not. That is the population this backtest could ever have drawn
    from, so the ratio is the share of the cohort that had entered the IEG
    ratings table by the 2026 snapshot.
    """
    from .dataset import load_ieg
    pad = pd.read_parquet(WDS / "pad.parquet")
    pj = pd.read_parquet(PROJECTS / "projects.parquet")
    pj["projectid"] = pj["id"].astype(str).str.strip().str.upper()
    approval = pj[["projectid", "boardapprovaldate_exact"]].copy()
    approval["boardapprovaldate"] = pd.to_datetime(
        approval["boardapprovaldate_exact"], errors="coerce")
    approval = approval[["projectid", "boardapprovaldate"]].drop_duplicates(
        "projectid")
    kept, _ = join.qualifying_pad(join.explode_projectids(pad), approval)
    kept = kept[kept["boardapprovaldate"].notna()].copy()
    kept["approval_year"] = kept["boardapprovaldate"].dt.year
    kept["rated"] = kept["projectid"].isin(set(load_ieg()["projectid"]))

    cohort = kept.groupby("approval_year").agg(
        n_with_qualifying_pad=("projectid", "nunique"),
        n_rated=("rated", "sum")).reset_index()
    cohort["evaluated_share"] = cohort["n_rated"] / cohort["n_with_qualifying_pad"]
    cohort["approval_year"] = cohort["approval_year"].astype("Int64")

    joined = pd.read_parquet(RESULTS / "pad_ieg_join.parquet")
    lab = joined[joined["y_satisfactory"].notna()].copy()
    lab["approval_year"] = lab["approval_year"].astype("Int64")
    lab["eval_lag_years"] = (lab["ieg_evaluation_fy"].astype(float)
                             - lab["approval_year"].astype(float))
    per = lab.groupby("approval_year").agg(
        n_labelled=("y_satisfactory", "size"),
        share_satisfactory=("y_satisfactory", "mean"),
        median_implementation_years=("implementation_years", "median"),
        median_eval_lag_years=("eval_lag_years", "median"),
    ).reset_index()

    out = cohort.merge(per, on="approval_year", how="left")
    out = out[out["approval_year"] >= 1996].reset_index(drop=True)
    out.to_csv(RESULTS / "censoring_by_year.csv", index=False)
    return out


def censoring_restricted(te, preds: dict, coverage: pd.DataFrame,
                         min_share: float = MIN_EVALUATED_SHARE) -> pd.DataFrame:
    """Re-score the test fold with the low-coverage approval years removed.

    Years whose evaluated share is below `min_share` are cohorts most of which
    has not been evaluated yet, so the rated members are a fast-closing,
    self-selected subset. Dropping them is not a better estimate; it is a check
    that the headline does not depend on them.
    """
    cov = coverage.set_index("approval_year")["evaluated_share"].to_dict()
    yr = te["approval_year"].astype(int)
    keep_years = sorted(int(y) for y in yr.unique()
                        if float(cov.get(y, 0.0)) >= min_share)
    mask = yr.isin(keep_years).values
    y = te["y_satisfactory"].astype(float).values
    g = te["ieg_country"].astype(str).values
    rows = []
    for name, p in preds.items():
        p = np.asarray(p, dtype=float)
        full = evaluate_pair(y, p, g)
        rest = evaluate_pair(y[mask], p[mask], g[mask])
        rows.append({
            "model": name,
            "n_full": int(len(y)), "n_restricted": int(mask.sum()),
            "pooled_auc_full": full["pooled_auc"],
            "pooled_auc_restricted": rest["pooled_auc"],
            "within_country_auc_full": full["within_country_auc"],
            "within_country_auc_restricted": rest["within_country_auc"],
        })
    out = pd.DataFrame(rows)
    out["min_evaluated_share"] = min_share
    out["years_kept"] = ",".join(str(y) for y in keep_years)
    out.to_csv(RESULTS / "censoring_restricted.csv", index=False)
    return out


# --------------------------------------------------------------------------
# G. post-treatment feature sensitivity
# --------------------------------------------------------------------------

def vintage_sensitivity(fit, te, best_C, Xt_f, Xt_t) -> pd.DataFrame:
    """What excluding the post-treatment FCS field cost, or bought.

    `model.CAT_FEATURES` excludes `ieg_country_fcs_status` because
    src/feature_vintage.py measures it as tracking the project's closing period
    rather than its approval period. Excluding a field on a vintage argument is
    a judgement, so the number it changes is reported rather than asserted to be
    zero: this refits the two rungs that use structured features with the field
    added back, and shows both.
    """
    y_fit = fit["y_satisfactory"].astype(float).values
    y_te = te["y_satisfactory"].astype(float).values
    countries = te["ieg_country"].values
    with_fcs = model.CAT_FEATURES + model.EXCLUDED_POST_TREATMENT_FEATURES

    def matrices(cats, nums=None):
        nums = model.NUM_FEATURES if nums is None else nums
        pre = ColumnTransformer([
            ("cat", Pipeline([
                ("imp", SimpleImputer(strategy="constant",
                                      fill_value="__missing__")),
                ("oh", OneHotEncoder(handle_unknown="ignore", min_frequency=5)),
            ]), cats),
            ("num", Pipeline([
                ("imp", SimpleImputer(strategy="median")),
                ("sc", StandardScaler()),
            ]), nums),
        ])
        return (sp.csr_matrix(pre.fit_transform(fit)),
                sp.csr_matrix(pre.transform(te)))

    rows = []
    variants = [
        ("ex-ante features only (reported ladder)", model.CAT_FEATURES,
         model.NUM_FEATURES),
        ("with ieg_country_fcs_status added back", with_fcs,
         model.NUM_FEATURES),
        # `log_commitment` is kept in the ladder but its vintage is UNKNOWN: the
        # naming convention that was supposed to establish it as approval-time
        # is falsified by the API's own data (see src/dataset.py). Dropping it
        # here shows what rests on it instead of asserting it is harmless.
        ("without log_commitment (vintage unknown)", model.CAT_FEATURES,
         [c for c in model.NUM_FEATURES
          if c not in model.UNKNOWN_VINTAGE_FEATURES]),
    ]
    for tag, cats, nums in variants:
        Xs_f, Xs_t = matrices(cats, nums)
        for rung, (Xf, Xt, C) in {
            "(e) structured only": (Xs_f, Xs_t,
                                    best_C.get("structured_only", 3.0)),
            "(c) text + structured": (sp.hstack([Xt_f, Xs_f]).tocsr(),
                                      sp.hstack([Xt_t, Xs_t]).tocsr(),
                                      best_C["text_structured"]),
        }.items():
            p = model.fit_predict_matrix(Xf, y_fit, Xt, C=C)
            r = {"feature set": tag, "rung": rung}
            r.update(evaluate_pair(y_te, p, countries))
            rows.append(r)
            print(f"[vintage] {tag} / {rung}: pooled {r['pooled_auc']:.4f} "
                  f"within {r['within_country_auc']:.4f}", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "vintage_sensitivity.csv", index=False)
    return out


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def run() -> dict:
    meta = json.loads((RESULTS / "model_meta.json").read_text())
    best_C = {k: float(v) for k, v in meta["best_C"].items()}
    df, fit, te, cuts = load_folds()
    print(f"[folds] fit={len(fit)} test={len(te)} cuts={cuts}", flush=True)

    Xt_f, Xt_t, pre = text_matrices(fit, te)
    y_fit = fit["y_satisfactory"].astype(float).values
    p_text = model.fit_predict_matrix(Xt_f, y_fit, Xt_t, C=best_C["text_only"])
    print(f"[text_only] refit, features={Xt_f.shape[1]:,}", flush=True)

    abl = country_ablation(fit, te, best_C, Xt_f, Xt_t)
    coefs = text_coefficients(fit, pre, Xt_f, best_C)
    by_year = skill_by_test_year(te, p_text)

    observed, draws, p_value = placebo_permute_within_country(te, p_text)
    pd.DataFrame({"within_country_auc": draws}).to_csv(
        RESULTS / "placebo_null.csv", index=False)
    print(f"[placebo-permute] observed={observed:.4f} "
          f"null mean={draws.mean():.4f} p={p_value:.4f}", flush=True)

    refit = placebo_refit(Xt_f, Xt_t, fit, te, C=best_C["text_only"])
    refit.to_csv(RESULTS / "placebo_refit.csv", index=False)

    cut2 = second_label_cut(fit, te, best_C, Xt_f, Xt_t)
    vintage = vintage_sensitivity(fit, te, best_C, Xt_f, Xt_t)
    coverage = censoring_by_year()

    stored = (pd.read_csv(RESULTS / "test_predictions.csv")
              .set_index("projectid").reindex(te["projectid"].values))
    restricted = censoring_restricted(
        te, {"PAD text only": p_text,
             "PAD text + structured": stored["p_text_structured"].values,
             "cell means, shrunk": stored["p_cell_shrunk"].values},
        coverage)

    out = {
        "placebo_permute": {
            "observed_within_country_auc": float(observed),
            "null_mean": float(draws.mean()),
            "null_sd": float(draws.std(ddof=1)),
            "null_p95": float(np.percentile(draws, 95)),
            "n_permutations": int(len(draws)),
            "p_value_one_sided": p_value,
        },
        "placebo_refit": {
            "n_repeats": int(len(refit)),
            "mean_within_country_auc": float(refit["within_country_auc"].mean()),
            "max_within_country_auc": float(refit["within_country_auc"].max()),
            "mean_pooled_auc": float(refit["pooled_auc"].mean()),
        },
        "second_cut": {
            "definition": "outcome >= Satisfactory (six-point >= 5)",
            "fit_base_rate": float(cut2["fit_base_rate"].iloc[0]),
            "test_base_rate": float(cut2["test_base_rate"].iloc[0]),
        },
        "censoring": {
            "n_test_full": int(restricted["n_full"].iloc[0]),
            "n_test_restricted": int(restricted["n_restricted"].iloc[0]),
            "years_kept": restricted["years_kept"].iloc[0],
            "min_evaluated_share": float(restricted["min_evaluated_share"].iloc[0]),
        },
        "best_C_reused": best_C,
        "excluded_post_treatment_features":
            model.EXCLUDED_POST_TREATMENT_FEATURES,
    }
    (RESULTS / "analysis_meta.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return {"ablation": abl, "coefficients": coefs, "by_year": by_year,
            "placebo_refit": refit, "second_cut": cut2, "coverage": coverage,
            "restricted": restricted, "vintage": vintage, "meta": out}


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
