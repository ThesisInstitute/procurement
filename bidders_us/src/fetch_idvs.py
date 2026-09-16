"""Fetch indefinite-delivery vehicle (IDV) records, FY2005 to FY2026, by fiscal year.

Why. A delivery order's parent_award_id_piid names the holder's own contract:
measured on the order panel, 103,491 of 104,993 parent PIIDs have exactly one
recipient. A multiple-award vehicle is therefore a SET of sibling contracts,
one per holder, awarded from one solicitation, and the set is only visible on
the IDV records themselves, which carry the solicitation identifier and the
multiple-or-single-award flag. This script fetches those records through the
same bulk-download API and machinery as usaspending/src/bulk_fetch.py
(imported, not copied: start_job is re-implemented here with the IDV award
types and a lean column list, and the rest is reused), one job per fiscal
year, polled at 30 s with a 60 minute cap, zip converted to parquet and
deleted.

IDV rows have no award_type_code (that field is for orders and contracts);
they carry idv_type_code instead, and every row of the zip is kept.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd

from bidders_us.src.common import RAW, RESULTS, USA_SRC, make_logger

sys.path.insert(0, str(USA_SRC))
import bulk_fetch as BF  # noqa: E402

IDV_TYPES = ["IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E"]
COLUMNS = [
    "contract_award_unique_key", "award_id_piid", "modification_number", "transaction_number",
    "action_date", "action_type_code", "award_or_idv_flag", "idv_type_code", "idv_type",
    "multiple_or_single_award_idv_code", "multiple_or_single_award_idv", "type_of_idc_code",
    "parent_award_id_piid", "parent_award_agency_id",
    "awarding_agency_code", "awarding_sub_agency_code", "awarding_office_code",
    "recipient_uei", "recipient_name", "recipient_parent_uei", "recipient_parent_name",
    "solicitation_identifier", "extent_competed_code", "number_of_offers_received",
    "type_of_set_aside_code", "naics_code", "product_or_service_code",
    "period_of_performance_start_date", "ordering_period_end_date",
    "base_and_all_options_value", "federal_action_obligation", "last_modified_date",
]
DATES = ["action_date", "period_of_performance_start_date", "ordering_period_end_date", "last_modified_date"]
NUMERIC = ["number_of_offers_received", "base_and_all_options_value", "federal_action_obligation"]


def start_job(fy: int, window, log) -> dict:
    start, end = window
    body = {
        "filters": {
            "prime_award_types": IDV_TYPES,
            "date_type": "action_date",
            "date_range": {"start_date": start, "end_date": end},
            "agencies": [{"type": "awarding", "tier": "toptier", "name": "All"}],
        },
        "columns": COLUMNS,
        "file_format": "csv",
    }
    resp = BF.post_with_retry(f"{BF.API}/bulk_download/awards/", body, log)
    log(f"FY{fy} IDV {start}..{end} job {resp['file_name']}")
    return resp


def zip_to_frame(zip_path: Path, fy: int, log) -> tuple[pd.DataFrame, int, list]:
    frames, header = [], None
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        log(f"FY{fy} IDV zip members {members}")
        for m in members:
            with zf.open(m) as fh:
                raw = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
                for chunk in pd.read_csv(raw, dtype=str, chunksize=250_000, low_memory=False):
                    if header is None:
                        header = list(chunk.columns)
                    frames.append(chunk[[c for c in COLUMNS if c in chunk.columns]])
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    return df, int(len(df)), header


def run_year(fy: int, zdir: Path, pdir: Path, log, splits: int = 1) -> dict:
    out = pdir / f"idv_FY{fy}.parquet"
    if out.exists():
        df = pd.read_parquet(out, columns=["contract_award_unique_key"])
        log(f"FY{fy} IDV parquet already present, reusing: rows={len(df)}")
        return {"fiscal_year": fy, "reused_existing_parquet": True, "rows": int(len(df)),
                "unique_idvs": int(df["contract_award_unique_key"].nunique()),
                "parquet_bytes": out.stat().st_size}
    parts, header = [], None
    for i, window in enumerate(BF.fy_windows(fy, splits)):
        job = start_job(fy, window, log)
        status = BF.poll_job(fy, job["status_url"], log)
        zp = zdir / f"idv_FY{fy}_{i}.zip"
        BF.download_file(job["file_url"], zp, log)
        part, n_raw, hdr = zip_to_frame(zp, fy, log)
        reported = status.get("total_rows")
        if reported is not None and int(reported) != n_raw:
            raise RuntimeError(f"FY{fy} IDV window {window}: service reported {reported} rows, zip parsed to {n_raw}")
        parts.append(part)
        header = header or hdr
        zp.unlink()
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLUMNS)
    df = df.drop_duplicates(subset=["contract_award_unique_key", "modification_number",
                                    "transaction_number", "action_date"])
    for c in NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    for c in DATES:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce", format="mixed")
    for c in df.columns:
        if c not in NUMERIC and c not in DATES:
            df[c] = df[c].astype("string")
    df["source_fiscal_year"] = fy
    pdir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False, compression="zstd")
    info = {"fiscal_year": fy, "rows": int(len(df)),
            "unique_idvs": int(df["contract_award_unique_key"].nunique()),
            "parquet_bytes": out.stat().st_size,
            "columns_missing_from_delivery": [c for c in COLUMNS if header and c not in header],
            "header": header}
    log(f"FY{fy} IDV parquet rows={info['rows']} idvs={info['unique_idvs']} "
        f"missing={info['columns_missing_from_delivery']}")
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fy-start", type=int, default=2005)
    ap.add_argument("--fy-end", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--splits", type=int, default=1)
    ap.add_argument("--zdir", type=Path, default=RAW / "zips")
    ap.add_argument("--pdir", type=Path, default=RAW / "idv")
    a = ap.parse_args()
    log = make_logger("fetch_idvs")
    t0 = time.time()
    a.zdir.mkdir(parents=True, exist_ok=True)
    years = list(range(a.fy_start, a.fy_end + 1))
    results = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_year, fy, a.zdir, a.pdir, log, a.splits): fy for fy in years}
        for fut in cf.as_completed(futs):
            fy = futs[fut]
            try:
                results.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                log(f"FY{fy} IDV ERROR {exc}")
                results.append({"fiscal_year": fy, "error": str(exc)})
    manifest_path = RESULTS / "idv_fetch_manifest.json"
    merged = {}
    if manifest_path.exists():
        merged = {int(r["fiscal_year"]): r for r in json.loads(manifest_path.read_text())}
    for r in results:
        fy = int(r["fiscal_year"])
        if "error" in r and fy in merged and "rows" in merged[fy]:
            merged[fy] = {**merged[fy], "last_run_error": r["error"]}
        else:
            merged[fy] = r
    manifest_path.write_text(json.dumps([merged[k] for k in sorted(merged)], indent=1))
    failed = sorted(int(r["fiscal_year"]) for r in results if "error" in r)
    log(f"done in {time.time()-t0:.0f}s; failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
