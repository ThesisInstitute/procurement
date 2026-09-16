"""Experiment 2: holders of the same multiple-award vehicle as a competition set.

Premise, from the brief and labelled as such: orders under a multiple-award
indefinite-delivery vehicle are competed among the vehicle's holders, so the
holders are an observable set of competing bidders and each holder's realised
schedule slip on its own orders under the vehicle is public. This script does
not verify that any particular order was competed; what it observes is the
referenced IDV's single-or-multiple-award flag (parent_award_single_or_multiple_code,
M or S in the data dictionary) and which recipients received orders under it.
The question is whether a holder's record forecasts the slip of its next
order under the same vehicle, once the order's own shape is known.

Population. In-scope orders from orders_panel.py (base obligation at least
250,000 dollars, labelled at 12, 24 and 36 months). A vehicle is the program
of sibling IDV contracts that share a solicitation (vehicle_map.py): the
parent PIID on an order names the holder's own contract, measured at one
recipient per parent PIID on 103,491 of 104,993 parents, so grouping by
parent PIID alone yields no competition set at all (one vehicle passed the
rule below on that definition). A vehicle is eligible when it is a sibling
set, its orders carry the multiple-award flag, its in-scope orders in the
training years number at least 30 and come from at least 3 distinct holders,
and its in-scope orders in the test years number at least 10. The
competition set is the distinct recipient UEIs with at least one in-scope
order under the program in the training years; the all-sizes holder count
from the fetch summaries, mapped to the same programs, is reported beside it.

Forecasts, per label and horizon, all fitted on the training rows of every
in-scope order with a vehicle and evaluated on test orders under eligible
vehicles:
  a  contract shape: order size, planned duration, PSC, NAICS, office, agency,
     pricing, competition fields, referenced IDV type and single/multiple flag;
  b  a plus the holder's prior record under THIS vehicle (as-of count of prior
     orders, count resolved, slip rate among resolved);
  c  a plus the holder's prior record on all its in-scope orders and on its
     definitive contracts of any size (usaspending history source);
  d  a plus the vehicle's own prior record (as-of, any holder);
  e  a plus b, c and d together.
As-of means: prior count uses orders with a base date strictly before this
order's base date; the rate uses only orders whose horizon had closed by this
order's base date (holder_history.py, tested).

Scores: overall AUC, within-vehicle cross-holder AUC (vehicle_scoring.py),
Brier skill against the training-period base rate and against the vehicle's
own training-period slip rate, expected calibration error. Holder persistence:
within-vehicle Spearman correlation between a holder's training-period and
test-period slip rate under the vehicle, weighted by test orders, with a
placebo that shuffles holder labels among the vehicle's test orders. Gaps: per
vehicle, the realised best-minus-worst holder test slip rate against the gap
recovered by ranking holders on their training-period rate.
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

from bidders_us.src import holder_history as HH  # noqa: E402
from bidders_us.src import vehicle_map as VM  # noqa: E402
from bidders_us.src import vehicle_scoring as V  # noqa: E402
from bidders_us.src.common import (HISTORY_SOURCE, HORIZONS, LABELS, RAW, RESULTS, USA_SRC,  # noqa: E402
                                   make_logger, record_timing, split_of, write_json)

sys.path.insert(0, str(USA_SRC))
import features as F  # noqa: E402
import models as UM  # noqa: E402
import scoring as S  # noqa: E402

CATEGORICAL = [c for c in F.CATEGORICAL
               if c != "contracting_officers_determination_of_business_size_code"] + [
    "parent_award_type_code", "parent_award_single_or_multiple_code"]
NUMERIC = [c for c in F.NUMERIC if c != "recipient_is_aggregate"]
HIST = {
    "hv": ["hv_prior_count", "hv_resolved_count", "hv_rate"],
    "ha": ["ha_prior_count", "ha_resolved_count", "ha_rate"],
    "v": ["v_prior_count", "v_resolved_count", "v_rate"],
}
VARIANTS = {
    "a_shape": [],
    "b_shape_holder_vehicle": HIST["hv"],
    "c_shape_holder_all": HIST["ha"],
    "d_shape_vehicle": HIST["v"],
    "e_shape_all_history": HIST["hv"] + HIST["ha"] + HIST["v"],
}
MIN_TRAIN_ORDERS, MIN_TRAIN_HOLDERS, MIN_TEST_ORDERS = 30, 3, 10
MIN_HOLDER_TRAIN, MIN_HOLDER_TEST = 3, 3
N_PERM = 100
CELLS = [(lab, h) for lab in LABELS for h in (12,) + tuple(HORIZONS)]


def holder_key(df: pd.DataFrame) -> pd.Series:
    agg = df["recipient_is_aggregate"].astype(float).fillna(0).astype(bool)
    return df["recipient_uei"].astype("string").where(~agg, pd.NA)


def modal_flag(s: pd.Series) -> str:
    vc = s.astype("string").dropna().value_counts()
    return str(vc.index[0]) if len(vc) else "NA"


def eligible_vehicles(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(eligible vehicles, vehicles passing the count rule but not flagged multiple-award)."""
    d = panel.dropna(subset=["vehicle", "holder"])
    tr = d[d["split"] == "train"].groupby("vehicle").agg(
        train_orders=("holder", "size"), train_holders=("holder", "nunique"))
    te = d[d["split"] == "test"].groupby("vehicle").agg(test_orders=("holder", "size"),
                                                         test_holders=("holder", "nunique"))
    t = tr.join(te, how="inner")
    t = t[(t["train_orders"] >= MIN_TRAIN_ORDERS) & (t["train_holders"] >= MIN_TRAIN_HOLDERS)
          & (t["test_orders"] >= MIN_TEST_ORDERS)]
    flag = d[d["vehicle"].isin(t.index)].groupby("vehicle")["parent_award_single_or_multiple_code"].agg(modal_flag)
    t["single_or_multiple"] = flag.reindex(t.index)
    t["is_sibling_set"] = pd.Series(t.index, index=t.index).astype("string").str.startswith("SOL|").fillna(False)
    ok = t["is_sibling_set"] & (t["single_or_multiple"] == "M")
    return t[ok].copy(), t[~ok].copy()


def add_history(panel: pd.DataFrame, hist_orders: pd.DataFrame, hist_d: pd.DataFrame,
                label: str, h: int, log) -> pd.DataFrame:
    col = f"{label}_{h}"
    out = panel.copy()
    q = pd.DataFrame({"date": out["action_date"]}, index=out.index)
    ho = hist_orders.dropna(subset=["holder"])
    # holder under this vehicle
    ev = pd.DataFrame({"group": ho["vehicle"].astype("string") + "|" + ho["holder"].astype("string"),
                       "base_date": ho["action_date"], "value": ho[col]})
    q["group"] = out["vehicle"].astype("string") + "|" + out["holder"].astype("string")
    r = HH.asof_history(ev, q, h)
    out["hv_prior_count"], out["hv_resolved_count"], out["hv_rate"] = (
        r["prior_count"], r["resolved_count"], r["resolved_rate"])
    # holder on all its in-scope orders and all its definitive contracts
    ev = pd.concat([
        pd.DataFrame({"group": ho["holder"].astype("string"), "base_date": ho["action_date"],
                      "value": ho[col]}),
        pd.DataFrame({"group": hist_d["holder"].astype("string"), "base_date": hist_d["action_date"],
                      "value": hist_d[col]}),
    ], ignore_index=True)
    q["group"] = out["holder"].astype("string")
    r = HH.asof_history(ev, q, h)
    out["ha_prior_count"], out["ha_resolved_count"], out["ha_rate"] = (
        r["prior_count"], r["resolved_count"], r["resolved_rate"])
    # the vehicle itself, any holder
    hv = hist_orders.dropna(subset=["vehicle"])
    ev = pd.DataFrame({"group": hv["vehicle"].astype("string"), "base_date": hv["action_date"],
                       "value": hv[col]})
    q["group"] = out["vehicle"].astype("string")
    r = HH.asof_history(ev, q, h)
    out["v_prior_count"], out["v_resolved_count"], out["v_rate"] = (
        r["prior_count"], r["resolved_count"], r["resolved_rate"])
    for k in ("hv", "ha", "v"):
        out.loc[out["holder"].isna() & (k != "v"), [f"{k}_prior_count", f"{k}_resolved_count", f"{k}_rate"]] = np.nan
    log(f"{col}: history added; hv_rate defined on {out['hv_rate'].notna().mean():.3f} of orders, "
        f"ha_rate on {out['ha_rate'].notna().mean():.3f}, v_rate on {out['v_rate'].notna().mean():.3f}")
    return out


def prepare(df: pd.DataFrame, maps: dict, cat: list, num: list) -> pd.DataFrame:
    d = F.apply_category_maps(df[cat], {c: maps[c] for c in cat})
    for c in num:
        d[c] = pd.to_numeric(df[c], errors="coerce")
    return d[cat + num]


def metrics(y, p, base_global, base_vehicle) -> dict:
    return {"n": int(len(y)), "auc": S.auc(y, p), "brier": S.brier_score(y, p),
            "bss_vs_train_base_rate": S.brier_skill_score(y, p, base_global),
            "bss_vs_vehicle_train_rate": S.brier_skill_score(y, p, base_vehicle),
            "ece": S.calibration_error(y, p)}


def run_cell(panel: pd.DataFrame, elig: pd.DataFrame, hist_orders, hist_d, label, h, rng, log) -> dict:
    col = f"{label}_{h}"
    d = panel[panel[f"qualifies_{h}"].astype(bool) & panel[col].notna() & panel["vehicle"].notna()].copy()
    d = add_history(d, hist_orders, hist_d, label, h, log)
    y_all = d[col].to_numpy(dtype=float)
    split = d["split"]
    tr, va, te = [(split == s).to_numpy() for s in ("train", "val", "test")]
    E = te & d["vehicle"].isin(elig.index).to_numpy() & d["holder"].notna().to_numpy()
    base = float(y_all[tr].mean())
    veh_rate = d[tr].groupby("vehicle")[col].mean()
    d["vehicle_train_rate"] = d["vehicle"].map(veh_rate)
    res = {"label": label, "horizon": h, "n_train": int(tr.sum()), "n_val": int(va.sum()),
           "n_test": int(te.sum()), "n_eval": int(E.sum()),
           "n_eval_vehicles": int(d.loc[E, "vehicle"].nunique()),
           "n_eval_holders": int(d.loc[E, "holder"].nunique()),
           "train_base_rate": base, "eval_rate": float(y_all[E].mean()), "models": {}}
    yE = y_all[E]
    vref = d.loc[E, "vehicle_train_rate"].to_numpy(dtype=float)
    maps = F.fit_category_maps(d[tr], CATEGORICAL)
    preds = {}
    for name, hist_cols in VARIANTS.items():
        num = NUMERIC + hist_cols
        X = prepare(d, maps, CATEGORICAL, num)
        t0 = time.time()
        clf, best_iter, _ = UM.fit_gbm(X[tr], y_all[tr], X[va], y_all[va], set(CATEGORICAL))
        p = clf.predict_proba(X[E])[:, 1]
        preds[name] = p
        m = metrics(yE, p, base, vref)
        m["n_iter"] = int(best_iter)
        m["within_vehicle_cross_holder"] = V.within_vehicle_cross_holder_auc(
            d.loc[E].assign(p=p), col, "p")
        res["models"][name] = m
        log(f"{col} {name}: auc={m['auc']:.4f} within={m['within_vehicle_cross_holder']['auc']:.4f} "
            f"bss_veh={m['bss_vs_vehicle_train_rate']:.4f} iter={best_iter} ({time.time()-t0:.0f}s)")
    res["calibration_e"] = S.calibration_table(yE, preds["e_shape_all_history"]).to_dict("records")
    res["calibration_a"] = S.calibration_table(yE, preds["a_shape"]).to_dict("records")
    # the raw histories as forecasts on their own
    for name, colname in (("holder_vehicle_rate_alone", "hv_rate"), ("holder_all_rate_alone", "ha_rate"),
                          ("vehicle_rate_alone", "v_rate")):
        s = d.loc[E, colname].to_numpy(dtype=float)
        ok = np.isfinite(s)
        res["models"][name] = {
            "n": int(ok.sum()), "auc": S.auc(yE[ok], s[ok]),
            "within_vehicle_cross_holder": V.within_vehicle_cross_holder_auc(
                d.loc[E][ok].assign(p=s[ok]), col, "p"),
            "brier": S.brier_score(yE[ok], s[ok]),
            "bss_vs_vehicle_train_rate": S.brier_skill_score(yE[ok], s[ok], vref[ok]),
        }
    res["models"]["vehicle_train_rate_reference"] = {
        "n": int(len(yE)), "auc": S.auc(yE, vref), "brier": S.brier_score(yE, vref),
        "bss_vs_train_base_rate": S.brier_skill_score(yE, vref, base)}

    # holder persistence within vehicle, raw rates
    dd = d[d["vehicle"].isin(elig.index)].dropna(subset=["holder"])
    tab = V.holder_rate_table(dd, col, min_train=MIN_HOLDER_TRAIN, min_test=MIN_HOLDER_TEST)
    sp = V.within_vehicle_spearman(tab, "rate_train", "rate_test")
    gaps = V.holder_gaps(tab)
    te_mask = (dd["split"] == "test").to_numpy()
    null_sp, null_pooled, null_rec = [], [], []
    for _ in range(N_PERM):
        perm = V.permute_holders_within_vehicle(dd, "holder", "vehicle", te_mask, rng)
        tp = V.holder_rate_table(dd.assign(holder=perm), col, min_train=MIN_HOLDER_TRAIN,
                                 min_test=MIN_HOLDER_TEST)
        s_ = V.within_vehicle_spearman(tp, "rate_train", "rate_test")
        null_sp.append(s_.get("weighted_mean", np.nan))
        null_pooled.append(s_.get("pooled_within_vehicle_weighted_pearson", np.nan))
        g_ = V.holder_gaps(tp)
        null_rec.append(float(g_["recovered_gap"].mean()) if len(g_) else np.nan)
    # training-period rate under the vehicle as a forecast of the holder's test orders
    tr_rate = dd[dd["split"] == "train"].groupby(["vehicle", "holder"])[col].agg(["size", "mean"])
    tr_rate = tr_rate[tr_rate["size"] >= MIN_HOLDER_TRAIN]["mean"]
    dE = d.loc[E].copy()
    dE["s"] = pd.MultiIndex.from_arrays([dE["vehicle"], dE["holder"]]).map(tr_rate.to_dict()).astype(float)
    okE = dE["s"].notna().to_numpy()
    res["holder_persistence"] = {
        "min_train_orders": MIN_HOLDER_TRAIN, "min_test_orders": MIN_HOLDER_TEST,
        "n_holder_vehicle_rows": int(len(tab)), "spearman": sp,
        "train_rate_as_forecast": {
            "n": int(okE.sum()),
            "auc": S.auc(yE[okE], dE.loc[okE, "s"].to_numpy()),
            "within_vehicle_cross_holder": V.within_vehicle_cross_holder_auc(
                dE[okE].assign(p=dE.loc[okE, "s"]), col, "p"),
        },
        "placebo_shuffle_holders_within_vehicle": {
            "n_perm": N_PERM,
            "spearman_weighted_mean": {"mean": float(np.nanmean(null_sp)),
                                       "p025": float(np.nanquantile(null_sp, 0.025)),
                                       "p975": float(np.nanquantile(null_sp, 0.975))},
            "pooled_pearson": {"mean": float(np.nanmean(null_pooled)),
                               "p025": float(np.nanquantile(null_pooled, 0.025)),
                               "p975": float(np.nanquantile(null_pooled, 0.975))},
            "recovered_gap_mean": {"mean": float(np.nanmean(null_rec)),
                                   "p025": float(np.nanquantile(null_rec, 0.025)),
                                   "p975": float(np.nanquantile(null_rec, 0.975))},
        },
    }
    res["gaps"] = {
        "n_vehicles": int(len(gaps)),
        "oracle_gap": gaps["oracle_gap"].describe().to_dict() if len(gaps) else {},
        "recovered_gap": gaps["recovered_gap"].describe().to_dict() if len(gaps) else {},
        "train_gap": gaps["train_gap"].describe().to_dict() if len(gaps) else {},
        "share_recovered_positive": float((gaps["recovered_gap"] > 0).mean()) if len(gaps) else float("nan"),
        "mean_recovered_over_mean_oracle": (float(gaps["recovered_gap"].mean() / gaps["oracle_gap"].mean())
                                            if len(gaps) and gaps["oracle_gap"].mean() > 0 else float("nan")),
    }
    log(f"{col}: holder spearman weighted={sp['weighted_mean']:.4f} null={np.nanmean(null_sp):.4f}; "
        f"gaps n={len(gaps)} oracle mean={gaps['oracle_gap'].mean() if len(gaps) else float('nan'):.3f} "
        f"recovered mean={gaps['recovered_gap'].mean() if len(gaps) else float('nan'):.3f}")
    return res, gaps, tab


def gap_chart(gaps: pd.DataFrame, title: str, path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.2))
    bins = np.linspace(-1, 1, 41)
    ax.hist(gaps["oracle_gap"], bins=bins, alpha=0.6, label="Realised best-minus-worst holder gap (oracle)")
    ax.hist(gaps["recovered_gap"], bins=bins, alpha=0.6,
            label="Gap between holders ranked worst and best on training record")
    ax.axvline(0, color="grey", lw=0.8)
    ax.set_xlabel("Difference in test-period slip rate between holders of one vehicle")
    ax.set_ylabel("Vehicles")
    ax.set_title(title)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default=str(RAW / "orders_panel.parquet"))
    ap.add_argument("--history", default=str(RAW / "orders_history_source.parquet"))
    ap.add_argument("--cells", default="all")
    ap.add_argument("--vehicle-map", default=str(RAW / "vehicle_map.parquet"))
    a = ap.parse_args()
    log = make_logger("exp2")
    t0 = time.time()
    panel = pd.read_parquet(a.panel)
    panel["split"] = split_of(panel["base_fy"])
    panel["holder"] = holder_key(panel)
    # The parent PIID is the holder's own contract (vehicle_map.py); the
    # competition set is the program of sibling contracts from one
    # solicitation. Orders whose parent has no sibling set keep the parent
    # key as their vehicle and fall out of the eligibility rule.
    vmap = pd.read_parquet(a.vehicle_map)
    panel["parent_key"] = panel["vehicle"]
    panel["vehicle"], map_diag = VM.map_orders(panel["parent_key"], vmap)
    log(f"vehicle map: {map_diag}")
    hist = pd.read_parquet(a.history, columns=["contract_award_unique_key", "vehicle", "recipient_uei",
                                               "recipient_is_aggregate", "action_date"]
                           + [f"{lab}_{h}" for lab, h in CELLS])
    hist["holder"] = holder_key(hist)
    hist["vehicle"], _ = VM.map_orders(hist["vehicle"], vmap)
    hd = pd.read_parquet(HISTORY_SOURCE, columns=["recipient_uei", "recipient_is_aggregate", "action_date"]
                         + [f"{lab}_{h}" for lab, h in CELLS])
    hd["holder"] = holder_key(hd)
    hd = hd.dropna(subset=["holder"])
    log(f"orders panel {len(panel)}, orders history {len(hist)}, definitive-contract history {len(hd)}")

    elig, not_multiple = eligible_vehicles(panel)
    all_sizes = pd.read_parquet(RAW / "vehicle_holders_all_sizes.parquet")
    all_sizes["vehicle"], _ = VM.map_orders(all_sizes["vehicle"].astype("string"), vmap)
    tr_all = all_sizes[all_sizes["fiscal_year"] <= 2017].groupby("vehicle").agg(
        holders_all_sizes_train=("recipient_uei", "nunique"),
        orders_all_sizes_train=("n_orders_all_sizes", "sum"))
    elig = elig.join(tr_all, how="left")
    vtype = panel.dropna(subset=["vehicle"]).groupby("vehicle").agg(
        parent_type=("parent_award_type_code", modal_flag))
    elig = elig.join(vtype, how="left")
    elig.reset_index().to_csv(RESULTS / "exp2_eligible_vehicles.csv", index=False)
    funnel = {
        "vehicle_definition": "program of sibling IDV contracts sharing a solicitation (vehicle_map.py); "
                              "the parent PIID where no sibling set is known",
        "vehicle_map": map_diag,
        "orders_in_panel": int(len(panel)),
        "orders_with_vehicle": int(panel["vehicle"].notna().sum()),
        "orders_with_identified_holder": int(panel["holder"].notna().sum()),
        "distinct_vehicles_in_panel": int(panel["vehicle"].nunique()),
        "rule": {"min_train_orders": MIN_TRAIN_ORDERS, "min_train_holders": MIN_TRAIN_HOLDERS,
                 "min_test_orders": MIN_TEST_ORDERS, "referenced_idv_flag": "M"},
        "vehicles_passing_count_rule": int(len(elig) + len(not_multiple)),
        "vehicles_passing_count_rule_not_flagged_multiple": int(len(not_multiple)),
        "not_flagged_multiple_flag_counts": not_multiple["single_or_multiple"].fillna("NA").value_counts().to_dict(),
        "eligible_vehicles": int(len(elig)),
        "eligible_train_orders": int(elig["train_orders"].sum()),
        "eligible_test_orders": int(elig["test_orders"].sum()),
        "eligible_train_holders_median": float(elig["train_holders"].median()),
        "eligible_holders_all_sizes_train_median": float(elig["holders_all_sizes_train"].median()),
        "parent_type_counts": elig["parent_type"].fillna("NA").value_counts().to_dict(),
        "single_or_multiple_counts": elig["single_or_multiple"].fillna("NA").value_counts().to_dict(),
        "all_sizes_note": "orders_all_sizes_train counts base-action ROWS in the archive; a base action "
                          "reported in several transaction rows is counted once per row",
        "train_holders_distribution": elig["train_holders"].describe().to_dict(),
    }
    log(f"eligible vehicles {len(elig)}: {funnel}")
    cells = CELLS if a.cells == "all" else [(c.split(":")[0], int(c.split(":")[1])) for c in a.cells.split(",")]
    results = []
    gap_frames = []
    for label, h in cells:
        rng = np.random.default_rng(0)
        res, gaps, tab = run_cell(panel, elig, hist, hd, label, h, rng, log)
        results.append(res)
        gaps.insert(0, "horizon", h)
        gaps.insert(0, "label", label)
        gap_frames.append(gaps)
        write_json(RESULTS / "exp2_results.json", {"funnel": funnel, "cells": results})
        if h == 36:
            gap_chart(gaps, f"{label} at 36 months: holder gaps within eligible vehicles",
                      RESULTS / f"exp2_holder_gaps_{label}_36.png")
        t = tab.reset_index()
        t.insert(0, "horizon", h)
        t.insert(0, "label", label)
        t.to_csv(RESULTS / f"exp2_holder_rates_{label}_{h}.csv", index=False)
    pd.concat(gap_frames, ignore_index=True).to_csv(RESULTS / "exp2_holder_gaps.csv", index=False)
    record_timing("exp2", time.time() - t0, {"cells": len(results)})
    log(f"done in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
