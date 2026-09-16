"""Fetch World Bank Projects API metadata (all projects) with fl=* and flatten.

Observed 2026-09-15: `fl=*` returns the full populated field set per record. Two
nested rating blocks are returned that are NOT in the Finances One IEG bulk CSV:

  icr_ratings : bankqualityentry, banksupervision, borrgovt, borrimplegency,
                borroverall, completion_riskdo, outratingind, overallrating, value
  ieg_ratings : evaldate, borrowcompliance, icrquality, mequality, outcome,
                overallbankperf, overallborrowperf, evaluation_riskdo

We keep both verbatim so the Bank-side and IEG-side ratings can be compared.
We do not assert here which block is authored by whom; that is tested empirically
in tests/ against the Finances One IEG bulk CSV.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import pandas as pd
import requests

from .paths import PROJECTS

API = "https://search.worldbank.org/api/v3/projects"

SCALARS = [
    "id", "proj_id", "project_name", "regionname", "countryname",
    "countryshortname", "countrycode", "boardapprovaldate_exact",
    "boardapprovaldate", "closingdate", "loan_effective_date",
    "public_disclosure_date", "proj_last_upd_date", "fiscalyear", "status",
    "last_stage_reached_name", "prodline_exact", "projectfinancialtype_exact",
    "envassesmentcategorycode", "esrc_ovrl_risk_rate", "lendprojectcost",
    "curr_project_cost", "totalamt", "grantamt", "idacommamt",
    "curr_ibrd_commitment", "curr_ida_commitment", "curr_total_commitment",
    "borrower", "impagency", "teamleadname", "major_sector_code",
    "major_sector_name", "mjsector", "sector_name", "sectorcode",
    "sector_percent", "theme", "themecode", "pdo", "project_abstract",
]

ICR_KEYS = ["bankqualityentry", "banksupervision", "borrgovt", "borrimplegency",
            "borroverall", "completion_riskdo", "outratingind", "overallrating",
            "value"]
IEG_KEYS = ["evaldate", "borrowcompliance", "icrquality", "mequality", "outcome",
            "overallbankperf", "overallborrowperf", "evaluation_riskdo"]
MILESTONE_KEYS = ["concpt_review_date", "begin_apprsl_date",
                  "authorize_negotiations_date", "apprvl_date",
                  "dsclsr_of_concpt_pid_date", "decsn_review_date",
                  "effctvnss_date", "icr_nco_date"]


def _get(session: requests.Session, params: dict, tries: int = 6) -> dict:
    delay = 2.0
    last: Exception | None = None
    for _ in range(tries):
        try:
            r = session.get(API, params=params, timeout=240)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code}")
        except Exception as exc:
            last = exc
        time.sleep(delay)
        delay = min(delay * 2, 60)
    raise RuntimeError(f"projects request failed: {last}")


def _blocks(block: Any) -> list[dict]:
    """Normalise a rating block to a deduplicated list of dicts.

    OBSERVED: the API returns `icr_ratings` as a list that can repeat its
    elements, so a naive read of "the first element" or "the element count" is
    not safe and the list is deduplicated before any value is read from it.
    Measured over the 6,381 projects that carry the block: 82.4% show no
    repetition at all (raw element count equals distinct count) and the rest
    repeat, up to 144 raw elements.

    WITHDRAWN CLAIM: an earlier version of this docstring said the length is
    "frequently k*(k+1) for small k (2, 6, 12, 20, 30, ...) with every element
    identical". The data refutes it -- observed raw counts include 1, 3, 4, 9,
    25, 121 and 144 -- so no length rule is asserted. Deduplication is correct
    whatever the length, which is why nothing downstream depended on the claim.
    """
    if isinstance(block, dict):
        block = [v for v in block.values() if isinstance(v, dict)]
    if not isinstance(block, list):
        return []
    seen, out = set(), []
    for bb in block:
        if not isinstance(bb, dict):
            continue
        k = json.dumps(bb, sort_keys=True)
        if k not in seen:
            seen.add(k)
            out.append(bb)
    return out


def _collapse(blocks: list[dict], keys: list[str], prefix: str) -> dict:
    """Flatten deduplicated blocks, recording conflicts instead of hiding them.

    For each key we keep the first non-null value AND the number of DISTINCT
    non-null values seen, so that a downstream conflict is visible in the data
    rather than silently resolved by taking element zero.
    """
    out: dict[str, Any] = {}
    for k in keys:
        vals = [b.get(k) for b in blocks if b.get(k) not in (None, "")]
        distinct = list(dict.fromkeys(vals))
        out[f"{prefix}_{k}"] = distinct[0] if distinct else None
        out[f"{prefix}_{k}__n_distinct"] = len(distinct)
    out[f"{prefix}__n_blocks_distinct"] = len(blocks)
    return out


def _flatten(rec: dict) -> dict:
    out: dict[str, Any] = {}
    for f in SCALARS:
        v = rec.get(f)
        if isinstance(v, list):
            v = ",".join(str(x).strip() for x in v)
        elif isinstance(v, dict):
            v = json.dumps(v)
        out[f] = v

    raw_icr = rec.get("icr_ratings") or []
    icr_blocks = _blocks(raw_icr)
    out.update(_collapse(icr_blocks, ICR_KEYS, "icr"))
    out["icr__n_blocks_raw"] = len(raw_icr) if isinstance(raw_icr, list) else 0

    raw_ieg = rec.get("ieg_ratings") or []
    ieg_blocks = _blocks(raw_ieg)
    # Where several distinct evaluations exist (an ICRR and a later PPAR), keep
    # the LATEST by evaldate as the primary and the earliest alongside it.
    ordered = sorted(ieg_blocks, key=lambda b: str(b.get("evaldate") or ""))
    out.update(_collapse(list(reversed(ordered)), IEG_KEYS, "iegapi"))
    out["iegapi__n_blocks_raw"] = len(raw_ieg) if isinstance(raw_ieg, list) else 0
    for k in IEG_KEYS:
        out[f"iegapi_first_{k}"] = ordered[0].get(k) if ordered else None

    ms_blocks = _blocks(rec.get("milestones"))
    ms = ms_blocks[0] if ms_blocks else {}
    for k in MILESTONE_KEYS:
        out[f"ms_{k}"] = ms.get(k)

    isr = rec.get("isr_ratings") or []
    out["n_isr_ratings"] = len(isr)
    for nm, tag in (("Progress towards achievement of PDO", "pdo"),
                    ("Overall Implementation Progress (IP)", "ip")):
        hits = [x for x in isr if isinstance(x, dict) and x.get("name") == nm
                and x.get("isr_date")]
        hits = sorted(hits, key=lambda x: str(x.get("isr_date")))
        out[f"isr_last_{tag}_rating"] = hits[-1].get("value") if hits else None
        out[f"isr_last_{tag}_date"] = hits[-1].get("isr_date") if hits else None
        out[f"isr_first_{tag}_rating"] = hits[0].get("value") if hits else None
        out[f"isr_first_{tag}_date"] = hits[0].get("isr_date") if hits else None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", type=int, default=500)
    args = ap.parse_args()
    session = requests.Session()
    session.headers["User-Agent"] = "thesis-institute-procurement-research/1.0"
    rows: dict[str, dict] = {}
    os_ = 0
    total = None
    while True:
        payload = _get(session, {"format": "json", "rows": args.page,
                                 "os": os_, "fl": "*"})
        if total is None:
            total = int(payload.get("total", 0))
            print(f"[projects] API total={total}", file=sys.stderr, flush=True)
        recs = payload.get("projects", {})
        recs = {k: v for k, v in recs.items() if isinstance(v, dict)}
        if not recs:
            break
        for k, v in recs.items():
            rows[k] = _flatten(v)
        print(f"[projects] os={os_} got={len(recs)} unique={len(rows)}/{total}",
              file=sys.stderr, flush=True)
        os_ += args.page
        if os_ >= total:
            break
        time.sleep(0.4)
    df = pd.DataFrame.from_records(list(rows.values()))
    df["api_total"] = total
    out = PROJECTS / "projects.parquet"
    df.to_parquet(out, index=False)
    print(f"[projects] wrote {out} rows={len(df)} cols={len(df.columns)} "
          f"coverage={len(df)}/{total}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
