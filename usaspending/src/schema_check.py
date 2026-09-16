"""Check the realised parquet schema against the column list that was requested.

columns.py promises a mapping between the USAspending download column names
requested from the API and the columns actually present in the extract. This
module produces that mapping by reading the parquet schema of every fiscal year,
without loading any data, and records any requested column that is absent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from columns import DATES, KEEP, NUMERIC  # noqa: E402


def check(pdir: Path) -> dict:
    files = sorted(pdir.glob("contracts_D_FY*.parquet"))
    if not files:
        raise FileNotFoundError(f"no parquet under {pdir}")
    per_year, all_present = {}, None
    for f in files:
        schema = pq.read_schema(f)
        names = list(schema.names)
        present = [c for c in KEEP if c in names]
        per_year[f.stem.replace("contracts_D_FY", "")] = {
            "columns_in_file": len(names),
            "requested_columns_present": len(present),
            "requested_columns_absent": [c for c in KEEP if c not in names],
            "extra_columns_not_requested": [c for c in names if c not in KEEP],
        }
        all_present = set(present) if all_present is None else (all_present & set(present))
    schema = pq.read_schema(files[-1])
    types = {n: str(t) for n, t in zip(schema.names, schema.types)}
    return {
        "parquet_files": len(files),
        "columns_requested": len(KEEP),
        "columns_present_in_every_year": sorted(all_present or []),
        "columns_absent_from_some_year": sorted(set(KEEP) - (all_present or set())),
        "per_year": per_year,
        "realised_dtypes": types,
        "declared_numeric": NUMERIC,
        "declared_dates": DATES,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdir", type=Path, default=Path("data/raw/usaspending/parquet"))
    ap.add_argument("--out", type=Path,
                    default=Path("usaspending/results/column_mapping.json"))
    a = ap.parse_args()
    info = check(a.pdir)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(info, indent=1))
    print(f"{info['parquet_files']} files; "
          f"{len(info['columns_present_in_every_year'])}/{info['columns_requested']} "
          f"requested columns present in every year; "
          f"absent: {info['columns_absent_from_some_year']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
