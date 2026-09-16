"""Build the canonical GMPP project-year panel.

One row per project per snapshot. Reads the CSV attachment of every data
publication (the CSV is the cleanest and most consistent format across all
years; the XLSX, XLS and ODS copies are downloaded too and used only for the
cross-checks in `gmpp.src.crosscheck`).

Writes:
  results/panel.csv               the canonical panel
  results/unmapped_headers.csv    every header not covered by gmpp.src.schema
  results/panel_build_log.csv     one row per file with what was read

Run: .venv/bin/python -m gmpp.src.panel
"""
from __future__ import annotations

import datetime as dt

import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .calendar_map import (
    REAL_PRICE_SNAPSHOTS,
    snapshot_disagreement,
    snapshot_for,
    snapshot_source_for,
)
from .identity import assign_project_keys
from .orientation import normalise
from .parsing import (
    detect_date_order,
    money_kind,
    parse_date,
    parse_money,
    parse_percent,
    parse_percent_parts,
)
from .paths import MANIFEST_PATH, RAW_DIR, RESULTS_DIR
from .profile_headers import norm_header
from .ratings import (
    FIVE_POINT,
    THREE_POINT,
    harmonise,
    normalised_rank,
    rank,
    scale_for_year,
)
from .readers import read_raw
from .schema import CANONICAL_COLUMNS, KNOWN_NON_DATA_HEADERS, map_header

warnings.filterwarnings("ignore")

PANEL_PATH = RESULTS_DIR / "panel.csv"
FUZZY_MERGES_PATH = RESULTS_DIR / "identity_fuzzy_merges.csv"
DUPLICATES_PATH = RESULTS_DIR / "panel_duplicates.csv"
UNMAPPED_PATH = RESULTS_DIR / "unmapped_headers.csv"
BUILD_LOG_PATH = RESULTS_DIR / "panel_build_log.csv"

def _pick_files(manifest: pd.DataFrame) -> pd.DataFrame:
    """One CSV per data publication, plus the two NISTA consolidated CSVs."""
    data = manifest[manifest["is_data_publication"] | manifest["publication_slug"]
                    .str.startswith("nista-")]
    csvs = data[data["ext"] == ".csv"].copy()
    # A publication occasionally carries two CSVs (2014 DfE and Defra publish a
    # duplicate). Keep the largest, which is the full table.
    csvs = csvs.sort_values("file_size", ascending=False)
    return csvs.drop_duplicates(subset=["publication_slug"], keep="first")


def build() -> tuple[pd.DataFrame, ...]:
    manifest = pd.read_csv(MANIFEST_PATH)
    chosen = _pick_files(manifest)

    frames: list[pd.DataFrame] = []
    unmapped: list[dict] = []
    build_log: list[dict] = []

    for row in chosen.itertuples():
        path = RAW_DIR / row.local_path
        log = {
            "publication_slug": row.publication_slug,
            "publication_year": row.publication_year,
            "department_slug": row.department_slug,
            "local_path": row.local_path,
            "snapshot_date": None,
            "n_rows": 0,
            "layout": None,
            "n_mapped": 0,
            "n_unmapped": 0,
            "date_order": "",
            "error": "",
        }
        try:
            wide, layout = normalise(read_raw(path).raw)
        except Exception as exc:  # noqa: BLE001 - record and continue
            log["error"] = f"{type(exc).__name__}: {exc}"
            build_log.append(log)
            continue

        log["layout"] = layout
        # The snapshot is dated from the file's own financial-year column header
        # where it has one, falling back to the publication-year table.
        snapshot = snapshot_for(
            row.publication_year, row.publication_slug, [str(c) for c in wide.columns]
        )
        log["snapshot_date"] = snapshot
        log["snapshot_source"] = snapshot_source_for(
            row.publication_year, row.publication_slug
        )
        log["snapshot_crosscheck"] = snapshot_disagreement(
            snapshot, [str(c) for c in wide.columns]
        )
        if snapshot is None:
            log["error"] = "no snapshot date"
            build_log.append(log)
            continue
        out = pd.DataFrame(index=wide.index)
        for col in wide.columns:
            key = norm_header(col)
            target = map_header(key)
            if target is None:
                if key not in KNOWN_NON_DATA_HEADERS and not key.startswith("_unnamed"):
                    unmapped.append(
                        {
                            "publication_slug": row.publication_slug,
                            "publication_year": row.publication_year,
                            "local_path": row.local_path,
                            "raw_header": col,
                            "norm_header": key,
                            "non_null": int(wide[col].notna().sum()),
                        }
                    )
                    log["n_unmapped"] += 1
                continue
            log["n_mapped"] += 1
            # When two source columns map to the same canonical field, keep the
            # first non-null. This happens where a file repeats a field.
            if target in out.columns:
                out[target] = out[target].fillna(wide[col])
            else:
                out[target] = wide[col]

        if "project_name" not in out.columns:
            log["error"] = "no project_name column"
            build_log.append(log)
            continue

        out = out[out["project_name"].notna()]
        out = out[
            out["project_name"].astype(str).str.strip().str.lower().isin(
                ("", "nan", "none", "project name", "total")
            )
            == False  # noqa: E712 - explicit for clarity on an object column
        ]
        if out.empty:
            log["error"] = "no data rows"
            build_log.append(log)
            continue

        # Dates are parsed here, inside the per-file loop, because the day/month
        # order is a property of the file. Three of the 196 panel files write
        # dates month first and the rest write them day first; reading a
        # month-first file day first silently transposes every cell where both
        # components are at most 12.
        date_cells = []
        for col in ("start_date", "end_date"):
            if col in out.columns:
                date_cells.extend(out[col].dropna().astype(str).tolist())
        order = detect_date_order(date_cells)
        log["date_order"] = order
        for col in ("start_date", "end_date"):
            if col in out.columns:
                out[col] = out[col].map(lambda v: parse_date(v, order=order))

        out["report_year"] = row.publication_year
        out["snapshot_date"] = pd.Timestamp(snapshot)
        out["publication_slug"] = row.publication_slug
        out["source_file"] = row.local_path
        out["source_department_slug"] = row.department_slug
        log["n_rows"] = len(out)
        frames.append(out)
        build_log.append(log)

    panel = pd.concat(frames, ignore_index=True, sort=False)

    for col in CANONICAL_COLUMNS:
        if col not in panel.columns:
            panel[col] = np.nan

    # --- typing and harmonisation -------------------------------------------
    for col in ("fy_baseline_gbp_m", "fy_forecast_gbp_m", "fy_variance_gbp_m",
                "wlc_baseline_gbp_m", "benefits_baseline_gbp_m"):
        panel[f"{col}_kind"] = panel[col].map(money_kind)
        panel[col] = panel[col].map(parse_money)
    # Parsed in two steps. The cell alone cannot say whether "0.64" means the
    # fraction 0.0064 or a variance of 0.64 per cent, so the number as written
    # and the ambiguity flag are kept and settled below against the baseline and
    # forecast published in the same row.
    _variance_parts = panel["fy_variance_pct"].map(parse_percent_parts)
    panel["fy_variance_pct_as_written"] = [v for v, _ in _variance_parts]
    panel["fy_variance_pct_ambiguous"] = [amb for _, amb in _variance_parts]
    panel["fy_variance_pct"] = panel["fy_variance_pct"].map(parse_percent)
    for col in ("start_date", "end_date"):
        panel[col] = pd.to_datetime(panel[col], errors="coerce")

    for col in ("project_name", "department", "gmpp_id", "annual_report_category"):
        panel[col] = panel[col].map(
            lambda v: re.sub(r"\s+", " ", str(v)).strip() if pd.notna(v) else None
        )

    panel["dca_ipa_raw"] = panel["dca_ipa"]
    panel["dca_sro_raw"] = panel["dca_sro"]
    panel["dca_ipa"] = panel["dca_ipa_raw"].map(harmonise)
    panel["dca_sro"] = panel["dca_sro_raw"].map(harmonise)
    # The category vocabulary is not stable. The March 2026 file renames "ICT"
    # to "Information and Communications Technology (ICT)"; a project-name join
    # shows 17 of the 19 continuing ICT projects are the same projects under the
    # new spelling, so leaving both in place would split one category in two
    # and understate it in any breakdown. The published string is kept and a
    # canonical form is derived beside it.
    panel["annual_report_category_published"] = panel["annual_report_category"]
    panel["annual_report_category"] = panel["annual_report_category"].map(
        canonical_category
    )

    panel["scale"] = panel["report_year"].map(scale_for_year)
    panel["dca_ipa_rank"] = [
        rank(r, s) for r, s in zip(panel["dca_ipa"], panel["scale"])
    ]
    panel["dca_sro_rank"] = [
        rank(r, s) for r, s in zip(panel["dca_sro"], panel["scale"])
    ]
    panel["dca_ipa_rank_norm"] = [
        normalised_rank(r, s) for r, s in zip(panel["dca_ipa"], panel["scale"])
    ]
    panel["is_real_prices"] = panel["snapshot_date"].dt.date.isin(
        REAL_PRICE_SNAPSHOTS
    )

    # The published in-year variance is not on one sign convention. Checked
    # against (forecast / baseline - 1) on the 1,988 rows that publish all
    # three: every snapshot up to March 2024 matches the SIGNED value on 90 to
    # 100 per cent of rows and publishes negatives on 33 to 65 per cent of them,
    # while the two NISTA files publish no negative at all and match the
    # MAGNITUDE on 94 to 95 per cent. The published figure is kept as it stands
    # and a signed figure is derived alongside it, so a user can choose.
    baseline = pd.to_numeric(panel["fy_baseline_gbp_m"], errors="coerce")
    forecast = pd.to_numeric(panel["fy_forecast_gbp_m"], errors="coerce")
    panel["fy_variance_pct_derived"] = (
        (forecast / baseline - 1.0) * 100.0
    ).where(baseline > 0)
    panel["fy_variance_sign_convention"] = np.where(
        panel["snapshot_date"].dt.year >= 2025, "unsigned magnitude", "signed"
    )

    # Settle the fraction-or-percent ambiguity from the row itself. Where the
    # same row publishes a positive baseline and a forecast, the derived
    # variance says which reading is right, on either sign convention. Of the
    # 1,201 ambiguous cells that can be settled this way, 1,181 really are
    # fractions and 20 are already percentages, all of them variances below one
    # per cent in the two NISTA files, the March 2024 MOD file and one 2013 Home
    # Office row. The blanket fraction rule turned those 20 into variances of up
    # to 97 per cent. Cells that cannot be settled keep the majority reading.
    _written = pd.to_numeric(panel["fy_variance_pct_as_written"], errors="coerce")
    _derived = panel["fy_variance_pct_derived"]
    _ambiguous = panel["fy_variance_pct_ambiguous"].fillna(False).astype(bool)

    def _matches(candidate: pd.Series) -> pd.Series:
        tolerance = 0.05 + 0.02 * _derived.abs()
        signed = (candidate - _derived).abs() <= tolerance
        # The two NISTA files publish the magnitude rather than the signed value.
        unsigned = (candidate - _derived.abs()).abs() <= tolerance
        return (signed | unsigned).fillna(False)

    _settleable = _ambiguous & _written.notna() & _derived.notna()
    _as_percent_fits = _settleable & _matches(_written)
    _as_fraction_fits = _settleable & _matches(_written * 100.0)
    _keep_as_written = _as_percent_fits & ~_as_fraction_fits
    panel.loc[_keep_as_written, "fy_variance_pct"] = _written[_keep_as_written]
    panel["fy_variance_pct_reading"] = np.where(
        ~_ambiguous,
        "as published",
        np.where(
            _keep_as_written,
            "as published (settled against the row's baseline and forecast)",
            np.where(
                _as_fraction_fits,
                "fraction scaled to a percentage (settled against the row)",
                "fraction scaled to a percentage (unsettled, majority reading)",
            ),
        ),
    )

    # The published DCA. Verified across all 2,496 project-years: the IPA and
    # SRO columns are NEVER both populated. Before the March 2022 snapshot only
    # the IPA column exists; from March 2022 exactly one of the two carries the
    # rating and the departmental commentary names which ("(IPA rating)" or
    # "(SRO rating)"). The published DCA is therefore the coalesce of the two,
    # and who made it is recorded as a covariate rather than thrown away.
    ratings = set(FIVE_POINT) | set(THREE_POINT)
    ipa_ok = panel["dca_ipa"].isin(ratings)
    sro_ok = panel["dca_sro"].isin(ratings)
    panel["dca_published"] = np.where(
        ipa_ok, panel["dca_ipa"], np.where(sro_ok, panel["dca_sro"], panel["dca_ipa"])
    )
    # Which body made the call. The column is headed "IPA Delivery Confidence
    # Assessment" throughout, but the IPA ceased to exist on 1 April 2025: the
    # 2024-25 publication body states the data was reported to the IPA on 31
    # March 2025, and the 2025-26 body states it was reported to NISTA on 31
    # March 2026. The March 2026 assessments are NISTA's.
    _authority = np.where(
        panel["snapshot_date"].dt.date >= dt.date(2026, 3, 31), "NISTA", "IPA"
    )
    panel["dca_assessor"] = np.where(
        ipa_ok, _authority, np.where(sro_ok, "SRO", "none")
    )
    panel["dca_published_rank"] = [
        rank(r, s) for r, s in zip(panel["dca_published"], panel["scale"])
    ]
    panel["dca_published_rank_norm"] = [
        normalised_rank(r, s) for r, s in zip(panel["dca_published"], panel["scale"])
    ]

    # Department: prefer the value published in the file, fall back to the slug.
    panel["department"] = panel["department"].fillna(
        panel["source_department_slug"].str.upper()
    )
    panel["department_norm"] = panel["department"].map(normalise_department)

    panel, fuzzy_merges, name_collisions, rename_merges = assign_project_keys(panel)

    # A project run jointly by two departments is published in both departments'
    # files, producing a duplicate row for the same snapshot (for example
    # "NO2 Reduction", DEFRA_0014_2021-Q4, in both the DEFRA and DFT March 2021
    # files). Those copies are dropped. Any other same-key, same-snapshot pair
    # would be two different projects that the linker wrongly merged, so the
    # published values are compared first and a pair that disagrees is kept as
    # two rows with distinguished keys rather than silently halved.
    dup_mask = panel.duplicated(subset=["project_key", "snapshot_date"], keep=False)
    duplicates = panel[dup_mask].sort_values(
        ["project_key", "snapshot_date"]
    ).copy()
    compare = ["dca_published", "wlc_baseline_gbp_m", "end_date", "project_name"]
    keep_rows = []
    for (key, snap), block in panel[dup_mask].groupby(
        ["project_key", "snapshot_date"]
    ):
        # pandas 3 keeps a missing value missing under `.astype(str)` rather
        # than rendering it "nan" (verified against pandas 3.0.5 on
        # 2026-09-15), so the missing values are filled explicitly. Two rows
        # that are both blank in a column count as agreeing on it.
        signature = (
            block[compare]
            .apply(lambda s: s.map(lambda v: "" if pd.isna(v) else str(v)))
            .agg("|".join, axis=1)
        )
        if signature.nunique() == 1:
            keep_rows.append(block.index[0])
            continue
        # Genuinely different rows sharing a key: keep them all, suffixing the
        # key so each remains its own project.
        for i, idx in enumerate(block.index):
            panel.loc[idx, "project_key"] = f"{key}#{i + 1}"
            panel.loc[idx, "project_key_source"] = (
                f"{panel.loc[idx, 'project_key_source']} (split: same key, "
                "different published values in one snapshot)"
            )
            keep_rows.append(idx)
    duplicates["resolution"] = duplicates.index.map(
        lambda i: "kept" if i in set(keep_rows) else "dropped as a copy"
    )
    drop_idx = set(panel[dup_mask].index) - set(keep_rows)
    panel = panel.drop(index=list(drop_idx))

    ordered = [
        c for c in CANONICAL_COLUMNS if c in panel.columns
    ] + [
        c for c in panel.columns if c not in CANONICAL_COLUMNS
    ]
    panel = panel[ordered].sort_values(
        ["snapshot_date", "department_norm", "project_name"]
    ).reset_index(drop=True)

    return (panel, pd.DataFrame(unmapped), pd.DataFrame(build_log), fuzzy_merges,
            duplicates, name_collisions, rename_merges)


# Published category spellings that name the same category. Every mapping below
# was read off the panel's own crosstab of category by snapshot on 2026-09-16:
# "ICT" runs from September 2016 to March 2025 and stops, and "Information and
# Communications Technology (ICT)" appears only in March 2026.
CATEGORY_ALIASES = {
    "information and communications technology (ict)": "ICT",
    "ict": "ICT",
    "government transformation and service delivery":
        "Government Transformation and Service Delivery",
    "infrastructure and construction": "Infrastructure and Construction",
    "military capability": "Military Capability",
}


def canonical_category(value: object) -> object:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    key = re.sub(r"\s+", " ", str(value)).strip().lower()
    if key in ("", "nan", "none"):
        return None
    return CATEGORY_ALIASES.get(key, str(value).strip())


DEPARTMENT_ALIASES = {
    # Machinery-of-government renames. Grouped so a project that moves between
    # a predecessor and successor department still links across years. Each pair
    # is a documented UK department rename or split, not a guess:
    "BIS": "BEIS/DBT", "BEIS": "BEIS/DBT", "DBT": "BEIS/DBT",
    "DECC": "DECC/DESNZ", "DESNZ": "DECC/DESNZ",
    "DCLG": "DCLG/MHCLG", "MHCLG": "DCLG/MHCLG", "DLUHC": "DCLG/MHCLG",
    "DH": "DH/DHSC", "DHSC": "DH/DHSC", "DOH": "DH/DHSC",
    "DFID": "FCO/FCDO", "FCO": "FCO/FCDO", "FCDO": "FCO/FCDO",
    "HMRC": "HMRC", "HM REVENUE & CUSTOMS": "HMRC",
    "HMT": "HMT", "HM TREASURY": "HMT",
    "MOD": "MOD", "MINISTRY OF DEFENCE": "MOD",
    "MOJ": "MOJ", "MINISTRY OF JUSTICE": "MOJ",
    "DFT": "DFT", "DFE": "DFE", "DWP": "DWP", "HO": "HO", "CO": "CO",
    "DEFRA": "DEFRA", "DCMS": "DCMS", "DSIT": "DSIT", "ONS": "ONS",
    "NCA": "NCA", "HMLR": "HMLR", "VOA": "VOA",
}


def normalise_department(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "UNKNOWN"
    key = re.sub(r"\s+", " ", str(value)).strip().upper()
    key = key.replace("&AMP;", "&")
    if key in DEPARTMENT_ALIASES:
        return DEPARTMENT_ALIASES[key]
    # Departmental suffixes seen in the consolidated tables, e.g.
    # "MOD Transformation", "DH Capital".
    head = key.split()[0] if key.split() else key
    return DEPARTMENT_ALIASES.get(head, key)


def main() -> int:
    (panel, unmapped, build_log, fuzzy_merges, duplicates, name_collisions,
     rename_merges) = build()
    panel.to_csv(PANEL_PATH, index=False)
    unmapped.to_csv(UNMAPPED_PATH, index=False)
    build_log.to_csv(BUILD_LOG_PATH, index=False)
    fuzzy_merges.to_csv(FUZZY_MERGES_PATH, index=False)
    duplicates.to_csv(DUPLICATES_PATH, index=False)
    name_collisions.to_csv(RESULTS_DIR / "identity_name_collisions.csv", index=False)
    rename_merges.to_csv(RESULTS_DIR / "identity_rename_merges.csv", index=False)

    print(f"panel: {len(panel)} project-years -> {PANEL_PATH}")
    print(f"unmapped headers: {len(unmapped)} -> {UNMAPPED_PATH}")
    print("\nrows per snapshot:")
    print(
        panel.groupby(panel["snapshot_date"].dt.date)
        .agg(
            projects=("project_name", "size"),
            departments=("department_norm", "nunique"),
            with_dca=("dca_ipa_rank", lambda s: int(s.notna().sum())),
            with_wlc=("wlc_baseline_gbp_m", lambda s: int(s.notna().sum())),
            with_end_date=("end_date", lambda s: int(s.notna().sum())),
            with_gmpp_id=("gmpp_id", lambda s: int(s.notna().sum())),
        )
        .to_string()
    )
    print("\nDCA categories (published):")
    print(panel["dca_published"].value_counts().to_string())
    print("\nassessor:")
    print(panel["dca_assessor"].value_counts().to_string())
    print(
        f"\nprojects: {panel['project_key'].nunique()} distinct keys; "
        f"key source: {panel['project_key_source'].value_counts().to_dict()}"
    )
    print(f"name collisions held apart: {len(name_collisions)}")
    if len(name_collisions):
        print(name_collisions[["link_group", "names", "snapshots"]].to_string())
    print(f"renames linked by start date and whole-life cost: {len(rename_merges)}")
    print(f"fuzzy merges: {len(fuzzy_merges)}; duplicate rows dropped: "
          f"{len(duplicates) - duplicates['project_key'].nunique() if len(duplicates) else 0}")
    print("\nproject-years per project:")
    print(panel.groupby("project_key").size().value_counts().sort_index().to_string())
    if len(unmapped):
        print("\nunmapped headers by norm_header:")
        print(
            unmapped.groupby("norm_header")
            .agg(n=("local_path", "nunique"), non_null=("non_null", "sum"))
            .sort_values("non_null", ascending=False)
            .head(30)
            .to_string()
        )
    errs = build_log[build_log["error"] != ""]
    if len(errs):
        print("\nbuild errors:")
        print(errs[["local_path", "error"]].to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
