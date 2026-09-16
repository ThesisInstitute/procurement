"""Walk the Prozorro tender feed and record every above-threshold tender.

The feed at `/tenders` is ordered by `dateModified`, and a tender appears in it
once, at its current `dateModified` (verified 2026-09-16: seeding `offset` with
an ISO datetime lands on rows with that dateModified, and `next_page.offset`
advances monotonically).  `dateModified` only ever increases, so a forward walk
from a seed date visits every tender whose current dateModified is at or after
that seed, with no misses.  A tender modified while the cursor is behind it is
seen twice, so callers must de-duplicate on `id`.

Because every tender created on or after the seed date must have a dateModified
on or after its creation, a walk from 2019-01-01 to now is a complete census of
tenders created from 2019-01-01 onwards.  That is what removes the
feed-ordering bias: nothing is truncated at the recent end.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import json
import os
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api import CLIENT, COUNTER, MAX_CONCURRENCY  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CENSUS_DIR = REPO / "data" / "raw" / "prozorro" / "census"

# The three competitive above-threshold procedures named in the brief.
ABOVE_THRESHOLD = ("aboveThreshold", "aboveThresholdUA", "aboveThresholdEU")

# The feed stamps dateModified in Ukrainian local time (+02:00 / +03:00).
KYIV = ZoneInfo("Europe/Kyiv")

# Window files are named by day in day-sample mode and by month in census mode.
TAG_DAYS = False

LISTING_FIELDS = "status,procurementMethodType,dateModified,tenderID"

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def _aware(value: str) -> datetime:
    """Parse an ISO string, assuming Kyiv local time when no offset is given."""
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=KYIV)


def day_windows(start: str, end: str, step: int) -> list[tuple[str, str]]:
    """Every `step`-th whole day in [start, end), as a systematic day sample.

    Selecting whole days and walking each one completely gives every tender in
    the range the same inclusion probability, 1/step, whatever the volume of
    the day it happens to sit in.  Sampling a fixed number of rows per day
    instead would have over-represented quiet days, and stopping the walk at a
    cut-off date would have dropped tenders whose award ran long.  A step
    coprime with 7 rotates through the days of the week.
    """
    s = _aware(start)
    e = _aware(end)
    out: list[tuple[str, str]] = []
    cur = s.replace(hour=0, minute=0, second=0, microsecond=0)
    i = 0
    while cur < e:
        nxt = (cur + timedelta(days=1, hours=3)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if i % step == 0:
            out.append((cur.isoformat(), min(nxt, e).isoformat()))
        cur = nxt
        i += 1
    return out


def month_windows(start: str, end: str) -> list[tuple[str, str]]:
    """Inclusive-start, exclusive-end month windows covering [start, end)."""
    s = _aware(start)
    e = _aware(end)
    out: list[tuple[str, str]] = []
    cur = s.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if cur < s:
        cur = s
    while cur < e:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        out.append((cur.isoformat(), min(nxt, e).isoformat()))
        cur = nxt
    return out


def tender_id_date(tender_id: str) -> str | None:
    """Creation date encoded in the human tenderID, e.g. UA-2021-01-29-003647-c.

    Verified 2026-09-16 on tender 6fffbf33eb8d4c908ce7578be33e15a6: tenderID
    UA-2024-01-26-000820-a and tenderPeriod.startDate 2024-01-26.  The report
    measures how often the two agree on the fetched sample.
    """
    if not tender_id or len(tender_id) < 13 or not tender_id.startswith("UA-"):
        return None
    d = tender_id[3:13]
    if d[4] != "-" or d[7] != "-":
        return None
    return d


def walk_window(window: tuple[str, str], out_dir: Path, overwrite: bool = False) -> dict:
    """Walk one dateModified window; write qualifying rows and daily counts."""
    start, end = window
    tag = start[:10] if TAG_DAYS else start[:7]
    cand_path = out_dir / f"cand_{tag}.jsonl.gz"
    meta_path = out_dir / f"meta_{tag}.json"
    if meta_path.exists() and not overwrite:
        return json.loads(meta_path.read_text())

    end_dt = _aware(end)
    counts: Counter[tuple[str, str, str]] = Counter()
    offset = start
    rows_seen = 0
    pages = 0
    kept = 0
    first_seen = last_seen = None
    t0 = time.time()
    tmp = cand_path.with_suffix(".gz.partial")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        while True:
            payload = CLIENT.get(
                "/tenders",
                {"offset": offset, "limit": 1000, "opt_fields": LISTING_FIELDS},
                kind="listing",
            )
            rows = payload.get("data", [])
            pages += 1
            if not rows:
                break
            for row in rows:
                dm = row.get("dateModified")
                if not dm:
                    continue
                day = dm[:10]
                counts[(day, row.get("procurementMethodType") or "", row.get("status") or "")] += 1
                rows_seen += 1
                if first_seen is None:
                    first_seen = dm
                last_seen = dm
                if (
                    row.get("procurementMethodType") in ABOVE_THRESHOLD
                    and row.get("status") == "complete"
                ):
                    fh.write(
                        json.dumps(
                            {
                                "id": row["id"],
                                "tenderID": row.get("tenderID"),
                                "method": row["procurementMethodType"],
                                "dateModified": dm,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    kept += 1
            if _aware(rows[-1]["dateModified"]) >= end_dt:
                break
            nxt = payload.get("next_page", {}).get("offset")
            if not nxt or nxt == offset:
                break
            offset = nxt
    os.replace(tmp, cand_path)
    meta = {
        "window_start": start,
        "window_end": end,
        "first_dateModified": first_seen,
        "last_dateModified": last_seen,
        "rows_seen": rows_seen,
        "pages": pages,
        "kept": kept,
        "seconds": round(time.time() - t0, 1),
        "daily_counts": [
            {"day": d, "method": m, "status": s, "n": n} for (d, m, s), n in sorted(counts.items())
        ],
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False))
    log(
        f"{tag}: {rows_seen:,} rows, {kept:,} kept, {pages} pages, "
        f"{meta['seconds']}s, through {last_seen}"
    )
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2019-01-01T00:00:00")
    ap.add_argument("--end", default=None, help="default: now")
    ap.add_argument("--workers", type=int, default=MAX_CONCURRENCY)
    ap.add_argument("--out", default=str(CENSUS_DIR))
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument(
        "--mode", choices=["months", "day-sample"], default="months",
        help="months = complete census by month; day-sample = every step-th whole day",
    )
    ap.add_argument("--step", type=int, default=5, help="day-sample only: keep every n-th day")
    args = ap.parse_args()

    global TAG_DAYS
    TAG_DAYS = args.mode == "day-sample"

    end = args.end or datetime.now().replace(microsecond=0).isoformat()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "day-sample":
        windows = day_windows(args.start, end, args.step)
        log(
            f"day sample: every {args.step}th day, {len(windows)} whole days "
            f"{windows[0][0][:10]} .. {windows[-1][1][:10]} "
            f"(inclusion probability 1/{args.step})"
        )
    else:
        windows = month_windows(args.start, end)
        log(f"census: {len(windows)} monthly windows {windows[0][0]} .. {windows[-1][1]}")
    (out_dir / "design.json").write_text(
        json.dumps(
            {
                "mode": args.mode,
                "step": args.step if args.mode == "day-sample" else None,
                "inclusion_probability": 1.0 / args.step if args.mode == "day-sample" else 1.0,
                "start": args.start,
                "end": end,
                "windows": len(windows),
                "first_window": windows[0][0],
                "last_window": windows[-1][1],
            }
        )
    )

    workers = min(args.workers, MAX_CONCURRENCY)
    done = 0
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(walk_window, w, out_dir, args.overwrite): w for w in windows}
        for fut in cf.as_completed(futs):
            fut.result()
            done += 1
            if done % 5 == 0:
                log(f"progress {done}/{len(windows)} windows; requests={COUNTER.total():,}")
    log(f"census complete: {json.dumps(COUNTER.snapshot())}")
    (out_dir / "census_requests.json").write_text(json.dumps(COUNTER.snapshot()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
