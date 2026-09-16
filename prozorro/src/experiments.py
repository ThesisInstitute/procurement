"""Run every experiment and write the result tables the report is built from.

One command produces everything: fill rates, base rates by year, the model
ladder, the transfer test with its permutation null, the two contrasts and the
charts.  Nothing in the report is computed anywhere else.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src.contrasts import (  # noqa: E402
    decile_table,
    dispersion_table,
    lowest_disqualified_contrast,
    conditional_icc,
    rate_table,
    variance_decomposition,
)
from src.features import build_history, lot_block, winner_bidder_block  # noqa: E402
from src.labels import DEAD_BID_STATUS  # noqa: E402
from src.models import DegenerateLabel, run_ladder  # noqa: E402
from src.scoring import (  # noqa: E402
    calibration_table,
    reliability_resolution,
    spearman,
    stratified_auc,
    summarise,
)
from src.times import to_kyiv_date, to_utc  # noqa: E402
from src.transfer import (  # noqa: E402
    counterfactual_frame,
    fit_transfer_models,
    identity_persistence,
    permutation_null,
    score_counterfactuals,
    transfer_cells,
    within_lot_test,
)

DATA = Path(__file__).resolve().parents[1] / "data"
RESULTS = Path(__file__).resolve().parents[1] / "results"

LABELS = [
    "duration_extension",
    "days_extended_gt90",
    "value_growth_gt10",
    "any_change",
    "underexecuted",
    "cancelled",
]

TRAIN = ("2019-01-01", "2020-12-31")
SPLITS = {
    "test 2021-2022": ("2021-01-01", "2022-12-31"),
    "test 2021 only (pre-invasion)": ("2021-01-01", "2021-12-31"),
    "test 2022 post-invasion": ("2022-02-24", "2022-12-31"),
}

PLOT_BG = "white"

# A stratified AUC resting on fewer strata than this is not reported.
MIN_STRATA = 20


def analysis_set(lots: pd.DataFrame) -> pd.DataFrame:
    """At least two live priced bids on the lot, an identified winner, a contract."""
    keep = (
        (lots["n_bids_lot"] >= 2)
        & lots["winner_id"].notna()
        & lots["contract_id"].notna()
        & lots["created_date"].notna()
    )
    return lots[keep].copy()


def fill_rates(lots: pd.DataFrame, analysis: pd.DataFrame) -> pd.DataFrame:
    """Field presence over every parsed lot, and over the analysis set."""
    rows = []
    checks_of = _checks
    for name, fn in checks_of().items():
        m_all = fn(lots)
        m_an = fn(analysis)
        rows.append(
            {
                "field": name,
                "n_all_lots": int(m_all.sum()),
                "share_all_lots": float(m_all.mean()) if len(lots) else float("nan"),
                "n_analysis_set": int(m_an.sum()),
                "share_analysis_set": float(m_an.mean()) if len(analysis) else float("nan"),
            }
        )
    rows.append(
        {
            "field": "lots (denominator)",
            "n_all_lots": len(lots),
            "share_all_lots": 1.0,
            "n_analysis_set": len(analysis),
            "share_analysis_set": 1.0,
        }
    )
    return pd.DataFrame(rows)


def _checks() -> dict:
    return {
        "at least two live priced bids on the lot": lambda d: d["n_bids_lot"] >= 2,
        "an identified winning bid": lambda d: d["winner_id"].notna(),
        "lot has a contract in the tender document": lambda d: d["contract_id"].notna(),
        "contract found in the live registry": lambda d: d["reg_status"].notna(),
        "registry amountPaid present": lambda d: d["amount_paid"].notna(),
        "registry amountPaid present and positive": lambda d: d["amount_paid"].fillna(0) > 0,
        "registry period.endDate present": lambda d: d["reg_period_end"].notna(),
        "tender-copy contract period.endDate present": lambda d: d["tc_period_end"].notna(),
        "both period end dates present": lambda d: d["reg_period_end"].notna()
        & d["tc_period_end"].notna(),
        "registry changes[] non-empty": lambda d: d["n_changes"].fillna(0) > 0,
        "value_change_ratio computable": lambda d: d["value_change_ratio"].notna(),
        "winner discount computable": lambda d: d["winner_discount"].notna(),
        "bid dispersion computable": lambda d: d["bid_cv"].notna(),
    }


def base_rates_by_year(lots: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, g in lots.groupby("year", observed=True):
        row = {
            "year": str(year),
            "n_lots": len(g),
            "n_tenders": g["tender_id"].nunique(),
            # Right censoring: every label is read at one snapshot, so a
            # contract the registry still calls `active` may yet acquire a
            # change that this panel will never see.
            "still_running_rate": float((g["reg_status"] == "active").mean()),
            "median_days_signing_to_registry_update": float(
                (
                    (to_utc(g["reg_dateModified"]) - to_utc(g["tc_dateSigned"]))
                    .dt.total_seconds()
                    / 86400.0
                ).median()
            ),
        }
        for lab in LABELS:
            s = g[lab]
            row[f"{lab}_n"] = int(s.notna().sum())
            row[f"{lab}_rate"] = float(s.mean()) if s.notna().any() else float("nan")
        rows.append(row)
    out = pd.DataFrame(rows).sort_values("year").reset_index(drop=True)
    return out


def period_end_agreement(lots: pd.DataFrame) -> dict[str, float]:
    """How often the tender copy and the registry agree on the contract end date."""
    both = lots[lots["reg_period_end"].notna() & lots["tc_period_end"].notna()]
    same = (both["days_extended"].abs() < 0.5).mean() if len(both) else float("nan")
    ext = both["duration_extension"] == 1
    return {
        "n_both_present": int(len(both)),
        "share_identical": float(same),
        "share_registry_later": float((both["days_extended"] > 0.5).mean()) if len(both) else float("nan"),
        "share_registry_earlier": float((both["days_extended"] < -0.5).mean()) if len(both) else float("nan"),
        "median_days_when_later": float(both.loc[both["days_extended"] > 0.5, "days_extended"].median())
        if (both["days_extended"] > 0.5).any()
        else float("nan"),
        "share_identical_given_duration_extension": float(
            (both.loc[ext, "days_extended"].abs() < 0.5).mean()
        )
        if ext.any()
        else float("nan"),
        "share_moved_given_duration_extension": float(
            (both.loc[ext, "days_extended"].abs() >= 0.5).mean()
        )
        if ext.any()
        else float("nan"),
        "share_moved_given_no_duration_extension": float(
            (both.loc[~ext, "days_extended"].abs() >= 0.5).mean()
        )
        if (~ext).any()
        else float("nan"),
        "share_with_duration_extension_given_moved": float(
            both.loc[both["days_extended"].abs() >= 0.5, "duration_extension"].mean()
        )
        if (both["days_extended"].abs() >= 0.5).any()
        else float("nan"),
    }


def run_all(data: Path, results: Path, n_perm: int) -> dict:
    results.mkdir(parents=True, exist_ok=True)
    lots_all = pd.read_parquet(data / "lots.parquet")
    bids = pd.read_parquet(data / "bids.parquet")
    tenders = pd.read_parquet(data / "tenders.parquet")
    lots = analysis_set(lots_all)

    summary: dict[str, object] = {
        "lots_parsed": int(len(lots_all)),
        "tenders_parsed": int(len(tenders)),
        "bids_parsed": int(len(bids)),
        "lots_in_analysis_set": int(len(lots)),
        "tenders_in_analysis_set": int(lots["tender_id"].nunique()),
        "distinct_bidders": int(
            bids.loc[~bids["bid_status"].isin(DEAD_BID_STATUS), "bidder_id"].nunique()
        ),
        "distinct_winners": int(lots["winner_id"].nunique()),
        "distinct_buyers": int(lots["buyer_id"].nunique()),
    }

    fill_rates(lots_all, lots).to_csv(results / "fill_rates.csv", index=False)
    base_rates_by_year(lots).to_csv(results / "base_rates_by_year.csv", index=False)
    summary["period_end_agreement"] = period_end_agreement(lots)
    summary["registry_status_counts"] = (
        lots["reg_status"].value_counts(dropna=False).astype(int).to_dict()
    )
    summary["tender_copy_status_counts"] = (
        lots["tc_status"].value_counts(dropna=False).astype(int).to_dict()
    )
    summary["change_rationale_counts"] = {
        c.replace("n_", ""): int(lots[c].fillna(0).gt(0).sum())
        for c in lots.columns
        if c.startswith("n_") and c not in {"n_lots", "n_bids", "n_bids_lot", "n_changes",
                                            "n_changes_active", "n_disqualified", "n_tenderers"}
    }
    summary["method_counts"] = lots["method"].value_counts().astype(int).to_dict()
    summary["bid_status_counts"] = bids["bid_status"].value_counts(dropna=False).astype(int).to_dict()
    summary["lot_value_status_counts"] = (
        bids["lot_value_status"].value_counts(dropna=False).astype(int).to_dict()
    )
    summary["tenderid_date_matches_tender_start"] = float(
        (to_kyiv_date(tenders["tender_start"]) == tenders["created_date"]).mean()
    )
    summary["consortium_bids"] = int((bids["n_tenderers"] > 1).sum())
    summary["award_status_totals"] = {
        "active": int(tenders["n_awards_active"].sum()),
        "unsuccessful": int(tenders["n_awards_unsuccessful"].sum()),
        "cancelled": int(tenders["n_awards_cancelled"].sum()),
        "all": int(tenders["n_awards"].sum()),
    }
    n_unsucc = int(tenders["n_unsuccessful_awards"].sum())
    summary["disqualification_visibility"] = {
        "unsuccessful_awards": n_unsucc,
        "with a priced bid to rank": int(tenders["n_unsuccessful_awards_priced"].sum()),
        "share_priced": float(tenders["n_unsuccessful_awards_priced"].sum() / n_unsucc)
        if n_unsucc
        else float("nan"),
        "bid_entries_with_no_price": int(tenders["n_bids_no_price"].sum()),
    }

    # The one truncation the sampling design can still cause: a tender whose
    # feed position (dateModified) fell after the walk's end date would never
    # have been seen. Measure the lag so the size of that hole is a number.
    lag = (
        to_utc(tenders["date_modified"]) - to_utc(tenders["created_date"])
    ).dt.total_seconds() / 86400.0
    lag = lag.dropna()
    summary["creation_to_datemodified_lag_days"] = {
        "n": int(len(lag)),
        "median": float(lag.median()),
        "p90": float(lag.quantile(0.90)),
        "p99": float(lag.quantile(0.99)),
        "p999": float(lag.quantile(0.999)),
        "max": float(lag.max()),
        "share_over_365": float((lag > 365).mean()),
        "n_over_365": int((lag > 365).sum()),
        "n_over_the_walk_slack": int((lag > 366).sum()),
        "walk_end": "2024-01-01",
        "slack_days_for_the_last_sampled_day": 366,
    }
    summary["invasion_counts"] = lots["invasion"].value_counts().astype(int).to_dict()
    summary["n_bids_lot_distribution"] = (
        lots["n_bids_lot"].clip(upper=10).value_counts().sort_index().astype(int).to_dict()
    )

    # --- features -------------------------------------------------------
    hist = build_history(lots, bids)
    lotX = lot_block(lots, hist).reset_index(drop=True)
    bidX = winner_bidder_block(lots, hist).reset_index(drop=True)
    frame = lots.reset_index(drop=True)
    created = frame["created_date"].to_numpy()
    train_mask = (created >= TRAIN[0]) & (created <= TRAIN[1])

    ladder_rows = []
    skipped: list[dict] = []
    calib_rows = []
    decomp = {}
    forecasts: dict[str, dict[str, np.ndarray]] = {}
    for split_name, (lo, hi) in SPLITS.items():
        test_mask = (created >= lo) & (created <= hi)
        for label in LABELS:
            n_tr = int((train_mask & frame[label].notna().to_numpy()).sum())
            n_te = int((test_mask & frame[label].notna().to_numpy()).sum())
            if n_tr < 500 or n_te < 200:
                skipped.append({"split": split_name, "label": label,
                                "reason": f"{n_tr} resolved in train, {n_te} in test"})
                continue
            try:
                tab, preds, _ = run_ladder(frame, lotX, bidX, label, train_mask, test_mask)
            except DegenerateLabel as exc:
                skipped.append({"split": split_name, "label": label, "reason": str(exc)})
                continue
            tab.insert(1, "split", split_name)
            ladder_rows.append(tab)
            if split_name == "test 2021-2022":
                forecasts[label] = preds
                for model_name, p in preds.items():
                    if model_name == "y":
                        continue
                    ct = calibration_table(preds["y"], p, bins=10)
                    ct.insert(0, "model", model_name)
                    ct.insert(0, "label", label)
                    calib_rows.append(ct)
                    decomp[f"{label}|{model_name}"] = reliability_resolution(preds["y"], p, 10)
    ladder = pd.concat(ladder_rows, ignore_index=True) if ladder_rows else pd.DataFrame()
    ladder.to_csv(results / "model_ladder.csv", index=False)
    if calib_rows:
        pd.concat(calib_rows, ignore_index=True).to_csv(results / "calibration.csv", index=False)
    summary["brier_decomposition"] = decomp
    summary["labels_not_scored"] = skipped

    # --- experiment 2: transfer ----------------------------------------
    transfer_summary = {}
    cells_out = {}
    within_lot_rows: list[pd.DataFrame] = []
    test_mask = (created >= SPLITS["test 2021-2022"][0]) & (created <= SPLITS["test 2021-2022"][1])
    cf = counterfactual_frame(frame, bids)
    for label in ["duration_extension", "days_extended_gt90"]:
        ok = frame[label].notna().to_numpy()
        tr = train_mask & ok
        if tr.sum() < 500:
            continue
        # Only rows in `tr` are used for fitting and all of those are non-missing;
        # the fill is so the array has no NaN where the mask is False.
        y = frame[label].where(ok, 0.0).to_numpy(dtype=float)
        models = fit_transfer_models(lotX, bidX, y, tr)
        test_tenders = set(frame.loc[test_mask, "tender_id"])
        cf_test = cf[cf["tender_id"].isin(test_tenders)].reset_index(drop=True)
        # Headline: bidder history frozen at the first day of the test window,
        # so no outcome inside the resolution window can feed the forecast.
        scored = score_counterfactuals(
            cf_test, frame, hist, models, lotX,
            history_cutoff=SPLITS["test 2021-2022"][0] + "T00:00:00+02:00",
        )
        scored_asof = score_counterfactuals(cf_test, frame, hist, models, lotX)
        cells = transfer_cells(
            scored, frame[test_mask & ok], label=label, min_wins=3, min_lost=1
        )
        cells_asof = transfer_cells(
            scored_asof, frame[test_mask & ok], label=label, min_wins=3, min_lost=1
        )
        cells.to_csv(results / f"transfer_cells_{label}.csv", index=False)
        cells_out[label] = cells
        res = {}
        for col, name in [
            ("f_full", "full model (price and identity)"),
            ("f_price", "price only"),
            ("f_prior", "prior extension rate only"),
            ("f_lot", "lot only (placebo)"),
        ]:
            res[name] = permutation_null(cells, col, n_perm=n_perm)
            res[name]["n_cells"] = int(len(cells))
            res[name]["n_bidders"] = int(cells["bidder_id"].nunique())
            res[name]["n_lost_lots"] = int(cells["n_lost"].sum())
            res[name]["n_won_lots"] = int(cells["n_won"].sum())
        for col, name in [
            ("f_full", "full model, history as of each tender (overlaps the resolution window)"),
            ("f_prior", "prior extension rate, history as of each tender (overlaps)"),
        ]:
            r = permutation_null(cells_asof, col, n_perm=n_perm)
            r["n_cells"] = int(len(cells_asof))
            r["n_bidders"] = int(cells_asof["bidder_id"].nunique())
            r["n_lost_lots"] = int(cells_asof["n_lost"].sum())
            r["n_won_lots"] = int(cells_asof["n_won"].sum())
            res[name] = r
        # Same test at the bidder level, ignoring CPV division.
        by_bidder = (
            scored[~scored["won"]]
            .groupby("bidder_id", observed=True)
            .agg(f_full=("p_full", "mean"), n_lost=("p_full", "size"))
            .reset_index()
        )
        won_b = (
            frame[test_mask & ok]
            .groupby("winner_id", observed=True)[label]
            .agg(["mean", "size"])
            .rename(columns={"mean": "realised_rate", "size": "n_won"})
            .reset_index()
            .rename(columns={"winner_id": "bidder_id"})
        )
        bb = by_bidder.merge(won_b, on="bidder_id", how="inner")
        bb = bb[bb["n_won"] >= 3]
        res["full model, pooled across divisions"] = {
            "observed": spearman(bb["f_full"].to_numpy(), bb["realised_rate"].to_numpy()),
            "n_cells": int(len(bb)),
        }
        transfer_summary[label] = res
        # The within-lot test uses the as-of history on purpose: the outcome is
        # that lot's own contract, which is strictly later than the tender
        # start, so a bidder's record before the tender cannot contain it.
        wl = within_lot_test(scored_asof, frame[test_mask], label=label, n_perm=1000)
        if len(wl):
            within_lot_rows.append(wl)
        # The same test on the pre-invasion part of the test window only, so
        # the headline result can be read with and without the war.
        pre = test_mask & ~frame["invasion"].to_numpy(dtype=bool)
        if int((pre & ok).sum()) >= 500:
            wl_pre = within_lot_test(
                scored_asof, frame[pre], label=label, n_perm=1000,
                sample="pre-invasion test lots only",
            )
            if len(wl_pre):
                within_lot_rows.append(wl_pre)
    summary["transfer"] = transfer_summary
    if within_lot_rows:
        pd.concat(within_lot_rows, ignore_index=True).to_csv(
            results / "within_lot_test.csv", index=False
        )

    # --- whose identity matters, the buyer's or the bidder's? -----------
    vd = [
        variance_decomposition(lots, lab, n_perm=min(n_perm, 500))
        for lab in ["duration_extension", "days_extended_gt90", "any_change", "underexecuted"]
        if lots[lab].notna().sum() > 500
    ]
    vd = [d for d in vd if len(d)]
    if vd:
        pd.concat(vd, ignore_index=True).to_csv(
            results / "variance_decomposition.csv", index=False
        )
    # A bidder's several lots in one tender move together, and a bidder's lots
    # cluster in time, so the strictest variant takes one lot per bidder per
    # tender and blocks on the buyer within the year.
    lots = lots.assign(
        buyer_year=lots["buyer_id"].astype(str) + "|" + lots["year"].astype(str)
    )
    deduped = lots.drop_duplicates(["winner_id", "tender_id"])
    summary["lots_dropped_by_one_per_bidder_per_tender"] = int(len(lots) - len(deduped))
    cond = []
    variants = [
        (lots, "winner_id", "buyer_id", "all lots"),
        (lots, "buyer_id", "winner_id", "all lots"),
        (lots, "winner_id", "cpv_division", "all lots"),
        (lots, "buyer_id", "cpv_division", "all lots"),
        (lots, "winner_id", "buyer_year", "all lots"),
        (deduped, "winner_id", "buyer_id", "one lot per bidder and tender"),
        (deduped, "winner_id", "buyer_year", "one lot per bidder and tender"),
        (deduped, "buyer_id", "winner_id", "one lot per bidder and tender"),
    ]
    pre_lots = lots[~lots["invasion"].astype(bool)]
    if len(pre_lots) > 1000:
        variants.append((pre_lots, "winner_id", "buyer_year", "pre-invasion lots only"))
        variants.append((pre_lots, "buyer_id", "winner_id", "pre-invasion lots only"))
    for lab in ["duration_extension", "days_extended_gt90", "any_change", "underexecuted"]:
        if lots[lab].notna().sum() <= 500:
            continue
        for frame_v, group, block, variant in variants:
            row = conditional_icc(frame_v, lab, group, block, n_perm=min(n_perm, 500))
            row["variant"] = variant
            cond.append(row)
    cond = [c for c in cond if "icc" in c and not pd.isna(c.get("icc", float("nan")))]
    if cond:
        pd.DataFrame(cond).to_csv(results / "conditional_icc.csv", index=False)

    h2h_rows = []
    for split_name, (lo, hi) in SPLITS.items():
        test_mask_h = (created >= lo) & (created <= hi)
        for label in LABELS:
            ok = frame[label].notna().to_numpy()
            tr = train_mask & ok
            te = test_mask_h & ok
            if te.sum() < 200 or frame.loc[tr, label].sum() < 20:
                continue
            ref = float(frame.loc[tr, label].mean())
            predictors = [
                ("buyer's as-of extension rate", lotX["buyer_prior_ext_rate"]),
                ("winner's as-of extension rate", bidX["bidder_prior_ext_rate"]),
                ("winner's as-of win rate", bidX["bidder_prior_win_rate"]),
                (
                    "winner's price as a share of the expected value",
                    1.0 - frame["winner_discount"].fillna(0.0),
                ),
                ("log lot value", lotX["log_value"]),
            ]
            # A thin history is the obvious alternative explanation for a null
            # bidder result, so the same comparison is repeated on the lots
            # whose winner already has a substantial record.
            established = bidX["bidder_prior_wins_log"].to_numpy() >= np.log1p(10)
            buyer_established = lotX["buyer_prior_lots_log"].to_numpy() >= np.log1p(10)
            subsets = [
                ("all test lots", te),
                ("winner has 10 or more prior wins", te & established),
                ("buyer has 10 or more prior lots", te & buyer_established),
            ]
            for subset_name, mask in subsets:
                if mask.sum() < 300 or frame.loc[mask, label].sum() < 20:
                    continue
                y_sub = frame.loc[mask, label].to_numpy(dtype=float)
                buyers_sub = frame.loc[mask, "buyer_id"].to_numpy(dtype=object)
                cell_sub = (
                    frame.loc[mask, "cpv_division"].astype(str)
                    + "|"
                    + frame.loc[mask, "year"].astype(str)
                ).to_numpy(dtype=object)
                for name, series in predictors:
                    p_sub = np.nan_to_num(series.to_numpy(dtype=float)[mask], nan=ref)
                    if not np.isfinite(p_sub).any():
                        continue
                    m = summarise(y_sub, p_sub, ref)
                    within = stratified_auc(y_sub, p_sub, buyers_sub)
                    cell = stratified_auc(y_sub, p_sub, cell_sub)
                    # A stratified AUC resting on a handful of strata is not a
                    # statistic; report it as missing rather than as a number.
                    h2h_rows.append({
                        "split": split_name, "label": label,
                        "subset": subset_name, "predictor": name,
                        "n": m["n"], "base_rate": m["base_rate"], "auc": m["auc"],
                        "auc_within_buyer": within["auc"]
                        if within["strata_used"] >= MIN_STRATA else float("nan"),
                        "buyers_contributing": within["strata_used"],
                        "auc_within_cpv_year": cell["auc"]
                        if cell["strata_used"] >= MIN_STRATA else float("nan"),
                        "cpv_year_cells_contributing": cell["strata_used"],
                    })
    if h2h_rows:
        pd.DataFrame(h2h_rows).to_csv(results / "identity_head_to_head.csv", index=False)

    # --- does a bidder's own record persist at all? ---------------------
    persistence = {}
    for label in LABELS:
        if frame[label].notna().sum() < 1000:
            continue
        for min_wins in (2, 3, 5):
            res = identity_persistence(
                frame, label, train_mask, test_mask, min_wins=min_wins, n_perm=n_perm
            )
            persistence[f"{label}|min_wins={min_wins}"] = res
    summary["identity_persistence"] = persistence

    # --- experiments 3 and 4 -------------------------------------------
    contrast_labels = [
        "duration_extension",
        "days_extended_gt90",
        "value_growth_gt10",
        "any_change",
        "underexecuted",
    ]
    lowest_disqualified_contrast(lots, contrast_labels).to_csv(
        results / "lowest_disqualified_contrast.csv", index=False
    )
    decile_table(lots, "winner_discount", contrast_labels, q=10).to_csv(
        results / "discount_deciles.csv", index=False
    )
    dispersion_table(lots, contrast_labels, bins=6).to_csv(
        results / "bid_dispersion.csv", index=False
    )
    rate_table(lots, "method", contrast_labels).to_csv(results / "rates_by_method.csv", index=False)
    rate_table(lots.assign(nb=lots["n_bids_lot"].clip(upper=8)), "nb", contrast_labels).to_csv(
        results / "rates_by_n_bids.csv", index=False
    )

    # --- charts ---------------------------------------------------------
    make_charts(lots, cells_out, forecasts, results)

    (results / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1,
                                                     default=float))
    return summary


def make_charts(
    lots: pd.DataFrame,
    cells: dict[str, pd.DataFrame],
    forecasts: dict[str, dict[str, np.ndarray]],
    results: Path,
) -> None:
    dec = decile_table(lots, "winner_discount", ["duration_extension", "days_extended_gt90"], q=10)
    fig, ax = plt.subplots(figsize=(8.2, 4.6), dpi=160)
    # Most winners discount by almost nothing, so the deciles bunch against
    # zero on a linear price axis. Plot the decile index and put the median
    # discount on the tick labels instead.
    x = np.arange(len(dec))
    ax.plot(x, dec["duration_extension_rate"] * 100, marker="o", color="#1b4965",
            label="duration extension recorded")
    ax.plot(x, dec["days_extended_gt90_rate"] * 100, marker="s", color="#bc4b51",
            label="end date moved out more than 90 days")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{v * 100:.1f}" for v in dec["winner_discount_median"]])
    ax.set_xlabel(
        "winner's discount against the expected lot value: deciles, labelled by median (percent)"
    )
    ax.set_ylabel("rate (percent)")
    ax.set_title("Winner's discount and the winning contract's slip")
    base = float(lots["duration_extension"].mean())
    ax.axhline(base * 100, color="#999999", lw=1, ls="--")
    ax.annotate("overall rate", xy=(x[-1], base * 100), xytext=(-2, 4),
                textcoords="offset points", ha="right", fontsize=8, color="#666666")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(results / "extension_by_discount_decile.png", facecolor=PLOT_BG)
    plt.close(fig)

    for label, c in cells.items():
        if not len(c):
            continue
        fig, ax = plt.subplots(figsize=(6.8, 5.6), dpi=160)
        ax.scatter(c["f_full"] * 100, c["realised_rate"] * 100, s=np.clip(c["n_won"] * 4, 6, 90),
                   alpha=0.35, color="#1b4965", edgecolors="none",
                   label="bidder by CPV division, area is wins")
        rho = spearman(c["f_full"].to_numpy(), c["realised_rate"].to_numpy())
        rho_p = spearman(c["f_lot"].to_numpy(), c["realised_rate"].to_numpy())
        # Bin the cells so the eye is not asked to read a cloud.
        try:
            b = pd.qcut(c["f_full"], 8, labels=False, duplicates="drop")
            g = c.groupby(b).agg(x=("f_full", "mean"), y=("realised_rate", "mean"))
            ax.plot(g["x"] * 100, g["y"] * 100, color="#bc4b51", marker="o", lw=1.6,
                    label="binned mean")
        except ValueError:
            pass
        ax.set_xlabel("mean forecast on lots the bidder LOST (percent)")
        ax.set_ylabel("realised rate on lots the bidder WON (percent)")
        ax.set_title(
            f"Transfer: {label.replace('_', ' ')}\n"
            f"Spearman {rho:.3f}; lot-only placebo {rho_p:.3f}; {len(c):,} cells"
        )
        ax.grid(alpha=0.3)
        ax.legend(frameon=False, fontsize=8, loc="upper left")
        fig.tight_layout()
        fig.savefig(results / f"transfer_scatter_{label}.png", facecolor=PLOT_BG)
        plt.close(fig)

    if "duration_extension" in forecasts:
        p = forecasts["duration_extension"]
        fig, ax = plt.subplots(figsize=(6.5, 5.5), dpi=160)
        ax.plot([0, 1], [0, 1], color="#999999", lw=1, ls="--")
        for name, colour in [
            ("reference class", "#7f9c96"),
            ("GBM lot, plus buyer history", "#bc4b51"),
            ("GBM plus the bidder's price and history", "#1b4965"),
        ]:
            if name not in p:
                continue
            ct = calibration_table(p["y"], p[name], bins=10)
            ax.plot(ct["mean_forecast"], ct["observed"], marker="o", label=name, color=colour)
        ax.set_xlabel("mean forecast")
        ax.set_ylabel("observed rate")
        ax.set_title("Calibration, duration extension, test 2021-2022")
        ax.grid(alpha=0.3)
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(results / "calibration_duration_extension.png", facecolor=PLOT_BG)
        plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--results", default=str(RESULTS))
    ap.add_argument("--permutations", type=int, default=2000)
    args = ap.parse_args()
    s = run_all(Path(args.data), Path(args.results), args.permutations)
    print(json.dumps({k: v for k, v in s.items() if not isinstance(v, dict)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
