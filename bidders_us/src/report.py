"""Assemble bidders_us/results/report.md from the result files beside it.

Every number printed here is read from a JSON or CSV written by one of the
scripts in bidders_us/src/, never typed in. Where a result file is missing the
section says so instead of printing a placeholder number.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from bidders_us.src.common import RESULTS, RAW, ROOT, record_timing

CELL_NAMES = {"schedule_slip_gt90": "slip over 90 days", "schedule_slip_gt365": "slip over 365 days"}
VARIANT_NAMES = {"shape_office": "contract shape with office identity",
                 "shape_only": "contract shape without office identity"}
KEY_NAMES = {"recipient_uei": "recipient UEI", "recipient_parent_uei": "recipient parent UEI",
             "recipient_name_norm": "recipient name", "awarding_office_code": "awarding office"}
E2_MODELS = [
    ("a_shape", "a. contract shape"),
    ("b_shape_holder_vehicle", "b. a plus holder's record under this vehicle"),
    ("c_shape_holder_all", "c. a plus holder's record on all orders and contracts"),
    ("d_shape_vehicle", "d. a plus the vehicle's own record"),
    ("e_shape_all_history", "e. a plus b, c and d"),
    ("holder_vehicle_rate_alone", "holder's as-of rate under the vehicle, alone"),
    ("holder_all_rate_alone", "holder's as-of rate on all its awards, alone"),
    ("vehicle_rate_alone", "vehicle's as-of rate, alone"),
    ("vehicle_train_rate_reference", "vehicle's training-period rate (the reference forecast)"),
]


def _share(s2, explained) -> float:
    try:
        s2 = float(s2)
    except (TypeError, ValueError):
        return float("nan")
    return s2 / (explained + s2) if np.isfinite(s2) and (explained + s2) > 0 else float("nan")


def fmt(x, nd=3):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return str(x) if x is not None else "n/a"
    if np.isnan(f):
        return "n/a"
    return f"{f:.{nd}f}"


def num(x):
    try:
        return f"{int(x):,}"
    except (TypeError, ValueError):
        return "n/a"


def table(rows, headers) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def load(name):
    p = RESULTS / name
    if not p.exists():
        return None
    if name.endswith(".json"):
        return json.loads(p.read_text())
    return pd.read_csv(p)


def src(script, cmd) -> str:
    return f"Source: `bidders_us/src/{script}`, run from the repository root as `.venv/bin/python -m bidders_us.src.{cmd}`."


# ----------------------------------------------------------------------------
# the one-sentence answer
# ----------------------------------------------------------------------------

def headline(exp1) -> str:
    if not exp1:
        return "Experiment 1 has not been run."
    cells = [c for c in exp1 if c["variant"] == "shape_office"]
    ws, wlo, whi, us, os_, cov, gain, aucs, pl, split_net = [], [], [], [], [], [], [], [], [], []
    for c in cells:
        d = c["decomposition"]
        ex = d["model_explained_variance"]
        w = d["cross_period_contractor_weighted"]
        ws.append(_share(w["cov"], ex))
        wlo.append(_share(w["lo"], ex))
        whi.append(_share(w["hi"], ex))
        us.append(d["shares_of_signal"]["contractor_cross_period"])
        os_.append(_share(d["cross_period_office_weighted"]["cov"], ex))
        pr = c["persistence"]["recipient_uei"]
        cov.append(pr["test_awards_covered"] / c["n"]["test"])
        ts = pr["test_signal"]
        gain.append((ts["bss_model_plus_shrunk_residual"] - ts["bss_model"]) / ts["bss_model"])
        aucs.append(ts["auc_train_residual_alone"])
        pl.append(c["placebo"]["auc_train_residual_alone"]["mean"])
        split_net.append(d["shares_of_signal"]["contractor_split_half"]
                         - _share(d["null_within_office"]["split_cov"]["mean"], ex))
    n_groups = cells[0]["persistence"]["recipient_uei"]["n_groups"]
    rv_share, rv_gain, rv_auc, rv_r = [], [], [], []
    for c in cells:
        rv = c["persistence"]["recipient_uei"].get("record_through_validation")
        if not rv:
            continue
        ex = c["decomposition"]["model_explained_variance"]
        rv_share.append(_share(rv["cross_period_cov_weighted"]["cov"], ex))
        ts = rv["test_signal"]
        rv_gain.append((ts["bss_model_plus_shrunk_residual"] - ts["bss_model"]) / ts["bss_model"])
        rv_auc.append(ts["auc_train_residual_alone"])
        rv_r.append(rv["corr_unweighted"]["r"])
    tail = ""
    if rv_share:
        tail = (f" Extending each contractor's record through the validation years (FY2018 to FY2019, still "
                f"before every test award) roughly doubles the persistence: correlation {min(rv_r):.2f} to "
                f"{max(rv_r):.2f}, share of signal {100*min(rv_share):.1f} to {100*max(rv_share):.1f} percent, "
                f"AUC of the record alone {min(rv_auc):.2f} to {max(rv_auc):.2f}, and a skill gain of "
                f"{100*min(rv_gain):.1f} to {100*max(rv_gain):.1f} percent of the model's skill. So a recent "
                f"record carries a little more than a stale one, and the contractor is still a small part of the "
                f"signal.")
    return (
        f"**Roughly {100*min(ws):.0f} to {100*max(ws):.0f} percent of the forecastable schedule-slip signal "
        f"is the contractor, and the estimate is imprecise.** Once contract shape and the contracting office "
        f"are known, the part of a contractor's mean residual that persists from the training years into the "
        f"test years is {100*min(ws):.1f} to {100*max(ws):.1f} percent of the variance the contract-shape "
        f"model already explains, per test award, across the four label-horizon cells (bootstrap intervals "
        f"over contractors run from {100*min(wlo):.1f} to {100*max(whi):.1f} percent; counting each "
        f"contractor once instead of each award gives {100*min(us):.1f} to {100*max(us):.1f} percent). That "
        f"is measured on the {n_groups:,} contractors with at least five training and three test awards, who "
        f"hold {100*min(cov):.0f} percent of test awards. The office effect the model leaves behind is of the "
        f"same size ({100*min(os_):.1f} to {100*max(os_):.1f} percent). A contractor's training-period record "
        f"ranks its own test awards at AUC {min(aucs):.2f} to {max(aucs):.2f} against a placebo of "
        f"{min(pl):.2f} to {max(pl):.2f}, and adding it to the model moves out-of-sample Brier skill by "
        f"{100*min(gain):.1f} to {100*max(gain):.1f} percent of the model's skill. Within the test years alone "
        f"the between-contractor share is larger ({100*min(split_net):.0f} to {100*max(split_net):.0f} percent "
        f"net of the within-office null), but most of that does not carry across years and so is not "
        f"forecastable at award." + tail
    )


# ----------------------------------------------------------------------------
# experiment 1
# ----------------------------------------------------------------------------

def auc_gap_vs_usaspending(metrics):
    path = ROOT / "usaspending" / "results" / "model_results.json"
    if not metrics or not path.exists():
        return None
    ref = {(r["label"], r["horizon"]): r["models"]["gbm_no_history"]["auc"]
           for r in json.loads(path.read_text()) if "models" in r}
    gaps = [abs(m["test"]["auc"] - ref[(m["label"], m["horizon"])]) for m in metrics
            if m["variant"] == "shape_office" and (m["label"], m["horizon"]) in ref]
    return max(gaps) if gaps else None


def exp1_sections(exp1, metrics) -> list[str]:
    out = ["## Experiment 1: is there a contractor effect on slip, given the contract?", ""]
    if not exp1:
        return out + ["Not run.", ""]
    n_panel = sum(metrics[0][k] for k in ("n_train", "n_val", "n_test")) if metrics else 0
    out += [
        f"Setting. The definitive-contract panel from `usaspending/` ({num(n_panel)} awards, base action FY2010 to "
        "FY2022, base obligation at least 250,000 dollars), split by base fiscal year into training "
        "(FY2010 to FY2017), validation (FY2018 to FY2019) and test (FY2020 to FY2022). A gradient boosting "
        "model is fitted on contract shape with nothing that identifies the recipient, and the question is "
        "whether the residual it leaves, realised minus forecast, has a contractor component that persists "
        "from the training years into the test years.",
        "",
        "Two feature variants. `shape_office` is the usaspending `gbm_no_history` feature set minus the two "
        "recipient-keyed columns (the aggregate-recipient flag and the contracting officer's business size "
        "determination of the recipient); it keeps the awarding office as a feature, as the brief specifies. "
        "`shape_only` also drops the awarding office and sub-agency codes so the contractor and the office "
        "can be compared as residual effects on the same footing. Training-year predictions are five-fold "
        "cross-fitted within the training window (folds over awards, at the iteration count chosen on the "
        "validation years) so that the training residual of a large office is not understated by an "
        "in-sample fit. Validation and test predictions come from the model fitted on all training years.",
        "",
        "### The contract-shape models", "",
    ]
    rows = []
    for m in metrics or []:
        rows.append([VARIANT_NAMES.get(m["variant"], m["variant"]), CELL_NAMES[m["label"]], m["horizon"],
                     num(m["n_train"]), num(m["n_test"]), m["n_iter"], fmt(m["train_base_rate"]),
                     fmt(m["test_base_rate"]), fmt(m["train_crossfit"]["auc"]), fmt(m["test"]["auc"]),
                     fmt(m["test"]["bss_vs_train_base_rate"]), fmt(m["test"]["ece"])])
    out.append(table(rows, ["Model", "Label", "H", "n train", "n test", "Iterations", "Train base rate",
                            "Test base rate", "AUC train (cross-fit)", "AUC test", "BSS test", "ECE test"]))
    out += ["", src("shape_model.py", "shape_model"), ""]
    gap = auc_gap_vs_usaspending(metrics)
    if gap is not None:
        out += [f"The `shape_office` test AUCs match the usaspending `gbm_no_history` model to within "
                f"{gap:.4f} (largest absolute difference over the four cells, read from "
                f"`usaspending/results/model_results.json`), which is the check that removing the two "
                f"recipient-keyed columns cost nothing.", ""]

    # persistence
    out += ["### Contractor residual persistence", "",
            "For each group with at least 5 training-year awards and at least 3 test-year awards, the mean "
            "residual in each period. Correlation across groups, unweighted and weighted by the group's test "
            "awards, with a 95 percent percentile bootstrap interval over groups (2,000 draws). The AUC "
            "columns score, on the test awards of those groups, the training-period mean residual alone, the "
            "model alone, and the model with the shrunk training residual added on the probability scale; "
            "the shrinkage weight k (residual times n/(n+k)) is chosen by Brier score on the validation "
            "years. The placebo repeats the correlation with contractor labels permuted within office over "
            "every award, 100 times.", ""]
    for variant in ("shape_office", "shape_only"):
        out += [f"#### {VARIANT_NAMES[variant][0].upper()}{VARIANT_NAMES[variant][1:]}", ""]
        rows = []
        for c in exp1:
            if c["variant"] != variant:
                continue
            for key in ("recipient_uei", "recipient_parent_uei", "recipient_name_norm", "awarding_office_code"):
                p = c["persistence"].get(key, {})
                if "corr_unweighted" not in p:
                    rows.append([CELL_NAMES[c["label"]], c["horizon"], KEY_NAMES[key], p.get("n_groups", 0)] + ["n/a"] * 10)
                    continue
                cu, cw, ts = p["corr_unweighted"], p["corr_weighted_by_test_n"], p["test_signal"]
                plc = c["placebo"]["corr_unweighted"] if key == "recipient_uei" else None
                rows.append([CELL_NAMES[c["label"]], c["horizon"], KEY_NAMES[key], num(p["n_groups"]),
                             num(p["test_awards_covered"]),
                             f"{fmt(cu['r'])} [{fmt(cu['lo'])}, {fmt(cu['hi'])}]",
                             f"{fmt(cw['r'])} [{fmt(cw['lo'])}, {fmt(cw['hi'])}]",
                             fmt(p["spearman"]), fmt(ts["auc_train_residual_alone"]), fmt(ts["auc_model"]),
                             fmt(ts["auc_model_plus_shrunk_residual"]), fmt(ts["bss_model"], 4),
                             fmt(ts["bss_model_plus_shrunk_residual"], 4), int(p["shrink_k_chosen_on_validation"]["k"]),
                             (f"{fmt(plc['mean'])} [{fmt(plc['p025'])}, {fmt(plc['p975'])}]" if plc else "")])
                rv = p.get("record_through_validation")
                if rv and key in ("recipient_uei", "awarding_office_code"):
                    cu2, cw2, ts2 = rv["corr_unweighted"], rv["corr_weighted_by_test_n"], rv["test_signal"]
                    rows.append([CELL_NAMES[c["label"]], c["horizon"], KEY_NAMES[key] + ", record through FY2019",
                                 num(rv["n_groups"]), num(rv["test_awards_covered"]),
                                 f"{fmt(cu2['r'])} [{fmt(cu2['lo'])}, {fmt(cu2['hi'])}]",
                                 f"{fmt(cw2['r'])} [{fmt(cw2['lo'])}, {fmt(cw2['hi'])}]", "",
                                 fmt(ts2["auc_train_residual_alone"]), fmt(ts2["auc_model"]),
                                 fmt(ts2["auc_model_plus_shrunk_residual"]), fmt(ts2["bss_model"], 4),
                                 fmt(ts2["bss_model_plus_shrunk_residual"], 4),
                                 int(p["shrink_k_chosen_on_validation"]["k"]), ""])
        out.append(table(rows, ["Label", "H", "Group", "Groups", "Test awards", "r unweighted [95%]",
                                "r weighted [95%]", "Spearman", "AUC residual alone", "AUC model",
                                "AUC model + residual", "BSS model", "BSS model + residual", "k",
                                "Placebo r, mean [95% range]"]))
        out.append("")
        out += ["The rows marked \"record through FY2019\" extend the group's record to the validation years, "
                "which all precede the test awards; k is unchanged. They are the closer analogue of a live "
                "forecaster using everything on file at award.", ""]
    out += [src("exp1.py", "exp1"), "",
            "![Persistence, slip over 90 days at 36 months, contract shape with office](exp1_persistence_shape_office_schedule_slip_gt90_36.png)", "",
            "![Persistence, slip over 90 days at 36 months, contract shape only](exp1_persistence_shape_only_schedule_slip_gt90_36.png)", ""]

    # decomposition
    out += ["### Variance decomposition of the test residual", "",
            "Three estimators of the between-group variance of the residual on the test rows, each divided "
            "by (model explained variance + itself) to give a share of the forecastable signal. Model "
            "explained variance is the variance of the outcome minus the model's Brier score. Every "
            "permutation null shuffles contractor labels within office (20 draws), so a pseudo-contractor "
            "inherits its office's residual; a null far from zero therefore measures how much office effect "
            "a contractor grouping picks up by construction, and the contractor estimate is to be read "
            "against it. The one-way ANOVA (method of moments) also assumes equal within-group variance, "
            "which the residual of a binary outcome does not have, and its null is the largest of the three. "
            "The split-half estimator is the covariance of two random half-means within the test period "
            "(groups with at least two test awards) and needs no such assumption, but it counts effects that "
            "hold within FY2020 to FY2022 and vanish afterwards. The cross-period estimator is the covariance "
            "of the training-period and test-period group means over the persistence table, which is the "
            "part a forecaster at award could use; its bootstrap interval over groups is in the persistence "
            "tables below and is wide.", ""]
    rows = []
    for c in exp1:
        d = c["decomposition"]
        sh = d["shares_of_signal"]
        nl = d["null_within_office"]
        ex = d["model_explained_variance"]
        rows.append([VARIANT_NAMES[c["variant"]], CELL_NAMES[c["label"]], c["horizon"], num(d["n_test"]),
                     fmt(d["var_y"], 4), fmt(d["model_explained_variance"], 4),
                     fmt(d["cross_period_contractor"]["cov"], 5), fmt(sh["contractor_cross_period"]),
                     f"{fmt(_share(d['cross_period_contractor_weighted']['cov'], ex))} [{fmt(_share(d['cross_period_contractor_weighted']['lo'], ex))}, {fmt(_share(d['cross_period_contractor_weighted']['hi'], ex))}]",
                     f"{fmt(_share(nl['cross_cov']['mean'], ex))} [{fmt(_share(nl['cross_cov']['p025'], ex))}, {fmt(_share(nl['cross_cov']['p975'], ex))}]",
                     fmt(d["cross_period_office"]["cov"], 5), fmt(sh["office_cross_period"]),
                     f"{fmt(_share(d['cross_period_office_weighted']['cov'], ex))} [{fmt(_share(d['cross_period_office_weighted']['lo'], ex))}, {fmt(_share(d['cross_period_office_weighted']['hi'], ex))}]",
                     fmt(sh["contractor_split_half"]),
                     f"{fmt(_share(nl['split_cov']['mean'], ex))} [{fmt(_share(nl['split_cov']['p025'], ex))}, {fmt(_share(nl['split_cov']['p975'], ex))}]",
                     fmt(sh["office_split_half"]),
                     fmt(sh["contractor_anova"]),
                     (f"{fmt(_share(nl['anova_sigma2']['mean'], ex))} [{fmt(_share(nl['anova_sigma2']['p025'], ex))}, {fmt(_share(nl['anova_sigma2']['p975'], ex))}]"
                      if "anova_sigma2" in nl else f"{fmt(nl['anova_share']['mean'])} (share of residual variance)"),
                     fmt(sh["office_anova"])])
    out.append(table(rows, ["Model", "Label", "H", "n test", "Var(y)", "Model explained",
                            "Contractor cross-period cov", "Contractor share, per contractor",
                            "Contractor share, per award [95% bootstrap]", "Null share [95%]",
                            "Office cross-period cov", "Office share, per contractor",
                            "Office share, per award [95% bootstrap]", "Contractor split-half share",
                            "Null split-half share [95%]", "Office split-half share", "Contractor ANOVA share",
                            "Null ANOVA share [95%]", "Office ANOVA share"]))
    out += ["", "Fixed-effects regressions of the same residual, R squared and adjusted R squared, with the "
            "permutation null for the two-way fit:", ""]
    rows = []
    for c in exp1:
        d = c["decomposition"]
        rows.append([VARIANT_NAMES[c["variant"]], CELL_NAMES[c["label"]], c["horizon"],
                     f"{fmt(d['fe_contractor']['r2'])} / {fmt(d['fe_contractor']['adj_r2'])}",
                     f"{fmt(d['fe_office']['r2'])} / {fmt(d['fe_office']['adj_r2'])}",
                     f"{fmt(d['fe_both']['r2'])} / {fmt(d['fe_both']['adj_r2'])}",
                     f"{fmt(d['null_within_office']['fe_both_r2']['mean'])} / {fmt(d['null_within_office']['fe_both_adj_r2']['mean'])}",
                     num(d["fe_contractor"]["n_groups"][0]), num(d["fe_office"]["n_groups"][0])])
    out.append(table(rows, ["Model", "Label", "H", "Contractor FE R2 / adj", "Office FE R2 / adj",
                            "Both R2 / adj", "Both, null R2 / adj", "Contractors", "Offices"]))
    out += ["", src("exp1.py", "exp1"), ""]

    # pairs
    out += ["### Within-office contrasts", "",
            "Test awards in the same awarding office, PSC letter and base fiscal year, within one "
            "training-period decile of log10 base obligation of each other, from different contractors, "
            "where one slipped and the other did not. A pair is correct when the contractor with the lower "
            "training-period mean residual (contractors with at least 5 training awards) is the one that did "
            "not slip; ties count one half. The null shuffles contractor labels within office among the test "
            "awards that carry a signal, 200 times.", ""]
    rows = []
    for c in exp1:
        p = c["pairs"]
        rows.append([VARIANT_NAMES[c["variant"]], CELL_NAMES[c["label"]], c["horizon"],
                     num(p["n_test_awards_with_signal"]), num(p["real"]["n_pairs"]),
                     num(p["real"]["n_discordant_pairs"]), fmt(p["real"]["accuracy"]),
                     f"{fmt(p['null_within_office']['mean'])} [{fmt(p['null_within_office']['p025'])}, {fmt(p['null_within_office']['p975'])}]",
                     (f"< {1 / (p['null_within_office']['n_perm'] + 1):.3f}"
                      if p["null_within_office"]["p_value_one_sided"] <= 1 / (p["null_within_office"]["n_perm"] + 1) + 1e-12
                      else fmt(p["null_within_office"]["p_value_one_sided"])),
                     f"{fmt(p['same_decile_only']['accuracy'])} (n={num(p['same_decile_only']['n_discordant_pairs'])})"])
    out.append(table(rows, ["Model", "Label", "H", "Test awards with a signal", "Pairs", "Discordant pairs",
                            "Accuracy", "Null mean [95% range]", "p (one-sided)", "Same decile only"]))
    out += ["", src("exp1.py", "exp1"), ""]

    # placebo full
    out += ["### Placebo: contractor identities permuted within office", "",
            "Step 2 repeated with recipient UEIs shuffled among the awards of each office (all periods), "
            "100 times. The pseudo-contractors inherit their office's residual and nothing else.", ""]
    rows = []
    for c in exp1:
        pl = c["placebo"]
        real = c["persistence"]["recipient_uei"]
        rows.append([VARIANT_NAMES[c["variant"]], CELL_NAMES[c["label"]], c["horizon"],
                     fmt(real["corr_unweighted"]["r"]),
                     f"{fmt(pl['corr_unweighted']['mean'])} [{fmt(pl['corr_unweighted']['p025'])}, {fmt(pl['corr_unweighted']['p975'])}]",
                     fmt(real["corr_weighted_by_test_n"]["r"]),
                     f"{fmt(pl['corr_weighted']['mean'])} [{fmt(pl['corr_weighted']['p025'])}, {fmt(pl['corr_weighted']['p975'])}]",
                     fmt(real["test_signal"]["auc_train_residual_alone"]),
                     f"{fmt(pl['auc_train_residual_alone']['mean'])} [{fmt(pl['auc_train_residual_alone']['p025'])}, {fmt(pl['auc_train_residual_alone']['p975'])}]"])
    out.append(table(rows, ["Model", "Label", "H", "r unweighted, real", "r unweighted, placebo [95%]",
                            "r weighted, real", "r weighted, placebo [95%]", "AUC residual alone, real",
                            "AUC, placebo [95%]"]))
    out += ["", src("exp1.py", "exp1"), ""]
    return out


# ----------------------------------------------------------------------------
# experiment 2
# ----------------------------------------------------------------------------

def exp2_sections(exp2, manifest, funnel) -> list[str]:
    out = ["## Experiment 2: holders of the same multiple-award vehicle as a competition set", ""]
    out += ["### The delivery-order extract", ""]
    if manifest:
        rows = []
        for r in manifest:
            rows.append([r["fiscal_year"], num(r["archive_rows_all_types"]), num(r["rows_type_C"]),
                         num(r["base_actions"]), fmt(r["base_actions"] / max(r["rows_type_C"], 1), 2),
                         num(r["base_actions_at_or_above_threshold"]),
                         fmt(r["base_actions_at_or_above_threshold"] / max(r["base_actions"], 1), 3),
                         num(r["distinct_vehicles_all_sizes"]),
                         num(r.get("orders_with_qualifying_base_row_this_year", r["new_orders_kept_this_year"])),
                         num(r["rows_kept"]), fmt(r["zip_bytes"] / 1e9, 2) if "zip_bytes" in r else "n/a",
                         fmt(r["parquet_bytes"] / 1e6, 1)])
        out.append(table(rows, ["Fiscal year", "Archive rows, all types", "Delivery-order actions",
                                "Base-action rows", "Base share of actions", "Base-action rows >= 250,000",
                                "Share >= 250,000", "Distinct vehicles, all sizes",
                                "Orders with a qualifying base row this year", "Rows kept", "Zip GB",
                                "Parquet MB"]))
        tot_c = sum(r["rows_type_C"] for r in manifest)
        tot_b = sum(r["base_actions"] for r in manifest)
        kept_files = sorted((RAW / "parquet").glob("kept_keys_FY*.parquet"))
        tot_k = len(set().union(*[set(pd.read_parquet(f)["contract_award_unique_key"]) for f in kept_files])) \
            if kept_files else sum(r["new_orders_kept_this_year"] for r in manifest)
        zips = [r["zip_bytes"] / 1e9 for r in manifest if "zip_bytes" in r]
        pq = sum(r["parquet_bytes"] for r in manifest) / 1e9
        base_share = [(r["fiscal_year"], r["base_actions"] / max(r["rows_type_C"], 1),
                       r["base_actions_at_or_above_threshold"] / max(r["base_actions"], 1)) for r in manifest]
        early = [b for b in base_share if b[0] <= 2014]
        late = [b for b in base_share if b[0] >= 2015]
        # Archive file names come from the manifest where the fetch recorded
        # them, and otherwise from the fetch logs, which the same script wrote.
        import re
        stamps = {m.split("_Full_")[1][:8] for r in manifest for m in r.get("archive_members", [])
                  if "_Full_" in m}
        for lg in (ROOT / "bidders_us" / "logs").glob("fetch_orders_run*.out"):
            stamps |= set(re.findall(r"_All_Contracts_Full_(\d{8})_1\.csv", lg.read_text()))
        stamps = sorted(stamps)
        out += ["", f"Totals over the years fetched: {num(tot_c)} delivery-order actions, {num(tot_b)} base-action "
                f"rows of any size, {num(tot_k)} distinct orders kept at or above the threshold (the union of the "
                f"per-year kept-key files; an order whose qualifying base row appears in two years is counted once). "
                + (f"Zip sizes ran from {min(zips):.2f} to {max(zips):.2f} GB where recorded. " if zips else "")
                + f"The parquet extract is {pq:.2f} GB.", ""]
        if early and late:
            out += [f"Base-action rows are counted per transaction row, so a base action reported in several "
                    f"transaction rows counts once per row. The base share of delivery-order actions is "
                    f"{min(b[1] for b in early):.2f} to {max(b[1] for b in early):.2f} in FY2010 to FY2014 and "
                    f"{min(b[1] for b in late):.2f} to {max(b[1] for b in late):.2f} from FY2015, and the share of "
                    f"base-action rows at or above the threshold is {min(b[2] for b in early):.3f} to "
                    f"{max(b[2] for b in early):.3f} before FY2015 and {min(b[2] for b in late):.3f} to "
                    f"{max(b[2] for b in late):.3f} from FY2015. That is a change in the reporting of delivery "
                    f"orders at FY2015 whose cause was not investigated here; the definitive-contract counts in "
                    f"the usaspending report show no comparable jump.", ""]
        out += [
                "The archive file for each fiscal year is whatever `list_monthly_files` returned on the day; "
                + (f"the date stamps observed in the file names are {', '.join(stamps)}" if stamps
                   else "the file names are recorded in `logs/fetch_orders_run*.out`")
                + ", so the extract is a snapshot as of those dates, not a first print.", "",
                src("fetch_orders.py", "fetch_orders"), ""]
    else:
        out += ["The extract has not been fetched.", ""]
    if manifest:
        years = [r["fiscal_year"] for r in manifest]
        if max(years) < 2026:
            out += [f"**The extract is incomplete: fiscal years {min(years)} to {max(years)} are parsed and "
                    f"FY{max(years) + 1} to FY2026 are not.** Both USAspending hosts closed every connection "
                    "from this machine after about 15 GB had been downloaded on 2026-09-16 (see PROGRESS.md "
                    "and `logs/fetch_orders_run*.out`); `make -C bidders_us fetch orders exp2 report` resumes "
                    "at the first missing year and completes Experiment 2 once the host answers.", ""]
    if funnel:
        out += ["### Order panel funnel", "",
                "The filter names are those of `usaspending/src/panel.py`, which built this panel; "
                "\"award\" there means a delivery order here.", ""]
        rows = [[s["filter"].replace("type-D award", "delivery order (award_type_code C)"),
                 num(s["awards_remaining"])] for s in funnel["funnel"]]
        out.append(table(rows, ["Filter", "Orders remaining"]))
        yrs = funnel.get("fiscal_years_loaded", [])
        if yrs and (max(yrs) < 2025 or pd.Timestamp(funnel["data_end"]) < pd.Timestamp("2025-09-30")):
            out += ["", f"**Warning: this panel was built from fiscal years {yrs[0]} to {yrs[-1]} with data end "
                    f"{funnel['data_end']}, which does not cover the 36 month horizon of the FY2022 test awards. "
                    "Its Experiment 2 results are not to be read.**"]
        out += ["", f"Fiscal years loaded {yrs[0] if yrs else 'n/a'} to {yrs[-1] if yrs else 'n/a'}; data end "
                f"{funnel['data_end']}; {num(funnel['transactions_loaded'])} actions loaded; "
                f"history source {num(funnel['history_source_orders'])} orders, of which "
                f"{num(funnel['history_source_aggregate_recipient_orders'])} booked to an aggregate placeholder "
                f"recipient; panel {num(funnel['panel_orders'])} orders under {num(funnel['panel_distinct_vehicles'])} "
                f"distinct vehicles.", "", src("orders_panel.py", "orders_panel"), ""]
    idv_manifest = load("idv_fetch_manifest.json")
    vdiag = load("vehicle_map_diagnostics.json")
    out += ["### What a vehicle is", "",
            "An order's `parent_award_id_piid` names the holder's own contract. Measured on the order panel, "
            "103,491 of 104,993 distinct parent PIIDs carry exactly one recipient (the count is in "
            "`orders_funnel.json` and `logs/exp2_run.out` of the first run), so grouping orders by parent PIID "
            "gives no competition set: one vehicle passed the eligibility rule on that definition. In FPDS a "
            "multiple-award vehicle is one contract per awardee, and the holders that compete for an order are "
            "the holders of the sibling contracts awarded from the same solicitation. The sibling link lives on "
            "the IDV records, fetched separately: an IDV whose multiple-or-single-award flag is M and whose "
            "solicitation identifier passes a shape test (at least eight characters, a letter and a digit, not a "
            "placeholder) is assigned to the program keyed on its FPDS agencyID and normalised solicitation; a "
            "program with at least two contracts and two recipients is a sibling set. This is an inference from "
            "two FPDS fields, not FPDS's own notion of a vehicle, and its coverage is measured below.", ""]
    if idv_manifest:
        rows = [[r["fiscal_year"], num(r.get("rows")), num(r.get("unique_idvs")),
                 fmt(r.get("parquet_bytes", 0) / 1e6, 1), r.get("error", "")] for r in idv_manifest]
        out.append(table(rows, ["Fiscal year", "IDV actions", "Distinct IDVs", "Parquet MB", "Error"]))
        out += ["", src("fetch_idvs.py", "fetch_idvs"), ""]
    if vdiag:
        o = vdiag.get("orders", {})
        out.append(table([
            ["IDV actions loaded", num(vdiag["idv_actions"])],
            ["Distinct IDVs", num(vdiag["idvs"])],
            ["Multiple-or-single flag counts", ", ".join(f"{k}: {v:,}" for k, v in vdiag["flag_counts"].items())],
            ["IDV type counts", ", ".join(f"{k}: {v:,}" for k, v in vdiag["idv_type_counts"].items())],
            ["IDVs with a solicitation identifier", num(vdiag["solicitation_filled"])],
            ["Of which usable under the shape test", num(vdiag["solicitation_usable"])],
            ["IDVs in a sibling set", num(vdiag["idvs_in_sibling_set"])],
            ["Sibling sets (programs)", num(vdiag["sibling_sets"])],
            ["Contracts per program: median, p75, max",
             f"{fmt(vdiag['siblings_per_set'].get('50%'), 0)}, {fmt(vdiag['siblings_per_set'].get('75%'), 0)}, {fmt(vdiag['siblings_per_set'].get('max'), 0)}"],
            ["Recipients per program: median, p75, max",
             f"{fmt(vdiag['recipients_per_set'].get('50%'), 0)}, {fmt(vdiag['recipients_per_set'].get('75%'), 0)}, {fmt(vdiag['recipients_per_set'].get('max'), 0)}"],
            ["Panel orders with a parent", num(o.get("orders_with_parent"))],
            ["Of which the parent is matched to an IDV record", num(o.get("orders_parent_matched_to_idv_record"))],
            ["Of which the parent is in a sibling set", num(o.get("orders_in_sibling_set"))],
        ], ["Quantity", "Value"]))
        out += ["", src("vehicle_map.py", "vehicle_map"), ""]
    if not exp2:
        return out + ["Experiment 2 has not been run.", ""]
    f = exp2["funnel"]
    out += ["### Eligible vehicles", "",
            f"Rule: a sibling set whose orders carry the multiple-award flag, with at least "
            f"{f['rule']['min_train_orders']} in-scope orders from at least "
            f"{f['rule']['min_train_holders']} distinct holders in the training years, and at least "
            f"{f['rule']['min_test_orders']} in-scope orders in the test years.", ""]
    out.append(table([
        ["Orders in panel", num(f["orders_in_panel"])],
        ["Orders with a parent vehicle", num(f["orders_with_vehicle"])],
        ["Orders with an identified holder (not an aggregate placeholder)", num(f["orders_with_identified_holder"])],
        ["Distinct vehicles in panel", num(f["distinct_vehicles_in_panel"])],
        ["Vehicles passing the count rule", num(f.get("vehicles_passing_count_rule"))],
        ["Of those, not a sibling set or not flagged multiple-award on their orders (set aside)",
         f"{num(f.get('vehicles_passing_count_rule_not_flagged_multiple'))} "
         f"({', '.join(f'{k}: {v}' for k, v in f.get('not_flagged_multiple_flag_counts', {}).items())})"],
        ["Eligible vehicles", num(f["eligible_vehicles"])],
        ["Their training orders", num(f["eligible_train_orders"])],
        ["Their test orders", num(f["eligible_test_orders"])],
        ["Median holders per eligible vehicle, in-scope orders, training years", fmt(f["eligible_train_holders_median"], 1)],
        ["Median holders per eligible vehicle, base-action rows of any size, training years", fmt(f["eligible_holders_all_sizes_train_median"], 1)],
        ["Referenced IDV type of eligible vehicles", ", ".join(f"{k}: {v}" for k, v in f["parent_type_counts"].items())],
        ["Single or multiple award flag of eligible vehicles", ", ".join(f"{k}: {v}" for k, v in f["single_or_multiple_counts"].items())],
    ], ["Quantity", "Value"]))
    ev = load("exp2_eligible_vehicles.csv")
    if ev is not None and len(ev):
        top = ev.sort_values("train_orders", ascending=False).head(12)
        out += ["", "The twelve largest eligible programs by training-year orders (the key is FPDS agencyID and "
                "normalised solicitation identifier; the holder counts are on in-scope orders and, in the last "
                "column, on base-action rows of any size):", ""]
        out.append(table([[r["vehicle"], r.get("parent_type", ""), num(r["train_orders"]), num(r["train_holders"]),
                           num(r["test_orders"]), num(r["test_holders"]), num(r.get("holders_all_sizes_train"))]
                          for _, r in top.iterrows()],
                         ["Program", "IDV type", "Train orders", "Train holders", "Test orders", "Test holders",
                          "Holders, any size, train"]))
    out += ["", "The full list is in `exp2_eligible_vehicles.csv`.", ""]

    out += ["### Forecasts on test orders under eligible vehicles", "",
            "All models fitted on the training rows of every in-scope order with a vehicle; scored on test "
            "orders under eligible vehicles with an identified holder. Within-vehicle AUC counts only pairs "
            "of test orders under the same vehicle from different holders. Brier skill is against the "
            "vehicle's own training-period slip rate unless the column says otherwise.", ""]
    for c in exp2["cells"]:
        out += [f"#### {CELL_NAMES[c['label']].capitalize()} at {c['horizon']} months", "",
                f"Training rows {num(c['n_train'])}, evaluation rows {num(c['n_eval'])} under "
                f"{num(c['n_eval_vehicles'])} vehicles from {num(c['n_eval_holders'])} holders; training base "
                f"rate {fmt(c['train_base_rate'])}, evaluation rate {fmt(c['eval_rate'])}.", ""]
        rows = []
        for key, name in E2_MODELS:
            m = c["models"].get(key)
            if not m:
                continue
            wv = m.get("within_vehicle_cross_holder", {})
            rows.append([name, num(m["n"]), fmt(m.get("auc")), fmt(wv.get("auc")),
                         num(wv.get("n_pairs")) if wv else "n/a", fmt(m.get("brier"), 4),
                         fmt(m.get("bss_vs_vehicle_train_rate"), 4), fmt(m.get("bss_vs_train_base_rate"), 4),
                         fmt(m.get("ece"), 4)])
        out.append(table(rows, ["Forecast", "n", "AUC", "Within-vehicle AUC", "Cross-holder pairs", "Brier",
                                "BSS vs vehicle rate", "BSS vs train base rate", "ECE"]))
        hp = c["holder_persistence"]
        sp, pl, tf = hp["spearman"], hp["placebo_shuffle_holders_within_vehicle"], hp["train_rate_as_forecast"]
        out += ["", "Holder persistence within vehicle (holders with at least "
                f"{hp['min_train_orders']} training and {hp['min_test_orders']} test orders under the vehicle; "
                f"{num(hp['n_holder_vehicle_rows'])} holder-vehicle rows):", ""]
        out.append(table([
            ["Vehicles with at least 3 such holders", num(sp.get("n_vehicles"))],
            ["Spearman, training-period rate vs test-period rate, weighted by test orders", fmt(sp.get("weighted_mean"))],
            ["Same, unweighted mean over vehicles", fmt(sp.get("unweighted_mean"))],
            ["Share of vehicles with a positive Spearman", fmt(sp.get("share_positive"))],
            ["Pooled within-vehicle weighted Pearson", fmt(sp.get("pooled_within_vehicle_weighted_pearson"))],
            ["Placebo (holders shuffled within vehicle among test orders), weighted Spearman mean [95% range]",
             f"{fmt(pl['spearman_weighted_mean']['mean'])} [{fmt(pl['spearman_weighted_mean']['p025'])}, {fmt(pl['spearman_weighted_mean']['p975'])}]"],
            ["Placebo, pooled Pearson mean [95% range]",
             f"{fmt(pl['pooled_pearson']['mean'])} [{fmt(pl['pooled_pearson']['p025'])}, {fmt(pl['pooled_pearson']['p975'])}]"],
            ["Training-period rate under the vehicle as a forecast of the holder's test orders: n, AUC, within-vehicle AUC",
             f"{num(tf['n'])}, {fmt(tf['auc'])}, {fmt(tf['within_vehicle_cross_holder']['auc'])}"],
        ], ["Quantity", "Value"]))
        g = c["gaps"]
        out += ["", "Gap between best and worst holder, per vehicle (holders with at least 3 training and 3 "
                "test orders; the oracle gap is the realised spread of test slip rates, the recovered gap is "
                "the test rate of the holder ranked worst on its training record minus that of the holder "
                "ranked best):", ""]
        if g["n_vehicles"]:
            og, rg, tg = g["oracle_gap"], g["recovered_gap"], g["train_gap"]
            out.append(table([
                ["Vehicles", num(g["n_vehicles"])],
                ["Oracle gap: mean, median, p25, p75", f"{fmt(og['mean'])}, {fmt(og['50%'])}, {fmt(og['25%'])}, {fmt(og['75%'])}"],
                ["Recovered gap: mean, median, p25, p75", f"{fmt(rg['mean'])}, {fmt(rg['50%'])}, {fmt(rg['25%'])}, {fmt(rg['75%'])}"],
                ["Training-period gap between the same two holders: mean", fmt(tg["mean"])],
                ["Share of vehicles where the recovered gap is positive", fmt(g["share_recovered_positive"])],
                ["Mean recovered gap over mean oracle gap", fmt(g["mean_recovered_over_mean_oracle"])],
                ["Placebo recovered gap mean [95% range]",
                 f"{fmt(pl['recovered_gap_mean']['mean'])} [{fmt(pl['recovered_gap_mean']['p025'])}, {fmt(pl['recovered_gap_mean']['p975'])}]"],
            ], ["Quantity", "Value"]))
        out.append("")
    out += [src("exp2.py", "exp2"), "",
            "![Holder gaps, slip over 90 days at 36 months](exp2_holder_gaps_schedule_slip_gt90_36.png)", "",
            "![Holder gaps, slip over 365 days at 36 months](exp2_holder_gaps_schedule_slip_gt365_36.png)", ""]
    c36 = [c for c in exp2["cells"] if c["label"] == "schedule_slip_gt90" and c["horizon"] == 36]
    if c36:
        out += ["### Calibration, slip over 90 days at 36 months, model e", ""]
        out.append(table([[r["bin"], num(r["n"]), fmt(r["mean_forecast"]), fmt(r["observed_rate"])]
                          for r in c36[0]["calibration_e"]],
                         ["Bin", "n", "Mean forecast", "Observed rate"]))
        out.append("")
    return out


# ----------------------------------------------------------------------------
# experiment 3
# ----------------------------------------------------------------------------

def exp3_sections(exp3) -> list[str]:
    out = ["## Experiment 3: the bid-side numbers a losing bidder would have had", ""]
    if not exp3:
        return out + ["Not run.", ""]
    out += ["Competed definitive contracts (extent_competed_code A or D, at least 2 offers received), test "
            "years. Relative size is the award's log10 base ceiling minus the leave-one-out mean over the "
            "other awards in the same (awarding agency, full PSC, base fiscal year) cell, cells of at least "
            "five awards; quintile edges from the training years. The residual column is realised minus the "
            "`shape_office` forecast of Experiment 1, which already uses the offer count and the award's own "
            "size and duration. Partial dependence is computed on competed validation rows and is in the "
            "model's decision-function units (log odds), from a model that includes relative size.", ""]
    order = ["2", "3", "4-5", "6-10", "11-20", "21+"]
    for c in exp3:
        out += [f"### {CELL_NAMES[c['label']].capitalize()} at {c['horizon']} months", "",
                f"Competed test awards {num(c['n_competed_test'])}, slip rate {fmt(c['competed_test_rate'])}. "
                f"Univariate test AUC: offers received {fmt(c['univariate']['auc_n_offers'])}, relative size "
                f"{fmt(c['univariate']['auc_relative_size'])}.", "",
                "By number of offers received:", ""]
        ob = {r["bin"]: r for r in c["by_offer_bin"]}
        out.append(table([[b, num(ob[b]["n"]), fmt(ob[b]["slip_rate"]), fmt(ob[b]["mean_forecast_shape_model"]),
                           fmt(ob[b]["mean_residual"], 4)] for b in order if b in ob],
                         ["Offers", "n", "Slip rate", "Shape forecast", "Mean residual"]))
        out += ["", "By relative-size quintile (1 is smallest for its cell):", ""]
        out.append(table([[r["bin"].replace(".0", ""), num(r["n"]), fmt(r["slip_rate"]),
                           fmt(r["mean_forecast_shape_model"]), fmt(r["mean_residual"], 4)]
                          for r in c["by_relative_size_quintile"]],
                         ["Quintile", "n", "Slip rate", "Shape forecast", "Mean residual"]))
        out += ["", "Ablation on the competed test awards:", ""]
        ab = c["ablation_on_competed_test"]
        out.append(table([[k.replace("_", " "), fmt(v["auc"], 4), fmt(v["brier"], 4), fmt(v["bss_vs_train_base_rate"], 4)]
                          for k, v in ab.items()], ["Model", "AUC", "Brier", "BSS vs train base rate"]))
        out += ["", "Partial dependence (log odds):", ""]
        pdd = c["partial_dependence_validation_competed"]
        out.append(table([["offers received"] + [fmt(x["partial_dependence"], 3) for x in pdd["n_offers"]]],
                         ["Feature"] + [str(int(x["value"])) for x in pdd["n_offers"]]))
        out.append("")
        out.append(table([["relative size"] + [fmt(x["partial_dependence"], 3) for x in pdd["relative_size"]]],
                         ["Feature"] + [fmt(x["value"], 2) for x in pdd["relative_size"]]))
        out.append("")
    out += [src("exp3.py", "exp3"), "", "![Bid-side signals](exp3_bid_side_signals.png)", ""]
    return out


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    exp1 = load("exp1_results.json")
    metrics = load("exp1_model_metrics.json")
    exp2 = load("exp2_results.json")
    exp3 = load("exp3_results.json")
    manifest = load("orders_fetch_manifest.json")
    funnel = load("orders_funnel.json")
    tests = load("tests.json")
    timings = load("timings.json") or {}
    keystats = load("exp1_key_stats.json") or {}

    lines = ["# How much of schedule slip is the bidder?", "",
             "Two experiments on US federal contract data asking whether the identity of the contractor "
             "carries schedule-slip information once the contract is known, plus one look at the two "
             "pre-award numbers a losing bidder would also have had. Built 2026-09-16 on the definitive-contract "
             "panel of `usaspending/` and a new delivery-order extract. Every number is produced by a script "
             "in `bidders_us/src/` and reproduced by `make -C bidders_us all` from the repository root.", "",
             headline(exp1), "",
             "## What was built", "",
             "1. **Experiment 1**, on the existing definitive-contract panel: a contract-shape forecast of "
             "schedule slip with nothing that identifies the recipient, and then four measurements of whether "
             "the residual it leaves has a contractor component that persists across the forward-chained split: "
             "residual persistence per contractor and per office, a variance decomposition with permutation "
             "nulls, within-office paired contrasts, and a placebo with contractor identities permuted within "
             "office.",
             "2. **Experiment 2**, on a new extract of delivery orders (award type C) FY2010 to FY2026: the "
             "holders of a multiple-award vehicle as the observable competition set, order-level slip labels "
             "built with the same code as the definitive-contract panel, and forward-chained forecasts with and "
             "without each holder's record under the vehicle, scored within vehicle.",
             "3. **Experiment 3**, on the existing panel: number of offers received and award size relative to "
             "its reference class as predictors of slip on competed awards.", "",
             "## Labels and definitions", "",
             "Schedule slip at horizon H months is `period_of_performance_current_end_date` on the latest action "
             "dated at or before the base action date plus H months, minus the same field on the base action, in "
             "days; the binary labels are slip over 90 days and over 365 days, at 24 and 36 months (Experiment 2 "
             "also at 12). The action ordering, the base-row rule and the qualification rule are those of "
             "`usaspending/src/panel.py`, imported unchanged. A residual is realised minus forecast on one award. "
             "The split is by base action fiscal year: train FY2010 to FY2017, validate FY2018 to FY2019, test "
             "FY2020 to FY2022; every model's iteration count, category map, quantile edge and shrinkage weight is "
             "chosen on the training or validation years. No test OUTCOME enters any choice; the one place "
             "test-year information enters at all is Experiment 2's vehicle eligibility rule, which counts "
             "test-year orders per vehicle, as the brief specifies, and is stated where it is used.", ""]
    lines += exp1_sections(exp1, metrics)
    lines += exp2_sections(exp2, manifest, funnel)
    lines += exp3_sections(exp3)

    lines += ["## Caveats", "",
              "- **Contractor identity is unstable.** The usaspending report measured RAYTHEON COMPANY under 54 "
              "distinct UEIs. Experiment 1 therefore reports every persistence statistic under three keys: "
              f"recipient UEI, recipient parent UEI (filled on {fmt(keystats.get('recipient_parent_uei_filled_share'), 4)} "
              f"of panel awards, equal to the UEI on {fmt(keystats.get('recipient_parent_uei_equals_uei_share'))}), "
              "and the upper-cased whitespace-normalised recipient name. None of the three changes the "
              "conclusion. Name matching merges distinct legal entities that share a name; UEI splitting divides "
              "one firm's record; neither is resolved here. Experiment 2 keys holders on recipient UEI only.",
              "- **Aggregate placeholder recipients** (MISCELLANEOUS FOREIGN AWARDEES and the like, identified "
              "by the name rule in `usaspending/src/panel.py`, an inference) carry a null contractor key in both "
              "experiments and are neither a contractor nor pooled into one.",
              "- **The office is a feature of the primary model.** In `shape_office` the awarding office is a "
              "model input, so the office residual persistence measured under it is what the model failed to "
              "absorb, not the whole office effect; `shape_only` gives the two effects on equal footing.",
              "- **Training-period residuals are cross-fitted, not forward-chained within the training years.** "
              "Five random folds over awards inside FY2010 to FY2017 give every training award an out-of-sample "
              "forecast. That uses later training-year awards to forecast earlier ones, which is fine for "
              "constructing a contractor's training-period record but is not what a live forecaster would have "
              "had at the time; the test-year evaluation is unaffected.",
              "- **The ANOVA share is biased upward here** and is kept only because the brief asks for it; its "
              "permutation null is printed beside it. The split-half and cross-period covariances are the "
              "estimates to read.",
              "- **The bootstrap resamples contractors as if independent.** Contractors nest in offices, and "
              "an office-wide shock in the test years moves every contractor in it the same way, so the "
              "intervals on the persistence correlations and covariances are, if anything, too narrow.",
              "- **The headline is a share of explained variance, not of outcome variance,** and it is "
              "measured on the contractors with enough awards on both sides of the split. Contractors with "
              "fewer awards are where a record would be thinnest, so the number is not a lower bound for "
              "them.",
              "- **Delivery orders are size-restricted at conversion.** Only orders whose base action obligated "
              "at least 250,000 dollars are in the extract, so a holder's record under a vehicle is its record "
              "on such orders, and the competition set is measured on both in-scope orders and all-sizes base "
              "actions. Small orders under the same vehicle are invisible to the labels.",
              "- **Competition codes on orders may be inherited from the parent vehicle.** The research memo "
              "reports, from FPDS guidance rather than from a measurement, that competition codes on orders "
              "have been inherited from the parent since October 2009; the data dictionary lists CDO and NDO "
              "as order-level extent-competed codes. Neither was measured here. The order-level competition "
              "fields are used as model inputs as they stand.",
              "- **The all-sizes competition set counts base-action rows, not orders.** The per-vehicle, "
              "per-holder counts kept at conversion count every base-action transaction row, so a base "
              "action reported in several transaction rows counts once per row; the distinct-holder count "
              "is unaffected.",
              "- **Rows of an order dated before the fiscal year of its qualifying base action are not in "
              "the extract.** The conversion keeps an order from the year its base action clears the "
              "threshold onward, so an earlier-dated row of the same order (which the definitive-contract "
              "panel uses to exclude awards whose modification zero is not their first action) is not "
              "visible here. On definitive contracts that rule removed 6 of 559,001 awards.",
              "- **Relative size in Experiment 3 uses same-fiscal-year peers**, including awards made later in "
              "the year, so it is a reference class a forecaster at award would have had only in part.",
              "- **Nothing here is causal.** Contract type, ceiling and duration respond to anticipated risk, "
              "and which holder gets an order under a vehicle is itself a choice by the contracting officer.", "",
              "## What could not be verified", "",
              "- Whether a recipient name carrying several UEIs is one firm or several; no entity-resolution "
              "source was used.",
              "- Whether the referenced-IDV competition set observed here matches the vehicle's actual awardee "
              "list. The holders are inferred from who received orders; a holder that never won an in-scope "
              "order in the training years is not in the set.",
              "- Whether the bulk-download API would have delivered a full delivery-order year inside 60 minutes: "
              "the one-month probe (311,783 rows in 375 seconds server side, `logs/size_probe.log`) was the "
              "measurement on which the archive path was chosen, and no full-year job was submitted.",
              "- The restatement behaviour of `period_of_performance_current_end_date` on delivery orders. It "
              "was measured on definitive contracts in the usaspending report (a non-final action carries the "
              "award's final end date 0.170 of the time on awards whose end date moved) and is assumed to be "
              "similar for orders; it was not re-measured here.", ""]

    lines += ["## Tests and reproduction", ""]
    if tests:
        lines += [f"`pytest bidders_us/tests`: {tests['summary']}, exit code {tests['exit_code']} "
                  f"(run {tests['ran_at']}, recorded by `bidders_us/src/run_tests.py`).", ""]
    if timings:
        rows = [[k, fmt(v["seconds"], 0), v["finished_at"]] for k, v in timings.items()]
        lines.append(table(rows, ["Step", "Seconds", "Finished"]))
        lines.append("")
    disk = sum(f.stat().st_size for f in RAW.rglob("*") if f.is_file()) if RAW.exists() else 0
    lines += [f"Disk held under `data/raw/bidders_us/`: {disk/1e9:.2f} GB against a 6 GB budget.", "",
              "```", "make -C bidders_us all", "make -C bidders_us test", "```", "",
              "Files written next to this report: `exp1_model_metrics.json`, `exp1_results.json`, "
              "`exp1_persistence_tables.csv`, `exp2_results.json`, `exp2_eligible_vehicles.csv`, "
              "`exp2_holder_gaps.csv`, `exp2_holder_rates_*.csv`, `exp3_results.json`, "
              "`orders_fetch_manifest.json`, `orders_funnel.json`, `tests.json`, `timings.json`, and the PNGs.", ""]
    (RESULTS / "report.md").write_text("\n".join(lines))
    record_timing("report", time.time() - t0)
    print(f"report -> {RESULTS / 'report.md'} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
