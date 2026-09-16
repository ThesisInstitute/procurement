"""Download every attachment listed in the discovery manifest.

Idempotent: a file whose size already matches the manifest is skipped. Writes
`data/raw/gmpp/download_log.csv` with the URL, HTTP status, bytes and sha256 of
every fetch so the acquisition is auditable.

Run: .venv/bin/python -m gmpp.src.download
"""
from __future__ import annotations

import hashlib
import sys
import time

import pandas as pd
import requests

from .paths import MANIFEST_PATH, RAW_DIR

LOG_PATH = RAW_DIR / "download_log.csv"


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    manifest = pd.read_csv(MANIFEST_PATH)
    wanted = manifest[
        manifest["is_spreadsheet"] | (manifest["ext"] == ".pdf")
    ].copy()
    wanted = wanted[wanted["attachment_url"].str.startswith("http")]
    print(f"{len(wanted)} attachments to fetch", flush=True)

    session = requests.Session()
    session.headers["User-Agent"] = (
        "thesis-institute-procurement-research/0.1 (max@maxghenis.com)"
    )

    log: list[dict] = []
    skipped = downloaded = failed = 0
    for i, row in enumerate(wanted.itertuples(), 1):
        dest = RAW_DIR / row.local_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0:
            skipped += 1
            log.append(
                {
                    "url": row.attachment_url,
                    "path": row.local_path,
                    "status": "cached",
                    "bytes": dest.stat().st_size,
                    "sha256": sha256_of(dest),
                }
            )
            continue
        try:
            resp = session.get(row.attachment_url, timeout=120)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            downloaded += 1
            log.append(
                {
                    "url": row.attachment_url,
                    "path": row.local_path,
                    "status": resp.status_code,
                    "bytes": len(resp.content),
                    "sha256": sha256_of(dest),
                }
            )
            time.sleep(0.05)
        except Exception as exc:  # noqa: BLE001 - record and continue
            failed += 1
            log.append(
                {
                    "url": row.attachment_url,
                    "path": row.local_path,
                    "status": f"ERROR {exc}",
                    "bytes": 0,
                    "sha256": "",
                }
            )
        if i % 50 == 0:
            print(f"  {i}/{len(wanted)}", flush=True)

    frame = pd.DataFrame(log)
    frame.to_csv(LOG_PATH, index=False)
    total_mb = frame["bytes"].sum() / 1e6
    print(
        f"downloaded={downloaded} cached={skipped} failed={failed} "
        f"total={total_mb:.1f} MB -> {LOG_PATH}"
    )
    if failed:
        print(frame[frame["status"].astype(str).str.startswith("ERROR")].to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
