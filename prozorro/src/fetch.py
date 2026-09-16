"""Fetch full tender documents and their contract-registry records.

Two documents matter and they are not the same document:

* `/tenders/{id}` carries `bids[]` (every bidder's identity and per-lot price),
  `awards[]` and a *copy* of each contract as it stood when the tender copy was
  last written.  Verified 2026-09-16: on tender
  6fffbf33eb8d4c908ce7578be33e15a6 the tender copy shows the contract as
  `active` while the registry shows `terminated`, so the tender copy lags.
* `/contracts/{id}` is the live registry record: `status`, `amountPaid`,
  `period`, and `changes[]` with `rationaleTypes`.

The registry record is only fetched for tenders that pass the two-bid filter,
which is why the filter lives here rather than downstream.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import json
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api import CLIENT, COUNTER, MAX_CONCURRENCY  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw" / "prozorro"
TENDER_DIR = RAW / "tenders"
CONTRACT_DIR = RAW / "contracts"

_log_lock = threading.Lock()


def log(msg: str) -> None:
    with _log_lock:
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def distinct_bidders(tender: dict) -> int:
    """Number of distinct bidder legal entities that submitted a live bid.

    `bids[]` holds one entry per bidder, so this counts bids whose status is not
    a draft/deleted placeholder.  A consortium bid lists several tenderers; it
    is still one bid, so the count is over bids, not tenderers.
    """
    n = 0
    for bid in tender.get("bids") or []:
        if bid.get("status") in {"deleted", "draft", "invalid.pre-qualification"}:
            continue
        n += 1
    return n


def fetched_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


class Worker:
    def __init__(self, k: int, min_bids: int):
        self.k = k
        self.min_bids = min_bids
        self.tender_fh = gzip.open(TENDER_DIR / f"tenders_w{k}.jsonl.gz", "at", encoding="utf-8")
        self.contract_fh = gzip.open(
            CONTRACT_DIR / f"contracts_w{k}.jsonl.gz", "at", encoding="utf-8"
        )
        self.index_fh = open(TENDER_DIR / f"done_w{k}.txt", "a")
        self.n_tenders = 0
        self.n_contracts = 0
        self.n_passed = 0
        self.n_errors = 0

    def close(self) -> None:
        for fh in (self.tender_fh, self.contract_fh, self.index_fh):
            fh.flush()
            fh.close()

    def run_one(self, tender_id: str) -> None:
        try:
            tender = CLIENT.get(f"/tenders/{tender_id}", kind="tender")["data"]
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed silently
            self.n_errors += 1
            self.index_fh.write(f"{tender_id}\n")
            log(f"w{self.k} tender {tender_id} failed: {exc}")
            return
        self.tender_fh.write(json.dumps(tender, ensure_ascii=False) + "\n")
        self.n_tenders += 1
        if distinct_bidders(tender) >= self.min_bids:
            self.n_passed += 1
            for contract in tender.get("contracts") or []:
                cid = contract.get("id")
                if not cid:
                    continue
                try:
                    reg = CLIENT.get(f"/contracts/{cid}", kind="contract")["data"]
                except Exception as exc:  # noqa: BLE001
                    self.n_errors += 1
                    log(f"w{self.k} contract {cid} failed: {exc}")
                    continue
                reg["_tender_id"] = tender_id
                self.contract_fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
                self.n_contracts += 1
        self.index_fh.write(f"{tender_id}\n")
        if self.n_tenders % 200 == 0:
            self.tender_fh.flush()
            self.contract_fh.flush()
            self.index_fh.flush()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ids", default=str(RAW / "census" / "sample_ids.txt"))
    ap.add_argument("--workers", type=int, default=MAX_CONCURRENCY)
    ap.add_argument("--min-bids", type=int, default=2)
    ap.add_argument("--max-seconds", type=float, default=11000.0)
    ap.add_argument("--limit", type=int, default=0, help="0 = all ids")
    args = ap.parse_args()

    TENDER_DIR.mkdir(parents=True, exist_ok=True)
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    workers = min(args.workers, MAX_CONCURRENCY)

    ids = [x.strip() for x in Path(args.ids).read_text().splitlines() if x.strip()]
    if args.limit:
        ids = ids[: args.limit]
    already: set[str] = set()
    for k in range(workers):
        already |= fetched_ids(TENDER_DIR / f"done_w{k}.txt")
    todo = [i for i in ids if i not in already]
    log(f"fetch: {len(ids):,} ids, {len(already):,} already done, {len(todo):,} to go")

    q: queue.Queue[str | None] = queue.Queue()
    for i in todo:
        q.put(i)
    deadline = time.time() + args.max_seconds
    stop = threading.Event()
    ws = [Worker(k, args.min_bids) for k in range(workers)]
    t0 = time.time()

    def run(w: Worker) -> None:
        while not stop.is_set():
            try:
                tid = q.get_nowait()
            except queue.Empty:
                return
            if tid is None:
                return
            w.run_one(tid)

    def monitor() -> None:
        last = 0
        while not stop.is_set():
            time.sleep(20)
            done = sum(w.n_tenders for w in ws)
            if time.time() > deadline:
                log("deadline reached; stopping")
                stop.set()
                return
            if done != last:
                rate = done / max(time.time() - t0, 1e-9)
                left = q.qsize()
                log(
                    f"{done:,} tenders ({sum(w.n_passed for w in ws):,} with >= {args.min_bids} bids), "
                    f"{sum(w.n_contracts for w in ws):,} contracts, {rate:.2f}/s, "
                    f"{left:,} queued, eta {left / max(rate, 1e-9) / 60:.0f} min, "
                    f"errors {sum(w.n_errors for w in ws)}"
                )
                last = done
            if q.empty():
                return

    mon = threading.Thread(target=monitor, daemon=True)
    mon.start()
    with cf.ThreadPoolExecutor(workers) as ex:
        list(ex.map(run, ws))
    stop.set()
    for w in ws:
        w.close()
    summary = {
        "ids_requested": len(ids),
        "tenders_fetched_this_run": sum(w.n_tenders for w in ws),
        "tenders_with_min_bids": sum(w.n_passed for w in ws),
        "contracts_fetched": sum(w.n_contracts for w in ws),
        "errors": sum(w.n_errors for w in ws),
        "seconds": round(time.time() - t0, 1),
        "requests": COUNTER.snapshot(),
    }
    log(json.dumps(summary))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    (RAW / f"fetch_summary_{stamp}.json").write_text(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
