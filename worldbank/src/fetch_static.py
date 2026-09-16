"""Download the two bulk files this workstream depends on.

Both URLs were verified by fetching them on 2026-09-15.

1. IEG ratings bulk CSV. The Finances One dataset page
   https://financesone.worldbank.org/ieg-world-bank-project-performance-ratings/DS00053
   is a JavaScript application, but the bulk download link is present in the
   server-rendered HTML, so no browser is needed:
     https://financesonefiles.worldbank.org/f-one/DS00053/RS00055/
         IEG_World_Bank_Project_Performance_Ratings.csv
   (The legacy Socrata host finances.worldbank.org now 302-redirects every
   /resource/ and /api/views/ path to the Finances One app, so the SODA API
   documented in older references no longer returns data.)

2. Digital Governance / GovTech Projects workbook, which carries the Bank's ICR
   self-ratings and the original closing date. See src/govtech.py.

Run:  .venv/bin/python -m worldbank.src.fetch_static
"""
from __future__ import annotations

import hashlib

import requests

from .govtech import URL as GOVTECH_URL, XLSX as GOVTECH_XLSX
from .paths import IEG_CSV, IEG_URL, RESULTS

TARGETS = [
    ("ieg_ratings_csv", IEG_URL, IEG_CSV),
    ("govtech_xlsx", GOVTECH_URL, GOVTECH_XLSX),
]


def download(url: str, dest) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "thesis-institute-procurement-research/1.0"
    r = s.get(url, timeout=600)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return {"url": url, "path": str(dest), "bytes": len(r.content),
            "sha256": hashlib.sha256(r.content).hexdigest(),
            "http_status": r.status_code}


def main() -> int:
    import pandas as pd
    rows = []
    for name, url, dest in TARGETS:
        info = download(url, dest)
        info["name"] = name
        rows.append(info)
        print(f"{name}: {info['bytes']:,} bytes  sha256={info['sha256'][:16]}...",
              flush=True)
    df = pd.DataFrame(rows)[["name", "url", "path", "bytes", "sha256",
                             "http_status"]]
    df.to_csv(RESULTS / "source_files.csv", index=False)
    print(f"wrote {RESULTS / 'source_files.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
