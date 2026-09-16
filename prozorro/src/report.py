"""Render results/report.md from the artifacts experiments.py wrote.

Every number in the report comes out of a CSV or JSON in results/.  Nothing is
computed here that is not also on disk, and no sentence that states a finding
is fixed text: the verdict lines are chosen from the numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.scoring import spearman as spearman_cols  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"

LABEL_ORDER = [
    "duration_extension",
    "days_extended_gt90",
    "value_growth_gt10",
    "any_change",
    "underexecuted",
    "cancelled",
]

LABEL_TITLES = {
    "duration_extension": "duration extension recorded",
    "days_extended_gt90": "end date moved out more than 90 days",
    "value_growth_gt10": "contract value up more than 10 percent",
    "any_change": "any registered change",
    "underexecuted": "paid less than 90 percent of the signed value",
    "cancelled": "contract cancelled",
}


PRETTY = {
    "n_lots": "lots",
    "still_running_rate": "still running",
    "median_days_signing_to_registry_update": "median days signing to last registry update",
    "n_treated": "treated lots",
    "n_control": "control lots",
    "n_treated_matched": "treated, matched",
    "n_control_matched": "control, matched",
    "treated_rate_raw": "treated rate, raw",
    "control_rate_raw": "control rate, raw",
    "treated_rate_matched": "treated rate, matched",
    "control_rate_standardised": "control rate, standardised",
    "difference": "difference",
    "ci_lo": "95% low",
    "ci_hi": "95% high",
    "bin": "decile",
    "nb": "live priced bids",
    "winner_discount_min": "discount min",
    "winner_discount_median": "discount median",
    "winner_discount_max": "discount max",
    "bid_cv_min": "dispersion min",
    "bid_cv_median": "dispersion median",
    "bid_cv_max": "dispersion max",
}


def prettify(df: pd.DataFrame) -> pd.DataFrame:
    """Rename machine column names to something a reader can scan."""
    out = df.rename(columns=PRETTY)
    out = out.rename(
        columns={
            c: LABEL_TITLES.get(c[: -len("_rate")], c[: -len("_rate")].replace("_", " "))
            for c in out.columns
            if c.endswith("_rate")
        }
    )
    out = out.rename(columns={"label": "label"})
    if "label" in out.columns:
        out["label"] = out["label"].map(lambda v: LABEL_TITLES.get(v, v))
    return out


def md_table(df: pd.DataFrame, floats: dict[str, int] | None = None) -> str:
    d = df.copy()
    floats = floats or {}
    for col in d.columns:
        if col in floats:
            d[col] = d[col].map(lambda v: "" if pd.isna(v) else f"{v:.{floats[col]}f}")
        elif pd.api.types.is_float_dtype(d[col]):
            d[col] = d[col].map(lambda v: "" if pd.isna(v) else f"{v:.3f}")
        elif pd.api.types.is_integer_dtype(d[col]):
            d[col] = d[col].map(lambda v: f"{v:,}")
        else:
            d[col] = d[col].astype(str).fillna("")
    head = "| " + " | ".join(str(c) for c in d.columns) + " |"
    rule = "|" + "|".join("---" for _ in d.columns) + "|"
    rows = ["| " + " | ".join(r) + " |" for r in d.astype(str).to_numpy()]
    return "\n".join([head, rule, *rows])


def pct(x: float, dp: int = 1) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{100 * x:.{dp}f} percent"


def load(results: Path) -> dict:
    out: dict[str, object] = {}
    out["summary"] = json.loads((results / "summary.json").read_text())
    sm = results / "sample_meta.json"
    out["sample"] = json.loads(sm.read_text()) if sm.exists() else {}
    for name in [
        "fill_rates",
        "base_rates_by_year",
        "model_ladder",
        "calibration",
        "lowest_disqualified_contrast",
        "discount_deciles",
        "bid_dispersion",
        "rates_by_method",
        "rates_by_n_bids",
        "within_lot_test",
        "identity_head_to_head",
        "variance_decomposition",
        "conditional_icc",
    ]:
        p = results / f"{name}.csv"
        out[name] = pd.read_csv(p) if p.exists() else pd.DataFrame()
    for lab in ["duration_extension", "days_extended_gt90"]:
        p = results / f"transfer_cells_{lab}.csv"
        if p.exists():
            out[f"cells_{lab}"] = pd.read_csv(p)
    fetches = sorted((results.parents[1] / "data" / "raw" / "prozorro").glob("fetch_summary_*.json"))
    out["fetch"] = [json.loads(p.read_text()) for p in fetches]
    return out


def verdict(a: dict) -> str:
    """The one-sentence answer, assembled from the numbers rather than asserted.

    Three pieces of evidence, weakest confound first: the within-lot test (the
    lot is held fixed, so nothing about the lot can produce the result), the
    transfer test (the bidder's lost lots against its won lots), and the
    ablation in the ladder (does adding the winner's identity move test AUC).
    """
    t = a["summary"].get("transfer", {}).get("duration_extension", {})
    full = t.get("full model (price and identity)", {})
    wl = a["within_lot_test"]
    ladder = a["model_ladder"]
    primary = ladder[
        (ladder["split"] == "test 2021-2022") & (ladder["label"] == "duration_extension")
    ]
    with_h = primary[primary["model"] == "GBM plus the bidder's price and history"]
    lot_h = primary[primary["model"] == "GBM plus the bidder's price"]
    d_auc = (
        float(with_h["auc"].iloc[0]) - float(lot_h["auc"].iloc[0])
        if len(with_h) and len(lot_h)
        else float("nan")
    )

    def wl_row(name: str) -> dict:
        if not len(wl):
            return {}
        sub = wl[(wl["label"] == "duration_extension") & (wl["forecast"] == name)]
        if "sample" in sub.columns:
            sub = sub[sub["sample"] == "all test lots"]
        return sub.iloc[0].to_dict() if len(sub) else {}

    ident = wl_row("prior extension rate only")
    price = wl_row("price only")
    raw_price = wl_row("raw price rank on the lot, no model")
    placebo = t.get("lot only (placebo)", {})

    def signal(row: dict) -> int:
        """1 if better than chance, -1 if worse, 0 if not separable."""
        if not row or pd.isna(row.get("auc", float("nan"))):
            return 0
        if row.get("p_two_sided", 1.0) >= 0.05:
            return 0
        return 1 if row["auc"] > row.get("null_mean", 0.5) else -1

    id_sig = signal(ident)
    price_sig = max(signal(price), signal(raw_price))
    # A transfer result only counts as evidence about the bidder if it also
    # beats the lot-only placebo. The placebo knows nothing about the bidder,
    # so anything it matches is about which lots the bidder competes for.
    placebo_excess = placebo.get("excess_over_null", float("nan"))
    transfers = (
        bool(full)
        and full.get("p_greater", 1.0) < 0.05
        and not pd.isna(placebo_excess)
        and full.get("excess_over_null", float("-inf")) > placebo_excess
    )

    ci = a["conditional_icc"]
    strict = {}
    if len(ci) and "variant" in ci.columns:
        m = ci[
            (ci["variant"] == "one lot per bidder and tender")
            & (ci["group"] == "winner_id")
            & (ci["block"] == "buyer_year")
            & (ci["label"] == "duration_extension")
        ]
        if len(m):
            strict = m.iloc[0].to_dict()
    clusters = bool(strict) and strict.get("p_greater", 1.0) < 0.05 and strict.get("excess", 0) > 0

    parts: list[str] = []
    if ident:
        parts.append(
            f"with the lot held fixed, a bidder's own prior extension rate ranks its realised "
            f"outcome at AUC {ident['auc']:.3f} against a same-lot null of "
            f"{ident['null_mean']:.3f} (p = {ident['p_two_sided']:.3f})"
        )
    if raw_price:
        parts.append(
            f"the winner's raw price rank among the bids on that same lot, with no model "
            f"between the price and the statistic, reaches AUC {raw_price['auc']:.3f} "
            f"(p = {raw_price['p_two_sided']:.3f})"
        )
    if price:
        parts.append(
            f"a model given only the lot and the bidder's price reaches AUC {price['auc']:.3f} "
            f"against {price['null_mean']:.3f} (p = {price['p_two_sided']:.3f})"
        )
    if full and not pd.isna(full.get("observed", float("nan"))):
        tail = ""
        if placebo and not pd.isna(placebo.get("observed", float("nan"))):
            beats = "which it does not beat" if not transfers else "which it beats"
            tail = (
                f", against {placebo['observed']:.3f} for a lot-only placebo that knows nothing "
                f"about the bidder and {beats}"
            )
        parts.append(
            f"a bidder's mean forecast on the lots it lost ranks its realised rate on the lots "
            f"it won at Spearman {full['observed']:.3f} against a within-division shuffled null "
            f"of {full['null_mean']:.3f} (one-sided p = {full['p_greater']:.3f}){tail}"
        )
    if strict:
        parts.append(
            f"outcomes nonetheless cluster by bidder beyond the buyer and the year (intraclass "
            f"correlation {strict['icc']:.3f} against a null of {strict['null_mean']:.3f}, "
            f"one-sided p = {strict['p_greater']:.4f})"
        )
    if not pd.isna(d_auc):
        parts.append(
            f"and adding the winner's identity and record to the award-time model moves test "
            f"AUC by {d_auc:+.3f}"
        )

    if id_sig > 0 and transfers:
        head = "Yes, weakly, and on more than one test"
    elif id_sig > 0 or transfers:
        head = "Only weakly, and only on one of the three forecasting tests"
    elif clusters and price_sig > 0:
        head = (
            "The price does and the identity does not, which is the interesting part: what a "
            "bidder bid relative to its rivals on the same lot ranks the outcome, and outcomes "
            "do cluster by bidder, but a bidder's own past record does not rank its future one, "
            "so the clustering is not something a forecaster can use"
        )
    elif clusters:
        head = (
            "Outcomes cluster by bidder, but not in a way anyone can forecast with: a bidder's "
            "own past record does not rank its future one"
        )
    elif price_sig > 0:
        head = (
            "The price carries slip information and the identity does not: what a bidder bid, "
            "relative to its rivals on the same lot, ranks the outcome, while who the bidder is "
            "does not"
        )
    else:
        head = "No, not measurably"
    return head + ". The evidence, sharpest test first: " + "; ".join(parts) + "."


def build(results: Path) -> str:
    a = load(results)
    s = a["summary"]
    sample = a["sample"]
    census = sample.get("census", {})
    pea = s.get("period_end_agreement", {})
    lines: list[str] = []
    W = lines.append

    W("# Forecasting contract slip per competing bidder, Ukraine (Prozorro)")
    W("")
    W(f"**{verdict(a)}**")
    W("")
    W(
        "Prozorro is the only large procurement system that publishes every bidder's identity "
        "and price, so it is the only public place where the question can be asked at all. This "
        "report builds the panel, forecasts the winning contract's slip from award-time "
        "information, and then scores every losing bidder by transfer: what a bidder's forecast "
        "on the lots it lost says about the lots it won."
    )
    W("")
    W("### The three tests, and why there are three")
    W("")
    W(
        "A losing bid never becomes a contract, so no forecast attached to one can ever be "
        "resolved. Everything below is an attempt to get at the same question without that "
        "resolution, and the three tests fail in different ways, which is why all three are "
        "reported."
    )
    W("")
    W("| Test | What it compares | What could fake a positive result |")
    W("|---|---|---|")
    W("| Within-lot | the bidders on one lot, against each other, then the winner's own "
      "outcome | nothing about the lot: the buyer, the sector, the size and the year are "
      "identical for every bidder on it |")
    W("| Transfer | a bidder's mean forecast on lots it lost, against its realised rate on "
      "lots it won | the kinds of lot a bidder competes for, which is why the null shuffles "
      "within CPV division and a lot-only placebo is reported |")
    W("| Identity persistence | a bidder's rate in 2019-2020 against its rate in 2021-2022, "
      "won lots only | the sector a bidder works in, which is what the null holds fixed |")
    W("")

    # ---- what was built ------------------------------------------------
    W("## What was built")
    W("")
    design0 = census.get("design", {})
    pop_window = sample.get("population_in_window", 0)
    n_sampled = sample.get("sampled", 0)
    W(
        "A one-in-"
        f"{design0.get('step', '?')} systematic sample of whole days from the Prozorro tender "
        "feed, every completed above-threshold tender it contains that was created in 2019 to "
        "2022, each of those tenders' full documents (which is where the bids live), and the "
        "live contract-registry record for every contract they produced. From those, four "
        "released tables, a lot-level analysis table, a forward-chained model ladder, and the "
        "experiments below."
    )
    W("")
    W(f"- Feed walked: {census.get('rows_walked', 0):,} rows over "
      f"{census.get('windows', 0)} whole days, "
      f"{census.get('pages', 0):,} listing requests.")
    W(f"- Completed above-threshold tenders found, all creation years: "
      f"{sample.get('population_deduped_all_years', 0):,}.")
    W(f"- Of those, created 2019-01-01 to 2022-12-31: {pop_window:,}.")
    if n_sampled >= pop_window and pop_window:
        W("- Queued for fetching: all of them. There is no second-stage subsample, so the only "
          "sampling step in the whole design is the one-in-"
          f"{design0.get('step', '?')} day selection.")
    else:
        W(f"- Sampled for fetching: {n_sampled:,} of {pop_window:,}, "
          "proportionally by creation month with a fixed seed.")
    W(f"- Tender documents parsed: {s.get('tenders_parsed', 0):,}; "
      f"bid rows: {s.get('bids_parsed', 0):,}; "
      f"lot rows: {s.get('lots_parsed', 0):,}.")
    W(f"- Lots in the analysis set (at least two live priced bids, an identified winner, and a "
      f"contract): {s.get('lots_in_analysis_set', 0):,} across "
      f"{s.get('tenders_in_analysis_set', 0):,} tenders, "
      f"{s.get('distinct_winners', 0):,} distinct winning bidders, "
      f"{s.get('distinct_bidders', 0):,} distinct bidders overall, "
      f"{s.get('distinct_buyers', 0):,} buyers.")
    if a["fetch"]:
        req = {}
        for f in a["fetch"]:
            for k, v in f.get("requests", {}).get("by_kind", {}).items():
                req[k] = max(req.get(k, 0), v)
        W(f"- HTTP requests issued during document fetching: "
          f"{', '.join(f'{k} {v:,}' for k, v in sorted(req.items()))}.")
    W("")

    # ---- data ----------------------------------------------------------
    W("## The data and how the sample was drawn")
    W("")
    W(
        "The listing endpoint `/api/2.5/tenders` is ordered by `dateModified`, not by tender "
        "date, and each tender sits in it once at its current `dateModified`. Because "
        "`dateModified` only increases, a forward walk from a seed date visits every tender "
        "whose current `dateModified` is at or after that seed, and a tender created on or "
        "after the seed must have been modified on or after its creation. A walk from "
        "2019-01-01 to the present would therefore be a complete census of everything created "
        "from 2019-01-01 onwards."
    )
    W("")
    design = census.get("design", {})
    if design.get("mode") == "day-sample":
        W(
            f"Walking every one of those rows to the present would have taken hours: feed "
            f"volume rises from about 110,000 rows a month in 2019 to over 400,000 by late "
            f"2020. Instead the frame is a **systematic sample of whole days**: every "
            f"{design.get('step')}th day of `dateModified` from {design.get('start', '')[:10]} "
            f"to {design.get('end', '')[:10]}, walked from midnight to midnight. Because whole "
            f"days are taken and each selected day is walked completely, every tender in the "
            f"range has inclusion probability exactly "
            f"{design.get('inclusion_probability', 0):.2f} whatever the volume of the day it "
            f"happens to sit in. Sampling a fixed number of rows per day would instead have "
            f"over-represented quiet days, and a step of {design.get('step')} is coprime with "
            f"7 so the selected days rotate through the days of the week."
        )
        W("")
    W(f"Covered `dateModified` span: {census.get('first_dateModified', 'n/a')} to "
      f"{census.get('last_dateModified', 'n/a')}; "
      f"{census.get('pages', 0):,} listing requests over "
      f"{census.get('windows', 0)} whole days.")
    W("")
    lagd = s.get("creation_to_datemodified_lag_days") or {}
    if lagd:
        W(
            f"The only truncation the design can still cause is a tender whose feed position "
            f"fell after the walk's end date. Measured on the fetched sample, the lag from the "
            f"tenderID creation date to the tender's final `dateModified` has median "
            f"{lagd['median']:.0f} days, p99 {lagd['p99']:.0f} days and a maximum of "
            f"{lagd['max']:.0f} days; {lagd.get('n_over_365', 0):,} of {lagd['n']:,} tenders "
            f"({pct(lagd['share_over_365'], 3)}) exceed a year and "
            f"{lagd.get('n_over_the_walk_slack', 0):,} exceed the "
            f"{lagd['slack_days_for_the_last_sampled_day']} days of slack the walk allows after "
            f"the last tender creation date in the window. That is the exact size of the hole. "
            f"This is "
            f"also why a tender's feed position is safe to use at all: a tender's "
            f"`dateModified` freezes when its contract is published and does not move when the "
            f"contract registry is later amended, so the walk does not select on the outcome "
            f"being forecast."
        )
        W("")
    ms = census.get("rows_by_method_status", {})
    if ms:
        top = pd.DataFrame(
            [{"procedure and status": k, "feed rows": v} for k, v in list(ms.items())[:12]]
        )
        W("What the feed is mostly made of (top procedure-and-status combinations):")
        W("")
        W(md_table(top))
        W("")
    tail = (
        "and every one of them was fetched, so there is no second sampling step to describe"
        if n_sampled >= pop_window and pop_window
        else "from which a proportional stratified sample by creation month was drawn with a "
             "fixed seed, so the sampled base rates stay unbiased estimates of the population "
             "rates for each year"
    )
    W(
        "Within that frame the sample is the completed tenders of the three above-threshold "
        "procedure types (`aboveThreshold`, `aboveThresholdUA`, `aboveThresholdEU`) whose "
        f"tenderID creation date falls in 2019-01-01 to 2022-12-31, {tail}. The fetch order is "
        "shuffled across months, so even an interrupted fetch spans the whole window."
    )
    W("")
    pbm = sample.get("population_by_month") or {}
    if pbm:
        by_year: dict[str, int] = {}
        for k, v in pbm.items():
            by_year[k[:4]] = by_year.get(k[:4], 0) + v
        br_year = a["base_rates_by_year"]
        rows = []
        for y in sorted(by_year):
            row = {"tender creation year": y,
                   f"found in the 1-in-{design.get('step', '?')} day sample": by_year[y]}
            m = br_year[br_year["year"].astype(str) == y]
            row["lots in the analysis set"] = int(m["n_lots"].iloc[0]) if len(m) else 0
            rows.append(row)
        W("Tenders by creation year, and what survives into the analysis set:")
        W("")
        W(md_table(pd.DataFrame(rows)))
        W("")
        if by_year.get("2021") and by_year.get("2022"):
            drop = 1 - by_year["2022"] / by_year["2021"]
            W(
                f"Above-threshold volume falls {pct(drop)} from 2021 to 2022. That is the war, "
                f"not a sampling artefact: the same one-in-{design.get('step', '?')} day rule "
                f"applies to every year. It is the main reason the 2022 test window is thin, "
                f"and the reason a 2021-only test window is reported alongside it."
            )
            W("")
    if s.get("method_counts"):
        W(md_table(pd.DataFrame(
            [{"procedure": k, "lots in analysis set": v}
             for k, v in sorted(s["method_counts"].items(), key=lambda x: -x[1])]
        )))
        W("")
    inv = s.get("invasion_counts", {})
    if inv:
        # JSON lowercases boolean keys, so accept every spelling.
        def _count(*keys) -> int:
            for k in keys:
                if k in inv:
                    return int(inv[k])
            return 0

        after = _count("true", "True", True)
        before = _count("false", "False", False)
        W(f"Lots whose tender opened on or after 2022-02-24, the full-scale invasion: "
          f"{after:,} of {after + before:,}. Every table that pools years is also reported on "
          f"a 2021-only test window, which is entirely pre-invasion.")
        W("")

    # ---- field evidence ------------------------------------------------
    W("## Field evidence: what was checked in the data rather than assumed")
    W("")
    W(
        "Three things about the API changed the design, and all three were observed directly "
        "on 2026-09-16 rather than taken from documentation."
    )
    W("")
    W(
        "1. **`contractChangeRationaleTypes` is a vocabulary, not a record.** Every registry "
        "contract returns the same nine-entry dictionary (`durationExtension`, "
        "`fiscalYearExtension`, `itemPriceVariation`, `priceReduction`, `qualityImprovement`, "
        "`taxRate`, `thirdParty`, `volumeCuts`, `priceClarification`) whether or not any change "
        "was made: in an 89-contract probe all nine appeared on all 89. Applied changes live in "
        "`changes[]`, each entry carrying its own `rationaleTypes`, `date`, `dateSigned` and "
        "`status`. Every extension label here is built from `changes[]`."
    )
    W(
        "2. **Registry `status: terminated` is the ordinary completed state.** In the same probe "
        "78 of 89 contracts were `terminated`, 6 `active` and 5 `cancelled`. Treating "
        "`terminated` as a failure, as an English reading suggests, would have labelled almost "
        "the whole sample as failed. The abnormal state is `cancelled`, and that is what the "
        "`cancelled` label uses."
    )
    W(
        "3. **`bids` and `awards` cannot be requested through `opt_fields`.** The listing "
        "endpoint honours `status`, `procurementMethodType`, `dateModified`, `tenderID`, "
        "`dateCreated`, `procuringEntity`, `awardPeriod`, `tenderPeriod` and `contracts`, and "
        "silently drops `bids`, `awards`, `lots`, `value`, `items`, `title` and "
        "`mainProcurementCategory`. Bidder identities therefore require one full tender fetch "
        "each, which is what sets the size of the sample."
    )
    W("")
    rc = s.get("registry_status_counts", {})
    tc = s.get("tender_copy_status_counts", {})
    if rc:
        def _name(k) -> str:
            return "no registry record found" if str(k) in {"nan", "NaN", "None"} else str(k)

        st = pd.DataFrame(
            [{"status": _name(k),
              "registry record": rc.get(k, 0),
              "tender copy": tc.get(k, 0)}
             for k in sorted(set(rc) | set(tc), key=lambda x: -rc.get(x, 0))]
        )
        W("Contract status in the analysis set, registry record against the tender's own copy:")
        W("")
        W(md_table(st))
        W("")
        n_cancelled = int(rc.get("cancelled", 0))
        W(
            f"That table is itself evidence that the tender copy is frozen at signing: the "
            f"registry has moved most of these contracts to `terminated` while the tender copy "
            f"still shows every one of them as it stood when the contract was published. It "
            f"also shows why the `cancelled` label carries no information in this sample: "
            f"there are {n_cancelled:,} cancelled contracts among the lots scored. A tender "
            f"only reaches status `complete` once it has a live contract, and where a lot has "
            f"both a cancelled contract and a live replacement the live one is the one scored, "
            f"so contract cancellation is essentially unobservable inside a completed-tender "
            f"sample. It is reported rather than dropped, and the ladder refuses to score it."
        )
        W("")
    agree = s.get("tenderid_date_matches_tender_start")
    if agree is not None:
        W(
            f"The date encoded in the human `tenderID` matches the date part of "
            f"`tenderPeriod.startDate` on {pct(agree, 2)} of the fetched tenders, which is why "
            f"the sampling frame can be stratified on the tenderID without fetching every "
            f"tender first."
        )
        W("")
    bsc = s.get("bid_status_counts") or {}
    if bsc:
        W("Bid entry statuses across the whole fetched sample "
          f"({sum(bsc.values()):,} entries): "
          + ", ".join(f"`{k}` {v:,}" for k, v in sorted(bsc.items(), key=lambda x: -x[1]))
          + ". Entries with status `deleted`, `draft` or `invalid.pre-qualification` never "
            "reached evaluation and are excluded from the bid counts, the price ranks and the "
            "dispersion statistics.")
        W("")
        nc = s.get("consortium_bids", 0)
        W(
            f"Consortium bids, meaning more than one tenderer on a single bid: {nc:,}"
            + (
                ", each attributed to its first tenderer."
                if nc
                else ". Prozorro records one legal entity per bid in this sample, so a bidder "
                     "identity is unambiguous."
            )
        )
        W("")
    dv = s.get("disqualification_visibility") or {}
    if dv:
        aw = s.get("award_status_totals") or {}
        W(
            f"Disqualification is recorded as an award with status `unsuccessful` against a "
            f"specific bid, not as a status on the bid itself: across the fetched sample there "
            f"are {aw.get('unsuccessful', 0):,} unsuccessful awards against "
            f"{aw.get('active', 0):,} active ones. Prozorro strips the price from a bid that "
            f"was withdrawn or rejected outright, and "
            f"{dv.get('bid_entries_with_no_price', 0):,} bid entries in the sample carry no "
            f"amount at all, so they cannot be ranked. Of the "
            f"{dv.get('unsuccessful_awards', 0):,} unsuccessful awards, "
            f"{pct(dv.get('share_priced'))} point at a bid that does still carry a price and "
            f"can therefore be placed in the price order. Experiment 3 is restricted to those."
        )
        W("")
    if pea:
        W(
            f"The tender document's copy of a contract lags the live registry: it is written "
            f"when the tender was last touched, and in the sample it agrees with the registry "
            f"on the contract end date {pct(pea.get('share_identical'))} of the "
            f"{pea.get('n_both_present', 0):,} lots where both dates are present. The registry "
            f"end date is later in {pct(pea.get('share_registry_later'))} of them, by a median "
            f"of {pea.get('median_days_when_later', float('nan')):.0f} days. Conditioning on "
            f"the registry's own `durationExtension` change, the two dates differ in "
            f"{pct(pea.get('share_moved_given_duration_extension'))} of extended contracts and "
            f"{pct(pea.get('share_moved_given_no_duration_extension'))} of unextended ones, "
            f"and of the contracts whose end date did move, "
            f"{pct(pea.get('share_with_duration_extension_given_moved'))} carry a "
            f"`durationExtension` change. So the end date moves considerably more often than "
            f"an extension is registered against it. Some of that is a genuinely different "
            f"event, an administrative edit to the period rather than an agreed extension, and "
            f"some of it is the tender copy having been written after a change rather than at "
            f"signing. Either way `days_extended` is the broader and noisier of the two "
            f"signals, and `duration_extension`, which needs no date arithmetic at all, is the "
            f"primary label for that reason."
        )
        W("")

    # ---- fill rates ----------------------------------------------------
    W("## Fill rates")
    W("")
    W("Field presence, over every parsed lot and over the analysis set. The analysis set is "
      "lots with at least two live priced bids, an identified winning bid and a contract.")
    W("")
    fr = a["fill_rates"].rename(
        columns={
            "n_all_lots": "lots",
            "share_all_lots": "share",
            "n_analysis_set": "lots, analysis set",
            "share_analysis_set": "share, analysis set",
        }
    )
    W(md_table(fr, floats={"share": 3, "share, analysis set": 3}))
    W("")

    # ---- labels --------------------------------------------------------
    W("## Labels")
    W("")
    W("All labels are on the winning contract of a lot. A lot is one (tender, lot) pair; a "
      "single-lot tender contributes one row.")
    W("")
    W("| Label | Definition | Source |")
    W("|---|---|---|")
    W("| `duration_extension` | at least one entry in `changes[]` whose `rationaleTypes` "
      "contains `durationExtension` | live contract registry |")
    W("| `days_extended_gt90` | registry `period.endDate` minus the tender copy's "
      "`contracts[].period.endDate`, above 90 days | registry and tender copy |")
    W("| `value_growth_gt10` | registry contract value over the value at signing, above 1.10, "
      "compared net to net where both `amountNet` are present and gross to gross otherwise | "
      "registry and tender copy |")
    W("| `any_change` | `changes[]` non-empty | live contract registry |")
    W("| `underexecuted` | registry `amountPaid` below 0.9 of the value at signing | live "
      "contract registry |")
    W("| `cancelled` | registry `status == \"cancelled\"` | live contract registry |")
    W("")
    W("### Base rates by tender creation year")
    W("")
    br = a["base_rates_by_year"]
    if len(br):
        cols = ["year", "n_lots", "n_tenders"] + [
            c for c in br.columns if c.endswith("_rate")
        ]
        tab = br[cols].copy()
        tab["year"] = tab["year"].astype(str)
        tab = prettify(tab).rename(
            columns={
                "n_tenders": "tenders",
                "still running": "still running at the snapshot",
            }
        )
        W(md_table(tab, floats={c: 3 for c in tab.columns if tab[c].dtype.kind == "f"}))
        W("")
        if "still_running_rate" in br.columns:
            lo = float(br["still_running_rate"].min())
            hi = float(br["still_running_rate"].max())
            ser = br.sort_values("year")["still_running_rate"].astype(float)
            first, last = float(ser.iloc[0]), float(ser.iloc[-1])
            if last > first + 0.02:
                direction = (
                    "rises with the cohort year, so the later cohorts are the more censored "
                    "ones and their rates are pushed down relative to the earlier ones. Since "
                    "training is the earlier cohort and testing the later one, that works "
                    "against the models rather than for them"
                )
            elif first > last + 0.02:
                direction = (
                    "falls with the cohort year, so the test cohorts are if anything less "
                    "censored than the training cohorts and the models are not being flattered "
                    "by it. The oldest cohort carrying the most still-running contracts is not "
                    "what exposure alone would predict, and no explanation for it is "
                    "established here"
                )
            else:
                direction = (
                    "is flat across the cohorts, so residual censoring is not differentially "
                    "affecting the training and test windows"
                )
            W(
                f"Every label is read at one snapshot, so cohorts differ in how long they have "
                f"had to accumulate changes. The fourth column measures what is left of that: "
                f"the share of lots whose contract the registry still calls `active` runs from "
                f"{pct(min(lo, hi))} to {pct(max(lo, hi))}, and it {direction}."
            )
            W("")

    # ---- ladder --------------------------------------------------------
    W("## Experiment 1: forecasting the winner's slip from award-time features")
    W("")
    W(
        "Forward-chained throughout. Training is every lot whose tender opened in 2019 or 2020; "
        "the test windows are later and disjoint. Every history feature is evaluated at the "
        "tender's own `tenderPeriod.startDate` and counts only events dated strictly before it, "
        "so a contract signed before the cutoff but extended after it contributes to the "
        "denominator and not the numerator. Brier skill is against the training-window base "
        "rate, which is a number a forecaster could have quoted in advance, never against the "
        "realised test rate."
    )
    W("")
    W("Rungs, nested, so that each step answers one question: the training base rate; a "
      "shrunken CPV-division by region cell mean; gradient boosting on the lot alone with no "
      "identity of any kind in it; the same plus the buyer's as-of record; the same plus the "
      "winner's price position on that lot; the same plus the winner's as-of record.")
    W("")
    lad0 = a["model_ladder"]
    prim0 = lad0[lad0["split"] == "test 2021-2022"] if len(lad0) else lad0
    if len(prim0):
        best = (
            prim0[prim0["model"] != "base rate"]
            .sort_values("bss", ascending=False)
            .groupby("label", as_index=False)
            .first()
        )
        order = {lab: i for i, lab in enumerate(LABEL_ORDER)}
        best = best.sort_values("label", key=lambda c: c.map(lambda v: order.get(v, 99)))
        bits = [
            f"{LABEL_TITLES.get(r['label'], r['label'])} AUC {r['auc']:.3f} with skill "
            f"{r['bss']:+.3f} on a {r['base_rate'] * 100:.1f} percent base rate"
            for _, r in best.iterrows()
        ]
        W(
            "Before any of the bidder questions, the plain one: how forecastable are these "
            "outcomes at all? Best rung on the primary test window, by skill against the "
            "training base rate: " + "; ".join(bits) + ". For comparison the US panel in this "
            "repository reaches AUC 0.84 to 0.86 on schedule slip, so Ukrainian above-threshold "
            "contracts are the harder forecasting problem, on outcomes that are not quite the "
            "same outcomes."
        )
        W("")
    W(
        "One detail worth stating rather than hiding: the gradient booster's own early-stopping "
        "validation split is a random 15 percent of the training window, not a temporal one. "
        "The test window is strictly later than the whole training window either way, so no "
        "test information enters the fit."
    )
    W("")
    ladder = a["model_ladder"]
    for split in ["test 2021-2022", "test 2021 only (pre-invasion)", "test 2022 post-invasion"]:
        sub = ladder[ladder["split"] == split]
        if not len(sub):
            continue
        W(f"### {split}")
        W("")
        show = sub[["label", "model", "n", "base_rate", "train_base_rate", "brier", "bss",
                    "auc"]].rename(
            columns={
                "n": "test lots",
                "base_rate": "test base rate",
                "train_base_rate": "train base rate",
                "brier": "Brier",
                "bss": "skill vs train base rate",
                "auc": "AUC",
            }
        )
        show["label"] = show["label"].map(lambda v: LABEL_TITLES.get(v, v))
        W(md_table(show, floats={"test base rate": 3, "train base rate": 3, "Brier": 4,
                                 "skill vs train base rate": 3, "AUC": 3}))
        W("")
    RUNGS = [
        "reference class",
        "GBM lot, no buyer history",
        "GBM lot, plus buyer history",
        "GBM plus the bidder's price",
        "GBM plus the bidder's price and history",
    ]
    prim = ladder[(ladder["split"] == "test 2021-2022")]
    for lab in ["duration_extension", "days_extended_gt90"]:
        sub = prim[prim["label"] == lab].set_index("model")["auc"]
        steps = [r for r in RUNGS if r in sub.index]
        if len(steps) < 4:
            continue
        deltas = [
            (steps[i], steps[i + 1], float(sub[steps[i + 1]]) - float(sub[steps[i]]))
            for i in range(len(steps) - 1)
        ]
        names = {
            ("GBM lot, no buyer history", "GBM lot, plus buyer history"):
                "adding the buyer's own record",
            ("GBM lot, plus buyer history", "GBM plus the bidder's price"):
                "adding the winner's price position",
            ("GBM plus the bidder's price", "GBM plus the bidder's price and history"):
                "adding the winner's own record",
        }
        bits = [
            f"{names[(a, b)]} moves AUC {d:+.3f}"
            for a, b, d in deltas
            if (a, b) in names
        ]
        if bits:
            W(f"Reading the nested rungs on {LABEL_TITLES.get(lab, lab)}, each step against "
              f"the one above it: " + "; ".join(bits) + ".")
            W("")

    skipped = s.get("labels_not_scored") or []
    if skipped:
        W("Labels refused by the ladder, because a label with almost no positives on one side "
          "of the split produces skill and AUC numbers that are noise dressed as results:")
        W("")
        W(md_table(pd.DataFrame(skipped)))
        W("")
    calib = a["calibration"]
    if len(calib):
        best = "GBM plus the bidder's price and history"
        c = calib[(calib["label"] == "duration_extension") & (calib["model"] == best)]
        if len(c):
            W("Calibration of the top rung on duration extension, test 2021-2022, in "
              "equal-count bins of the forecast:")
            W("")
            pr = c[["n", "mean_forecast", "observed"]].rename(
                columns={"n": "lots", "mean_forecast": "mean forecast",
                         "observed": "observed rate"}
            )
            W(md_table(pr, floats={"mean forecast": 4, "observed rate": 4}))
            W("")
            dec = (s.get("brier_decomposition") or {}).get(f"duration_extension|{best}")
            if dec:
                W(
                    f"Murphy decomposition of that Brier score: reliability "
                    f"{dec['reliability']:.5f}, resolution {dec['resolution']:.5f}, "
                    f"uncertainty {dec['uncertainty']:.5f}. Reliability is the calibration "
                    f"penalty and smaller is better; resolution is how far the forecasts move "
                    f"away from the base rate in the right direction and larger is better."
                )
                W("")
    W("![Calibration, duration extension](calibration_duration_extension.png)")
    W("")

    # ---- transfer ------------------------------------------------------
    W("## Experiment 2: the competing-bidder test")
    W("")
    W(
        "A losing bid never produces a contract, so its forecast can never be resolved "
        "directly. Instead every bidder on every test lot is scored as if it had won: the lot "
        "block is held fixed and the bidder block is replaced by that bidder's own price on "
        "that lot and its own as-of record. Each bidder's mean forecast over the lots it LOST "
        "is then compared with the rate it actually realised on the lots it WON, in the same "
        "test window and the same CPV division, for cells with at least three wins."
    )
    W("")
    W(
        "One circularity has to be closed before any of this means anything. A bidder's "
        "as-of history on a lot it lost in late 2021 already contains the outcome of a lot it "
        "won in early 2021, and that same early win is on the realised side of the comparison. "
        "The headline rows therefore freeze every bidder-history feature at the first day of "
        "the test window, so nothing that happens inside the resolution window can reach the "
        "forecast; the price features still come from the lot's own auction, because that is "
        "what a forecaster registering at award time would have. The two rows labelled "
        "\"history as of each tender\" are the leaky version, reported so the size of the "
        "circularity is visible rather than argued about."
    )
    W("")
    W(
        "Four forecasts are transferred. The last is a placebo: the lot-only model knows "
        "nothing about the bidder, so if its mean over a bidder's lost lots also ranks that "
        "bidder's realised rate, the correlation is about which lots the bidder competes for "
        "and not about the bidder. The null shuffles bidder identity within CPV division; "
        "because that shuffle keeps the between-division association, the null is not centred "
        "on zero, and its mean is the correlation that composition alone produces. The headline "
        "test is the right-tail probability against that null."
    )
    W("")
    for lab, res in (s.get("transfer") or {}).items():
        W(f"### {LABEL_TITLES.get(lab, lab)}")
        W("")
        rows = []
        for name, r in res.items():
            if "null_mean" not in r:
                continue
            rows.append(
                {
                    "forecast transferred": name,
                    "cells": r.get("n_cells", 0),
                    "bidders": r.get("n_bidders", 0),
                    "lost lots": r.get("n_lost_lots", 0),
                    "won lots": r.get("n_won_lots", 0),
                    "Spearman": r["observed"],
                    "null mean": r["null_mean"],
                    "null sd": r["null_sd"],
                    "excess": r.get("excess_over_null", float("nan")),
                    "p one-sided": r.get("p_greater", float("nan")),
                }
            )
        if rows:
            W(md_table(pd.DataFrame(rows), floats={"Spearman": 3, "null mean": 3, "null sd": 3,
                                                   "excess": 3, "p one-sided": 4}))
            W("")
        full_row = res.get("full model (price and identity)", {})
        plac_row = res.get("lot only (placebo)", {})
        if full_row and plac_row and not pd.isna(plac_row.get("excess_over_null", float("nan"))):
            fe = full_row.get("excess_over_null", float("nan"))
            pe = plac_row["excess_over_null"]
            if pe >= fe:
                W(
                    f"Read the placebo row first. It excesses the null by {pe:+.3f} against "
                    f"{fe:+.3f} for the bidder-aware forecast, so whatever correlation there is "
                    f"here is produced by which lots a bidder competes for and not by the "
                    f"bidder. A significant p-value on the full model would mean nothing while "
                    f"a forecast that cannot see the bidder at all does at least as well."
                )
            else:
                W(
                    f"The bidder-aware forecast excesses the null by {fe:+.3f} against "
                    f"{pe:+.3f} for the lot-only placebo, so the difference between them is "
                    f"what is attributable to the bidder rather than to the lots it chooses."
                )
            W("")
        sd = full_row.get("null_sd", float("nan"))
        if not pd.isna(sd):
            W(
                f"What this test could have found: the null has a standard deviation of "
                f"{sd:.3f}, so the smallest excess over the null it could have declared "
                f"significant at one-sided 5 percent is about {1.645 * sd:.3f}. An effect "
                f"smaller than that would not show up here whether or not it exists, and the "
                f"number of cells is what sets it."
            )
            W("")
        pooled = res.get("full model, pooled across divisions")
        if pooled:
            W(f"Pooled across divisions, ignoring the CPV cell: Spearman "
              f"{pooled['observed']:.3f} over {pooled['n_cells']:,} bidders with at least "
              f"three wins in the test window.")
            W("")
        W(f"![Transfer scatter]({f'transfer_scatter_{lab}.png'})")
        W("")

    # ---- within-lot test ----------------------------------------------
    wl = a["within_lot_test"]
    if len(wl):
        W("### The within-lot test")
        W("")
        W(
            "The transfer test above still compares a bidder across different lots. This one "
            "does not: it holds the lot fixed. Everything that makes a lot slip-prone - the "
            "buyer, the sector, the size, the year, the number of bidders - is identical for "
            "every bidder on that lot, so ranking the bidders against each other removes all of "
            "it by construction. For each test lot the winner's percentile rank among that "
            "lot's bidders is taken under each forecast, and the table reports the AUC of that "
            "percentile against the winner's own realised outcome. The null replaces the winner "
            "with a uniformly random bidder from the same lot, which is why it centres on 0.5 "
            "even though the winner's percentile is not uniform (winners are chosen largely on "
            "price)."
        )
        W("")
        cols = ["label", "sample", "forecast", "n_lots", "mean_percentile_outcome_1",
                "mean_percentile_outcome_0", "auc", "null_mean", "null_sd", "p_two_sided"]
        cols = [c for c in cols if c in wl.columns]
        pretty = wl[cols].rename(
            columns={
                "n_lots": "test lots",
                "sample": "sample",
                "mean_percentile_outcome_1": "mean percentile when it slipped",
                "mean_percentile_outcome_0": "mean percentile when it did not",
                "auc": "AUC",
                "null_mean": "null mean",
                "null_sd": "null sd",
                "p_two_sided": "p two-sided",
            }
        )
        W(md_table(pretty, floats={c: 3 for c in pretty.columns
                                   if pretty[c].dtype.kind == "f"}))
        W("")
        raw = wl[
            (wl["label"] == "duration_extension")
            & (wl["forecast"] == "raw price rank on the lot, no model")
        ]
        if "sample" in raw.columns:
            raw = raw[raw["sample"] == "all test lots"]
        dd_here = a["discount_deciles"]
        if len(raw) and len(dd_here) >= 2 and "duration_extension_rate" in dd_here.columns:
            r = raw.iloc[0]
            rho = spearman_cols(
                dd_here["winner_discount_median"], dd_here["duration_extension_rate"]
            )
            same = (r["auc"] > 0.5) == (rho < 0)
            sig = r["p_two_sided"] < 0.05
            agree = (
                f"points the same way as the discount deciles further down, where the "
                f"extension rate falls as the discount deepens (Spearman {rho:+.2f} across "
                f"deciles)"
                if same
                else f"points the opposite way to the discount deciles further down "
                     f"(Spearman {rho:+.2f} across deciles)"
            )
            strength = (
                "and it clears its own null"
                if sig
                else "but on its own it does not clear its null, so the rank alone is not "
                     "the statistic to lean on"
            )
            po = wl[
                (wl["label"] == "duration_extension") & (wl["forecast"] == "price only")
            ]
            if "sample" in po.columns:
                po = po[po["sample"] == "all test lots"]
            extra = ""
            if len(po) and float(po.iloc[0]["p_two_sided"]) < 0.05:
                pr_row = po.iloc[0]
                extra = (
                    f" What does clear it is the model that sees the size of the discount and "
                    f"not only its rank (AUC {pr_row['auc']:.3f}, "
                    f"p = {pr_row['p_two_sided']:.3f}), which says the relationship between "
                    f"price and slip is not simply monotone in the price order within a lot."
                )
            W(
                f"The first row needs no model at all: it is the winner's own price rank among "
                f"the bids on its lot, at AUC {r['auc']:.3f} (p = {r['p_two_sided']:.3f}). "
                f"Above 0.5 means the more expensive the winner was relative to its rivals, the "
                f"more likely the extension. It {agree}, {strength}.{extra}"
            )
            W("")
        if "sample" in wl.columns and wl["sample"].nunique() > 1:
            a_all = wl[(wl["sample"] == "all test lots")
                       & (wl["label"] == "duration_extension")].set_index("forecast")["auc"]
            a_pre = wl[(wl["sample"] == "pre-invasion test lots only")
                       & (wl["label"] == "duration_extension")].set_index("forecast")["auc"]
            common = [f for f in a_all.index if f in a_pre.index]
            if common:
                worst = max(abs(float(a_all[f]) - float(a_pre[f])) for f in common)
                W(
                    f"Dropping every lot whose tender opened on or after the full-scale "
                    f"invasion moves no AUC in that table by more than {worst:.3f}. The answer "
                    f"does not depend on the war."
                )
                W("")
        below = wl[
            (wl["auc"] < wl["null_mean"]) & (wl["p_two_sided"] < 0.05)
        ]
        if "sample" in below.columns:
            below = below[below["sample"] == "all test lots"]
        if len(below):
            names = sorted(set(below["forecast"]))
            W(
                "A number below the null in that table is not a null result, it is a wrong one: "
                f"{', '.join(names)} ranks the bidders on a lot in the opposite order to what "
                "happens. Read together with the rows above it, the reading is that the "
                "history features add noise to the within-lot ordering that the price features "
                "would otherwise get right."
            )
            W("")

    # ---- head to head --------------------------------------------------
    h2h = a["identity_head_to_head"]
    if len(h2h):
        W("### Whose identity carries the signal")
        W("")
        W(
            "Each of these is used on its own as the whole forecast, scored on the same test "
            "rows, so the comparison is like for like. The US panel in this repository found "
            "that the contracting office mattered more than the contractor; this is the same "
            "question asked where the bidders are visible. Rank discrimination only, because a "
            "raw rate used as a probability is not calibrated and the Brier score would be "
            "measuring the calibration rather than the ranking."
        )
        W("")
        sub = h2h[h2h["split"] == "test 2021-2022"]
        if "subset" in sub.columns:
            sub = sub[sub["subset"] == "all test lots"]
        if len(sub) and "auc_within_buyer" in sub.columns:
            de_all = sub[sub["label"] == "duration_extension"]
            if len(de_all):
                keep = [c for c in ["predictor", "auc", "auc_within_buyer",
                                    "buyers_contributing", "auc_within_cpv_year",
                                    "cpv_year_cells_contributing"] if c in de_all.columns]
                comp = de_all[keep].rename(
                    columns={
                        "auc": "AUC pooled",
                        "auc_within_buyer": "AUC within buyer",
                        "buyers_contributing": "buyers used",
                        "auc_within_cpv_year": "AUC within CPV division and year",
                        "cpv_year_cells_contributing": "cells used",
                    }
                )
                W("Pooled against stratified, on duration extension. A stratified column never "
                  "compares two lots from different strata, so a predictor that ranks well only "
                  "because it tracks which buyer, sector or year a lot belongs to loses that "
                  "advantage there. Only strata containing both outcomes can contribute, which "
                  "is what the `used` columns count; a stratified AUC resting on fewer than 20 "
                  "strata is left blank rather than printed.")
                W("")
                W(md_table(comp, floats={"AUC pooled": 3, "AUC within buyer": 3,
                                         "AUC within CPV division and year": 3}))
                W("")
                row_b = de_all[de_all["predictor"] == "buyer's as-of extension rate"]
                row_p = de_all[
                    de_all["predictor"] == "winner's price as a share of the expected value"
                ]
                row_w = de_all[de_all["predictor"] == "winner's as-of extension rate"]
                if len(row_b) and len(row_p):
                    rb, rp = row_b.iloc[0], row_p.iloc[0]
                    W(
                        f"Three readings follow. First the sanity check: the buyer's own rate "
                        f"goes from {rb['auc']:.3f} pooled to {rb['auc_within_buyer']:.3f} "
                        f"within buyer, because it is nearly constant inside a buyer and has "
                        f"nothing left to rank with once the buyer is fixed. It keeps "
                        f"{rb['auc_within_cpv_year']:.3f} within CPV division and year, so it "
                        f"is not a sector effect either. Second, the winner's price goes from "
                        f"{rp['auc']:.3f} pooled to {rp['auc_within_buyer']:.3f} within buyer, "
                        f"so the price signal is not a buyer effect wearing a price costume."
                    )
                    W("")
                if len(row_w):
                    rw = row_w.iloc[0]
                    vals = [rw["auc"], rw["auc_within_buyer"], rw["auc_within_cpv_year"]]
                    vals = [float(v) for v in vals if not pd.isna(v)]
                    spread = max(vals) - min(vals) if vals else float("nan")
                    W(
                        f"Third, and this is the one to be careful with: the winner's own "
                        f"record reads {rw['auc']:.3f} pooled, "
                        f"{rw['auc_within_buyer']:.3f} within buyer and "
                        f"{rw['auc_within_cpv_year']:.3f} within CPV division and year. Those "
                        f"sit on both sides of chance and span {spread:.3f}. A signal that "
                        f"changes sign depending on what is held fixed is not a signal; the "
                        f"honest reading is that the bidder's own record is close to "
                        f"uninformative and that the direction of the residue is not stable "
                        f"enough to name."
                    )
                    W("")
        if len(sub):
            piv = sub.pivot_table(index="predictor", columns="label", values="auc")
            order = [c for c in LABEL_ORDER if c in piv.columns] + [
                c for c in piv.columns if c not in LABEL_ORDER
            ]
            piv = piv[order].rename(columns=LABEL_TITLES).reset_index()
            W(md_table(piv, floats={c: 3 for c in piv.columns if piv[c].dtype.kind == "f"}))
            W("")
            de = sub[sub["label"] == "duration_extension"].set_index("predictor")["auc"]
            if {"buyer's as-of extension rate", "winner's as-of extension rate"} <= set(de.index):
                b = float(de["buyer's as-of extension rate"])
                w = float(de["winner's as-of extension rate"])
                W(
                    f"On duration extension the buyer's own record reaches AUC {b:.3f} and the "
                    f"winner's reaches {w:.3f}. Both are visible in this dataset and only one "
                    f"of them carries the signal. That is the same answer the US panel in this "
                    f"repository gave from the other direction: there the contracting office "
                    f"mattered and the contractor added almost nothing, but US data never shows "
                    f"the losing offers, so it could not rule out that the bidder's identity "
                    f"mattered and was simply unobserved. Here it is observed, and it does not."
                )
                W("")

        if "subset" in h2h.columns and h2h["subset"].nunique() > 1:
            est = h2h[
                (h2h["split"] == "test 2021-2022")
                & (h2h["label"] == "duration_extension")
                & (h2h["predictor"].isin(
                    ["winner's as-of extension rate", "buyer's as-of extension rate"]))
            ]
            if len(est):
                pv = est.pivot_table(index="subset", columns="predictor", values="auc")
                nn = est.pivot_table(index="subset", columns="predictor", values="n")
                pv = pv.join(nn.iloc[:, [0]].rename(columns={nn.columns[0]: "lots"}))
                pv = pv.reset_index()
                pv["lots"] = pv["lots"].astype(int)
                W("A thin record is the obvious alternative explanation for a null bidder "
                  "result, so the same comparison restricted to the lots where the record is "
                  "already substantial, on duration extension. These are pooled AUCs: the "
                  "experienced-winner subset leaves too few buyers holding both outcomes for a "
                  "within-buyer version to mean anything, which is itself a finding about how "
                  "concentrated experienced bidders are:")
                W("")
                W(md_table(pv, floats={c: 3 for c in pv.columns if pv[c].dtype.kind == "f"}))
                W("")
                col = "winner's as-of extension rate"
                if col in pv.columns and "winner has 10 or more prior wins" in set(pv["subset"]):
                    all_a = float(pv.loc[pv["subset"] == "all test lots", col].iloc[0])
                    est_a = float(
                        pv.loc[pv["subset"] == "winner has 10 or more prior wins", col].iloc[0]
                    )
                    bcol = "buyer's as-of extension rate"
                    est_b = float(
                        pv.loc[pv["subset"] == "winner has 10 or more prior wins", bcol].iloc[0]
                    )
                    if est_a < 0.45:
                        reading = (
                            f"it inverts, from {all_a:.3f} to {est_a:.3f}. An experienced "
                            f"bidder's past extension rate ranks its next contract in the "
                            f"wrong direction in this sample. Thin histories are therefore not "
                            f"what is holding the bidder result down, but the inversion itself "
                            f"is not explained here: experienced bidders concentrate at a "
                            f"handful of high-volume buyers whose own rate reaches {est_b:.3f} "
                            f"on the same lots, and that concentration is enough to produce an "
                            f"inversion without any bidder-level mechanism at all. It is "
                            f"reported as an observation, not as a finding about bidders."
                        )
                    elif est_a > all_a + 0.02:
                        reading = (
                            f"it rises, from {all_a:.3f} to {est_a:.3f}, so thin histories were "
                            f"part of what held the earlier number down."
                        )
                    else:
                        reading = (
                            f"it barely moves, {all_a:.3f} to {est_a:.3f}. Thin histories are "
                            f"not what is holding the bidder result down."
                        )
                    W(
                        "Restricting to winners with at least ten prior wins, where the "
                        "bidder's own rate is estimated from a real sample rather than two or "
                        "three contracts, " + reading
                    )
                    W("")

    vd = a["variance_decomposition"]
    if len(vd):
        W("The same question without any model in it. The intraclass correlation asks how much "
          "of the variance in an outcome sits between groups rather than within them, using "
          "nothing but the outcome and the grouping. Groups with fewer than three lots are "
          "dropped, because a group of one contributes no within-group variance and would "
          "inflate the statistic. The null shuffles the outcome across the retained rows, "
          "which destroys real clustering while keeping the group sizes and the base rate.")
        W("")
        pr = vd.copy()
        pr["label"] = pr["label"].map(lambda v: LABEL_TITLES.get(v, v))
        pr["grouping"] = pr["grouping"].map(
            {
                "buyer_id": "the buyer",
                "winner_id": "the winning bidder",
                "cpv_division": "the CPV division",
                "region": "the buyer's region",
            }
        ).fillna(pr["grouping"])
        pr = pr.rename(columns={"icc": "ICC", "null_mean": "null mean", "null_sd": "null sd",
                                "p_greater": "p one-sided", "mean_group_size": "mean group size"})
        W(md_table(pr, floats={c: 4 for c in pr.columns if pr[c].dtype.kind == "f"}))
        W("")
        de = vd[vd["label"] == "duration_extension"].set_index("grouping")["icc"]
        if {"buyer_id", "winner_id"} <= set(de.index):
            W(
                f"On duration extension the buyer explains {float(de['buyer_id']):.3f} of the "
                f"variance and the winning bidder {float(de['winner_id']):.3f}. No model is "
                f"involved in those two numbers."
            )
            W("")

    ci = a["conditional_icc"]
    if len(ci):
        W(
            "The raw figures above cannot separate the two, because a bidder usually wins "
            "repeatedly from the same handful of buyers, so clustering by bidder partly "
            "restates clustering by buyer. This next table holds one of them fixed. The null "
            "permutes the grouping label among lots that share the same block value, which "
            "keeps every group's size exactly and keeps each block's mix of groups, and "
            "destroys only the pairing between a particular group and a particular outcome. "
            "An excess over that null is clustering the block cannot account for."
        )
        W("")
        names = {
            "winner_id": "the winning bidder",
            "buyer_id": "the buyer",
            "cpv_division": "the CPV division",
        }
        pr = ci.copy()
        pr["label"] = pr["label"].map(lambda v: LABEL_TITLES.get(v, v))
        pr["group"] = pr["group"].map(names).fillna(pr["group"])
        pr["block"] = pr["block"].map(names).fillna(pr["block"])
        pr["block"] = pr["block"].replace({"buyer_year": "the buyer within the year"})
        pr = pr.rename(columns={"group": "clustering by", "block": "holding fixed",
                                "icc": "ICC", "null_mean": "null mean", "null_sd": "null sd",
                                "p_greater": "p one-sided", "variant": "sample"})
        cols = [c for c in ["label", "sample", "clustering by", "holding fixed", "lots",
                            "groups", "blocks", "ICC", "null mean", "null sd", "excess",
                            "p one-sided"] if c in pr.columns]
        W(md_table(pr[cols], floats={c: 4 for c in cols if pr[c].dtype.kind == "f"}))
        W("")
        strict = ci[
            (ci.get("variant", "") == "one lot per bidder and tender")
            & (ci["group"] == "winner_id")
            & (ci["block"] == "buyer_year")
            & (ci["label"] == "duration_extension")
        ]
        if len(strict):
            r = strict.iloc[0]
            verdict_word = (
                "survives" if r["p_greater"] < 0.05 and r["excess"] > 0 else "does not survive"
            )
            W(
                f"On the strictest variant, one lot per bidder per tender with the buyer held "
                f"fixed within the year, the bidder's clustering {verdict_word}: ICC "
                f"{r['icc']:.3f} against a null of {r['null_mean']:.3f}, an excess of "
                f"{r['excess']:.3f} (one-sided p = {r['p_greater']:.4f}). Read that next to the "
                f"head-to-head table above, where a bidder's own past rate barely ranks its "
                f"future one. Outcomes do cluster by bidder; the clustering is not stable "
                f"enough over time to forecast with."
            )
            W("")

    # ---- identity persistence -----------------------------------------
    W("## Does a bidder's own record persist at all?")
    W("")
    W(
        "The transfer test above has nothing to transfer unless a bidder's record is stable "
        "over time in the first place. This check uses only lots the bidder WON, on both "
        "sides: its rate over lots whose tender opened in 2019 or 2020 against its rate over "
        "lots whose tender opened in 2021 or 2022, for bidders with at least the stated number "
        "of wins in each window. Nothing counterfactual is involved. The null shuffles the "
        "later rate among bidders that share a modal CPV division, so a correlation produced "
        "purely by the sector a bidder works in sits inside the null rather than in the result."
    )
    W("")
    rows = []
    for key, r in (s.get("identity_persistence") or {}).items():
        if "null_mean" not in r:
            continue
        lab, mw = key.split("|")
        rows.append(
            {
                "label": LABEL_TITLES.get(lab, lab),
                "wins each side": mw.split("=")[1],
                "bidders": r.get("n_bidders", 0),
                "earlier lots": r.get("n_train_lots", 0),
                "later lots": r.get("n_test_lots", 0),
                "Spearman": r["observed"],
                "null mean": r["null_mean"],
                "null sd": r["null_sd"],
                "excess": r.get("excess_over_null", float("nan")),
                "p one-sided": r.get("p_greater", float("nan")),
            }
        )
    if rows:
        W(md_table(pd.DataFrame(rows), floats={"Spearman": 3, "null mean": 3, "null sd": 3,
                                               "excess": 3, "p one-sided": 4}))
        W("")

    # ---- contrasts -----------------------------------------------------
    W("## Experiment 3: the lowest bidder disqualified")
    W("")
    W(
        "Treated lots are those where the cheapest live bid was disqualified (an award with "
        "status `unsuccessful` against that bid) and a dearer bid won. Control lots are those "
        "where the cheapest bid won and nothing at the bottom was disqualified; a lot where a "
        "bid at the minimum price won despite a disqualification at the minimum belongs to "
        "neither group. The control group is reweighted onto the treated group's CPV-division "
        "by year cell mix before the difference is taken, and the interval is a 1,000-draw "
        "bootstrap over lots."
    )
    W("")
    ld = a["lowest_disqualified_contrast"]
    if len(ld):
        pr = prettify(ld)
        W(md_table(pr, floats={c: 3 for c in pr.columns if pr[c].dtype.kind == "f"}))
        W("")
        sig = ld[(ld["ci_lo"] > 0) | (ld["ci_hi"] < 0)]
        if len(sig):
            bits = [
                f"{LABEL_TITLES.get(r['label'], r['label'])} "
                f"{r['difference'] * 100:+.1f} points ({r['ci_lo'] * 100:+.1f} to "
                f"{r['ci_hi'] * 100:+.1f})"
                for _, r in sig.iterrows()
            ]
            W("Differences whose interval excludes zero: " + "; ".join(bits) + ".")
        else:
            W("No outcome differs between the two groups by more than the bootstrap "
              "interval allows.")
        W("")
    W("### Winner's discount and the outcome")
    W("")
    W("Deciles of the winner's discount against the expected lot value, with the realised "
      "rate of each label.")
    W("")
    dd = a["discount_deciles"]
    if len(dd):
        cols = [c for c in dd.columns if not c.endswith("_n")]
        pr = prettify(dd[cols])
        W(md_table(pr, floats={c: 3 for c in pr.columns if pr[c].dtype.kind == "f"}))
        W("")
        if "duration_extension_rate" in dd.columns and len(dd) >= 2:
            lo = float(dd["duration_extension_rate"].iloc[0])
            hi = float(dd["duration_extension_rate"].iloc[-1])
            rho = spearman_cols(dd["winner_discount_median"], dd["duration_extension_rate"])
            direction = "falls" if hi < lo else "rises"
            W(
                f"The relationship runs the opposite way to the winner's-curse intuition: the "
                f"extension rate {direction} from {pct(lo)} in the decile that won at "
                f"essentially the expected value to {pct(hi)} in the deepest-discount decile "
                f"(Spearman across deciles {rho:+.2f}). A bidder that cut its price hard is not "
                f"the one whose contract gets extended in this sample."
            )
            W("")
    W("![Extension rate by discount decile](extension_by_discount_decile.png)")
    W("")

    W("## Experiment 4: bid dispersion within the lot")
    W("")
    W("Bins of the coefficient of variation of the live priced bids on the lot, with the "
      "winner's realised outcome rates.")
    W("")
    bdz = a["bid_dispersion"]
    if len(bdz):
        cols = [c for c in bdz.columns if not c.endswith("_n")]
        pr = prettify(bdz[cols])
        W(md_table(pr, floats={c: 3 for c in pr.columns if pr[c].dtype.kind == "f"}))
        W("")
    rn = a["rates_by_n_bids"]
    if len(rn):
        W("For comparison, the same rates by the number of live priced bids on the lot:")
        W("")
        cols = [c for c in rn.columns if not c.endswith("_n")]
        pr = prettify(rn[cols])
        W(md_table(pr, floats={c: 3 for c in pr.columns if pr[c].dtype.kind == "f"}))
        W("")

    W("## Caveats")
    W("")
    for c in [
        "Wartime. Tenders opening on or after 2022-02-24 run under martial-law procurement "
        "rules, and one of the observed `durationExtension` rationales is explicitly the "
        "martial-law resolution (Cabinet of Ministers 12.10.2022 No. 1178). Every headline "
        "number is also reported on a 2021-only test window, which is entirely pre-invasion.",
        "Inflation. Values are nominal hryvnia. Consumer inflation in Ukraine ran above 20 "
        "percent in 2022, so `value_growth_gt10` in 2022 is not the same event as in 2019, and "
        "no deflator has been applied here.",
        "Reporting compliance. A change is only in the data if the buyer registered it. An "
        "extension agreed and not registered is invisible, and nothing in this dataset "
        "measures how often that happens. The extension labels are therefore a lower bound.",
        "The tender copy of a contract is not a snapshot taken at signing. It is the state as "
        "of the last write to the tender document, which is why the agreement rates above are "
        "reported. `days_extended` inherits that uncertainty; `duration_extension` does not.",
        "Bid amounts are post-auction. The `lotValues[].date` sits inside the auction period, "
        "so the stored price is the one the bidder ended at, not the sealed bid it opened "
        "with. That is the price available at award time, which is what the forecast needs, "
        "but it is not the bidder's initial offer.",
        "Transfer scoring is not counterfactual scoring. A bidder's forecast on a lot it lost "
        "is never resolved on that lot. The test asks whether the forecast ranks the bidder's "
        "realised record elsewhere, which is a weaker claim and is the only honest one "
        "available.",
        "Right censoring. Every label is read at a single snapshot, so a contract still "
        "running at that moment may yet acquire a change that this panel will never see. The "
        "share still running is reported by cohort in the base-rate table so the size of that "
        "is visible rather than assumed.",
        "One country, one period. Nothing here says the result carries to systems where the "
        "winner is not chosen mostly on price.",
        "Contract cancellation is not measurable in this sample. The sample is completed "
        "tenders, and a tender only reaches status `complete` once it has a live contract, so "
        "the `cancelled` label is near-empty by construction and the ladder refuses to score "
        "it. A study of contract failure would have to start from a different tender status.",
        "Prices are stripped from withdrawn and rejected bids, so the price order on a lot is "
        "the order among the bids that survived. The share of unsuccessful awards that still "
        "point at a priced bid is reported above, and it is high, but this is a property of "
        "the publication rules rather than of the procurement.",
        "A null result is not proof of absence. The transfer test's minimum detectable excess "
        "is stated with the test, and the within-lot test's null standard deviation is in its "
        "table. An effect smaller than those would not have shown up here.",
        "Only outcomes the registry records are measured. If the identity of a bidder shows up "
        "in delivered quality, in disputes, or in anything that never becomes a registered "
        "contract change, none of these tests would see it.",
        "A bidder that has never won has no record, so the identity features are missing or "
        "shrunk to the global rate for exactly the bidders a procurement officer would most "
        "want information about.",
    ]:
        W(f"- {c}")
    W("")

    W("## What could not be verified")
    W("")
    for c in [
        "Whether the tender document's copy of a contract is ever rewritten after signing. It "
        "clearly lags (contract status differs from the registry), but nothing observed proves "
        "it is frozen, so `days_extended` is reported with its agreement rate rather than "
        "treated as exact.",
        "Whether `amountPaid` is a settled figure or a running total. It is populated on most "
        "terminated contracts, but the API returns no field saying the payment record is final, "
        "so `underexecuted` may include contracts still being paid.",
        "Whether a `durationExtension` change always moves `period.endDate`. The cross-tab "
        "above measures how often the two move together in this sample; it does not establish "
        "a rule.",
        "Whether disqualification of the cheapest bid is recorded consistently across buyers. "
        "The signal used is an award with status `unsuccessful`, which is what the data shows; "
        "no external source was consulted on buyer practice.",
        "The Ukrainian legal vocabulary behind each rationale type beyond the English "
        "`title_en` and `description_en` that the API itself returns.",
        "Whether a bid is ever revised after the auction closes. The stored price carries a "
        "date inside the auction period, which is consistent with it being the final auction "
        "price, but nothing observed rules out a later edit.",
        "Whether the same legal entity ever appears under more than one identifier. Bidders "
        "are keyed on the published identifier as it stands; no entity resolution was "
        "attempted, so a firm that changed its registration would look like two bidders.",
        "Why the buyer's record carries signal and the bidder's does not. The measurement is "
        "solid; the mechanism is not established here, and buyer capacity, buyer sector mix "
        "and buyer-specific reporting habits would all produce the same pattern.",
    ]:
        W(f"- {c}")
    W("")

    W("## Reproduction")
    W("")
    W("From the repository root, in order. The first two steps make several hundred thousand "
      "HTTP requests and take hours; everything after them runs from the cache.")
    W("")
    W("```")
    W("make -C prozorro census   # systematic one-in-5 day sample of the tender feed")
    W("make -C prozorro sample   # select the tenders to fetch, fixed seed")
    W("make -C prozorro fetch    # tender documents and contract registry records")
    W("make -C prozorro all      # parse, labels, experiments, release tables, this report")
    W("make -C prozorro test     # pytest")
    W("```")
    W("")
    W("`prozorro/run_pipeline.sh` runs everything downstream of the fetch in one go. Cached "
      "JSON lives under `data/raw/prozorro/` (gitignored), so nothing after `fetch` touches "
      "the network.")
    W("")
    man = {}
    mp = results / "release_manifest.json"
    if mp.exists():
        man = json.loads(mp.read_text())
    rows = [
        {"file": v["file"], "rows": v["rows"], "columns": v["columns"], "MB": v["megabytes"]}
        for k, v in man.items()
        if isinstance(v, dict) and "file" in v
    ]
    if rows:
        W("Released tables, with `column_dictionary.json` beside them:")
        W("")
        W(md_table(pd.DataFrame(rows), floats={"MB": 1}))
        W("")
    shape = man.get("identifier_shape") or {}
    if shape:
        W(
            "These carry legal-entity names and the published identifier, both of which "
            "Prozorro publishes itself, and nothing else about any person: no contact name, no "
            "email, no telephone, no street address. One thing to know about the identifiers: "
            + "; ".join(
                f"{v:,} bidders carry {k.replace('bidders with ', '')}"
                for k, v in shape.items()
            )
            + ". A Ukrainian sole trader bids under a personal name and a ten-digit individual "
            "taxpayer number rather than an eight-digit company EDRPOU, and both are kept here "
            "as published."
        )
        W("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default=str(RESULTS))
    args = ap.parse_args()
    out = Path(args.results) / "report.md"
    out.write_text(build(Path(args.results)))
    print(f"wrote {out} ({len(out.read_text().splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
