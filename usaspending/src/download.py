"""Robust parallel range downloader for the USAspending award data archive.

files.usaspending.gov frequently returns empty replies (curl error 52) on this
path, so every chunk is retried independently and the file is assembled from
byte ranges. Observed 2026-09-15: HEAD works, ranged GET returns 206, aggregate
throughput saturates near 2.5 MB/s regardless of stream count.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import time
from pathlib import Path

import requests

ARCHIVE = "https://files.usaspending.gov/award_data_archive/{name}"
LIST_URL = "https://api.usaspending.gov/api/v2/bulk_download/list_monthly_files/"
UA = {"User-Agent": "thesis-institute-procurement-backtest/1.0"}
CHUNK = 16 * 1024 * 1024


def archive_url(fiscal_year: int, session: requests.Session) -> str:
    r = session.post(
        LIST_URL,
        json={"agency": "all", "fiscal_year": fiscal_year, "type": "contracts"},
        timeout=120,
    )
    r.raise_for_status()
    files = r.json()["monthly_files"]
    if not files:
        raise RuntimeError(f"no monthly archive for FY{fiscal_year}")
    return files[0]["url"]


def content_length(url: str, session: requests.Session) -> int:
    for _ in range(10):
        try:
            r = session.head(url, timeout=60, allow_redirects=True)
            if r.status_code == 200 and "Content-Length" in r.headers:
                return int(r.headers["Content-Length"])
        except requests.RequestException:
            pass
        time.sleep(3)
    raise RuntimeError(f"could not size {url}")


def fetch_range(url: str, start: int, end: int, dest: Path, attempts: int = 40) -> int:
    """Download [start, end] inclusive into dest at offset start. Returns bytes."""
    want = end - start + 1
    for attempt in range(attempts):
        try:
            with requests.get(
                url,
                headers={**UA, "Range": f"bytes={start}-{end}"},
                stream=True,
                timeout=(30, 180),
            ) as r:
                if r.status_code not in (200, 206):
                    raise requests.RequestException(f"status {r.status_code}")
                buf = bytearray()
                for block in r.iter_content(1024 * 256):
                    buf.extend(block)
                if len(buf) != want:
                    raise requests.RequestException(
                        f"short read {len(buf)} != {want}"
                    )
            with open(dest, "r+b") as fh:
                fh.seek(start)
                fh.write(buf)
            return want
        except (requests.RequestException, OSError) as exc:
            if attempt == attempts - 1:
                raise RuntimeError(f"range {start}-{end} failed: {exc}") from exc
            time.sleep(min(2 * (attempt + 1), 20))
    raise AssertionError("unreachable")


def download(fiscal_year: int, out: Path, workers: int, log) -> Path:
    session = requests.Session()
    session.headers.update(UA)
    url = archive_url(fiscal_year, session)
    total = content_length(url, session)
    log(f"FY{fiscal_year} url={url} size={total}")

    out.parent.mkdir(parents=True, exist_ok=True)
    # The file is assembled under a .part name and renamed only after every range
    # has been written and counted. Ranges are fetched concurrently, so the file
    # has to be pre-sized to its full length before any of them can seek into it,
    # which means its size says nothing about how much of it is real. Writing
    # straight to `out` therefore made both checks below vacuous: a download
    # killed halfway left a full-length file of mostly zeros, the "already
    # complete" test passed on the next run, and the final size check could never
    # fail. `out` now exists only when it is genuinely finished.
    part = out.with_name(out.name + ".part")
    if out.exists() and out.stat().st_size == total:
        log(f"FY{fiscal_year} already complete at {out}")
        return out
    with open(part, "wb") as fh:
        fh.truncate(total)

    ranges = [(s, min(s + CHUNK - 1, total - 1)) for s in range(0, total, CHUNK)]
    done_bytes = 0
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_range, url, s, e, part): (s, e) for s, e in ranges}
        for i, fut in enumerate(cf.as_completed(futures), 1):
            done_bytes += fut.result()
            if i % 5 == 0 or i == len(ranges):
                el = time.time() - t0
                log(
                    f"FY{fiscal_year} {i}/{len(ranges)} chunks "
                    f"{done_bytes/1e6:.0f}/{total/1e6:.0f} MB "
                    f"{done_bytes/1e6/max(el,1e-6):.2f} MB/s "
                    f"elapsed {el:.0f}s"
                )
    # done_bytes is the sum of the lengths each range actually delivered, and a
    # range that failed raised out of fut.result() above, so this is a real check
    # rather than a restatement of the pre-sized length.
    if done_bytes != total:
        raise RuntimeError(
            f"wrote {done_bytes} bytes across ranges but the file is {total}")
    got = part.stat().st_size
    if got != total:
        raise RuntimeError(f"size mismatch {got} != {total}")
    part.replace(out)
    log(f"FY{fiscal_year} download complete in {time.time()-t0:.0f}s -> {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fy", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--log", type=Path, default=None)
    a = ap.parse_args()

    handle = open(a.log, "a") if a.log else None

    def log(msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}"
        print(line, flush=True)
        if handle:
            handle.write(line + "\n")
            handle.flush()

    try:
        download(a.fy, a.out, a.workers, log)
    finally:
        if handle:
            handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
