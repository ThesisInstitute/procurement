"""Fetch definitive-contract (award_type_code D) transactions by fiscal year.

Primary path: the USAspending Custom Award Data Download API
(POST /api/v2/bulk_download/awards/), which accepts prime_award_types ["D"] and
an explicit `columns` list, so the server does the type filter and the column
projection before the bytes are sent. Verified 2026-09-15: the all-agencies
form is {"type": "awarding", "tier": "toptier", "name": "All"} and the response
is a zip of "*_Contracts_PrimeTransactions_*.csv" files, one row per contract
action.

Each fiscal year becomes one job. Jobs are polled at 30 s with a 60 min cap.
The zip is converted to parquet and deleted.
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
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from columns import DATES, KEEP, NUMERIC  # noqa: E402

API = "https://api.usaspending.gov/api/v2"
UA = {"User-Agent": "thesis-institute-procurement-backtest/1.0"}
POLL_SECONDS = 30
POLL_CAP_SECONDS = 60 * 60


def fy_window(fy: int) -> tuple[str, str]:
    """Federal fiscal year FY ends 30 September of FY."""
    return f"{fy - 1}-10-01", f"{fy}-09-30"


def post_with_retry(url: str, body: dict, log, attempts: int = 12) -> dict:
    for attempt in range(attempts):
        try:
            r = requests.post(url, json=body, headers=UA, timeout=180)
            if r.status_code == 200:
                return r.json()
            log(f"POST {url} -> {r.status_code} {r.text[:300]}")
        except requests.RequestException as exc:
            log(f"POST {url} raised {exc}")
        time.sleep(min(5 * (attempt + 1), 60))
    raise RuntimeError(f"POST {url} failed after {attempts} attempts")


def get_with_retry(url: str, log, attempts: int = 12) -> dict:
    for attempt in range(attempts):
        try:
            r = requests.get(url, headers=UA, timeout=180)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException as exc:
            log(f"GET {url} raised {exc}")
        time.sleep(min(5 * (attempt + 1), 60))
    raise RuntimeError(f"GET {url} failed after {attempts} attempts")


def fy_windows(fy: int, splits: int) -> list[tuple[str, str]]:
    """Split the fiscal year into `splits` contiguous action_date windows.

    The API keys a job on the request body, so a retry of an identical request
    returns the same job, including a job that already failed. Splitting the year
    changes the body and therefore forces a fresh job, and it also cuts the size
    of any single server-side query.
    """
    start, end = fy_window(fy)
    if splits <= 1:
        return [(start, end)]
    edges = pd.date_range(pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1),
                          periods=splits + 1).normalize()
    out = []
    for i in range(splits):
        a = edges[i]
        b = edges[i + 1] - pd.Timedelta(days=1)
        out.append((a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")))
    return out


def start_job(fy: int, window: tuple[str, str], log) -> dict:
    start, end = window
    body = {
        "filters": {
            "prime_award_types": ["D"],
            "date_type": "action_date",
            "date_range": {"start_date": start, "end_date": end},
            "agencies": [{"type": "awarding", "tier": "toptier", "name": "All"}],
        },
        "columns": KEEP,
        "file_format": "csv",
    }
    resp = post_with_retry(f"{API}/bulk_download/awards/", body, log)
    log(f"FY{fy} {start}..{end} job {resp['file_name']}")
    return resp


def poll_job(fy: int, status_url: str, log) -> dict:
    t0 = time.time()
    while time.time() - t0 < POLL_CAP_SECONDS:
        st = get_with_retry(status_url, log)
        status = st.get("status")
        if status == "finished":
            log(
                f"FY{fy} finished rows={st.get('total_rows')} "
                f"size={st.get('file_size')} sec={st.get('seconds_elapsed')}"
            )
            return st
        if status == "failed":
            raise RuntimeError(f"FY{fy} job failed: {st}")
        log(f"FY{fy} {status} rows={st.get('total_rows')} t={time.time()-t0:.0f}s")
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"FY{fy} job exceeded {POLL_CAP_SECONDS}s")


def download_file(url: str, dest: Path, log, attempts: int = 30) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(attempts):
        try:
            with requests.get(url, headers=UA, stream=True, timeout=(30, 600)) as r:
                if r.status_code != 200:
                    raise requests.RequestException(f"status {r.status_code}")
                n = 0
                with open(dest, "wb") as fh:
                    for block in r.iter_content(1024 * 1024):
                        fh.write(block)
                        n += len(block)
            log(f"downloaded {dest.name} {n} bytes")
            return dest
        except (requests.RequestException, OSError) as exc:
            log(f"download attempt {attempt} for {url} failed: {exc}")
            time.sleep(min(5 * (attempt + 1), 45))
    raise RuntimeError(f"could not download {url}")


def coerce(df: pd.DataFrame) -> pd.DataFrame:
    for c in NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    for c in DATES:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce", format="mixed")
    for c in df.columns:
        if c not in NUMERIC and c not in DATES:
            df[c] = df[c].astype("string")
    return df


def zip_to_frame(zip_path: Path, fy: int, log) -> tuple[pd.DataFrame, int, list]:
    frames = []
    header_seen = None
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        log(f"FY{fy} zip members {members}")
        for m in members:
            with zf.open(m) as fh:
                raw = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
                for chunk in pd.read_csv(raw, dtype=str, chunksize=250_000,
                                         low_memory=False):
                    if header_seen is None:
                        header_seen = list(chunk.columns)
                    chunk = chunk[[c for c in KEEP if c in chunk.columns]]
                    frames.append(chunk)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=KEEP)
    n_raw = len(df)
    if "award_type_code" in df.columns:
        df = df[df["award_type_code"] == "D"].copy()
    return df, n_raw, header_seen


def run_year(fy: int, zdir: Path, pdir: Path, log, splits: int = 1) -> dict:
    out_parquet = pdir / f"contracts_D_FY{fy}.parquet"
    if out_parquet.exists():
        log(f"FY{fy} parquet already present, skipping")
        return {"fiscal_year": fy, "skipped": True,
                "parquet_bytes": out_parquet.stat().st_size}
    parts, n_raw_total, header_seen = [], 0, None
    for i, window in enumerate(fy_windows(fy, splits)):
        job = start_job(fy, window, log)
        poll_job(fy, job["status_url"], log)
        zp = zdir / f"bulk_FY{fy}_{i}.zip"
        download_file(job["file_url"], zp, log)
        part, n_raw, header = zip_to_frame(zp, fy, log)
        parts.append(part)
        n_raw_total += n_raw
        header_seen = header_seen or header
        zp.unlink()
        log(f"FY{fy} part {i} rows={len(part)} zip deleted")
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=KEEP)
    before = len(df)
    df = df.drop_duplicates(
        subset=["contract_award_unique_key", "modification_number",
                "transaction_number", "action_date"])
    df = coerce(df)
    df["source_fiscal_year"] = fy
    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_parquet, index=False, compression="zstd")
    info = {
        "fiscal_year": fy,
        "windows": splits,
        "rows_in_zip": int(n_raw_total),
        "rows_type_D": int(len(df)),
        "duplicate_rows_removed_across_windows": int(before - len(df)),
        "unique_awards": int(df["contract_award_unique_key"].nunique()) if len(df) else 0,
        "parquet_bytes": out_parquet.stat().st_size,
        "header": header_seen,
    }
    log(f"FY{fy} parquet {out_parquet} rows={info['rows_type_D']} "
        f"bytes={info['parquet_bytes']}")
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fy-start", type=int, default=2010)
    ap.add_argument("--fy-end", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--splits", type=int, default=1,
                    help="split each fiscal year into this many action_date "
                         "windows; use >1 to force a fresh server-side job")
    ap.add_argument("--zdir", type=Path,
                    default=Path("data/raw/usaspending/zips"))
    ap.add_argument("--pdir", type=Path,
                    default=Path("data/raw/usaspending/parquet"))
    ap.add_argument("--log", type=Path,
                    default=Path("usaspending/logs/bulk_fetch.log"))
    ap.add_argument("--manifest", type=Path,
                    default=Path("usaspending/results/fetch_manifest.json"))
    a = ap.parse_args()

    a.log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(a.log, "a")

    def log(msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}"
        print(line, flush=True)
        handle.write(line + "\n")
        handle.flush()

    years = list(range(a.fy_start, a.fy_end + 1))
    results = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_year, fy, a.zdir, a.pdir, log, a.splits): fy
                for fy in years}
        for fut in cf.as_completed(futs):
            fy = futs[fut]
            try:
                results.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                log(f"FY{fy} ERROR {exc}")
                results.append({"fiscal_year": fy, "error": str(exc)})
    results.sort(key=lambda r: r["fiscal_year"])
    a.manifest.parent.mkdir(parents=True, exist_ok=True)
    a.manifest.write_text(json.dumps(results, indent=1))
    log(f"manifest -> {a.manifest}")
    handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
