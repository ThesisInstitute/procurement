"""Load the World Bank Digital Governance / GovTech Projects workbook.

Why this file exists. Neither the Finances One IEG bulk CSV nor the Projects API
gives a usable pair of (a) the Bank's OWN ICR self-rating and (b) the ORIGINAL
(planned) closing date. This workbook gives both, for a subset of projects.

Source, verified 2026-09-15:
  https://datacatalogfiles.worldbank.org/ddh-published/0038056/DR0095723/
      WBG_DG-GovTech_Projects_Nov2025.xlsx            (3,808,135 bytes)
  Data Catalog dataset 0038056, resource DR0095723. Also reachable at
  https://ddh-openapi.worldbank.org/resources/DR0095723/download (identical
  byte count).

Sheets used: "DG Projects" (1,536 rows) and "DG Other" (1,998 rows),
3,490 distinct P-numbers combined.

Columns used, with the observed value sets:
  Project ID      P-number
  Org Closing Dt  ORIGINAL (planned) closing date  -- Metadata row 28
  Rev Closing Dt  ACTUAL closing date              -- Metadata row 29
                  (the abbreviation reads as "revised"; the workbook's own
                   Metadata sheet defines it as "Actual Closing Date")
  ICR Out         Bank ICR self-rating of outcome    HS S MS MU U HU + sentinels
  IEG Out         IEG rating of outcome              HS S MS MU U HU + sentinels
  ICR BaP/IEG BaP Bank performance, self vs IEG
  ICR BoP/IEG BoP Borrower performance, self vs IEG

Sentinels observed in the rating columns and treated as "no rating":
  "-", "?", "#", "#MULTIVALUE", "NR", "NV", 0

COVERAGE CAVEAT, stated wherever these numbers are used: this workbook is the
Digital Governance / GovTech portfolio, not the whole Bank portfolio. Any rate
computed from it describes that subset and is not a portfolio-wide statistic.
"""
from __future__ import annotations

import pandas as pd

from . import scales
from .paths import RAW

XLSX = RAW / "govtech" / "WBG_DG-GovTech_Projects_Nov2025.xlsx"
URL = ("https://datacatalogfiles.worldbank.org/ddh-published/0038056/"
       "DR0095723/WBG_DG-GovTech_Projects_Nov2025.xlsx")
SHEETS = ["DG Projects", "DG Other"]

COLS = {
    "Project ID": "projectid",
    "Org Closing Dt": "gt_original_closing_date",
    # NOT a "revised" date. The workbook's own Metadata sheet, row 29, defines
    # column AC "Rev Closing Dt" as "Actual Closing Date" (source: OP), against
    # row 28's column AB "Org Closing Dt" = "Original Closing Date". The
    # abbreviation is misleading and this column was mis-named here until the
    # metadata sheet was read.
    "Rev Closing Dt": "gt_actual_closing_date",
    "ICR Out": "gt_icr_outcome",
    "IEG Out": "gt_ieg_outcome",
    "ICR BaP": "gt_icr_bank_perf",
    "IEG BaP": "gt_ieg_bank_perf",
    "ICR BoP": "gt_icr_borrower_perf",
    "IEG BoP": "gt_ieg_borrower_perf",
}


def load() -> pd.DataFrame:
    if not XLSX.exists():
        raise FileNotFoundError(
            f"{XLSX} missing; run `make static` "
            f"(or .venv/bin/python -m worldbank.src.fetch_static), "
            f"or download {URL}")
    frames = []
    for sh in SHEETS:
        d = pd.read_excel(XLSX, sheet_name=sh)
        keep = {k: v for k, v in COLS.items() if k in d.columns}
        d = d[list(keep)].rename(columns=keep)
        d["gt_sheet"] = sh
        frames.append(d)
    g = pd.concat(frames, ignore_index=True)
    g["projectid"] = g["projectid"].astype(str).str.strip().str.upper()
    g = g[g["projectid"].str.fullmatch(r"P\d+", na=False)]
    for c in ("gt_original_closing_date", "gt_actual_closing_date"):
        g[c] = pd.to_datetime(g[c], errors="coerce")
    # The rating columns mix strings ("MS") with the numeric sentinel 0, so cast
    # them to a single string dtype before anything downstream touches them.
    for c in [v for v in COLS.values() if v.startswith("gt_")
              and "closing" not in v]:
        if c in g.columns:
            g[c] = g[c].astype("string")
    # keep the row with the most information per project
    g["__info"] = g[[c for c in g.columns if c.startswith("gt_")
                     and c != "gt_sheet"]].notna().sum(axis=1)
    g = g.sort_values(["projectid", "__info"]).drop_duplicates(
        "projectid", keep="last").drop(columns="__info")
    return g.reset_index(drop=True)


# The workbook's rating columns are known rating columns, so abbreviation
# expansion is safe here and ONLY here. See scales.canonicalise for why it is
# off by default everywhere else.
RATING_COLS = ["gt_icr_outcome", "gt_ieg_outcome", "gt_icr_bank_perf",
               "gt_ieg_bank_perf", "gt_icr_borrower_perf",
               "gt_ieg_borrower_perf"]


def six_point(value) -> float | None:
    return scales.to_six_point(value, allow_abbrev=True)


def add_six_point(df):
    out = df.copy()
    for c in RATING_COLS:
        if c in out.columns:
            out[f"{c}_six_point"] = out[c].map(six_point)
    return out
