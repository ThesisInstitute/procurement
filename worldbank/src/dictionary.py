"""Emit a data dictionary for results/pad_ieg_join.csv.

Every column gets its source, dtype, non-null count and, for low-cardinality
columns, its observed value set. Provenance prefixes:

  ieg_*      Finances One IEG bulk CSV (DS00053 / RS00055)
  iegapi_*   Projects API `ieg_ratings` block (IEG side; carries ICR quality,
             risk to development outcome and borrower performance, which the
             bulk CSV omits)
  icr_*      Projects API `icr_ratings` block (the Bank's own self-rating; see
             src/icr_selfrating.py for the two measured defects)
  pad_*      Documents and Reports API record for the qualifying appraisal document
  ms_*       Projects API `milestones` block
  isr_*      Projects API `isr_ratings` block (supervision ratings, POST-approval)
  gt_*       GovTech workbook (Data Catalog 0038056 / DR0095723)
  derived    computed in src/dataset.py

Run:  .venv/bin/python -m worldbank.src.dictionary
"""
from __future__ import annotations

import pandas as pd

from .paths import RESULTS

SOURCES = [
    ("ieg_", "Finances One IEG bulk CSV (DS00053/RS00055)"),
    ("iegapi_", "Projects API ieg_ratings block"),
    ("icr_", "Projects API icr_ratings block (Bank self-rating)"),
    ("pad_", "Documents and Reports API (qualifying PAD record)"),
    ("ms_", "Projects API milestones block"),
    ("isr_", "Projects API isr_ratings block (POST-approval)"),
    ("gt_", "GovTech workbook (Data Catalog 0038056/DR0095723)"),
]

EX_ANTE = {
    "projectid", "boardapprovaldate", "approval_year", "approval_decade",
    "approval_amount_usd", "log_commitment", "pad_lead_days",
    "ieg_country", "ieg_region", "ieg_agreement_type",
    "ieg_lending_instrument_type", "ieg_country_lending_group",
    "ieg_country_fcs_status", "ieg_practice_group", "ieg_global_practice",
    "prodline_exact", "envassesmentcategorycode", "totalamt",
    "lendprojectcost", "idacommamt", "grantamt", "borrower", "impagency",
    "countryname", "countrycode", "regionname", "fiscalyear",
    "major_sector_code", "major_sector_name", "sector_name", "sectorcode",
    "sector_percent", "theme", "themecode", "pdo", "project_abstract",
    "project_name", "planned_closing_date", "gt_original_closing_date",
}


def source_of(col: str) -> str:
    for pre, label in SOURCES:
        if col.startswith(pre):
            return label
    return "derived in src/dataset.py or Projects API scalar field"


def build() -> pd.DataFrame:
    df = pd.read_parquet(RESULTS / "pad_ieg_join.parquet")
    rows = []
    for c in df.columns:
        s = df[c]
        nun = int(s.nunique(dropna=True))
        vals = ""
        if nun <= 12 and nun > 0:
            vals = "; ".join(sorted(str(v) for v in s.dropna().unique())[:12])
        rows.append({
            "column": c,
            "dtype": str(s.dtype),
            "non_null": int(s.notna().sum()),
            "distinct": nun,
            "known_at_board_approval": c in EX_ANTE,
            "source": source_of(c),
            "observed_values_if_few": vals,
        })
    return pd.DataFrame(rows)


def main() -> int:
    d = build()
    out = RESULTS / "pad_ieg_join_dictionary.csv"
    d.to_csv(out, index=False)
    print(f"wrote {out} rows={len(d)}")
    print("columns knowable at board approval:",
          int(d["known_at_board_approval"].sum()), "of", len(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
