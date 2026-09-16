"""Assemble results/report.md and the PNG charts from the computed artefacts.

Run:  .venv/bin/python -m worldbank.src.report
Every table in the report is read from a CSV or JSON written by another module
in this directory. Nothing here computes a headline number for the first time
except the descriptive summaries explicitly built below.
"""
from __future__ import annotations

import json

import pandas as pd

from . import charts, govtech, guards, icr_selfrating, scales
from . import model as model_mod
from .paths import IEG_CSV, PROJECTS, RESULTS, WDS


def md_table(df: pd.DataFrame, floatfmt: str = "{:.4f}") -> str:
    d = df.copy()
    # A crosstab carries its row labels in the index; without this they would be
    # silently dropped and the table would be unreadable.
    if d.index.name is not None or not isinstance(d.index, pd.RangeIndex):
        d = d.reset_index()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(lambda v: "" if pd.isna(v) else floatfmt.format(v))
        else:
            d[c] = d[c].astype(str).replace("nan", "")
    head = "| " + " | ".join(str(c) for c in d.columns) + " |"
    rule = "| " + " | ".join("---" for _ in d.columns) + " |"
    body = "\n".join("| " + " | ".join(r) + " |" for r in d.astype(str).values)
    return "\n".join([head, rule, body])


def ieg_column_report() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(IEG_CSV, encoding="utf-8-sig", dtype=str)
    cols = pd.DataFrame({
        "n": range(1, len(raw.columns) + 1),
        "column": list(raw.columns),
        "distinct values": [raw[c].nunique() for c in raw.columns],
        "null": [int(raw[c].isna().sum()) for c in raw.columns],
    })
    scale_rows = []
    for c in ["Outcome", "Quality at Entry", "Quality of Supervision",
              "Bank Performance", "M&E Quality"]:
        vc = raw[c].value_counts()
        for v, n in vc.items():
            scale_rows.append({"column": c, "value": v, "n": int(n),
                               "six point": scales.to_six_point(v),
                               "four point": scales.to_four_point(v)})
    return cols, pd.DataFrame(scale_rows)


def build_disagreement() -> dict:
    """Bank ICR self-rating versus IEG rating, two independent ways."""
    pj = pd.read_parquet(PROJECTS / "projects.parquet")
    pj["projectid"] = pj["id"].astype(str).str.strip().str.upper()
    pj = icr_selfrating.repair_frame(pj)
    join = pd.read_parquet(RESULTS / "pad_ieg_join.parquet")

    ieg = pd.read_csv(IEG_CSV, encoding="utf-8-sig", dtype=str).rename(
        columns={"Project ID": "projectid", "Outcome": "ieg_outcome",
                 "Approval FY": "approval_fy"})
    ieg["projectid"] = ieg["projectid"].str.strip().str.upper()
    ieg["ieg_six"] = ieg["ieg_outcome"].map(scales.to_six_point)
    ieg["approval_fy"] = pd.to_numeric(ieg["approval_fy"], errors="coerce")

    gt = govtech.load()
    # The workbook writes ratings as HS / S / MS / MU / U / HU. Abbreviation
    # expansion is off by default in `scales` because those letters collide with
    # other World Bank code sets; `govtech.six_point` is the opt-in wrapper that
    # asserts these columns really are rating columns. Calling
    # `scales.to_six_point` here instead returns None for every abbreviated row
    # and silently empties Route 1, which is exactly what it did until
    # 2026-09-15. The guard below is what makes that failure loud: the workbook
    # columns also carry the sentinels "-", "?", "#" and 0, so the threshold is
    # a majority of non-null values surviving, not all of them.
    gt["gt_icr_six"] = guards.require_mapped(
        gt["gt_icr_outcome"], gt["gt_icr_outcome"].map(govtech.six_point),
        "govtech ICR outcome -> six point", min_share=0.5,
        hint="govtech.six_point sets allow_abbrev=True; scales.to_six_point "
             "does not and returns None for every HS/S/MS/MU/U/HU value.")
    gt["gt_ieg_six"] = guards.require_mapped(
        gt["gt_ieg_outcome"], gt["gt_ieg_outcome"].map(govtech.six_point),
        "govtech IEG outcome -> six point", min_share=0.5)

    # -- (i) verified subset: the GovTech workbook alone, no repair needed
    a = gt.merge(ieg[["projectid", "ieg_six", "approval_fy"]], on="projectid",
                 how="inner").dropna(subset=["gt_icr_six", "ieg_six"])
    guards.require_rows(a, "GovTech x IEG overlap (disagreement route 1)",
                        minimum=100)
    tbl_gt = guards.require_rows(
        icr_selfrating.disagreement_table(a, "gt_icr_six", "ieg_six",
                                          "approval_fy"),
        "disagreement table, route 1 (GovTech)", minimum=5)

    # -- (ii) API-wide, using the documented repair
    b = pj[["projectid", "icr_outratingind_six_point"]].merge(
        ieg[["projectid", "ieg_six", "approval_fy"]], on="projectid",
        how="inner").dropna(subset=["icr_outratingind_six_point", "ieg_six"])
    tbl_api = guards.require_rows(
        icr_selfrating.disagreement_table(
            b, "icr_outratingind_six_point", "ieg_six", "approval_fy"),
        "disagreement table, route 2 (Projects API, repaired)", minimum=5)

    # -- validation crosstabs that justify the repair, recomputed here so the
    #    narrative can never drift from the data
    def _validate(api_col: str, gt_col: str):
        v = gt.merge(pj[["projectid", api_col]], on="projectid", how="inner")
        v = v[v[api_col].notna()]
        ct = pd.crosstab(v[api_col], v[gt_col])
        keep = [c for c in ["HS", "S", "MS", "MU", "U", "HU"] if c in ct.columns]
        ct = ct[keep]
        sub = ct.loc["Substantial"] if "Substantial" in ct.index else None
        stats = {
            "substantial_rows_rated": int(sub.sum()) if sub is not None else 0,
            "substantial_is_S": int(sub.get("S", 0)) if sub is not None else 0,
            "n_satisfactory_emitted": int(ct.loc["Satisfactory"].sum())
            if "Satisfactory" in ct.index else 0,
        }
        stats["substantial_is_S_share"] = (
            stats["substantial_is_S"] / stats["substantial_rows_rated"]
            if stats["substantial_rows_rated"] else float("nan"))
        diag = {}
        for lbl, abbr in [("Highly Satisfactory", "HS"),
                          ("Moderately Satisfactory", "MS"),
                          ("Moderately Unsatisfactory", "MU"),
                          ("Unsatisfactory", "U"),
                          ("Highly Unsatisfactory", "HU")]:
            if lbl in ct.index and abbr in ct.columns:
                diag[abbr] = (int(ct.loc[lbl, abbr]), int(ct.loc[lbl].sum()))
        stats["diagonal"] = diag
        return ct, stats

    ct, ct_stats = _validate("icr_outratingind", "gt_icr_outcome")
    ct_borr, ct_borr_stats = _validate("icr_borroverall", "gt_icr_borrower_perf")

    # -- the same comparison restricted to the joined backtest sample
    c = join[["projectid", "approval_year", "outcome_six_point"]].merge(
        pj[["projectid", "icr_outratingind_six_point"]], on="projectid",
        how="left").dropna(subset=["icr_outratingind_six_point",
                                   "outcome_six_point"])
    tbl_join = icr_selfrating.disagreement_table(
        c, "icr_outratingind_six_point", "outcome_six_point", "approval_year")

    for name, t in (("govtech", tbl_gt), ("api_repaired", tbl_api),
                    ("join_sample", tbl_join)):
        t.to_csv(RESULTS / f"disagreement_{name}.csv", index=False)
    ct.to_csv(RESULTS / "icr_repair_validation_crosstab.csv")
    ct_borr.to_csv(RESULTS / "icr_repair_validation_crosstab_borrower.csv")

    def overall(d, bank, iegc):
        d = d.dropna(subset=[bank, iegc])
        guards.require_rows(d, f"overall disagreement on {bank} vs {iegc}",
                            minimum=1)
        return {"n": int(len(d)),
                "agree": float((d[bank] == d[iegc]).mean()),
                "bank_higher": float((d[bank] > d[iegc]).mean()),
                "bank_lower": float((d[bank] < d[iegc]).mean()),
                "mean_gap": float((d[bank] - d[iegc]).mean())}

    return {
        "tbl_gt": tbl_gt, "tbl_api": tbl_api, "tbl_join": tbl_join,
        "crosstab": ct, "crosstab_stats": ct_stats,
        "crosstab_borrower": ct_borr, "crosstab_borrower_stats": ct_borr_stats,
        "overall_gt": overall(a, "gt_icr_six", "ieg_six"),
        "overall_api": overall(b, "icr_outratingind_six_point", "ieg_six"),
        "overall_join": overall(c, "icr_outratingind_six_point",
                                "outcome_six_point"),
        "gt_vs_fo_ieg_agreement": guards.require_finite(
            (gt.merge(ieg[["projectid", "ieg_six"]], on="projectid")
             .dropna(subset=["gt_ieg_six", "ieg_six"])
             .pipe(lambda d: (d["gt_ieg_six"] == d["ieg_six"]).mean())),
            "GovTech IEG Out vs Finances One Outcome agreement",
            hint="this is the cross-source check that validates the workbook; "
                 "NaN means the two sources shared no rated rows."),
    }


def main() -> int:
    df = pd.read_parquet(RESULTS / "pad_ieg_join.parquet")
    funnel = pd.read_csv(RESULTS / "funnel.csv")
    rej = pd.read_csv(RESULTS / "pad_rejections.csv")
    model = pd.read_csv(RESULTS / "model_table.csv")
    cal = pd.read_csv(RESULTS / "calibration.csv")
    meta = json.loads((RESULTS / "model_meta.json").read_text())
    manifest = pd.read_csv(RESULTS / "pad_text_manifest.csv")
    src = pd.read_csv(RESULTS / "source_files.csv")
    wcauc = pd.read_csv(RESULTS / "within_country_auc.csv")
    tuning = pd.read_csv(RESULTS / "tuning.csv")
    # Whether any tuned C landed on the edge of the grid is a property of the
    # run, not a fact to hardcode: it was true before the corpus was cleaned and
    # false after, and a sentence asserting either would drift.
    _grid = sorted(tuning["C"].unique())
    _edge = [k for k, v in meta["best_C"].items()
             if float(v) in (_grid[0], _grid[-1])]
    # Whether any rung beats the zero-information benchmark is a RESULT, not a
    # sentence to hardcode. It was false before the corpus was cleaned and true
    # after, and an asserted version of it was wrong in this report for exactly
    # one run. Computed from the table so it cannot be wrong again.
    _beat = model[model["bss_vs_test_base_rate"] > 0]
    if _beat.empty:
        brier_headline = (
            "No rung of the ladder beats a constant forecast at the realised "
            "test base rate on Brier score.** Every `bss_vs_test_base_rate` in "
            "the model table below is negative. As a probability forecast, "
            "this does not work.")
    else:
        _b = _beat.sort_values("bss_vs_test_base_rate", ascending=False).iloc[0]
        _n = len(_beat)
        brier_headline = (
            f"{_n} of the {len(model)} rungs "
            f"{'beats' if _n == 1 else 'beat'} a constant forecast "
            f"at the realised test base rate on Brier score.** The best is "
            f"`{_b['model']}`, at a Brier skill score of "
            f"{_b['bss_vs_test_base_rate']:+.4f} against that benchmark "
            f"(Brier {_b['brier']:.4f} against {model['brier'].iloc[0]:.4f} for "
            f"a constant at the training base rate) and "
            f"{_b['bss_vs_cell']:+.4f} against the reference-class baseline. "
            f"That benchmark is the strict one: no forecaster could have known "
            f"the realised test base rate in advance, so beating it is a real "
            f"if small result rather than an artefact of the base rate drifting "
            f"upward from {meta['train_base_rate']:.3f} to "
            f"{meta['test_base_rate']:.3f}. Every other rung is negative "
            f"against it.")
    brier_column_note = (
        "**Every rung is negative on this column.**" if _beat.empty else
        "**"
        + ", ".join(f"`{m}`" for m in _beat["model"])
        + (" is" if len(_beat) == 1 else " are")
        + " positive on this column; every other rung is negative.**")
    c_boundary_note = (
        "Every chosen C is interior to the search grid "
        f"({_grid[0]:g} to {_grid[-1]:g}), so none is a boundary selection."
        if not _edge else
        "The chosen C sits at the edge of the search grid for "
        + ", ".join(f"`{k}`" for k in _edge)
        + ", so for those rungs the value is a boundary selection rather than "
          "an interior optimum.")

    # Second pass (src/analysis.py). Loaded, never recomputed here.
    abl = pd.read_csv(RESULTS / "country_ablation.csv")
    coefs = pd.read_csv(RESULTS / "text_coefficients.csv")
    by_test_year = pd.read_csv(RESULTS / "skill_by_test_year.csv")
    refit = pd.read_csv(RESULTS / "placebo_refit.csv")
    cut2 = pd.read_csv(RESULTS / "second_label_cut.csv")
    coverage = pd.read_csv(RESULTS / "censoring_by_year.csv")
    restricted = pd.read_csv(RESULTS / "censoring_restricted.csv")
    ameta = json.loads((RESULTS / "analysis_meta.json").read_text())
    repair_doc = pd.read_csv(RESULTS / "repair_document_summary.csv")
    vintage_tbl = pd.read_csv(RESULTS / "feature_vintage.csv")[
        ["field", "countries_varying", "countries_tested",
         "mean_approval_fy_accuracy", "mean_closing_fy_accuracy",
         "closing_better_in", "approval_better_in", "verdict"]]
    vintage_sens = pd.read_csv(RESULTS / "vintage_sensitivity.csv")
    tq_fold = pd.read_csv(RESULTS / "text_quality_by_fold.csv")
    tq_year = pd.read_csv(RESULTS / "text_quality_by_year.csv")

    # Facts the prose states, computed here so they cannot drift. Each of these
    # was a hardcoded literal until the audit; one of them (the icr_ratings
    # block-length "law") was a mechanism claim the data contradicts.
    _pj = pd.read_parquet(PROJECTS / "projects.parquet")
    _raw = pd.to_numeric(_pj["icr__n_blocks_raw"], errors="coerce")
    _dis = pd.to_numeric(_pj["icr__n_blocks_distinct"], errors="coerce")
    _b = pd.DataFrame({"raw": _raw, "distinct": _dis}).dropna()
    _b = _b[_b["raw"] > 0]
    block_facts = {
        "n": int(len(_b)),
        "no_repeat_share": float((_b["raw"] == _b["distinct"]).mean()),
        "max_raw": int(_b["raw"].max()),
        "max_distinct_where_max_raw": int(
            _b.loc[_b["raw"].idxmax(), "distinct"]),
    }
    # share of not-selected PAD rows that share the kept document's docdt
    _rejrows = pd.read_csv(RESULTS / "pad_rejected_rows.csv")
    _ns = _rejrows[_rejrows["reject_reason"].isin(
        ["same_date_duplicate_or_translation",
         "later_version_within_grace_window"])]
    same_day_share = (
        float((_ns["reject_reason"] == "same_date_duplicate_or_translation"
               ).mean()) if len(_ns) else float("nan"))
    # FCS vintage numbers, from the table rather than retyped
    _f = vintage_tbl[vintage_tbl["field"].eq("Country / Economy FCS Status")
                     ].iloc[0]
    fcs = {
        "varying": int(_f["countries_varying"]),
        "total": 187,
        "tested": int(_f["countries_tested"]),
        "appr": float(_f["mean_approval_fy_accuracy"]),
        "close": float(_f["mean_closing_fy_accuracy"]),
        "closer_better": int(_f["closing_better_in"]),
        "appr_better": int(_f["approval_better_in"]),
    }
    # PAD coverage among RATED projects, by approval FY
    _ieg_all = pd.read_csv(IEG_CSV, encoding="utf-8-sig", dtype=str)
    _ieg_all["fy"] = pd.to_numeric(_ieg_all["Approval FY"], errors="coerce")
    _ieg_all["haspad"] = _ieg_all["Project ID"].str.strip().str.upper().isin(
        set(df["projectid"]))
    _cov = _ieg_all.groupby(_ieg_all["fy"].astype("Int64"))["haspad"].mean()
    _mid = _cov.loc[2002:2019]
    coverage_facts = {
        "mid_lo": float(_mid.min()), "mid_hi": float(_mid.max()),
        "first_year_with_any": int(_cov[_cov > 0].index.min()),
    }
    null_draws = pd.read_csv(RESULTS / "placebo_null.csv")["within_country_auc"]
    guards.require_rows(by_test_year, "skill by test year", minimum=5,
                        hint="fewer rows than there are test approval years "
                             "means this file was written by something other "
                             "than a full analysis run.")

    cols, scale = ieg_column_report()
    dis = build_disagreement()

    p1 = charts.n_by_year(df)
    p2 = charts.outcome_rate_by_year(df)
    p3 = charts.calibration(cal)
    p4 = charts.disagreement(dis["tbl_gt"])
    p5 = charts.country_ablation(abl)
    p6 = charts.placebo_null(null_draws.values,
                             ameta["placebo_permute"]["observed_within_country_auc"],
                             ameta["placebo_permute"]["p_value_one_sided"])
    p7 = charts.evaluation_coverage(coverage,
                                    ameta["censoring"]["min_evaluated_share"])
    p8 = charts.skill_by_year(by_test_year)
    p9 = charts.text_quality(tq_year, meta["cuts"])

    labelled = df[df["y_satisfactory"].notna()]
    lab_eval_lag_median = float(
        (labelled["ieg_evaluation_fy"].astype(float)
         - labelled["approval_year"].astype(float)).median())
    by_year = labelled.groupby("approval_year").agg(
        n=("y_satisfactory", "size"),
        share_satisfactory=("y_satisfactory", "mean")).reset_index()
    by_year["approval_year"] = by_year["approval_year"].astype(int)

    wds_counts = pd.DataFrame([
        {"document type": k,
         "rows fetched": len(pd.read_parquet(WDS / f"{k}.parquet")),
         "API total": int(pd.read_parquet(WDS / f"{k}.parquet")["api_total"].iloc[0])}
        for k in ("pad", "icr", "icrr")])
    wds_counts["document type"] = ["Project Appraisal Document",
                                   "Implementation Completion and Results Report",
                                   "Implementation Completion Report Review"]

    slip = df["schedule_slip_days"].dropna()
    _slip_api = df["schedule_slip_days_api_actual"].dropna()
    slip_compare = pd.DataFrame([
        {"definition": "same source (workbook actual - workbook original)",
         "n": int(len(slip)), "median days": float(slip.median()),
         "mean days": float(slip.mean()),
         "share closing late": float((slip > 0).mean())},
        {"definition": "mixed source (API closingdate - workbook original)",
         "n": int(len(_slip_api)), "median days": float(_slip_api.median()),
         "mean days": float(_slip_api.mean()),
         "share closing late": float((_slip_api > 0).mean())},
    ])
    slip_summary = pd.DataFrame([{
        "projects with both a planned and an actual closing date": int(len(slip)),
        "median slip (days)": float(slip.median()),
        "mean slip (days)": float(slip.mean()),
        "share closing late": float((slip > 0).mean()),
        "90th percentile slip (days)": float(slip.quantile(0.9)),
    }])

    text_status = manifest["status"].value_counts().rename("n").reset_index()
    text_status.columns = ["status", "n"]
    man_ok = manifest[manifest["status"].eq("ok")]

    vt = (df["pad_versiontyp"].fillna("(missing)").value_counts()
          .rename("n").reset_index())
    vt.columns = ["PAD version type", "n"]
    vt["share"] = vt["n"] / vt["n"].sum()

    et = labelled.groupby("ieg_evaluation_type").agg(
        n=("y_satisfactory", "size"),
        share_satisfactory=("y_satisfactory", "mean")).reset_index()
    et.columns = ["evaluation type", "n", "share satisfactory"]

    # counts quoted in the leakage-filter narrative, recomputed here so the text
    # can never drift from the data
    pad_raw = pd.read_parquet(WDS / "pad.parquet")
    pid = pad_raw["projectid"].astype("string")
    multi = int(pid.str.contains(r"[;,]", na=False).sum())
    per_project = (pid.dropna().str.split(r"[;,]").explode().str.strip()
                   .str.upper().value_counts())
    dist = per_project.value_counts().sort_index()
    pad_counts = {
        "records": len(pad_raw),
        "distinct_pnumbers": int(per_project.size),
        "multi_project_records": multi,
        "dist": {int(k): int(v) for k, v in dist.items()},
        "null_projectid": int(pid.isna().sum()),
    }
    dist_tbl = pd.DataFrame({"PADs per P-number": dist.index.astype(int),
                             "P-numbers": dist.values})

    out = RESULTS / "report.md"
    T = md_table
    md = f"""# World Bank Project Appraisal Documents to IEG outcome ratings

A leakage-controlled join from the proposal document a project was approved on
to the independent rating that evaluation gave it years later, plus a
forward-chained text baseline that tries to predict the rating from the
proposal.

Built 2026-09-15. Every number below is produced by a script in `worldbank/src`
and reproduced by `make all` from `worldbank/`. Test suite: `make test`.

## What was built

1. A complete pull of World Bank Documents and Reports metadata for three
   document types, a complete pull of the Projects API, and the IEG ratings
   bulk table.
2. A join on the P-number that keeps only the appraisal document that existed
   at or before board approval, so the input cannot contain knowledge of the
   outcome.
3. A release table, `results/pad_ieg_join.csv`, with {len(df):,} projects and
   {len(df.columns)} columns.
4. A model ladder scored forward-chained on board approval year.
5. A second pass that attacks the ladder's one positive result: a country
   ablation, a per-year skill table, an exact within-country permutation null, a
   permuted-label refit of the whole pipeline, a second label cut, and a
   measurement of the evaluation lag that censors the recent cohorts.
6. The Bank-versus-IEG rating disagreement series, which is the quantity a
   public scoreboard would show first.

## The headline, stated plainly

On {meta["n_test"]:,} test projects approved from {meta["cuts"]["valid_end"] + 1}
onward, with models fitted only on projects approved earlier:

- **{brier_headline}
- **The PAD text does carry some ranking information about the outcome.** The
  text-only rung reaches a within-country AUC of
  {ameta["placebo_permute"]["observed_within_country_auc"]:.3f} against an exact
  permutation null of {ameta["placebo_permute"]["null_mean"]:.3f}, one-sided
  p = {ameta["placebo_permute"]["p_value_one_sided"]:.3f}.
- **That p-value does not survive the search that produced it.** Six rungs and a
  nine-point regularisation sweep were examined before this one was reported. A
  Bonferroni threshold across the rungs alone would be 0.008, and the largest of
  {ameta["placebo_refit"]["n_repeats"]} pure-noise pipeline refits reached
  {ameta["placebo_refit"]["max_within_country_auc"]:.3f}, close to the reported
  effect.
- **Most of the naive pooled skill is the country.** A model given nothing but
  the country identity reaches a pooled AUC of
  {abl.loc[abl["model"].eq("country identity only"), "pooled_auc"].iloc[0]:.3f}
  and, necessarily, a within-country AUC of exactly 0.500.

The defensible claim is therefore: **the joined dataset is the contribution, and
the text baseline is a weak positive that has not been replicated.** The PAD text
carries real but small information about the outcome an evaluator will record
years later, on both the Brier and the ranking measure, and the effect is of the
same order as what the search that found it can produce by chance. It is a
reason to run one pre-registered replication on a later period, not a reason to
forecast anything with this model. The rest of this report is the evidence for
each of those four statements.

For a scoreboard, the operative number is not the AUC but the Brier skill score
against the zero-information benchmark, because that is what a published forecast
would be scored on. On this test fold that is
{model["bss_vs_test_base_rate"].max():+.4f}: positive, and small.

## The data

### Source files

{T(src[["name", "bytes", "sha256", "http_status"]], "{:.0f}")}

The IEG dataset page at financesone.worldbank.org is a JavaScript application,
but the bulk download URL is present in the server-rendered HTML, so no browser
was needed. The legacy Socrata host `finances.worldbank.org` now redirects every
`/resource/` and `/api/views/` path to the Finances One application, so the SODA
API described in older references no longer returns data. That was tested, not
assumed.

### Documents and Reports API coverage

{T(wds_counts, "{:.0f}")}

Every document type was paginated to completion against the API's own reported
total. Records carry `projectid`, `docdt`, `txturl`, `pdfurl`, `guid` and `url`.

### Projects API

28,113 of 28,113 projects fetched. The default response carries only 15 fields
and no ratings at all; `fl=*` is required, and returns the nested `icr_ratings`,
`ieg_ratings`, `milestones` and `isr_ratings` blocks.

### IEG ratings dataset, exactly as observed

12,598 rows and 21 columns, "As of Date" 09/13/2026, CC BY 4.0.

{T(cols, "{:.0f}")}

The dataset does **not** carry Risk to Development Outcome, Borrower
Performance, ICR Quality, or the Bank's own ICR self-rating. Those were
obtained elsewhere and are described below.

### The rating scale, exactly as observed

{T(scale[scale["column"] == "Outcome"].reset_index(drop=True), "{:.0f}")}

`Outcome`, `Quality at Entry`, `Quality of Supervision` and `Bank Performance`
all use this six-point ordinal scale plus an explicit `Not Rated` sentinel.
`M&E Quality` uses a different four-point scale (High, Substantial, Modest,
Negligible), which is why the code keeps the two scales strictly separate and
tests that a four-point value never lands on the six-point scale.

**Label definition.** `y_satisfactory = 1` when `Outcome` is one of
Moderately Satisfactory, Satisfactory or Highly Satisfactory; `0` when it is one
of Moderately Unsatisfactory, Unsatisfactory or Highly Unsatisfactory; and
undefined (row dropped) when `Not Rated`. That is the "at least Moderately
Satisfactory" cut, on the observed scale.

## The leakage filter

Additional-financing appraisal documents and restructuring papers are filed
under the same P-number as the original project and are dated after board
approval. A document written years into implementation can describe what has
already happened, so using it as an ex-ante input would leak the outcome.

Rule, in order. Among the PADs of a project, keep the one that
1. has `docdt` on or before the board approval date plus 30 days -- **this is
   the leakage test, and it is the only step that is about leakage**;
2. is in English, if any qualifying version is;
3. is the earliest of what remains;
4. has the lowest document id, purely so the result is deterministic.

Steps 2 to 4 choose among documents that have all already passed step 1. The
grace window exists because the document date and the board date are recorded
independently.

**Why step 2 is there.** WDS carries translations of the appraisal document
under the same P-number, and a translation is frequently dated *earlier* than
the English original, so an earliest-only rule selected it. Measured before this
step was added: 40 projects were represented by a French, Spanish, Arabic,
Russian or Portuguese document, and an English PAD existed and qualified for 39
of them. Those documents then entered an English-stopword TF-IDF model as their
own vocabulary. After the fix the corpus is
{int((df["pad_lang"] == "English").sum()):,} English and
{int((df["pad_lang"] != "English").sum())} other, the remainder being the one
project with no qualifying English version.

**Dates are compared as calendar dates.** WDS renders `docdt` as an instant at
midnight US Eastern (04:00Z or 05:00Z across all {pad_counts["records"]:,}
records), while the board date is a bare date at 00:00. Differencing them without normalising lost a
partial day to truncation, which made `pad_lead_days` one day short on every
single row and shortened the documented 30-day grace window to 29 days and 20
hours. Both sides are now floored to midnight. (No PAD actually falls between 27
and 32 days after approval, so the grace-window half of that bug changed no
row's inclusion; it was wrong regardless.)

Of {pad_counts["records"]:,} PAD records, {pad_counts["null_projectid"]} carry no
`projectid` at all and {pad_counts["multi_project_records"]} carry a
comma-separated multi-project `projectid`, which is exploded to one row per
project. That leaves {pad_counts["distinct_pnumbers"]:,} distinct P-numbers,
distributed like this:

{T(dist_tbl, "{:.0f}")}

Documents excluded, by reason:

{T(rej, "{:.0f}")}

The last two reasons are separated on purpose, because collapsing them
overstates what the filter does. `docdt_after_approval_plus_grace` is the
leakage case: an additional-financing or restructuring paper filed under the
original P-number. `same_date_duplicate_or_translation` and
`later_version_within_grace_window` are documents that PASSED the leakage test
and simply were not the one selected. Of the not-selected rows belonging to a
project that is in the release table, {same_day_share:.1%} carry the same
`docdt` as the document that was kept, so most of what the filter removes is a
same-day duplicate or a translation rather than a post-hoc document.

The single P-number carrying 30 PAD rows in the table above is P173789, and it
is not 30 versions of a project's history: it is one 2020 operation whose
appraisal document was disclosed in English, Spanish and Arabic across several
same-week dates.

### Which version of the appraisal document was kept

{T(vt, "{:.4f}")}

**What is and is not known about these labels.** `versiontyp` is a WDS metadata
field and no World Bank dictionary defining its values was found or read this
session, so what "Buff cover" and "Final" mean editorially is NOT claimed here.
What is established is the only thing the leakage argument needs: every row in
this table has a `docdt` on or before board approval plus 30 days, because that
is the filter that admitted it. A reader who wants to restrict the corpus to one
version type can do so from `pad_versiontyp` in the release table; the counts
are given here for that purpose, not as evidence about editorial status.

## The funnel

{T(funnel, "{:.0f}")}

### Evaluation type in the joined sample

{T(et, "{:.4f}")}

LABELLED INFERENCE: that IEG selects projects for a Project Performance
Assessment Report rather than sampling at random is an inference from the
observed difference in satisfactory rates between the two evaluation types, not
something an IEG methodology document read this session states. What is
established is that the two types have different satisfactory rates in this
sample, which is in the table. They are pooled for the label, and the difference
is reported here so a reader can split them.

This table covers the {int(et["n"].sum()):,} joined projects that carry a usable
outcome label, not all {len(df):,} rows of the release table; the difference is
the {len(df) - int(et["n"].sum())} projects rated "Not Rated".

## Joined sample by approval year

![Projects by approval year](n_by_approval_year.png)

![Outcome rate by approval year](outcome_rate_by_approval_year.png)

{T(by_year, "{:.4f}")}

## PAD text corpus

{T(text_status, "{:.0f}")}

Total bytes downloaded: {int(manifest["text_bytes"].sum()):,}. Every document
has its sha256 and byte size recorded in `results/pad_text_manifest.csv` and in
the release table (`pad_text_sha256`, `pad_text_bytes`, `pad_text_status`).
**The truncation is a real limitation, and bigger than it looks.** The models
read the first 200,000 characters of each document. The mean usable document is
{man_ok["text_bytes"].mean():,.0f} bytes and the median is
{man_ok["text_bytes"].median():,.0f}, so
**{(man_ok["text_bytes"] > 200_000).mean():.1%} of the corpus is truncated** and
the models never see the later pages of four documents in five. Appraisal
documents put the results framework, the risk matrix and the economic analysis
towards the end, so this is not a tail-trimming exercise. The cut was made to
keep the TF-IDF matrix tractable, it was not tuned, and the effect of raising it
was not measured. Any skill reported here is skill from the front of the
document only.
Downloads used four concurrent requests with exponential backoff. Some `txturl`
responses return HTTP 200 with a short sentinel body rather than document text
("The original PDF is Password Protected for Opening. Unable to extract text for
Index."); those are classified `extract_failed` and excluded from the corpus
rather than entering it as an 88-byte document.

## Models

### What goes into each rung

Rungs (c) and (e) use structured fields. They are named here because a claim
that the inputs predate the outcome is empty unless the inputs are listed.

- categorical: {", ".join("`" + c + "`" for c in model_mod.CAT_FEATURES)}
- numeric: {", ".join("`" + c + "`" for c in model_mod.NUM_FEATURES)}
- the country identity is NOT among them; see the country ablation below
- excluded as post-treatment: {", ".join("`" + c + "`" for c in model_mod.EXCLUDED_POST_TREATMENT_FEATURES)}

{T(vintage_tbl)}

**Why `ieg_country_fcs_status` was excluded.** Both source tables are 2026
snapshots, so whether a field carries an approval-time or a closing-time value
is a measurement, not an assumption. `src/feature_vintage.py` makes it: for each
country, it finds the best single threshold on Approval FY and the best single
threshold on Final Closing FY for reproducing the field, and compares them.
Fragile-state status varies within a country in {fcs["varying"]} of
{fcs["total"]} countries, and the closing-year threshold reproduces it better
({fcs["close"]:.3f} against {fcs["appr"]:.3f} on average, better in
{fcs["closer_better"]} of {fcs["tested"]} countries tested and worse in
{fcs["appr_better"]}). Burkina Faso is the clean case: every non-FCS project closes 1995 to 2019
and every FCS project closes 2020 to 2025, while the two groups' approval years
overlap almost entirely. A status carried at closing is post-treatment and
cannot be an ex-ante input. **What is not claimed:** no World Bank dictionary
stating the field's as-of date was found, so the cause is unknown. The field is
excluded because its ex-ante status could not be established, not because a
mechanism was proven. What the exclusion changed is in the sensitivity table
below rather than asserted to be nothing.

Two fields are kept with a caveat. `ieg_country_lending_group` takes one value
per country in this snapshot (it varies within only 4 of 187 countries), so it
is a 2026 country attribute stamped on projects of every vintage; being
country-constant is exactly what the within-country statistic neutralises.
`ieg_practice_group` is the post-2014 Global Practice vocabulary applied to
projects of every vintage: the underlying sector is ex ante, the vocabulary is
not, and the vintage test puts it on the approval side.

### Folds

Splits are by board approval year, never random. Train and validation are fitted
together for the final model and scored once on the test fold.

- train: approval year <= {meta["cuts"]["train_end"]}, n = {meta["cuts"]["n_train"]:,}
- validate: {meta["cuts"]["train_end"] + 1} to {meta["cuts"]["valid_end"]}, n = {meta["cuts"]["n_valid"]:,}
- test: {meta["cuts"]["valid_end"] + 1} onward, n = {meta["cuts"]["n_test"]:,}

The pre-registered cut points (2005 / 2010) gave a test fold above the required
800 rows, so they were not moved. (`moved_from_preregistered` in
`results/model_meta.json` records this, and reads
`{meta["cuts"]["moved_from_preregistered"]}`.)

Train-plus-validation base rate {meta["train_base_rate"]:.4f}; test-fold base
rate {meta["test_base_rate"]:.4f}. Documents with usable text:
{meta["fit_with_text"]:,} of {meta["n_fit"]:,} in train-plus-validation and
{meta["test_with_text"]:,} of {meta["n_test"]:,} in test. Regularisation strength
was chosen on the validation fold only: {meta["best_C"]}.

**The pre-registered cell baseline degenerates, and the report shows both.** The
specified reference class is country by approval decade by practice group. Under
forward chaining the test fold's decade is, by construction, nearly absent from
the training fold, so most test rows fall back to the global mean and the
"baseline" stops being a reference class at all. Measured here:
{meta["cell_with_decade_fallback_share"]:.1%} of test rows fall back with the
decade term, against {meta["cell_no_decade_fallback_share"]:.1%} without it.
Model (b) is the pre-registered cell and model (b2) drops the decade term. The
BSS-versus-cell column is computed against (b2), the one that actually behaves
like a reference class.

{T(model)}

Reading the columns:

- `bss_vs_train_base_rate` is the Brier skill score against a constant at the
  **training** base rate, which is the only constant a forecaster could actually
  have registered before the test period began.
- `bss_vs_test_base_rate` is against a constant at the **realised test** base
  rate. No forecaster could know that number, but it is the correct
  zero-information benchmark, and it is the decisive column here: a model that
  beats the training constant only because the base rate drifted upward from
  {meta["train_base_rate"]:.3f} to {meta["test_base_rate"]:.3f} scores positive
  on the first column and negative on this one. {brier_column_note}
- `bss_vs_cell` is against the shrunk cell baseline, model (b2).
- `within_country_auc_pairwt` is the mean of per-country AUC weighted by
  **comparable pairs** (positives times negatives in the country), which is the
  weighting under which the pooled and within-country quantities are
  commensurable. `within_country_auc_nwt` is the same mean weighted by country
  row count instead; both are shown because they can differ when class balance
  varies across countries. The pair-weighted column is the one quoted in the
  text.
- Both within-country columns count only countries with at least 10 test
  projects and at least 2 of each class, and
  `within_country_rows_excluded` is the share of test rows that exclusion
  discards. That is a selection on realised labels, so it is reported on every
  row rather than buried.

### Calibration

![Calibration](calibration.png)

{T(cal[["model", "bin", "n", "mean_forecast", "observed_rate", "gap"]], "{:.4f}")}

### Within-country AUC, largest countries in the test fold

{T(wcauc.head(20), "{:.4f}")}

## Does the result survive

The ladder has exactly one positive finding: PAD text alone reaches a
within-country AUC above 0.5 on the test fold. Everything in this section exists
to attack that number. Five checks, all forward-chained on the same folds, all
reusing the regularisation strength chosen on the validation fold rather than
tuning again.

### What the country identity is worth

![Country ablation](country_ablation.png)

{T(abl[["model", "n_features", "pooled_auc", "within_country_auc", "brier"]])}

Read the first row first. A model given nothing but the country identity is
**constant inside a country**, so its within-country AUC comes out at exactly
{abl.loc[abl["model"].eq("country identity only"), "within_country_auc"].iloc[0]:.4f}
while its pooled AUC is
{abl.loc[abl["model"].eq("country identity only"), "pooled_auc"].iloc[0]:.4f}.
That is the arithmetic check on the statistic: pooled AUC on this data rewards
knowing which country a project is in, and the within-country column refuses to.
A pooled AUC of about 0.57 is available for free, from the country name alone,
which is most of what the reference-class baseline in the ladder achieves.

The country identity is deliberately absent from the ladder's structured
features, so no ladder rung is handed that 0.57 directly. The rows here that are
given it are diagnostics, not rungs.

### What the post-treatment exclusion changed

`ieg_country_fcs_status` was dropped from the feature set on the vintage
measurement above. Dropping a field on that kind of argument is a judgement, so
here is the number it moved, rather than an assurance that it moved nothing:

{T(vintage_sens[["feature set", "rung", "pooled_auc", "within_country_auc", "brier"]])}

Note which rungs this can touch at all. Rungs (a), (b), (b2) and (d) use no
structured fields, and (d) PAD text only is the rung the headline rests on, so
the headline is unaffected by this choice either way.

### Skill by test approval year

![Skill by test year](skill_by_test_year.png)

{T(by_test_year)}

The skill is not concentrated in a single year, and it is not present in every
year either: several years sit below 0.5. With roughly 100 to 200 projects and
20 to 40 unsatisfactory outcomes in a year, no single year can resolve an effect
of this size, so the scatter is the expected picture rather than a defect.

### The within-country permutation null

![Permutation null](placebo_null.png)

The cluster bootstrap in the model section resamples countries. This does the
complementary thing: it holds the forecasts fixed and permutes the realised
labels **within each country**, {ameta["placebo_permute"]["n_permutations"]:,}
times. Permuting inside a country leaves every country's class counts unchanged,
so the set of countries eligible for a within-country AUC is identical in every
draw, and the null is exact rather than approximate.

| quantity | value |
| --- | --- |
| observed within-country AUC (PAD text only) | {ameta["placebo_permute"]["observed_within_country_auc"]:.4f} |
| permutation null mean | {ameta["placebo_permute"]["null_mean"]:.4f} |
| permutation null standard deviation | {ameta["placebo_permute"]["null_sd"]:.4f} |
| permutation null 95th percentile | {ameta["placebo_permute"]["null_p95"]:.4f} |
| one-sided p-value | {ameta["placebo_permute"]["p_value_one_sided"]:.4f} |

The null lands on {ameta["placebo_permute"]["null_mean"]:.4f}, which is what a
correct within-country statistic must do when the labels carry no information.
The observed value clears the 95th percentile, at a one-sided p-value of
{ameta["placebo_permute"]["p_value_one_sided"]:.3f}.

**What that p-value is not.** It is one test on the rung that happened to score
highest, selected after looking at six rungs and a nine-point regularisation
sweep. No multiplicity correction is applied, and none would rescue a p of
{ameta["placebo_permute"]["p_value_one_sided"]:.3f} if one were: a Bonferroni
correction across the six rungs alone puts the threshold at 0.008. The honest
summary is that the text signal is **not distinguishable from noise at a
standard applied to the whole search**, and that it deserves one pre-registered
replication on a later period rather than a claim.

### The pipeline placebo

The permutation above holds the model fixed. This one breaks the model: it
permutes the labels of the training fold, refits the text model on the noise,
and scores the result against the real test labels,
{ameta["placebo_refit"]["n_repeats"]} times. A pipeline that leaked outcome
information through any route other than the labels would still score above 0.5
here.

| quantity | value |
| --- | --- |
| repeats | {ameta["placebo_refit"]["n_repeats"]} |
| mean within-country AUC on permuted training labels | {ameta["placebo_refit"]["mean_within_country_auc"]:.4f} |
| minimum across repeats | {refit["within_country_auc"].min():.4f} |
| maximum across repeats | {ameta["placebo_refit"]["max_within_country_auc"]:.4f} |
| standard deviation across repeats | {refit["within_country_auc"].std(ddof=1):.4f} |
| mean pooled AUC | {ameta["placebo_refit"]["mean_pooled_auc"]:.4f} |

The mean is {ameta["placebo_refit"]["mean_within_country_auc"]:.4f}, so the
pipeline does not manufacture skill from noise, which is the leakage test this
placebo is for. The spread matters as much as the mean: the largest of
{ameta["placebo_refit"]["n_repeats"]} pure-noise refits reached
{ameta["placebo_refit"]["max_within_country_auc"]:.4f}. An effect of the size
reported here is close to what the noisiest draw from a null pipeline produces,
which is the same conclusion the p-value reaches by a different route.

### The second label cut

The pre-registered label is outcome at least Moderately Satisfactory. The other
natural cut on the same six-point scale is outcome at least Satisfactory, which
is much closer to balanced: the fit-fold rate falls from
{meta["train_base_rate"]:.4f} to {ameta["second_cut"]["fit_base_rate"]:.4f}, and
the test-fold rate from {meta["test_base_rate"]:.4f} to
{ameta["second_cut"]["test_base_rate"]:.4f}.

{T(cut2[["model", "pooled_auc", "within_country_auc", "brier"]])}

Discrimination survives the move: the text model keeps a within-country AUC of
{cut2.loc[cut2["model"].str.contains("text only"), "within_country_auc"].iloc[0]:.4f}
at the tighter cut. Calibration does not. The Brier scores of the fitted models
are **worse than the constant** here, because the regularisation strength was
deliberately not re-tuned for this label and the forecasts are therefore centred
on the wrong base rate. That is the intended trade: re-tuning would have turned
a robustness check into a second search. Ranking information transfers across
the cut; probabilities do not.

### Evaluation lag and right-censoring

![Evaluation coverage](evaluation_coverage.png)

A project cannot carry an IEG rating until it closes and is evaluated. On this
sample the median lag from board approval to evaluation fiscal year is
{lab_eval_lag_median:.0f} years. The recent approval cohorts in the test fold
are therefore not samples of the projects approved in those years; they are the
subset that finished fast enough to have been evaluated by the September 2026
snapshot.

The size of that distortion, measured against every project with a qualifying
PAD and a board approval date, rated or not:

{T(coverage.tail(16))}

Coverage holds above 75 percent through 2016 and then falls away: it is
{coverage.loc[coverage["approval_year"].eq(2019), "evaluated_share"].iloc[0]:.1%}
for 2019 and
{coverage.loc[coverage["approval_year"].eq(2021), "evaluated_share"].iloc[0]:.1%}
for 2021. The median implementation length of the rated projects falls with it,
from about seven years to
{coverage.loc[coverage["approval_year"].eq(2021), "median_implementation_years"].iloc[0]:.1f}
years. That is the selection made visible: in the recent cohorts, only the fast
projects are in the table yet.

Re-scoring the test fold with the low-coverage years dropped, keeping approval
years {ameta["censoring"]["years_kept"]} (those at or above
{ameta["censoring"]["min_evaluated_share"]:.0%} coverage), which removes
{ameta["censoring"]["n_test_full"] - ameta["censoring"]["n_test_restricted"]}
of {ameta["censoring"]["n_test_full"]} test rows:

{T(restricted[["model", "n_full", "n_restricted", "pooled_auc_full", "pooled_auc_restricted", "within_country_auc_full", "within_country_auc_restricted"]])}

The headline does not depend on the censored years. This is a robustness check
and not a correction: dropping the incomplete cohorts does nothing about the
selection inside the cohorts that remain, and the 2011 to 2018 cohorts are
themselves not fully evaluated either.

### OCR noise, and where it lands

![Text quality](text_quality.png)

An earlier version of this report carried the caveat "older documents are
scanned and OCR'd; the text layer is noisier before roughly 2005, which is
exactly the training fold". Nothing measured it. `src/text_quality.py` now does,
with two noise proxies: the rate of characteristic OCR corruptions of common
short words ("Ia" for "la", "ofthe", "tbe", "arid") per 1,000 tokens, and the
share of alphabetic tokens that are a single character other than "a" or "i".
Neither proves a document was scanned, and no World Bank source states which
were; they are noise proxies and are reported as such.

**The caveat was wrong in both halves.**

{T(tq_fold[["fold", "n", "broken_of_per_1k", "mean_broken_of_per_1k", "single_char_token_rate"]])}

The noisy block is approval years 2004 to 2009, not "before 2005": documents
from 1996 to 2003 are the cleanest in the corpus, and everything from 2010
onward is clean again. And the fold carrying that noise is not the training fold
but the **validation** fold, where the single-character token rate is
{float(tq_fold.set_index("fold").loc["validate", "single_char_token_rate"]):.4f}
against {float(tq_fold.set_index("fold").loc["train", "single_char_token_rate"]):.4f}
in train and {float(tq_fold.set_index("fold").loc["test", "single_char_token_rate"]):.4f}
in test, roughly a fourfold difference.

That matters, because the validation fold is the only thing that chooses the
regularisation strength. The penalty for a TF-IDF model is being selected on the
noisiest text in the corpus and then applied to the cleanest. Nothing here
corrects for it and the direction of the resulting bias is not established; it
is stated because a reader scoring this work should know the tuning fold is not
representative of the test fold.

{T(tq_year[tq_year["n"] >= 5][["approval_year", "n", "broken_of_per_1k", "single_char_token_rate"]])}

### What the text model leans on

The forty highest and forty lowest weighted TF-IDF terms are in
`results/text_coefficients.csv`. The first fifteen in each direction:

{T(pd.concat([coefs[coefs["direction"].eq("toward satisfactory")].head(15), coefs[coefs["direction"].eq("toward unsatisfactory")].head(15)])[["direction", "rank", "term", "coefficient"]], floatfmt="{{:.3f}}")}

These are descriptive. They are the weights one regularised linear model placed
on one training fold, not causes, and they are not claimed to be stable under a
different seed or a different fold.

One thing in them is load-bearing rather than decorative: **country and place
names appear among the highest-weight terms in both directions**. A PAD names
the country it is about, so a bag-of-words model over PAD text is not
country-blind, and part of the pooled AUC of the "text only" rung is the country
effect arriving through the vocabulary rather than through a feature column.
That is exactly why the within-country AUC, and not the pooled AUC, is the
number this report leads with.

## Bank self-rating versus IEG rating

The Bank's operational team rates its own project in the Implementation
Completion and Results Report; IEG then reviews it and issues an independent
rating. The gap between the two is a published, mechanical quantity, and it is
the first thing a procurement-style scoreboard would show.

Neither the IEG bulk CSV nor the Projects API gives this cleanly, so two
independent routes were used and are reported side by side.

**Route 1, verified, no repair needed.** The World Bank Digital Governance and
GovTech Projects workbook (Data Catalog dataset 0038056, resource DR0095723)
publishes `ICR Out` and `IEG Out` side by side for a subset of projects. Its
`IEG Out` column agrees with the Finances One IEG `Outcome` column on
{dis["gt_vs_fo_ieg_agreement"]:.2%} of overlapping rated rows, which is what
validates the workbook as a source.

Overall on that subset: n = {dis["overall_gt"]["n"]:,}, exact agreement
{dis["overall_gt"]["agree"]:.2%}, Bank rates itself **higher** than IEG
{dis["overall_gt"]["bank_higher"]:.2%} of the time and lower
{dis["overall_gt"]["bank_lower"]:.2%}, mean gap
{dis["overall_gt"]["mean_gap"]:+.3f} scale points.

![Bank versus IEG](bank_vs_ieg_disagreement.png)

{T(dis["tbl_gt"], "{:.4f}")}

**Route 2, API-wide, with a documented repair.** The Projects API `icr_ratings`
block carries the same self-rating for many more projects, but two defects had
to be handled first, both established by measurement:

1. The block can contain repeated elements, so the fetcher deduplicates before
   reading any value. **What is observed**, across the
   {block_facts["n"]:,} projects that carry the block:
   {block_facts["no_repeat_share"]:.1%} have no repetition at all (the raw
   element count equals the distinct count), and the rest repeat, up to a
   maximum of {block_facts["max_raw"]} raw elements carrying
   {block_facts["max_distinct_where_max_raw"]} distinct value(s). **What is NOT
   claimed:** an earlier version of this report asserted the length follows
   k*(k+1). That is false and the repo's own data refutes it -- observed counts
   include 1, 3, 4, 9, 25, 121 and 144, which are not of that form. No rule
   governing the block length is claimed here, because none was established.
   Deduplication does not depend on one.
2. The value "Satisfactory" never appears in the block. In its place the API
   emits "Substantial", a value from the four-point risk scale. The crosstab
   below is the evidence: rows where the API says "Substantial" are "S" in the
   independently published workbook, and the diagonal is otherwise clean.

{T(dis["crosstab"], "{:.0f}")}

Rows where the API says "Substantial" carry workbook value "S" in
{dis["crosstab_stats"]["substantial_is_S"]} of
{dis["crosstab_stats"]["substantial_rows_rated"]} rated cases
({dis["crosstab_stats"]["substantial_is_S_share"]:.1%}), and the API emits
"Satisfactory" in {dis["crosstab_stats"]["n_satisfactory_emitted"]} rows in the
whole overlap. The rest of the diagonal, as
(matched / row total): {", ".join(f"{k} {v[0]}/{v[1]}" for k, v in dis["crosstab_stats"]["diagonal"].items())}.

The same defect appears independently on `icr_borroverall`, the Bank's
self-rating of borrower performance, against the workbook's `ICR BoP`:

{T(dis["crosstab_borrower"], "{:.0f}")}

There, "Substantial" carries workbook "S" in
{dis["crosstab_borrower_stats"]["substantial_is_S"]} of
{dis["crosstab_borrower_stats"]["substantial_rows_rated"]} rated cases
({dis["crosstab_borrower_stats"]["substantial_is_S_share"]:.1%}). Two fields,
two independent confirmations. The repair maps "Substantial" to "Satisfactory"
inside the `icr_ratings` block only, never on the IEG side and never on a
genuine four-point field such as M&E quality or risk to development outcome.

**Route 3, the primary documents.** The two routes above are both datasets, so
agreeing with each other only shows they share a convention. `make verify`
(`src/verify_repair.py`) goes to the source of record instead: it downloads IEG
Implementation Completion Report Review documents, parses the standard Ratings
table that carries an `ICR` column and an `IEG` column, and compares the
document's own words to what the API returns for the same P-number.

| quantity | value |
| --- | --- |
| ICRR documents parsed | {int(repair_doc["documents parsed"].iloc[0])} |
| raw API value matches the document verbatim | {float(repair_doc["API value matches document verbatim"].iloc[0]):.1%} |
| REPAIRED value matches the document | {float(repair_doc["REPAIRED value matches document"].iloc[0]):.1%} |
| rows where the API says "Substantial" | {int(repair_doc["rows where API says Substantial"].iloc[0])} |
| of those, the document says "Satisfactory" | {int(repair_doc["of those, document says Satisfactory"].iloc[0])} |

Every one of the {int(repair_doc["rows where API says Substantial"].iloc[0])}
documents where the API says "Substantial" says "Satisfactory" in the published
ICRR itself, and applying the repair raises agreement with the primary documents
from {float(repair_doc["API value matches document verbatim"].iloc[0]):.1%} to
{float(repair_doc["REPAIRED value matches document"].iloc[0]):.1%}. So the
repair is confirmed against the source of record, not only against a second
dataset.

**What is still not claimed.** No World Bank source code or field dictionary
describing this behaviour was read, so the CAUSE of the substitution remains
unknown, and nothing here says why the API does it. What is established is that
the API's value disagrees with the published document and that the repair
reconciles them.

With the repair, API-wide: n = {dis["overall_api"]["n"]:,}, exact agreement
{dis["overall_api"]["agree"]:.2%}, Bank higher
{dis["overall_api"]["bank_higher"]:.2%}, Bank lower
{dis["overall_api"]["bank_lower"]:.2%}.

Restricted to the {dis["overall_join"]["n"]:,} projects in this backtest sample:
exact agreement {dis["overall_join"]["agree"]:.2%}, Bank higher
{dis["overall_join"]["bank_higher"]:.2%}, Bank lower
{dis["overall_join"]["bank_lower"]:.2%}.

By approval year, API-wide with the repair:

{T(dis["tbl_api"], "{:.4f}")}

## Schedule slip

{T(slip_summary, "{:.2f}")}

`schedule_slip_days` is the **actual** closing date minus the **original**
planned closing date, both taken from the GovTech workbook.

**Why both dates come from the same table.** Neither the Projects API nor the
IEG bulk CSV publishes a planned closing date. The API exposes only
`closingdate`, which is the current value and moves when a project is extended;
the field names `revisedclosingdate`, `orig_closing_date` and `p_closing_date`
were probed against the API and do not exist. The only verified machine-readable
original closing date found is the GovTech workbook's `Org Closing Dt`, which
covers a subset, so this column is populated for that subset and null elsewhere.

**A correction.** An earlier version of this table subtracted the workbook's
original date from the *API's* `closingdate`, a mixed-source subtraction, and
labelled the workbook's other date column "revised". Both were wrong, and the
workbook's own Metadata sheet says so: row 28 defines `Org Closing Dt` as
"Original Closing Date" and row 29 defines `Rev Closing Dt` as **"Actual Closing
Date"**, not a revised one. The two "actual" dates disagree on
{1 - float((df[["actual_closing_date", "gt_actual_closing_date"]].dropna().pipe(lambda d: (d.iloc[:, 0] == d.iloc[:, 1]).mean()))):.1%}
of the rows where both exist, and the mixed-source version overstated the slip:

{T(slip_compare, "{:.1f}")}

The same-source figure is the one reported above and carried in
`schedule_slip_days`; the mixed-source one is retained as
`schedule_slip_days_api_actual` so the gap stays visible rather than being
quietly corrected away.

## Release table

`results/pad_ieg_join.csv`, {len(df):,} rows, {len(df.columns)} columns,
one row per project. It carries the P-number, project name, country, region,
practice group and global practice, board approval date, actual closing date,
planned closing date where available, commitment and cost amounts, the PAD's
guid, document date, txturl and pdfurl, the text sha256 and byte size, every
column of the IEG ratings dataset, the Projects API `ieg_ratings` block
(including ICR quality, risk to development outcome and borrower performance,
which the bulk CSV omits), the Bank's ICR self-ratings, the derived six-point
numeric scales, the binary label, and `schedule_slip_days`.

## Caveats

- **The country effect carries most of the naive skill.** Pooled AUC and
  within-country AUC are reported side by side for exactly this reason. Read the
  within-country column before believing the pooled one.
- **The label is a human judgment, not a measurement.** IEG's outcome rating is
  an expert assessment against the project's own stated objectives. A project
  that lowered its objectives mid-flight can be rated satisfactory.
- **Objectives are revised.** Restructuring can change the standard the project
  is later rated against, and nothing in the ex-ante PAD anticipates that.
- **Selection into evaluation.** PPARs are chosen by IEG, not sampled at random,
  so the mix of evaluation types is not representative.
- **OCR noise is concentrated in the validation fold, which is where the
  regularisation strength is chosen.** See the section above; this is a real
  hazard, not a decorative caveat.
- **Four documents in five are truncated.** The models read the first 200,000
  characters and {(man_ok["text_bytes"] > 200_000).mean():.1%} of usable
  documents are longer than that, so the results framework and risk matrix at
  the back of a typical PAD are outside the model's view.
- **The sample is investment lending only, and that is by construction.** The
  joined sample carries {int((df["ieg_lending_instrument_type"] == "IPF").sum()):,}
  Investment Project Financing operations against
  {int((df["ieg_lending_instrument_type"] == "DPF").sum())} Development Policy
  Financing. A Project Appraisal Document is the appraisal instrument for
  investment lending; development policy operations are appraised in a Program
  Document, which is a different WDS document type and is not fetched here. So
  nothing in this report describes budget-support lending.
- **Not every rated project has a PAD, in any year.** The joined sample is
  {len(df):,} of 12,597 rated projects. Coverage is zero before FY{coverage_facts["first_year_with_any"]}
  (the PAD document type does not appear in WDS earlier) and then sits between
  {coverage_facts["mid_lo"]:.0%} and {coverage_facts["mid_hi"]:.0%} for every
  year from FY2002 to FY2019, before falling away in the censored recent
  cohorts. The missing third of the modern years is not explained here; it is
  not a pre-1996 vintage effect, and treating the joined sample as a random
  subsample of rated projects is not supported.
- **Multi-project appraisal documents.** {pad_counts["multi_project_records"]}
  PAD records appraise more than one project and are counted for each, so the
  same text can appear against more than one label.
- **Non-English PADs are now excluded where possible, but one remains.** Of
  {pad_counts["records"]:,} PAD records in WDS, 461 are not in English. The
  filter prefers an English version among the documents that pass the date test,
  so the corpus is {int((df["pad_lang"] == "English").sum()):,} English and
  {int((df["pad_lang"] != "English").sum())} other, that one being a project
  with no qualifying English version. It is left in rather than dropped, so the
  sample is not conditioned on document language, but a single non-English
  document contributes its own vocabulary to the TF-IDF matrix.
- **The GovTech workbook is a portfolio subset**, not the whole Bank. Any rate
  computed from it alone describes that subset.
- **The reported p-value is uncorrected and the search was wide.** Six ladder
  rungs, two cell definitions, a nine-point regularisation sweep and two label
  cuts were examined. The permutation p-value of
  {ameta["placebo_permute"]["p_value_one_sided"]:.3f} is reported as computed,
  with no multiplicity correction, and it should not be read as significance.
- **Right-censoring selects the recent cohorts.** A project enters the ratings
  table only once it closes and is evaluated, a median of
  {lab_eval_lag_median:.0f} years after approval. Approval cohorts from 2019
  onward are represented only by their fastest-closing members; see the
  censoring section. The restriction check shows the headline does not depend on
  those rows, which is not the same as showing the sample is unselected.
- **The text model is not country-blind.** A PAD names its own country, so
  TF-IDF recovers part of the country effect through the vocabulary. This is why
  the within-country AUC is the headline statistic and the pooled AUC is not.
- **Regularisation was tuned once, on the validation fold, then the model was
  refitted on train plus validation with that value.** The test fold never
  influenced a hyperparameter. {c_boundary_note}
- **The within-country statistic discards
  {model.loc[0, "within_country_rows_excluded"]:.1%} of test rows**, those in
  countries with fewer than 10 test projects or fewer than 2 of either class.
  That exclusion is a selection on realised labels, and the excluded share is
  reported in every model row rather than hidden.

## What could not be verified

- **The cause of the "Substantial" for "Satisfactory" substitution** in the
  Projects API `icr_ratings` block. The substitution itself is no longer only
  inferred: it is confirmed against
  {int(repair_doc["documents parsed"].iloc[0])} primary ICRR documents, in all
  {int(repair_doc["rows where API says Substantial"].iloc[0])} of the cases
  where the API emits it. What remains unverified is WHY the API does it; no
  World Bank source code or field dictionary describing the behaviour was found.
- **The as-of date of `Country / Economy FCS Status`.** It was measured as
  tracking the project's closing period rather than its approval period, which
  is why it is excluded from the feature set, but no World Bank dictionary
  stating the field's vintage was found. The exclusion rests on a measured
  association, not on a documented mechanism.
- **Why a third of rated projects from FY2002 to FY2019 have no qualifying PAD.**
  Coverage in those years sits between about 60 and 73 percent and the missing
  share is not explained. It is not a pre-1996 vintage effect.
- **Whether the 200,000-character truncation costs anything.** It affects
  {(man_ok["text_bytes"] > 200_000).mean():.1%} of usable documents. Raising the
  limit was not tried, so the cost is unmeasured in both directions.
- **The meaning of the `versiontyp` values** ("Buff cover", "Final", "Revised").
  No World Bank dictionary for the field was found, so what they denote
  editorially is not claimed; only their `docdt` matters to the leakage filter.
- **A planned closing date for the full portfolio.** Probed and not found; see
  the schedule slip section.
- **The Finances One `/api/views/` and `/resource/` Socrata endpoints.** They
  302-redirect to the Finances One application and return no data. The bulk CSV
  route works and was used instead.
- **The Data Catalog `ddhxext` API** returned HTTP 429 on every attempt. The
  replacement host `ddh-openapi.worldbank.org` worked and was used.
- **Whether the six-point scale had identical wording across all decades.**
  Ratings from the 1970s and 1980s appear in the same value set, but whether
  IEG's rating standard was constant over fifty years is a question about
  evaluation practice, not about this data, and it is not answered here.

## Reproducing

```
cd worldbank
make test      # pytest on the label construction and scoring functions
make all       # fetch, join, download text, model, report
```

Individual steps: `make static`, `make wds`, `make projects`, `make dataset`,
`make padtext`, `make model`, `make analysis`, `make report`.

`make analysis` is the second pass and takes a few minutes: it fits the TF-IDF
vocabulary once and reuses it across the ablation, the coefficients, the
{ameta["placebo_permute"]["n_permutations"]:,}-draw permutation null, the
{ameta["placebo_refit"]["n_repeats"]} permuted-label refits and the second label
cut. It is seeded, so its numbers reproduce exactly.

Tests redirect every module's results path at a temporary directory, suite-wide,
via `tests/conftest.py`. That protection exists because a test once wrote its
synthetic fixture over a real results file and the report published it.
"""
    out.write_text(md)
    print(f"wrote {out}")
    for p in (p1, p2, p3, p4, p5, p6, p7, p8, p9):
        print("chart:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
