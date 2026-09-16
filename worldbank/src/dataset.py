"""Build the leakage-controlled PAD-to-IEG release table.

Authoritative label source: the Finances One IEG bulk CSV
(DS00053 / RS00055), "As of Date" 09/13/2026, 12,598 rows x 21 columns,
CC BY 4.0. The Projects API `ieg_ratings` block is carried alongside it as a
SECONDARY copy for cross-checking, never as the label.

Run:  .venv/bin/python -m worldbank.src.dataset
"""
from __future__ import annotations

import pandas as pd

from . import govtech, join, scales
from .paths import IEG_CSV, PROJECTS, RESULTS, WDS

IEG_RENAME = {
    "As of Date": "ieg_as_of_date",
    "Project ID": "projectid",
    "Project Name": "ieg_project_name",
    "WB Region": "ieg_region",
    "Country / Economy": "ieg_country",
    "Country / Economy Lending Group": "ieg_country_lending_group",
    "Country / Economy FCS Status": "ieg_country_fcs_status",
    "Country / Economy FCS Lending Group": "ieg_country_fcs_lending_group",
    "Practice Group": "ieg_practice_group",
    "Global Practice": "ieg_global_practice",
    "Agreement Type": "ieg_agreement_type",
    "Lending Instrument Type": "ieg_lending_instrument_type",
    "Approval FY": "ieg_approval_fy",
    "Final Closing FY": "ieg_final_closing_fy",
    "Evaluation Type": "ieg_evaluation_type",
    "Outcome": "ieg_outcome",
    "Quality at Entry": "ieg_quality_at_entry",
    "Quality of Supervision": "ieg_quality_of_supervision",
    "Bank Performance": "ieg_bank_performance",
    "M&E Quality": "ieg_me_quality",
    "Evaluation FY": "ieg_evaluation_fy",
}

PAD_KEEP = {
    "id": "pad_doc_id", "docdt": "pad_docdt", "guid": "pad_guid",
    "txturl": "pad_txturl", "pdfurl": "pad_pdfurl", "url": "pad_url",
    "display_title": "pad_display_title", "repnb": "pad_repnb",
    "lang": "pad_lang", "versiontyp": "pad_versiontyp",
    "disclstat": "pad_disclstat", "seccl": "pad_seccl",
    "abstract": "pad_abstract", "sectr": "pad_sectr", "theme": "pad_theme",
    "count": "pad_country_field", "admreg": "pad_admreg",
    "datestored": "pad_datestored", "disclosure_date": "pad_disclosure_date",
}

PJ_KEEP = [
    "project_name", "regionname", "countryname", "countryshortname",
    "countrycode", "boardapprovaldate_exact", "closingdate",
    "loan_effective_date", "public_disclosure_date", "fiscalyear", "status",
    "last_stage_reached_name", "prodline_exact", "projectfinancialtype_exact",
    "envassesmentcategorycode", "esrc_ovrl_risk_rate", "lendprojectcost",
    "curr_project_cost", "totalamt", "grantamt", "idacommamt",
    "curr_ibrd_commitment", "curr_ida_commitment", "curr_total_commitment",
    "borrower", "impagency", "major_sector_code", "major_sector_name",
    "sector_name", "sectorcode", "sector_percent", "theme", "themecode",
    "pdo", "project_abstract",
    "ms_concpt_review_date", "ms_begin_apprsl_date", "ms_apprvl_date",
    "ms_effctvnss_date", "ms_icr_nco_date", "ms_decsn_review_date",
    "n_isr_ratings", "isr_first_pdo_rating", "isr_first_pdo_date",
    "isr_last_pdo_rating", "isr_last_pdo_date",
    "isr_first_ip_rating", "isr_first_ip_date",
    "isr_last_ip_rating", "isr_last_ip_date",
]

# A PAD dated more than two years before the Board is not the appraisal document
# that Board approved; see the plausibility bound in build().
MAX_PLAUSIBLE_LEAD_DAYS = 730

NUMERIC = ["lendprojectcost", "curr_project_cost", "totalamt", "grantamt",
           "idacommamt", "curr_ibrd_commitment", "curr_ida_commitment",
           "curr_total_commitment"]


def load_ieg(return_raw_n: bool = False):
    df = pd.read_csv(IEG_CSV, encoding="utf-8-sig", dtype=str)
    n_raw = len(df)
    missing = set(IEG_RENAME) - set(df.columns)
    if missing:
        raise RuntimeError(f"IEG CSV columns changed; missing {sorted(missing)}")
    df = df.rename(columns=IEG_RENAME)
    df["projectid"] = df["projectid"].str.strip().str.upper()
    # One row per project, keeping the LATEST evaluation. The bulk CSV contains
    # one duplicate P-number, so this drops exactly one row; the raw count is
    # returned so the funnel can report the file as published rather than as
    # deduplicated.
    df = df.sort_values(["projectid", "ieg_evaluation_fy"]).drop_duplicates(
        "projectid", keep="last")
    return (df, n_raw) if return_raw_n else df


def build() -> pd.DataFrame:
    ieg, n_ieg_raw = load_ieg(return_raw_n=True)
    pad = pd.read_parquet(WDS / "pad.parquet")
    pj = pd.read_parquet(PROJECTS / "projects.parquet")
    pj["projectid"] = pj["id"].astype(str).str.strip().str.upper()

    approval = pj[["projectid", "boardapprovaldate_exact"]].copy()
    approval["boardapprovaldate"] = pd.to_datetime(
        approval["boardapprovaldate_exact"], errors="coerce")
    approval = approval[["projectid", "boardapprovaldate"]].drop_duplicates(
        "projectid")

    pad_ex = join.explode_projectids(pad)
    kept, rejected = join.qualifying_pad(pad_ex, approval)

    fun = join.funnel(ieg, pad_ex, approval, kept, n_ieg_rows_raw=n_ieg_raw)
    fun.to_csv(RESULTS / "funnel.csv", index=False)
    rejected.groupby("reject_reason").size().rename("n").reset_index().to_csv(
        RESULTS / "pad_rejections.csv", index=False)
    rejected[["projectid", "id", "docdt", "reject_reason"]].to_csv(
        RESULTS / "pad_rejected_rows.csv", index=False)

    kept = kept.rename(columns=PAD_KEEP)
    keep_cols = ["projectid", "boardapprovaldate"] + list(PAD_KEEP.values())
    kept = kept[[c for c in keep_cols if c in kept.columns]]

    df = ieg.merge(kept, on="projectid", how="inner")
    pj_cols = ["projectid"] + [c for c in PJ_KEEP if c in pj.columns]
    pj_cols += [c for c in pj.columns if c.startswith(("icr_", "iegapi_"))]
    df = df.merge(pj[pj_cols].drop_duplicates("projectid"), on="projectid",
                  how="left")

    for c in NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["boardapprovaldate"] = pd.to_datetime(df["boardapprovaldate"])
    df["approval_year"] = df["boardapprovaldate"].dt.year
    df["approval_decade"] = (df["approval_year"] // 10 * 10).astype("Int64")
    df["pad_docdt_dt"] = join.parse_dt(df["pad_docdt"])
    # Days from the PAD's date to board approval. Positive is the normal case
    # (the document predates the Board); negative is a document stamped just
    # after the Board, which the 30-day grace window admits.
    #
    # PLAUSIBILITY BOUND. `pad_lead_days` is a standardised model feature, so a
    # single wild value distorts the scaler for every row. Observed before this
    # bound: median 26 days and interquartile range 21 to 31, but a maximum of
    # 3,651 days. That maximum is P152646, whose PAD is dated 2005-03-19 against
    # a board date of 2015-03-19: the same month and day, ten years apart, which
    # is a date that cannot be right. Six rows exceed two years and the extreme
    # one sits at 48 standard deviations, inflating the feature's standard
    # deviation to 75 days against an interquartile range of about 10.
    #
    # Values outside [-GRACE_DAYS, MAX_PLAUSIBLE_LEAD_DAYS] are therefore set to
    # missing, so the median imputer handles them, and are counted in
    # `pad_lead_days_out_of_range`. Nothing is dropped from the release table:
    # the raw difference is kept in `pad_lead_days_raw` so a reader can undo
    # this. LABELLED INFERENCE: that these are data errors rather than genuine
    # ten-year-old appraisal documents is an inference from the date pattern,
    # not something a World Bank source states.
    lead_raw = (df["boardapprovaldate"]
                - df["pad_docdt_dt"]).dt.days.astype("Float64")
    df["pad_lead_days_raw"] = lead_raw
    implausible = (lead_raw < -join.GRACE_DAYS) | (lead_raw
                                                   > MAX_PLAUSIBLE_LEAD_DAYS)
    df["pad_lead_days_out_of_range"] = implausible.fillna(False)
    df["pad_lead_days"] = lead_raw.mask(implausible)
    df["actual_closing_date"] = pd.to_datetime(df["closingdate"], errors="coerce")
    df["ieg_approval_fy"] = pd.to_numeric(df["ieg_approval_fy"], errors="coerce")
    df["ieg_final_closing_fy"] = pd.to_numeric(df["ieg_final_closing_fy"],
                                               errors="coerce")
    df["ieg_evaluation_fy"] = pd.to_numeric(df["ieg_evaluation_fy"],
                                            errors="coerce")

    # ORIGINAL (planned) closing date. Neither the Projects API nor the Finances
    # One IEG CSV publishes one: the API exposes only `closingdate`, the current
    # value. The GovTech workbook does publish "Org Closing Dt", so the planned
    # date is available for the subset of projects that workbook covers and null
    # elsewhere. This is stated in the report rather than filled in.
    gt = govtech.load()
    df = df.merge(gt, on="projectid", how="left")
    df["planned_closing_date"] = df["gt_original_closing_date"]
    # SAME-SOURCE slip is the headline. Both dates come from the GovTech
    # workbook, whose Metadata sheet defines "Org Closing Dt" as the Original
    # Closing Date (row 28) and "Rev Closing Dt" as the ACTUAL Closing Date
    # (row 29). Subtracting two columns of one table is the clean computation.
    #
    # The earlier version subtracted the workbook's original date from the
    # Projects API's `closingdate`, which is a MIXED-SOURCE subtraction. The two
    # "actual" dates agree on only 88.9% of the 1,860 rows where both exist, and
    # the mixed version overstates mean slip by 73.6 days (+15.6%): median 457
    # against 365, mean 545.1 against 471.5. Both are kept so the gap is
    # visible, but the same-source one is `schedule_slip_days`.
    df["schedule_slip_days"] = join.schedule_slip_days(
        df["gt_actual_closing_date"], df["planned_closing_date"])
    df["schedule_slip_days_api_actual"] = join.schedule_slip_days(
        df["actual_closing_date"], df["planned_closing_date"])

    # Bank self-rating versus IEG rating, from the GovTech workbook (the only
    # verified machine-readable pairing found; see src/govtech.py).
    df["icr_self_outcome_six_point"] = df["gt_icr_outcome"].map(
        govtech.six_point)
    df["ieg_outcome_six_point_govtech"] = df["gt_ieg_outcome"].map(
        govtech.six_point)
    df["bank_minus_ieg_outcome"] = (df["icr_self_outcome_six_point"]
                                    - df["ieg_outcome_six_point_govtech"])
    df["implementation_days"] = (df["actual_closing_date"]
                                 - df["boardapprovaldate"]).dt.days.astype("Float64")
    df["implementation_years"] = df["implementation_days"] / 365.25

    df["outcome_six_point"] = scales.series_six_point(df["ieg_outcome"])
    df["y_satisfactory"] = scales.series_satisfactory(df["ieg_outcome"])
    df["bank_perf_six_point"] = scales.series_six_point(df["ieg_bank_performance"])
    df["quality_entry_six_point"] = scales.series_six_point(
        df["ieg_quality_at_entry"])
    df["quality_supervision_six_point"] = scales.series_six_point(
        df["ieg_quality_of_supervision"])
    df["me_quality_four_point"] = df["ieg_me_quality"].map(scales.to_four_point)
    # Risk to development outcome uses two four-point vocabularies; the vintage
    # is recorded so a reader can refuse to pool them.
    df["risk_to_dev_outcome_four_point"] = df["iegapi_evaluation_riskdo"].map(
        scales.to_four_point)
    df["risk_to_dev_outcome_scale_vintage"] = df["iegapi_evaluation_riskdo"].map(
        scales.risk_vintage)
    df["borrower_perf_six_point"] = scales.series_six_point(
        df["iegapi_overallborrowperf"])

    # Amount feature for the models.
    #
    # WITHDRAWN CLAIM. An earlier version of this comment said the `curr_`
    # prefix marks CURRENT values that move on restructuring, and that the
    # un-prefixed fields are therefore the approval-time values. The API's own
    # data falsifies that naming convention:
    #   lendprojectcost == curr_project_cost   on 27,477 of 27,477 rows (100%),
    #                                          across 5,960 distinct values
    #   idacommamt      == curr_ida_commitment on 13,650 of 13,650 rows (100%)
    #   totalamt        == curr_ibrd_commitment + curr_ida_commitment
    #                                          on 99.83% of rows
    # The prefixed and un-prefixed fields are the SAME numbers served under two
    # names, so the prefix carries no approval-versus-current semantics.
    #
    # The "23.4% differ" statistic that used to support the claim measured
    # something else entirely: totalamt differs from curr_total_commitment on
    # 21.06% of rows, 100% of those rows have grantamt > 0, and the gap equals
    # grantamt exactly on 94.57% of them. That is a SCOPE difference (whether
    # the grant component is included), not drift over time.
    #
    # WHAT IS ACTUALLY KNOWN: nothing establishes any of these fields as an
    # approval-time value. `approval_amount_usd` may be a current value. It is
    # kept as a feature because the Board does approve an amount and it is the
    # most natural ex-ante structured input, but its vintage is UNKNOWN, it is
    # labelled as such in the report, and src/analysis.py reports what the
    # models score without it so a reader can see what rests on it.
    # `curr_total_commitment` is still not used, now simply because it is the
    # grant-inclusive variant rather than because of a vintage argument.
    import numpy as np
    amount = pd.to_numeric(df["totalamt"], errors="coerce")
    amount = amount.fillna(pd.to_numeric(df["lendprojectcost"], errors="coerce"))
    df["approval_amount_usd"] = amount
    df["log_commitment"] = np.log10(amount.clip(lower=1))
    df["log_curr_commitment_excluded_from_features"] = np.log10(
        pd.to_numeric(df["curr_total_commitment"], errors="coerce").clip(lower=1))

    # Text release columns. The manifest is written by fetch_pad_text, which runs
    # after the first dataset build, so this merge is a no-op on the first pass
    # and populated on the second. `make all` runs dataset, padtext, dataset.
    man_path = RESULTS / "pad_text_manifest.csv"
    if man_path.exists():
        man = pd.read_csv(man_path)[
            ["projectid", "text_sha256", "text_bytes", "status", "http_status"]]
        man = man.rename(columns={"status": "pad_text_status",
                                  "http_status": "pad_text_http_status",
                                  "text_sha256": "pad_text_sha256",
                                  "text_bytes": "pad_text_bytes"})
        df = df.merge(man.drop_duplicates("projectid"), on="projectid",
                      how="left")
        df["pad_text_usable"] = df["pad_text_status"].eq("ok")
    else:
        for c in ("pad_text_sha256", "pad_text_bytes", "pad_text_status",
                  "pad_text_http_status"):
            df[c] = None
        df["pad_text_usable"] = False

    return df.sort_values("projectid").reset_index(drop=True)


# The CSV is a text file, and pandas' defaults silently corrupt two kinds of
# value in it. Reading the release table with a bare `pd.read_csv` will:
#   - strip the leading zero from 11 `pad_guid` values, because they look
#     numeric ("099751207242621222" -> 99751207242621222); and
#   - turn Namibia's ISO country code "NA" into a null, because "NA" is in
#     pandas' default missing-value list.
# Both are defects of the READER, not of the file, and both disappear with the
# arguments below. `verify_csv_roundtrip` asserts it every build so the released
# artefact can never quietly stop round-tripping.
READ_CSV_KWARGS = dict(dtype=str, keep_default_na=False, na_values=[""],
                       low_memory=False)


def read_release_table(path=None) -> pd.DataFrame:
    """Read results/pad_ieg_join.csv without pandas' lossy defaults."""
    return pd.read_csv(path or (RESULTS / "pad_ieg_join.csv"),
                       **READ_CSV_KWARGS)


def verify_csv_roundtrip(df: pd.DataFrame, path) -> None:
    """Fail the build if the written CSV does not read back identically.

    Compared as strings, because the CSV has no dtypes: what must survive is
    the VALUE, and the two cases this catches are exactly the ones that fail
    silently otherwise.
    """
    back = read_release_table(path)
    if list(back.columns) != list(df.columns):
        raise RuntimeError(
            f"CSV round-trip changed the columns: wrote {len(df.columns)}, "
            f"read {len(back.columns)}")
    if len(back) != len(df):
        raise RuntimeError(
            f"CSV round-trip changed the row count: {len(df)} -> {len(back)}")
    bad = []
    for c in ("projectid", "pad_guid", "countrycode", "pad_doc_id"):
        if c not in df.columns:
            continue
        # numpy object arrays, not arrow-backed ones, so the comparison
        # returns a plain boolean array rather than an extension array
        want = df[c].astype("string").fillna("").to_numpy(dtype=object)
        got = back[c].astype("string").fillna("").to_numpy(dtype=object)
        n = int((want != got).sum())
        if n:
            bad.append(f"{c}: {n} value(s) differ")
    if bad:
        raise RuntimeError("CSV round-trip lost data in " + "; ".join(bad))


def main() -> int:
    df = build()
    out = RESULTS / "pad_ieg_join.csv"
    df.to_csv(out, index=False)
    df.to_parquet(RESULTS / "pad_ieg_join.parquet", index=False)
    verify_csv_roundtrip(df, out)
    # the download queue consumed by fetch_pad_text
    q = df.loc[df["pad_txturl"].notna(), ["projectid", "pad_txturl"]].rename(
        columns={"pad_txturl": "txturl"})
    q.to_csv(RESULTS / "pad_download_queue.csv", index=False)
    print(f"wrote download queue rows={len(q)}")
    print(f"wrote {out} rows={len(df)} cols={len(df.columns)}")
    print("labelled rows (outcome on scale):", int(df["y_satisfactory"].notna().sum()))
    print("with txturl:", int(df["pad_txturl"].notna().sum()))
    print(df["approval_year"].describe().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
