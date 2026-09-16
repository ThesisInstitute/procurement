"""Download qualifying PAD plain text, recording sha256 and byte size.

Politeness: 4 concurrent requests maximum, exponential backoff on failure.

Observed 2026-09-15: some `txturl` responses return HTTP 200 with a short
sentinel body instead of document text, e.g.
    "The original PDF is Password Protected for Opening. Unable to extract
     text for Index."
Those are detected here and marked `extract_failed` rather than silently
entering the corpus as an 88-byte document.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import sys
import time

import pandas as pd
import requests

from .paths import PAD_TEXT, RESULTS

MAX_WORKERS = 4
MIN_USABLE_BYTES = 2000

SENTINELS = (
    "password protected",
    "unable to extract text",
    "the original pdf is",
)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "thesis-institute-procurement-research/1.0"
    return s


def classify(text: str, nbytes: int) -> str:
    head = text[:600].lower()
    if any(k in head for k in SENTINELS):
        return "extract_failed"
    if nbytes < MIN_USABLE_BYTES:
        return "too_short"
    return "ok"


def fetch_one(session: requests.Session, projectid: str, url: str,
              tries: int = 4) -> dict:
    dest = PAD_TEXT / f"{projectid}.txt"
    if dest.exists():
        raw = dest.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        return {
            "projectid": projectid, "txturl": url, "http_status": 200,
            "text_bytes": len(raw),
            "text_sha256": hashlib.sha256(raw).hexdigest(),
            "status": classify(text, len(raw)), "cached": True,
        }
    delay = 2.0
    last = ""
    for _ in range(tries):
        try:
            r = session.get(url, timeout=120)
            if r.status_code == 200:
                raw = r.content
                text = r.text
                status = classify(text, len(raw))
                if status == "ok":
                    dest.write_bytes(raw)
                return {
                    "projectid": projectid, "txturl": url, "http_status": 200,
                    "text_bytes": len(raw),
                    "text_sha256": hashlib.sha256(raw).hexdigest(),
                    "status": status, "cached": False,
                }
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 404, 410):
                return {"projectid": projectid, "txturl": url,
                        "http_status": r.status_code, "text_bytes": 0,
                        "text_sha256": None, "status": f"http_{r.status_code}",
                        "cached": False}
        except Exception as exc:
            last = type(exc).__name__
        time.sleep(delay)
        delay = min(delay * 2, 30)
    return {"projectid": projectid, "txturl": url, "http_status": None,
            "text_bytes": 0, "text_sha256": None, "status": f"failed:{last}",
            "cached": False}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest-in", default=str(RESULTS / "pad_download_queue.csv"))
    ap.add_argument("--manifest-out", default=str(RESULTS / "pad_text_manifest.csv"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    q = pd.read_csv(args.manifest_in)
    q = q[q["txturl"].notna()].drop_duplicates("projectid")
    if args.limit:
        q = q.head(args.limit)
    print(f"[padtext] queue={len(q)}", file=sys.stderr, flush=True)

    sessions = [_session() for _ in range(MAX_WORKERS)]
    out = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {
            ex.submit(fetch_one, sessions[i % MAX_WORKERS], r.projectid, r.txturl): r.projectid
            for i, r in enumerate(q.itertuples())
        }
        for fut in cf.as_completed(futs):
            out.append(fut.result())
            done += 1
            if done % 100 == 0:
                okn = sum(1 for o in out if o["status"] == "ok")
                gb = sum(o["text_bytes"] for o in out) / 1e9
                print(f"[padtext] {done}/{len(q)} ok={okn} {gb:.2f}GB",
                      file=sys.stderr, flush=True)

    m = pd.DataFrame(out)
    m.to_csv(args.manifest_out, index=False)
    print(m["status"].value_counts().to_string(), flush=True)
    print(f"[padtext] wrote {args.manifest_out} rows={len(m)} "
          f"bytes={m['text_bytes'].sum():,}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
