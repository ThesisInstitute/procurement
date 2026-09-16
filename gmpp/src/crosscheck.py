"""Check the reconstructed panel against the IPA's own consolidated back-series.

The XLSX attachments of the 2020 publications carry a sheet named `SourceTable`
holding 1,255 project-years from AR 2013 (Q2 2012/13) to AR 2020 (Q2 2019/20)
across every department, with the GMPP id, the MPA RAG rating, the start and end
dates and the whole-life cost. That sheet was never the published product; the
per-department files were. It is used here only as an independent check that the
per-department reconstruction reproduces the same portfolio.

Writes `results/crosscheck_sourcetable.csv` and prints the agreement rates.

Run: .venv/bin/python -m gmpp.src.crosscheck
"""
from __future__ import annotations

import sys
import warnings

import numpy as np
import pandas as pd

from .identity import normalise_name
from .paths import RAW_DIR, RESULTS_DIR
from .parsing import parse_date, parse_money
from .ratings import harmonise

warnings.filterwarnings("ignore")

OUT_PATH = RESULTS_DIR / "crosscheck_sourcetable.csv"
SUMMARY_PATH = RESULTS_DIR / "table_crosscheck.csv"
GAP_PATH = RESULTS_DIR / "table_crosscheck_gap.csv"

# AR year in the SourceTable -> the snapshot that publication describes. The
# sheet's own "Quarter" column states the period, e.g. AR 2013 carries
# "1213-Q2", which is the quarter ending 30 September 2012.
AR_TO_SNAPSHOT = {
    "AR 2013": "2012-09-30",
    "AR 2014": "2013-09-30",
    "AR 2015": "2014-09-30",
    "AR 2016": "2015-09-30",
    "AR 2017": "2016-09-30",
    "AR 2018": "2017-09-30",
    "AR 2019": "2018-09-30",
    "AR 2020": "2019-09-30",
}


def load_source_table() -> pd.DataFrame:
    candidates = sorted(RAW_DIR.glob("2020/*/*.xlsx"))
    for path in candidates:
        try:
            sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
        except Exception:  # noqa: BLE001 - try the next file
            continue
        if "SourceTable" not in sheets:
            continue
        raw = sheets["SourceTable"].dropna(how="all")
        header = [str(v).replace("\n", " ").strip() for v in raw.iloc[0]]
        body = raw.iloc[1:].copy()
        body.columns = header
        body = body[body["GMPP ID Number"].notna()]
        body["source_workbook"] = str(path.relative_to(RAW_DIR))
        print(f"SourceTable read from {path.name}: {len(body)} rows")
        return body
    raise RuntimeError("no SourceTable sheet found in any 2020 XLSX")


def main() -> int:
    source = load_source_table()
    source["snapshot_date"] = source["AR Year"].map(AR_TO_SNAPSHOT)
    source["gmpp_id_norm"] = source["GMPP ID Number"].str.upper().str.strip()
    source["dca_source"] = source[
        "MPA RAG (Departmental RAG used if MPA RAG missing)"
    ].map(harmonise)
    source["wlc_source"] = source[
        [c for c in source.columns if c.startswith("TOTAL BUDGETED WHOLE LIFE")][0]
    ].map(parse_money)
    source["end_source"] = source[
        "Project - End Date (Latest Approved End Date)"
    ].map(parse_date)

    panel = pd.read_csv(RESULTS_DIR / "panel.csv")
    panel["snapshot_date"] = pd.to_datetime(panel["snapshot_date"]).dt.date.astype(str)
    panel["end_date"] = pd.to_datetime(panel["end_date"], errors="coerce")
    # The per-department files publish no id before the September 2019 snapshot,
    # so the join runs through the panel's project_key, which carries the id
    # forward and backward across the years it links.
    key_lookup = (
        panel[panel["gmpp_id"].notna()]
        .assign(gmpp_id_norm=lambda d: d["gmpp_id"].str.upper().str.strip())
        .drop_duplicates(subset=["gmpp_id_norm"])[["gmpp_id_norm", "project_key"]]
    )
    source = source.merge(key_lookup, on="gmpp_id_norm", how="left")

    # Second pass for the years before ids were published: match on the
    # normalised project name within the same snapshot. Names in the SourceTable
    # are the same strings the department files used.
    panel = panel.copy()
    panel["name_norm"] = panel["project_name"].map(normalise_name)
    source["name_norm"] = source["Project Name"].map(normalise_name)
    name_lookup = (
        panel.drop_duplicates(subset=["snapshot_date", "name_norm"], keep=False)
        [["snapshot_date", "name_norm", "project_key"]]
        .rename(columns={"project_key": "project_key_by_name"})
    )
    source = source.merge(name_lookup, on=["snapshot_date", "name_norm"], how="left")
    source["project_key"] = source["project_key"].fillna(
        source["project_key_by_name"]
    )
    source["join_route"] = np.where(
        source["project_key"].isna(), "unmatched",
        np.where(source["gmpp_id_norm"].isin(key_lookup["gmpp_id_norm"]),
                 "gmpp_id", "name"),
    )

    merged = source.merge(
        panel[["project_key", "snapshot_date", "project_name", "dca_published",
               "wlc_baseline_gbp_m", "end_date"]],
        on=["project_key", "snapshot_date"],
        how="left",
        indicator=True,
    )
    merged["matched"] = merged["_merge"] == "both"
    matched = merged[merged["matched"]].copy()
    matched["dca_agrees"] = matched["dca_source"] == matched["dca_published"]
    matched["wlc_agrees"] = (
        (matched["wlc_source"] - matched["wlc_baseline_gbp_m"]).abs()
        <= (0.005 * matched["wlc_source"].abs()).fillna(0)
    ) | (matched["wlc_source"].isna() & matched["wlc_baseline_gbp_m"].isna())
    matched["end_agrees"] = (
        matched["end_source"] == matched["end_date"]
    ) | (matched["end_source"].isna() & matched["end_date"].isna())

    merged.to_csv(OUT_PATH, index=False)

    rows = []
    for snapshot, block in matched.groupby("snapshot_date"):
        all_rows = merged[merged["snapshot_date"] == snapshot]
        rows.append(
            {
                "snapshot": snapshot,
                "source_table_rows": len(all_rows),
                "joined_to_panel": len(block),
                "join_rate": round(len(block) / len(all_rows), 4),
                "dca_agreement": round(float(block["dca_agrees"].mean()), 4),
                "wlc_agreement": round(float(block["wlc_agrees"].mean()), 4),
                "end_date_agreement": round(float(block["end_agrees"].mean()), 4),
                "joined_by_id": int((block["join_route"] == "gmpp_id").sum()),
                "joined_by_name": int((block["join_route"] == "name").sum()),
            }
        )
    summary = pd.DataFrame(rows)
    summary.to_csv(SUMMARY_PATH, index=False)

    # Where the panel does not reach the IPA's own back-series. Some
    # departments never published a departmental GMPP file at all and appear
    # only inside the IPA's consolidated table, so their project-years exist in
    # the portfolio and not in this panel. That is a coverage limit of the
    # published departmental releases, not a parse failure, and it is reported
    # rather than left implicit.
    unmatched = merged[~merged["matched"]].copy()
    if len(unmatched):
        dept_col = next(
            (
                c
                for c in ("Department Grouped", "Department", "department_source")
                if c in unmatched.columns
            ),
            None,
        )
        if dept_col:
            gap = (
                unmatched.groupby(dept_col)
                .agg(
                    rows_in_the_ipa_back_series=("matched", "size"),
                    snapshots=(
                        "snapshot_date",
                        lambda col: " ".join(sorted({str(v)[:10] for v in col})),
                    ),
                )
                .sort_values("rows_in_the_ipa_back_series", ascending=False)
                .reset_index()
                .rename(columns={dept_col: "department"})
            )
            gap.to_csv(GAP_PATH, index=False)
            print(f"\nback-series rows with no panel row, by department -> {GAP_PATH}")
            print(gap.to_string(index=False))
    print(summary.to_string(index=False))
    print(
        f"\noverall: joined {int(merged['matched'].sum())}/{len(merged)} "
        f"({merged['matched'].mean():.1%}); "
        f"DCA agrees {matched['dca_agrees'].mean():.1%}; "
        f"whole-life cost agrees {matched['wlc_agrees'].mean():.1%}; "
        f"end date agrees {matched['end_agrees'].mean():.1%}"
    )
    disagree = matched[~matched["dca_agrees"]]
    if len(disagree):
        print("\nsample of DCA disagreements:")
        print(
            disagree[["snapshot_date", "project_name", "dca_source",
                      "dca_published"]].head(15).to_string(index=False)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
