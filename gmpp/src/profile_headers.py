"""Read every downloaded GMPP file and inventory its headers.

Outputs (under `data/raw/gmpp/`):
  file_profile.csv    one row per file: layout, shape, chosen sheet, encoding
  header_inventory.csv one row per (normalised header, file) pair
  header_summary.csv  distinct normalised headers with file counts and years

This is the evidence base for the canonicalisation map in `gmpp.src.schema`.

Run: .venv/bin/python -m gmpp.src.profile_headers
"""
from __future__ import annotations

import re
import sys
import traceback

import pandas as pd

from .orientation import normalise
from .paths import MANIFEST_PATH, RAW_DIR
from .readers import _excel_sheets, read_raw


def _all_sheets(path) -> dict:
    """Every sheet of a workbook, or the single frame of a CSV."""
    if str(path).lower().endswith(".csv"):
        return {"__csv__": read_raw(path).raw}
    return _excel_sheets(path)

PROFILE_PATH = RAW_DIR / "file_profile.csv"
INVENTORY_PATH = RAW_DIR / "header_inventory.csv"
SUMMARY_PATH = RAW_DIR / "header_summary.csv"
ALL_SHEETS_PATH = RAW_DIR / "header_all_sheets.csv"
PANEL_HEADERS_PATH = RAW_DIR / "header_panel_files.csv"


def norm_header(text: str) -> str:
    """Collapse a raw header to a comparable key.

    Parenthesised explanatory text is dropped: from 2014 the headers embed the
    full DCA definition in brackets and the wording of that definition changes
    between years even when the field does not.
    """
    t = str(text)
    t = t.replace(" ", " ").replace("’", "'").replace("â€™", "'")
    t = re.sub(r"\(.*?\)", " ", t, flags=re.S)  # drop bracketed definitions
    t = re.sub(r"\(.*$", " ", t, flags=re.S)  # drop an unclosed trailing bracket
    t = t.replace("£", "gbp").replace("Â£", "gbp")
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def main() -> int:
    manifest = pd.read_csv(MANIFEST_PATH)
    files = manifest[manifest["is_spreadsheet"]].copy()

    profile_rows: list[dict] = []
    inventory_rows: list[dict] = []
    all_sheet_rows: list[dict] = []
    for i, row in enumerate(files.itertuples(), 1):
        path = RAW_DIR / row.local_path
        rec = {
            "publication_slug": row.publication_slug,
            "publication_year": row.publication_year,
            "department_slug": row.department_slug,
            "ext": row.ext,
            "local_path": row.local_path,
            "ok": False,
            "layout": None,
            "n_rows": None,
            "n_cols": None,
            "sheet": None,
            "encoding": None,
            "notes": "",
            "error": "",
        }
        if not path.exists():
            rec["error"] = "missing file"
            profile_rows.append(rec)
            continue
        try:
            result = read_raw(path)
            wide, layout = normalise(result.raw)
            rec.update(
                ok=True,
                layout=layout,
                n_rows=int(wide.shape[0]),
                n_cols=int(wide.shape[1]),
                sheet=result.sheet,
                encoding=result.encoding,
                notes="; ".join(result.notes),
            )
            for pos, col in enumerate(wide.columns):
                inventory_rows.append(
                    {
                        "publication_slug": row.publication_slug,
                        "publication_year": row.publication_year,
                        "department_slug": row.department_slug,
                        "ext": row.ext,
                        "local_path": row.local_path,
                        "position": pos,
                        "raw_header": str(col),
                        "norm_header": norm_header(col),
                        "non_null": int(wide[col].notna().sum()),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - record and continue
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["notes"] = traceback.format_exc(limit=1).replace("\n", " ")

        # Every sheet, not only the one the pipeline selects. The map in
        # gmpp.src.schema has to describe headers the corpus really carries,
        # and some of those live in a sheet the selector passes over: the
        # analytical `SourceTable` back-series, which `gmpp.src.crosscheck`
        # reads by name. Without this, a key serving that sheet looks dead.
        try:
            for sheet_name, sheet_raw in _all_sheets(path).items():
                try:
                    sheet_wide, _ = normalise(sheet_raw)
                except Exception:  # noqa: BLE001 - a sheet that will not shape
                    continue
                for col in sheet_wide.columns:
                    all_sheet_rows.append(
                        {
                            "local_path": row.local_path,
                            "sheet": sheet_name,
                            "raw_header": str(col),
                            "norm_header": norm_header(col),
                        }
                    )
        except Exception:  # noqa: BLE001 - unreadable file, already recorded
            pass

        profile_rows.append(rec)
        if i % 100 == 0:
            print(f"  {i}/{len(files)}", flush=True)

    profile = pd.DataFrame(profile_rows)
    inventory = pd.DataFrame(inventory_rows)
    profile.to_csv(PROFILE_PATH, index=False)
    inventory.to_csv(INVENTORY_PATH, index=False)

    summary = (
        inventory.groupby("norm_header")
        .agg(
            n_files=("local_path", "nunique"),
            n_publications=("publication_slug", "nunique"),
            years=("publication_year", lambda s: ",".join(map(str, sorted(set(s))))),
            example_raw=("raw_header", "first"),
        )
        .sort_values("n_files", ascending=False)
        .reset_index()
    )
    summary.to_csv(SUMMARY_PATH, index=False)

    # Headers across EVERY sheet of every file, the universe the schema map is
    # checked against, and the subset the panel actually reads, which is what
    # the report quotes.
    all_sheets = pd.DataFrame(all_sheet_rows)
    if len(all_sheets):
        (
            all_sheets.groupby("norm_header")
            .agg(
                n_files=("local_path", "nunique"),
                n_sheets=("sheet", "nunique"),
                example_raw=("raw_header", "first"),
            )
            .sort_values("n_files", ascending=False)
            .reset_index()
            .to_csv(ALL_SHEETS_PATH, index=False)
        )

    from .panel import _pick_files

    panel_paths = set(_pick_files(manifest)["local_path"])
    panel_headers = inventory[inventory["local_path"].isin(panel_paths)]
    (
        panel_headers.groupby("norm_header")
        .agg(
            n_files=("local_path", "nunique"),
            years=("publication_year", lambda s: ",".join(map(str, sorted(set(s))))),
            example_raw=("raw_header", "first"),
        )
        .sort_values("n_files", ascending=False)
        .reset_index()
        .to_csv(PANEL_HEADERS_PATH, index=False)
    )
    print(
        f"{panel_headers['norm_header'].nunique()} distinct headers in the "
        f"{len(panel_paths)} files the panel reads -> {PANEL_HEADERS_PATH}"
    )

    print(f"profiled {len(profile)} files, ok={int(profile['ok'].sum())}")
    print(profile.groupby(["ext", "ok"]).size().to_string())
    print("\nlayout by publication year:")
    print(
        pd.crosstab(profile["publication_year"], profile["layout"]).to_string()
    )
    print(f"\n{len(summary)} distinct normalised headers -> {SUMMARY_PATH}")
    if (~profile["ok"]).any():
        print("\nfailures:")
        print(
            profile[~profile["ok"]][["local_path", "error"]].head(40).to_string()
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
