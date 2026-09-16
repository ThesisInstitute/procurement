"""Independent cross-check of the bulk-download extract.

Streams the monthly full archive zip for one fiscal year without extracting it,
counts rows with award_type_code == 'D', and writes a small parquet of the
overlapping columns so the two sources can be compared row for row.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from columns import KEEP  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, required=True)
    ap.add_argument("--fy", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--log", type=Path, required=True)
    a = ap.parse_args()

    a.log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(a.log, "a")

    def log(msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] xcheck {msg}"
        print(line, flush=True)
        handle.write(line + "\n")
        handle.flush()

    total = 0
    kept_frames = []
    t0 = time.time()
    with zipfile.ZipFile(a.zip) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        log(f"FY{a.fy} members {len(members)}")
        for m in members:
            with zf.open(m) as fh:
                raw = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
                for chunk in pd.read_csv(raw, dtype=str, chunksize=200_000,
                                         low_memory=False):
                    total += len(chunk)
                    d = chunk[chunk["award_type_code"] == "D"]
                    if len(d):
                        kept_frames.append(
                            d[[c for c in KEEP if c in d.columns]].copy()
                        )
                    if total % 2_000_000 < 200_000:
                        log(f"FY{a.fy} scanned {total} rows "
                            f"{time.time()-t0:.0f}s")
    df = (pd.concat(kept_frames, ignore_index=True)
          if kept_frames else pd.DataFrame(columns=KEEP))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(a.out, index=False, compression="zstd")
    summary = {
        "fiscal_year": a.fy,
        "archive_rows_all_types": int(total),
        "archive_rows_type_D": int(len(df)),
        "archive_unique_awards_type_D": int(
            df["contract_award_unique_key"].nunique()) if len(df) else 0,
        "columns_present": [c for c in KEEP if c in df.columns],
        "columns_absent": [c for c in KEEP if c not in df.columns],
        "seconds": round(time.time() - t0, 1),
    }
    log(json.dumps(summary))
    (a.out.parent / f"archive_crosscheck_FY{a.fy}.json").write_text(
        json.dumps(summary, indent=1))
    handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
