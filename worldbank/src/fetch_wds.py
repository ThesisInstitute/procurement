"""Fetch World Bank Documents & Reports (WDS) metadata for the document types we need.

Pagination is by `rows` (page size) and `os` (offset). The API returns a `documents`
object keyed by "D<id>", plus a "facets" key that is not a document. Observed
2026-09-15: rows=1000 is accepted and deep offsets (os=6000) work.

We do not trust the offset paging to be perfectly stable, so we deduplicate on the
document id and report coverage against the API's own `total`.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import pandas as pd
import requests

from .paths import WDS

API = "https://search.worldbank.org/api/v3/wds"

DOCTYPES = {
    "pad": "Project Appraisal Document",
    "icr": "Implementation Completion and Results Report",
    "icrr": "Implementation Completion Report Review",
}

# Fields we keep flat. Anything else is dropped or JSON-encoded.
SCALAR_FIELDS = [
    "id", "projectid", "docty", "docdt", "datestored", "last_modified_date",
    "disclosure_date", "display_title", "projn", "repnb", "guid", "url",
    "pdfurl", "txturl", "count", "admreg", "lang", "majdocty", "prdln",
    "prdln_exact", "seccl", "disclstat", "versiontyp", "owner", "volnb",
    "lndinstr_exact", "chronical_docm_id", "bdmdt",
]


def _get(session: requests.Session, params: dict, tries: int = 6) -> dict:
    delay = 2.0
    last: Exception | None = None
    for attempt in range(tries):
        try:
            r = session.get(API, params=params, timeout=180)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code}")
        except Exception as exc:  # network, json, timeout
            last = exc
        time.sleep(delay)
        delay = min(delay * 2, 60)
    raise RuntimeError(f"WDS request failed after {tries} tries: {last}")


def _flatten(doc: dict) -> dict:
    out: dict[str, Any] = {}
    for f in SCALAR_FIELDS:
        v = doc.get(f)
        out[f] = v if (v is None or isinstance(v, (str, int, float))) else json.dumps(v)
    # abstracts arrive as {"cdata!": "..."}
    abs_ = doc.get("abstracts")
    if isinstance(abs_, dict):
        out["abstract"] = abs_.get("cdata!")
    elif isinstance(abs_, str):
        out["abstract"] = abs_
    else:
        out["abstract"] = None
    # nested list-like dicts we want as joined strings
    for f in ("sectr", "theme", "subsc", "majtheme", "lndinstr", "docna"):
        v = doc.get(f)
        if isinstance(v, dict):
            vals = []
            for item in v.values():
                if isinstance(item, dict):
                    vals.extend(str(x) for x in item.values())
                else:
                    vals.append(str(item))
            out[f] = "; ".join(vals)
        elif isinstance(v, str):
            out[f] = v
        else:
            out[f] = None
    return out


def fetch_doctype(key: str, page: int = 1000, log=sys.stderr) -> pd.DataFrame:
    docty = DOCTYPES[key]
    session = requests.Session()
    session.headers["User-Agent"] = "thesis-institute-procurement-research/1.0"
    rows: dict[str, dict] = {}
    os_ = 0
    total = None
    while True:
        params = {"format": "json", "rows": page, "os": os_, "docty_exact": docty}
        payload = _get(session, params)
        if total is None:
            total = int(payload.get("total", 0))
            print(f"[{key}] API total={total}", file=log, flush=True)
        docs = {k: v for k, v in payload.get("documents", {}).items() if k != "facets"}
        if not docs:
            break
        for k, v in docs.items():
            if isinstance(v, dict):
                rows[k] = _flatten(v)
        print(f"[{key}] os={os_} got={len(docs)} unique={len(rows)}/{total}",
              file=log, flush=True)
        os_ += page
        if os_ >= total:
            break
        time.sleep(0.4)
    df = pd.DataFrame.from_records(list(rows.values()))
    df["doctype_key"] = key
    df["api_total"] = total
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="*", default=list(DOCTYPES))
    ap.add_argument("--page", type=int, default=1000)
    args = ap.parse_args()
    for key in args.which:
        df = fetch_doctype(key, page=args.page)
        out = WDS / f"{key}.parquet"
        df.to_parquet(out, index=False)
        print(f"[{key}] wrote {out} rows={len(df)} cols={len(df.columns)} "
              f"coverage={len(df)}/{df['api_total'].iloc[0]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
