"""Cross-check the snapshot dating against each file's own money-column headers.

Every publication is dated from what it says about itself (`gmpp.src.snapshots`
reads the attachment title, the attachment filename, then the publication body).
That is one source. This module checks it against a genuinely independent one:
the financial year the file names in its own money-column headers.

In the September era the money columns are headed "2018/19 TOTAL Baseline",
"2013/2014 Budget" and so on. The transparency policy PDF states the position is
quarter two of the financial year, which ends 30 September of the year named, so
a file's money headers date it without reference to anything the publication
page says. From the March 2021 snapshot the headers are "Financial Year
Baseline" with no year, so there is nothing to check.

Narrative columns are excluded. They are the reason this is a cross-check and
not the dating rule: the September 2019 files carry "Departmental narrative on
budget/forecast variance for 2018/19" as a leftover from the previous year's
template, and reading a financial year out of it dated every September 2019
project-year to September 2018.

Run: .venv/bin/python -m gmpp.src.validate_calendar
"""
from __future__ import annotations

import sys

import pandas as pd

from .calendar_map import snapshot_for, snapshot_from_financial_year
from .paths import MANIFEST_PATH, RAW_DIR, RESULTS_DIR
from .readers import read_raw

OUT_PATH = RESULTS_DIR / "table_calendar_validation.csv"


def check() -> pd.DataFrame:
    from .panel import _pick_files, normalise

    chosen = _pick_files(pd.read_csv(MANIFEST_PATH))
    rows: list[dict] = []
    for row in chosen.itertuples():
        dated = snapshot_for(row.publication_year, row.publication_slug)
        try:
            wide, _ = normalise(read_raw(RAW_DIR / row.local_path).raw)
            headers = [str(c) for c in wide.columns]
            error = ""
        except Exception as exc:  # noqa: BLE001 - recorded, not raised
            headers, error = [], f"{type(exc).__name__}: {exc}"
        implied = snapshot_from_financial_year(headers) if headers else None
        if error:
            verdict = "unreadable"
        elif implied is None:
            verdict = "no financial year in any money header"
        elif implied == dated:
            verdict = "agrees"
        else:
            verdict = "DISAGREES"
        rows.append(
            {
                "publication_slug": row.publication_slug,
                "publication_year": row.publication_year,
                "dated_snapshot": dated,
                "money_header_implies": implied,
                "verdict": verdict,
                "error": error,
            }
        )
    return pd.DataFrame(rows).sort_values(["publication_year", "publication_slug"])


def main() -> int:
    frame = check()
    frame.to_csv(OUT_PATH, index=False)
    counts = frame["verdict"].value_counts()
    print(f"wrote {OUT_PATH} ({len(frame)} publications)")
    print(counts.to_string())
    disagreements = frame[frame["verdict"] == "DISAGREES"]
    if len(disagreements):
        print("\ndisagreements:")
        print(disagreements.to_string(index=False))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
