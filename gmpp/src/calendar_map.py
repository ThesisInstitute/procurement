"""The GMPP snapshot calendar: which portfolio position each publication carries.

The publication year is not the snapshot date. Sources, all read on 2026-09-15:

* The transparency policy PDF (`Transparency_policy_and_exemptions_guidance_
  text_for_publication_230513.pdf`, downloaded from gov.uk) states: "The data
  for publication in May 2013 will be drawn from same period, the second quarter
  of 2012/13. The annual updates will similarly be drawn from the second quarter
  of the relevant financial year" and "The MPA RAG rating six months in arrears
  ie GMPP Q2 12/13". Q2 of a UK financial year ends 30 September.
* Attachment titles state the month directly from the 2014 publication onward
  ("MOD Government Major Project Portfolio data, September 2014").
* The two NISTA publications state the date in the publication body: the
  2024-25 report says "The GMPP data presented here was reported to the IPA by
  departments on 31 March 2025"; the 2025-26 report says "reported to the NISTA
  by departments on 31 March 2026".

The September-to-March move happened between the 2020 and 2021 publications, so
there is no snapshot between September 2019 and March 2021 and that one gap is
18 months, not 12. `interval_months` reports the true gap for every transition
and the scoring restricts to 12-month transitions where stated.
"""
from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache

import pandas as pd

# publication year -> snapshot date (the position the file describes)
SNAPSHOT_DATES: dict[int, dt.date] = {
    2013: dt.date(2012, 9, 30),
    2014: dt.date(2013, 9, 30),
    2015: dt.date(2014, 9, 30),
    2016: dt.date(2015, 9, 30),
    2017: dt.date(2016, 9, 30),
    2018: dt.date(2017, 9, 30),
    2019: dt.date(2018, 9, 30),
    2020: dt.date(2019, 9, 30),
    2021: dt.date(2021, 3, 31),
    2022: dt.date(2022, 3, 31),
    2023: dt.date(2023, 3, 31),
    2024: dt.date(2024, 3, 31),
}

# The two NISTA annual-report files are consolidated across departments and are
# keyed by publication slug rather than by year, because both sit under 2025.
NISTA_SNAPSHOT_DATES: dict[str, dt.date] = {
    "nista-annual-report-2024-2025": dt.date(2025, 3, 31),
    "nista-major-projects-annual-report-2025-26": dt.date(2026, 3, 31),
}

SNAPSHOT_PROVENANCE = {
    2013: "transparency policy PDF: Q2 FY2012/13",
    **{y: "attachment title" for y in range(2014, 2025)},
    2025: "publication body: reported by departments on 31 March 2025",
    2026: "publication body: reported by departments on 31 March 2026",
}

# Prices. Only the March 2026 file is published in real prices; every other file
# is nominal. Read from the headers: the 2025-26 NISTA file spells its money
# columns "Financial Year Baseline (GBPm, Presented in 2024/25 Real Prices)"
# while every earlier file spells them "(GBPm)".
REAL_PRICE_SNAPSHOTS = frozenset({dt.date(2026, 3, 31)})


# Dating each publication.
#
# The strongest evidence is the publication's own statement of the position it
# carries, which `gmpp.src.snapshots` extracts per publication from, in order,
# the attachment title, the attachment filename and the publication body prose,
# and writes to `data/raw/gmpp/snapshots.csv`. That is the primary source here.
#
# It is accepted only when the month it names is one the portfolio actually
# reports on. Observed across all 194 data publications on 2026-09-15: 104
# resolve to September, 74 to March, 15 name no month at all, and exactly one
# names a different month. That one is the 2013 Home Office publication, whose
# attachments are titled "MPA dashboard 14 May 2013"; May 2013 is the date the
# dashboard was published, not the position it reports. Rejecting off-calendar
# months and falling back to the year table dates it September 2012, with its
# fifteen siblings.
#
# An earlier version of this module preferred a financial year parsed out of a
# money-column header. That was wrong: its column filter also matched the
# narrative header "Departmental narrative on budget/forecast variance for
# 2018/19", which the September 2019 files carry as a leftover from the previous
# year's template while heading their own money columns "Financial Year Baseline
# (GBPm)" with no year at all. Every September 2019 row was therefore stamped
# September 2018. The financial-year reading is kept below as an independent
# cross-check only, tightened to exclude narrative columns, and it is never
# allowed to decide the date.
REPORTING_MONTHS = frozenset({3, 9})

FY_HEADER_RE = re.compile(r"\b(20\d{2})\s*[/\-]\s*(\d{2,4})\b")

_MONEY_TOKENS = ("budget", "forecast", "baseline", "variance")
# A header that describes prose about the money, not the money itself.
_NARRATIVE_TOKENS = ("narrative", "commentary", "comment", "explanation")
# "Financial Year Baseline (GBPm, Presented in 2024/25 Real Prices)" in the
# March 2026 NISTA file names a price base, not the position's financial year.
_PRICE_BASE_TOKENS = ("real price", "real term", "price base")


def snapshot_from_financial_year(headers: "list[str]") -> dt.date | None:
    """Snapshot implied by a financial year named in a money column header.

    Cross-check only. A header qualifies when it names a money quantity and is
    not a narrative column about that quantity. The snapshot is quarter two of
    the financial year named, which ends 30 September of its first calendar
    year, per the transparency policy quoted above.
    """
    for header in headers:
        low = str(header).lower()
        if not any(token in low for token in _MONEY_TOKENS):
            continue
        if any(token in low for token in _NARRATIVE_TOKENS):
            continue
        if any(token in low for token in _PRICE_BASE_TOKENS):
            continue
        match = FY_HEADER_RE.search(str(header))
        if not match:
            continue
        start_year = int(match.group(1))
        if 2011 <= start_year <= 2030:
            return dt.date(start_year, 9, 30)
    return None


@lru_cache(maxsize=1)
def _published_positions() -> dict[str, dt.date]:
    """publication slug -> the position it states it carries, where on-calendar."""
    from .paths import RAW_DIR

    path = RAW_DIR / "snapshots.csv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    out: dict[str, dt.date] = {}
    for row in frame.itertuples():
        month, year = row.snapshot_month, row.snapshot_year
        if pd.isna(month) or pd.isna(year):
            continue
        month, year = int(month), int(year)
        if month not in REPORTING_MONTHS:
            continue
        day = 31 if month == 3 else 30
        out[row.publication_slug] = dt.date(year, month, day)
    return out


def snapshot_for(
    publication_year: int,
    publication_slug: str,
    headers: "list[str] | None" = None,
) -> dt.date | None:
    """The portfolio position a publication carries.

    `headers` is accepted for the caller's convenience and used only by
    `snapshot_disagreement`; it never decides the date.
    """
    if publication_slug in NISTA_SNAPSHOT_DATES:
        return NISTA_SNAPSHOT_DATES[publication_slug]
    stated = _published_positions().get(publication_slug)
    if stated is not None:
        return stated
    return SNAPSHOT_DATES.get(publication_year)


def snapshot_source_for(publication_year: int, publication_slug: str) -> str:
    if publication_slug in NISTA_SNAPSHOT_DATES:
        return "publication body"
    if publication_slug in _published_positions():
        return "publication statement (title, filename or body)"
    return "publication-year table"


def snapshot_disagreement(
    snapshot: dt.date, headers: "list[str] | None"
) -> str:
    """Cross-check: does the file's own money-column financial year agree?

    Returns "" when there is nothing to check (no financial year in any money
    header, which is every file from the March 2021 snapshot on) or when the two
    agree, and a description otherwise.
    """
    if not headers:
        return ""
    from_fy = snapshot_from_financial_year([str(h) for h in headers])
    if from_fy is None:
        return ""
    if from_fy == snapshot:
        return ""
    return f"money-column financial year implies {from_fy}"


def ordered_snapshots() -> list[dt.date]:
    return sorted(set(SNAPSHOT_DATES.values()) | set(NISTA_SNAPSHOT_DATES.values()))


def interval_months(earlier: dt.date, later: dt.date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def next_snapshot(date: dt.date) -> dt.date | None:
    order = ordered_snapshots()
    if date not in order:
        return None
    i = order.index(date)
    return order[i + 1] if i + 1 < len(order) else None


def snapshot_offset(date: dt.date, steps: int) -> dt.date | None:
    order = ordered_snapshots()
    if date not in order:
        return None
    i = order.index(date) + steps
    return order[i] if 0 <= i < len(order) else None
