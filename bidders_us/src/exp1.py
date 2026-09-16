"""Experiment 1: is there a contractor effect on schedule slip, given the contract?

Reads the out-of-sample predictions written by shape_model.py and runs, for
each label and horizon and for both feature variants:

  2. residual persistence per contractor and per office (group_table,
     bootstrap_corr, signal_on_test in persistence.py), with the shrinkage
     weight chosen on the validation years;
  3. variance decomposition of the test-period residual (anova_between_variance
     and fe_r2), with a permutation null that shuffles contractor labels within
     office;
  4. within-office pairs of test awards (within_cell_pairs) with the same
     permutation null;
  5. the placebo for step 2: contractor identities permuted within office over
     every award, repeated, so the reader can see what persistence looks like
     when the contractor label carries no information beyond the office.

Contractor keys. recipient_uei is the primary key, as in the usaspending
panel. Because one firm can appear under many UEIs (RAYTHEON COMPANY under 54
in that panel), the whole of step 2 is repeated with recipient_parent_uei and
with the upper-cased, whitespace-stripped recipient_name as the key. Awards
booked to an aggregate placeholder recipient (recipient_is_aggregate, an
inference from the name made in usaspending/src/panel.py) carry a null
contractor key here, so they are neither a contractor nor pooled into one.

Writes results/exp1_results.json, results/exp1_persistence_tables.csv and the
persistence scatter PNGs.
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

from bidders_us.src import persistence as P  # noqa: E402
from bidders_us.src.common import (CELLS, RAW, RESULTS, make_logger,  # noqa: E402
                                   record_timing, write_json)

VARIANTS = ("shape_office", "shape_only")
CONTRACTOR_KEYS = ("recipient_uei", "recipient_parent_uei", "recipient_name_norm")
OFFICE_KEY = "awarding_office_code"
MIN_TRAIN, MIN_TEST = 5, 3
N_BOOT = 2000
N_PERM_PAIRS = 200
N_PERM_PLACEBO = 100
N_PERM_DECOMP = 20


def load_predictions(path) -> pd.DataFrame:
    d = pd.read_parquet(path)
    d["recipient_name_norm"] = (d["recipient_name"].astype("string").str.upper()
                                .str.replace(r"\s+", " ", regex=True).str.strip())
    agg = d["recipient_is_aggregate"].astype(float).fillna(0).astype(bool)
    for k in CONTRACTOR_KEYS:
        d.loc[agg, k] = pd.NA
    return d


def cell_frame(d: pd.DataFrame, variant: str, label: str, h: int) -> pd.DataFrame:
    f = d[["contract_award_unique_key", "split", "base_fy", "psc1", "log_base_obligation",
           OFFICE_KEY, *CONTRACTOR_KEYS]].copy()
    f["y"] = d[f"y_{label}_{h}"].astype(float)
    f["p"] = d[f"p_{variant}_{label}_{h}"].astype(float)
    return f.dropna(subset=["y", "p", "split"])


def persistence_block(f: pd.DataFrame, key: str, log) -> tuple[dict, pd.DataFrame]:
    tab = P.group_table(f, key, MIN_TRAIN, MIN_TEST)
    out = {"key": key, "n_groups": int(len(tab)),
           "test_awards_covered": int(tab["n_test"].sum()) if len(tab) else 0,
           "train_awards_covered": int(tab["n_train"].sum()) if len(tab) else 0}
    if len(tab) < 3:
        return out, tab
    out["corr_unweighted"] = P.bootstrap_corr(tab, "resid_train", "resid_test", None, N_BOOT, 0)
    out["corr_weighted_by_test_n"] = P.bootstrap_corr(tab, "resid_train", "resid_test", "n_test", N_BOOT, 0)
    out["spearman"] = P.spearman(tab["resid_train"], tab["resid_test"])
    k = P.choose_shrink_k(f, key, MIN_TRAIN, MIN_TEST)
    out["shrink_k_chosen_on_validation"] = k
    out["test_signal"] = P.signal_on_test(f, key, tab, k["k"])
    # Sensitivity: the group's record extended through the validation years
    # (FY2018 to FY2019), which precede every test award, so the record is
    # more recent and larger. k stays as chosen above, on training against
    # validation, so nothing here is tuned on the rows it is scored on.
    f2 = f.copy()
    f2.loc[f2["split"] == "val", "split"] = "train"
    tab2 = P.group_table(f2, key, MIN_TRAIN, MIN_TEST)
    if len(tab2) >= 3:
        out["record_through_validation"] = {
            "n_groups": int(len(tab2)),
            "test_awards_covered": int(tab2["n_test"].sum()),
            "corr_unweighted": P.bootstrap_corr(tab2, "resid_train", "resid_test", None, N_BOOT, 0),
            "corr_weighted_by_test_n": P.bootstrap_corr(tab2, "resid_train", "resid_test", "n_test", N_BOOT, 0),
            "cross_period_cov_weighted": P.cross_period_covariance(tab2, "n_test"),
            "test_signal": P.signal_on_test(f2, key, tab2, k["k"]),
        }
    return out, tab


def _share(s2, explained) -> float:
    return s2 / (explained + s2) if np.isfinite(s2) and (explained + s2) > 0 else float("nan")


def decomposition_block(f: pd.DataFrame, ckey: str, tab_c: pd.DataFrame, tab_o: pd.DataFrame,
                        rng: np.random.Generator, log) -> dict:
    """Three estimators of the between-group variance of the test residual.

    anova   one-way method of moments on all test rows. It assumes equal
            within-group variance, which a residual of a binary outcome does
            not have, so its permutation null (contractor labels shuffled
            within office) is reported beside it and is not zero.
    split   covariance of two random half-means within the test period, on
            groups with at least two test awards. No equal-variance assumption.
    cross   covariance of the training-period and test-period group means, on
            the groups in the persistence table. This is the part of the group
            effect that persists across the split, which is the only part a
            forecaster registering at award could use.
    Each is converted to a share of the forecastable signal, taking the model's
    explained variance (variance of the outcome minus its Brier score) as the
    rest of the signal.
    """
    te = f[f["split"] == "test"].copy()
    te["resid"] = te["y"] - te["p"]
    var_y = float(te["y"].var(ddof=0))
    brier = float(np.mean(te["resid"] ** 2))
    explained = var_y - brier
    out = {
        "n_test": int(len(te)), "var_y": var_y, "brier": brier,
        "model_explained_variance": explained,
        "anova_contractor": P.anova_between_variance(te["resid"], te[ckey]),
        "anova_office": P.anova_between_variance(te["resid"], te[OFFICE_KEY]),
        "split_half_contractor": P.split_half_between_variance(te, ckey, "resid", rng),
        "split_half_office": P.split_half_between_variance(te, OFFICE_KEY, "resid", rng),
        "cross_period_contractor": P.cross_period_covariance(tab_c),
        "cross_period_contractor_weighted": P.cross_period_covariance(tab_c, "n_test"),
        "cross_period_office": P.cross_period_covariance(tab_o),
        "cross_period_office_weighted": P.cross_period_covariance(tab_o, "n_test"),
        "fe_contractor": P.fe_r2(te["resid"], [te[ckey]]),
        "fe_office": P.fe_r2(te["resid"], [te[OFFICE_KEY]]),
        "fe_both": P.fe_r2(te["resid"], [te[ckey], te[OFFICE_KEY]]),
    }
    out["shares_of_signal"] = {
        "contractor_anova": _share(out["anova_contractor"]["sigma2_between"], explained),
        "office_anova": _share(out["anova_office"]["sigma2_between"], explained),
        "contractor_split_half": _share(out["split_half_contractor"]["cov_unweighted"], explained),
        "office_split_half": _share(out["split_half_office"]["cov_unweighted"], explained),
        "contractor_cross_period": _share(out["cross_period_contractor"]["cov"], explained),
        "office_cross_period": _share(out["cross_period_office"]["cov"], explained),
    }
    # permutation null: contractor labels shuffled within office
    null = {"anova_share": [], "anova_sigma2": [], "split_cov": [], "fe_both_r2": [],
            "fe_both_adj_r2": [], "cross_cov": []}
    for _ in range(N_PERM_DECOMP):
        perm = P.permute_within(te[ckey], te[OFFICE_KEY], rng)
        an = P.anova_between_variance(te["resid"], perm)
        null["anova_share"].append(an["share"])
        null["anova_sigma2"].append(an["sigma2_between"])
        tp = te.assign(**{ckey: perm.to_numpy()})
        null["split_cov"].append(P.split_half_between_variance(tp, ckey, "resid", rng, 5)["cov_unweighted"])
        r = P.fe_r2(te["resid"], [perm, te[OFFICE_KEY]])
        null["fe_both_r2"].append(r["r2"])
        null["fe_both_adj_r2"].append(r["adj_r2"])
        fp = f.assign(**{ckey: P.permute_within(f[ckey], f[OFFICE_KEY], rng).to_numpy()})
        tabp = P.group_table(fp, ckey, MIN_TRAIN, MIN_TEST)
        null["cross_cov"].append(P.cross_period_covariance(tabp)["cov"])
    out["null_within_office"] = {"n_perm": N_PERM_DECOMP}
    for k, v in null.items():
        v = np.array(v, dtype=float)
        out["null_within_office"][k] = {"mean": float(np.nanmean(v)),
                                        "p025": float(np.nanquantile(v, 0.025)),
                                        "p975": float(np.nanquantile(v, 0.975))}
    return out


def pairs_block(f: pd.DataFrame, ckey: str, rng: np.random.Generator, log) -> dict:
    tr = f[f["split"] == "train"]
    edges = np.quantile(tr["log_base_obligation"].dropna(), np.linspace(0.1, 0.9, 9))
    te = f[f["split"] == "test"].copy()
    te["decile"] = np.digitize(te["log_base_obligation"].to_numpy(dtype=float), edges)
    sig = tr.groupby(ckey).agg(n=("y", "size"), s=("y", lambda s: 0.0))
    resid = (tr["y"] - tr["p"]).groupby(tr[ckey]).agg(["size", "mean"])
    resid = resid[resid["size"] >= MIN_TRAIN]["mean"]
    te["signal"] = te[ckey].map(resid)
    cells = [OFFICE_KEY, "psc1", "base_fy"]
    real = P.within_cell_pairs(te, cells, ckey, "signal", "y", "decile", 1)
    same = P.within_cell_pairs(te, cells, ckey, "signal", "y", "decile", 0)
    nulls = []
    has = te["signal"].notna()
    for _ in range(N_PERM_PAIRS):
        tp = te.copy()
        perm_key = P.permute_within(tp.loc[has, ckey], tp.loc[has, OFFICE_KEY], rng)
        tp.loc[has, ckey] = perm_key.to_numpy()
        tp["signal"] = tp[ckey].map(resid)
        nulls.append(P.within_cell_pairs(tp, cells, ckey, "signal", "y", "decile", 1)["accuracy"])
    nulls = np.array(nulls, dtype=float)
    return {
        "cells": cells, "decile_rule": "train-period deciles of log10 base obligation, gap <= 1",
        "real": real, "same_decile_only": same,
        "n_test_awards_with_signal": int(has.sum()),
        "null_within_office": {
            "n_perm": N_PERM_PAIRS, "mean": float(np.nanmean(nulls)),
            "p025": float(np.nanquantile(nulls, 0.025)), "p975": float(np.nanquantile(nulls, 0.975)),
            # (b + 1) / (B + 1): the observed statistic counts as one draw, so
            # the smallest reportable p from 200 permutations is 1/201.
            "p_value_one_sided": (float((np.sum(nulls >= real["accuracy"]) + 1) / (len(nulls) + 1))
                                  if np.isfinite(real["accuracy"]) else float("nan")),
        },
    }


def placebo_block(f: pd.DataFrame, ckey: str, rng: np.random.Generator, log) -> dict:
    """Step 2 again with contractor identities permuted within office, repeated."""
    rs, rws, aucs, ns = [], [], [], []
    for _ in range(N_PERM_PLACEBO):
        fp = f.copy()
        fp[ckey] = P.permute_within(fp[ckey], fp[OFFICE_KEY], rng).to_numpy()
        tab = P.group_table(fp, ckey, MIN_TRAIN, MIN_TEST)
        if len(tab) < 3:
            continue
        rs.append(P.pearson(tab["resid_train"], tab["resid_test"]))
        rws.append(P.pearson(tab["resid_train"], tab["resid_test"], tab["n_test"]))
        aucs.append(P.signal_on_test(fp, ckey, tab, 1.0)["auc_train_residual_alone"])
        ns.append(len(tab))
    return {
        "n_perm": len(rs),
        "corr_unweighted": {"mean": float(np.nanmean(rs)), "p025": float(np.nanquantile(rs, 0.025)),
                            "p975": float(np.nanquantile(rs, 0.975))},
        "corr_weighted": {"mean": float(np.nanmean(rws)), "p025": float(np.nanquantile(rws, 0.025)),
                          "p975": float(np.nanquantile(rws, 0.975))},
        "auc_train_residual_alone": {"mean": float(np.nanmean(aucs)),
                                     "p025": float(np.nanquantile(aucs, 0.025)),
                                     "p975": float(np.nanquantile(aucs, 0.975))},
        "mean_n_groups": float(np.mean(ns)) if ns else float("nan"),
    }


def scatter(tab_c: pd.DataFrame, tab_o: pd.DataFrame, title: str, path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6))
    for ax, tab, name in ((axes[0], tab_c, "Contractor (recipient UEI)"),
                          (axes[1], tab_o, "Awarding office")):
        if len(tab):
            ax.scatter(tab["resid_train"], tab["resid_test"], s=np.sqrt(tab["n_test"]) * 4,
                       alpha=0.35, color="#1f4e79", edgecolor="none")
            r = P.pearson(tab["resid_train"], tab["resid_test"])
            ax.set_title(f"{name}: n={len(tab)}, r={r:.3f}")
        ax.axhline(0, color="grey", lw=0.6)
        ax.axvline(0, color="grey", lw=0.6)
        ax.set_xlabel("Mean residual, training years (realised minus forecast)")
        ax.set_ylabel("Mean residual, test years")
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", default=str(RAW / "exp1_predictions.parquet"))
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--fast", action="store_true", help="fewer permutations, for smoke runs")
    a = ap.parse_args()
    global N_PERM_PAIRS, N_PERM_PLACEBO, N_PERM_DECOMP, N_BOOT
    if a.fast:
        N_PERM_PAIRS, N_PERM_PLACEBO, N_PERM_DECOMP, N_BOOT = 5, 5, 3, 100
    log = make_logger("exp1")
    t0 = time.time()
    d = load_predictions(a.pred)
    log(f"predictions rows {len(d)}")
    raw = pd.read_parquet(a.pred, columns=["recipient_uei", "recipient_parent_uei", "recipient_name"])
    write_json(RESULTS / "exp1_key_stats.json", {
        "panel_awards": int(len(raw)),
        "recipient_parent_uei_filled_share": float(raw["recipient_parent_uei"].notna().mean()),
        "recipient_parent_uei_equals_uei_share": float((raw["recipient_parent_uei"] == raw["recipient_uei"]).mean()),
        "distinct_recipient_uei": int(raw["recipient_uei"].nunique()),
        "distinct_recipient_parent_uei": int(raw["recipient_parent_uei"].nunique()),
        "distinct_recipient_name_norm": int(d["recipient_name_norm"].nunique()),
    })
    results, tables = [], []
    for variant in a.variants.split(","):
        for label, h in CELLS:
            f = cell_frame(d, variant, label, h)
            rng = np.random.default_rng(0)
            res = {"variant": variant, "label": label, "horizon": h,
                   "n": {s: int((f["split"] == s).sum()) for s in ("train", "val", "test")},
                   "persistence": {}}
            tabs = {}
            for key in (*CONTRACTOR_KEYS, OFFICE_KEY):
                blk, tab = persistence_block(f, key, log)
                res["persistence"][key] = blk
                tabs[key] = tab
                t = tab.reset_index().rename(columns={key: "group"})
                t.insert(0, "key", key)
                t.insert(0, "horizon", h)
                t.insert(0, "label", label)
                t.insert(0, "variant", variant)
                tables.append(t)
                log(f"{variant} {label} {h} {key}: n_groups={blk['n_groups']} "
                    f"r={blk.get('corr_unweighted', {}).get('r', float('nan')):.3f} "
                    f"auc_resid={blk.get('test_signal', {}).get('auc_train_residual_alone', float('nan')):.3f}")
            res["decomposition"] = decomposition_block(
                f, "recipient_uei", tabs["recipient_uei"], tabs[OFFICE_KEY], rng, log)
            sh = res["decomposition"]["shares_of_signal"]
            log(f"{variant} {label} {h}: contractor share of signal anova="
                f"{sh['contractor_anova']:.4f} split={sh['contractor_split_half']:.4f} "
                f"cross={sh['contractor_cross_period']:.4f}; office cross="
                f"{sh['office_cross_period']:.4f}")
            res["pairs"] = pairs_block(f, "recipient_uei", rng, log)
            log(f"{variant} {label} {h}: pairs acc={res['pairs']['real']['accuracy']:.4f} "
                f"null={res['pairs']['null_within_office']['mean']:.4f} "
                f"n_disc={res['pairs']['real']['n_discordant_pairs']}")
            res["placebo"] = placebo_block(f, "recipient_uei", rng, log)
            log(f"{variant} {label} {h}: placebo r mean={res['placebo']['corr_unweighted']['mean']:.4f}")
            results.append(res)
            write_json(RESULTS / "exp1_results.json", results)
            scatter(tabs["recipient_uei"], tabs[OFFICE_KEY],
                    f"{label} at {h} months, {variant} model",
                    RESULTS / f"exp1_persistence_{variant}_{label}_{h}.png")
    pd.concat(tables, ignore_index=True).to_csv(RESULTS / "exp1_persistence_tables.csv", index=False)
    record_timing("exp1", time.time() - t0, {"cells": len(results)})
    log(f"done in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
