"""Resolve the portfolio snapshot date behind every GMPP publication.

The publication year is not the snapshot date. Observed in the gov.uk API on
2026-09-15: the 2015 publications carry the "September 2014" position, the 2019
publications carry "September 2018", and the 2024 publications carry "March
2024". The snapshot is resolved per publication from, in priority order:

1. a month-year in an attachment title,
2. a month-year in an attachment filename,
3. a month-year in the publication body prose ("This September 2014 GMPP data"),
4. the publication year, with month unknown.

The winning source is recorded so the dating is auditable.

Run: .venv/bin/python -m gmpp.src.snapshots
"""
from __future__ import annotations

import json
import re
import sys

import pandas as pd

from .paths import MANIFEST_PATH, RAW_DIR

SNAPSHOTS_PATH = RAW_DIR / "snapshots.csv"
API_DIR = RAW_DIR / "_api"

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
]
MONTH_ALT = "|".join(MONTH_NAMES)
MONTH_RE = re.compile(rf"\b({MONTH_ALT})[_\s]+(20\d{{2}})\b", re.I)


def find_month_year(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    m = MONTH_RE.search(text)
    if not m:
        return None
    return MONTH_NAMES.index(m.group(1).title()) + 1, int(m.group(2))


def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "")


def resolve() -> pd.DataFrame:
    manifest = pd.read_csv(MANIFEST_PATH)
    data_pubs = manifest[manifest["is_data_publication"]]
    rows: list[dict] = []
    for slug, group in data_pubs.groupby("publication_slug"):
        pub_year = int(group["publication_year"].iloc[0])
        dept = group["department_slug"].iloc[0]

        hit = source = None
        for title in group["attachment_title"].dropna():
            hit = find_month_year(str(title))
            if hit:
                source = "attachment_title"
                break
        if not hit:
            for url in group["attachment_url"]:
                hit = find_month_year(str(url).rsplit("/", 1)[-1].replace("__", "_"))
                if hit:
                    source = "filename"
                    break
        if not hit:
            cache = API_DIR / f"{slug}.json"
            if cache.exists():
                body = strip_tags(
                    json.loads(cache.read_text()).get("details", {}).get("body", "")
                )
                hit = find_month_year(body)
                if hit:
                    source = "publication_body"
        if not hit:
            hit, source = (None, pub_year), "publication_year"

        month, year = hit
        rows.append(
            {
                "publication_slug": slug,
                "department_slug": dept,
                "publication_year": pub_year,
                "snapshot_month": month,
                "snapshot_year": year,
                "snapshot_source": source,
                "snapshot_label": (
                    f"{MONTH_NAMES[month - 1]} {year}" if month else f"{year}"
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["publication_year", "department_slug"])


def main() -> int:
    frame = resolve()
    frame.to_csv(SNAPSHOTS_PATH, index=False)
    print(f"wrote {SNAPSHOTS_PATH} ({len(frame)} publications)")
    print("\nsnapshot label by publication year:")
    print(
        pd.crosstab(frame["publication_year"], frame["snapshot_label"]).to_string()
    )
    print("\nresolution source:")
    print(frame["snapshot_source"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
