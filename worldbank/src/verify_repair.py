"""Confirm the icr_ratings repair against the PRIMARY document, not just a
second dataset.

IEG's Implementation Completion Report Review contains a standard ratings table
laid out as:

    <n>. Ratings
                                            Reason for
    Ratings      ICR      IEG               Disagreements/Comment
    Outcome      Satisfactory  Moderately Satisfactory   ...
    Risk to Development Outcome ...
    Bank Performance ...
    Quality of ICR ...

The `ICR` column is the Bank operational team's own rating and the `IEG` column
is IEG's. This module downloads a sample of those documents, extracts the
Outcome row, and compares the document's ICR value to what the Projects API
returns in `icr_ratings.outratingind` for the same P-number.

The point: if the API says "Substantial" where the document says "Satisfactory",
the repair in src/icr_selfrating.py is confirmed against the source of record
rather than inferred from a second dataset.

Run:  .venv/bin/python -m worldbank.src.verify_repair --n 80
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import re

import pandas as pd
import requests

from .paths import PROJECTS, RESULTS, WDS

RATING_WORDS = [
    "Highly Satisfactory", "Highly Unsatisfactory",
    "Moderately Satisfactory", "Moderately Unsatisfactory",
    "Satisfactory", "Unsatisfactory",
]
RATING_RE = "|".join(re.escape(w) for w in RATING_WORDS)
TABLE_RE = re.compile(r"Ratings\s+ICR\s+IEG", re.IGNORECASE)

# The PDF text layer wraps a two-word rating across lines, so flattening the
# table can put the qualifiers BEFORE the row label. Observed verbatim in
# P157035, P122229 and P116696:
#     "... Disagreements/Comment Moderately Moderately Outcome
#      Unsatisfactory Unsatisfactory ..."
# Both columns are "Moderately Unsatisfactory" there, not "Unsatisfactory".
# The pattern below captures any qualifiers stranded before "Outcome" and
# reattaches them in column order. Where exactly one qualifier is stranded the
# column it belongs to is genuinely ambiguous, so the row is dropped rather than
# guessed.
QUALIFIERS = ("Moderately", "Highly")
OUTCOME_RE = re.compile(
    rf"((?:(?:Moderately|Highly)\s+){{0,2}})Outcome\s+({RATING_RE})\s+({RATING_RE})",
    re.IGNORECASE)


def extract_outcome_pair(text: str) -> tuple[str | None, str | None]:
    """Return (ICR outcome, IEG outcome) from the document's ratings table.

    Returns (None, None) when the table is absent or the layout is ambiguous.
    """
    flat = re.sub(r"\s+", " ", text)
    m = TABLE_RE.search(flat)
    if not m:
        return None, None
    window = flat[m.end(): m.end() + 1200]
    om = OUTCOME_RE.search(window)
    if not om:
        return None, None
    stranded = [w for w in om.group(1).split() if w.title() in QUALIFIERS]
    icr, ieg = om.group(2).title(), om.group(3).title()
    if len(stranded) == 2:
        # one qualifier per column, in column order
        if not icr.startswith(QUALIFIERS):
            icr = f"{stranded[0].title()} {icr}"
        if not ieg.startswith(QUALIFIERS):
            ieg = f"{stranded[1].title()} {ieg}"
    elif len(stranded) == 1:
        # cannot tell which column it belongs to; refuse rather than guess
        return None, None
    return icr, ieg


def _fetch(session: requests.Session, projectid: str, url: str) -> dict:
    try:
        r = session.get(url, timeout=120)
        if r.status_code != 200:
            return {"projectid": projectid, "doc_icr": None, "doc_ieg": None,
                    "note": f"http_{r.status_code}"}
        icr, ieg = extract_outcome_pair(r.text)
        return {"projectid": projectid, "doc_icr": icr, "doc_ieg": ieg,
                "note": "ok" if icr else "table_not_found"}
    except Exception as exc:
        return {"projectid": projectid, "doc_icr": None, "doc_ieg": None,
                "note": type(exc).__name__}


def run(n: int = 80, seed: int = 0) -> pd.DataFrame:
    pj = pd.read_parquet(PROJECTS / "projects.parquet")
    pj["projectid"] = pj["id"].astype(str).str.upper()
    icrr = pd.read_parquet(WDS / "icrr.parquet")[["projectid", "txturl"]].dropna()
    icrr["projectid"] = icrr["projectid"].astype(str).str.upper()
    icrr = icrr.drop_duplicates("projectid")

    have = pj.loc[pj["icr_outratingind"].notna(),
                  ["projectid", "icr_outratingind", "iegapi_outcome"]]
    pool = have.merge(icrr, on="projectid")
    # stratify: sample within each API value so the test is not dominated by one
    per = max(1, n // max(1, pool["icr_outratingind"].nunique()))
    parts = []
    for _, d in pool.groupby("icr_outratingind"):
        parts.append(d.sample(min(len(d), per), random_state=seed))
    sample = pd.concat(parts, ignore_index=True)

    s = requests.Session()
    s.headers["User-Agent"] = "thesis-institute-procurement-research/1.0"
    out = []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(_fetch, s, r.projectid, r.txturl)
                for r in sample.itertuples()]
        for f in cf.as_completed(futs):
            out.append(f.result())

    res = sample.merge(pd.DataFrame(out), on="projectid")
    ok = res[res["doc_icr"].notna()].copy()
    ok["api_matches_document"] = ok["icr_outratingind"] == ok["doc_icr"]
    ok["repaired_matches_document"] = ok.apply(
        lambda r: (r["doc_icr"] == "Satisfactory"
                   if r["icr_outratingind"] == "Substantial"
                   else r["icr_outratingind"] == r["doc_icr"]), axis=1)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=80)
    args = ap.parse_args()
    ok = run(n=args.n)
    ok.to_csv(RESULTS / "repair_document_verification.csv", index=False)

    ct = pd.crosstab(ok["icr_outratingind"], ok["doc_icr"])
    ct.to_csv(RESULTS / "repair_document_crosstab.csv")

    sub = ok[ok["icr_outratingind"] == "Substantial"]
    summary = pd.DataFrame([{
        "documents parsed": int(len(ok)),
        "API value matches document verbatim": float(
            ok["api_matches_document"].mean()),
        "REPAIRED value matches document": float(
            ok["repaired_matches_document"].mean()),
        "rows where API says Substantial": int(len(sub)),
        "of those, document says Satisfactory": int(
            (sub["doc_icr"] == "Satisfactory").sum()),
    }])
    summary.to_csv(RESULTS / "repair_document_summary.csv", index=False)
    print(ct.to_string())
    print()
    print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
