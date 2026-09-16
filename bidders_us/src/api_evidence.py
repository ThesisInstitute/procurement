"""Record the two API measurements the fetch docstring relies on.

1. Delivery-order volume per fiscal year from the search count endpoints
   (POST /api/v2/search/spending_by_award_count/ and
   /spending_by_transaction_count/ with award_type_codes ["C"] and, for
   scale, ["D"]).
2. The data dictionary rows (GET /api/v2/references/data_dictionary/) for
   the parent-vehicle download columns, the award type domain and the
   extent-competed domain.

Both are saved to results/api_evidence.json so the docstrings and the report
cite a file this workstream wrote rather than a number typed from memory.
"""
from __future__ import annotations

import json
import re
import sys
import time

import requests

from bidders_us.src.common import RESULTS, make_logger

API = "https://api.usaspending.gov/api/v2"
UA = {"User-Agent": "thesis-institute-procurement-backtest/1.0"}
DICT_PATTERN = re.compile(r"parent_award_id_piid|parent_award_agency_id|parent_award_type_code|"
                          r"parent_award_single_or_multiple_code|parent_award_modification_number|"
                          r"^ContractAwardType\b|^ExtentCompeted\b|^Referenced_IDV_Agency_Identifier|"
                          r"^IDV_Type\b|^MultipleOrSingleAwardIDV")


def post(url, body, log, attempts=6):
    for i in range(attempts):
        try:
            r = requests.post(url, json=body, headers=UA, timeout=180)
            if r.status_code == 200:
                return r.json()
            log(f"POST {url} -> {r.status_code}")
        except requests.RequestException as exc:
            log(f"POST {url} raised {exc}")
        time.sleep(15 * (i + 1))
    return None


def main() -> int:
    log = make_logger("api_evidence")
    out = {"pulled_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "counts": [], "dictionary": []}
    for fy in range(2010, 2027):
        s, e = f"{fy - 1}-10-01", f"{fy}-09-30"
        rec = {"fiscal_year": fy}
        for code in ("C", "D"):
            body = {"filters": {"award_type_codes": [code],
                                "time_period": [{"start_date": s, "end_date": e, "date_type": "action_date"}]}}
            a = post(f"{API}/search/spending_by_award_count/", body, log)
            t = post(f"{API}/search/spending_by_transaction_count/", body, log)
            rec[f"awards_with_activity_{code}"] = (a or {}).get("results", {}).get("contracts")
            rec[f"transactions_{code}"] = (t or {}).get("results", {}).get("contracts")
        out["counts"].append(rec)
        log(json.dumps(rec))
    try:
        d = requests.get(f"{API}/references/data_dictionary/", headers=UA, timeout=180).json()["document"]
        headers = [h["display"] for h in d["headers"]]
        for row in d["rows"]:
            joined = " | ".join(str(x) for x in row)
            if DICT_PATTERN.search(joined):
                out["dictionary"].append(dict(zip(headers, row)))
        log(f"dictionary rows kept: {len(out['dictionary'])}")
    except Exception as exc:  # noqa: BLE001
        log(f"dictionary pull failed: {exc}")
        out["dictionary_error"] = str(exc)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "api_evidence.json").write_text(json.dumps(out, indent=1, default=str))
    log(f"-> {RESULTS / 'api_evidence.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
