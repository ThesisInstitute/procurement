"""Parsers for the published GMPP money, percentage and date cells.

The money columns are free text, not numbers, and carry several non-numeric
conventions that must not be read as values. All of these were observed in the
downloaded files on 2026-09-15:

* Freedom of Information withholding, in two spellings. The department files up
  to March 2024 write "Exempt under Section 43 of the Freedom of Information Act
  2000 (Commercial Interests)". The two NISTA files write the bare
  "Section 43 - Commercial interests". A naive number-grab reads the latter as
  43, which is why every exemption pattern is rejected before any digits are
  looked at.
* Unavailability prose: "The GMPP project is still at the planning stage
  (Pre-SOC or equivalent) and is not yet in a position to provide cost/schedule
  information".
* Ranges, only in the two NISTA files: "Low: 2,750.00, Mid: 2,820.00, High:
  3,100.00". `parse_money` returns the mid point of such a range and
  `money_kind` reports that it was a range, so range-valued project-years can be
  excluded from growth measures if wanted.
"""
from __future__ import annotations

import re

import pandas as pd

_NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

# Text that means "no value published". Checked before any digits are read.
_REJECT_PATTERNS = (
    re.compile(r"\bexempt", re.I),
    re.compile(r"\bsections?\s*\d", re.I),
    re.compile(r"freedom of information", re.I),
    re.compile(r"not (?:yet )?in a position", re.I),
    re.compile(r"planning stage", re.I),
    re.compile(r"commercial interests", re.I),
    re.compile(r"national security", re.I),
    re.compile(r"\bnot applicable\b", re.I),
    re.compile(r"intended for future publication", re.I),
    re.compile(r"formulation of government policy", re.I),
    re.compile(r"international relations", re.I),
    re.compile(r"law enforcement", re.I),
    re.compile(r"\bdefence\b", re.I),
    re.compile(r"\bno dca\b", re.I),
    re.compile(r"\bto be confirmed\b", re.I),
)

_BLANKS = {"", "nan", "none", "n/a", "na", "-", "tbc", "null", "#n/a", "not known"}

# A numeric cell may carry currency signs, a percent sign, thousands separators,
# bracketed negatives and a trailing unit. Anything else alphabetic means the
# cell is prose, not a number. The 2016 publications write "Budget variance less
# than 5%." in the variance column, which a plain number-grab reads as 5.
_DECORATION_RE = re.compile(
    r"[\d.,()+\-%\s\u00a3\u00c2\u0153$]|^(?:m|mn|bn|k|million|billion)$", re.I
)
_UNIT_TAIL_RE = re.compile(r"(?<=\d)\s*(?:m|mn|bn|k|million|billion)\b\.?$", re.I)


def is_prose(text: str) -> bool:
    """True when a cell carries words rather than a number."""
    stripped = _UNIT_TAIL_RE.sub("", text).strip()
    residue = re.sub(
        # Digits and the punctuation a number may carry, plus every character a
        # pound sign turns into when a file's encoding is guessed wrongly:
        # U+00A3 itself, and U+00C2, U+0153, U+00FF and U+00FA from readings of
        # the same byte under a different code page. Without U+00FF the single
        # cell "\u00ff9941.96" in the September 2017 MOD file read as prose and
        # a GBP 9.94bn whole-life cost vanished from the panel.
        r"[\d.,()+\-%\s\u00a3\u00c2\u0153\u00ff\u00fa$\u2264\u2265<>~]",
        "",
        stripped,
    )
    return bool(residue)


_LOW_RE = re.compile(r"low\s*[:=]\s*(-?\d[\d,]*(?:\.\d+)?)", re.I)
_MID_RE = re.compile(r"mid\s*[:=]\s*(-?\d[\d,]*(?:\.\d+)?)", re.I)
_DATE_TOKEN = r"(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}-\d{2}-\d{2})"
_MID_RE_DATE = re.compile(rf"mid\s*[:=]\s*{_DATE_TOKEN}", re.I)
_LOW_RE_DATE = re.compile(rf"low\s*[:=]\s*{_DATE_TOKEN}", re.I)
_HIGH_RE_DATE = re.compile(rf"high\s*[:=]\s*{_DATE_TOKEN}", re.I)
_HIGH_RE = re.compile(r"high\s*[:=]\s*(-?\d[\d,]*(?:\.\d+)?)", re.I)


def _clean(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).replace(" ", " ").replace("−", "-")
    text = re.sub(r"\s+", " ", text).strip()
    if text.lower() in _BLANKS:
        return None
    return text


def is_withheld(value: object) -> bool:
    text = _clean(value)
    if text is None:
        return False
    return any(p.search(text) for p in _REJECT_PATTERNS)


def money_kind(value: object) -> str:
    """'value', 'range', 'withheld', or 'missing'."""
    text = _clean(value)
    if text is None:
        return "missing"
    if is_withheld(text):
        return "withheld"
    if _LOW_RE.search(text) or _MID_RE.search(text):
        return "range"
    if is_prose(text):
        return "prose"
    return "value" if _NUM_RE.search(text) else "missing"


def _to_float(token: str) -> float | None:
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def parse_money(value: object) -> float | None:
    """GBP million as published, or None when no number is published.

    A Low/Mid/High range returns the mid point, falling back to the mean of the
    low and high, then to the low.
    """
    text = _clean(value)
    if text is None or is_withheld(text):
        return None

    mid = _MID_RE.search(text)
    if mid:
        return _to_float(mid.group(1))
    low, high = _LOW_RE.search(text), _HIGH_RE.search(text)
    if low and high:
        a, b = _to_float(low.group(1)), _to_float(high.group(1))
        return (a + b) / 2 if a is not None and b is not None else (a if a is not None else b)
    if low:
        return _to_float(low.group(1))

    if is_prose(text):
        return None

    negative = text.startswith("(") and text.endswith(")")
    body = text.replace("£", "").replace("$", "")
    m = _NUM_RE.search(body)
    if not m:
        return None
    out = _to_float(m.group(0))
    if out is None:
        return None
    return -out if negative else out


def parse_percent_parts(value: object) -> tuple[float | None, bool]:
    """(the number as written, whether it is ambiguous between the conventions).

    Two conventions are mixed in the files: "5%" and the spreadsheet-native
    0.05 for the same 5 per cent. A cell written without a percent sign, with a
    decimal point, and with a magnitude of at most 1 could be either: the
    fraction 0.0064, or a genuinely small variance of 0.64 per cent. Both occur.
    Nothing in the cell itself settles it, so this returns the number as written
    together with the fact that it is ambiguous, and the caller resolves it
    against the baseline and forecast published in the same row.
    """
    text = _clean(value)
    if text is None or is_withheld(text):
        return None, False
    if is_prose(text):
        return None, False
    has_sign = "%" in text
    number = parse_money(text.replace("%", ""))
    if number is None:
        return None, False
    ambiguous = not has_sign and abs(number) <= 1.0 and "." in text
    return number, ambiguous


def parse_percent(value: object) -> float | None:
    """A published variance as a percentage, resolving ambiguity by the majority.

    The fraction reading is right far more often than not (1,181 of the 1,201
    ambiguous cells that the published baseline and forecast can settle, checked
    on 2026-09-16), so it is the fallback when nothing else settles the cell.
    `gmpp.src.panel` settles it from the row where it can, and only falls back
    here.
    """
    number, ambiguous = parse_percent_parts(value)
    if number is None:
        return None
    return number * 100.0 if ambiguous else number


_DAY_FIRST_FORMATS = (
    "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y",
)
_MONTH_FIRST_FORMATS = (
    "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m.%d.%Y",
)
_UNAMBIGUOUS_FORMATS = (
    "%Y-%m-%d", "%d %B %Y", "%B %Y", "%b-%y", "%d %b %Y",
    "%Y-%m-%d %H:%M:%S", "%m/%Y",
)

_SLASH_DATE_RE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$")
# "00:00:00" and friends: a time with no date at all.
_TIME_ONLY_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?$")


def detect_date_order(values) -> str:
    """'day_first' or 'month_first' for a column or file of dates.

    Most published files write dates day first, but three of the 196 panel
    source files do not (BIS September 2012, FCO September 2013 and FCO
    September 2016), and reading those day first silently transposes the day and
    the month on every cell where both are at most 12. The convention is decided
    per file from the cells that settle it: a first component above 12 proves
    day first, a second component above 12 proves month first. Day first is the
    default when nothing settles it, because it is the majority convention.
    """
    day_first_proof = month_first_proof = 0
    for value in values:
        text = _clean(value)
        if text is None:
            continue
        match = _SLASH_DATE_RE.match(text)
        if not match:
            continue
        first, second = int(match.group(1)), int(match.group(2))
        if first > 12 >= second:
            day_first_proof += 1
        elif second > 12 >= first:
            month_first_proof += 1
    if month_first_proof > day_first_proof:
        return "month_first"
    return "day_first"


def parse_date(value: object, order: str = "day_first") -> pd.Timestamp | None:
    """Parse a published date.

    `order` decides how an ambiguous numeric date is read; use
    `detect_date_order` on the whole column or file to choose it. A Low/Mid/High
    range, which the two NISTA files use for dates as well as for money, resolves
    to its mid point, matching `parse_money`.
    """
    text = _clean(value)
    if text is None or is_withheld(text):
        return None

    # The NISTA files publish some end dates as a Low/Mid/High range, for
    # example "Low: 31/03/2025, Mid: 31/03/2025, High: 31/03/2025".
    for pattern in (_MID_RE_DATE, _LOW_RE_DATE, _HIGH_RE_DATE):
        found = pattern.search(text)
        if found:
            return parse_date(found.group(1), order=order)

    ordered = (
        _MONTH_FIRST_FORMATS if order == "month_first" else _DAY_FIRST_FORMATS
    )
    for fmt in _UNAMBIGUOUS_FORMATS + ordered:
        try:
            return pd.Timestamp(pd.to_datetime(text, format=fmt))
        except (ValueError, TypeError):
            continue
    # Fall back to the other order before giving up, so a stray cell written the
    # other way round is still read rather than dropped.
    other = _DAY_FIRST_FORMATS if order == "month_first" else _MONTH_FIRST_FORMATS
    for fmt in other:
        try:
            return pd.Timestamp(pd.to_datetime(text, format=fmt))
        except (ValueError, TypeError):
            continue
    # A cell that carries a time and no date, "00:00:00", is not a date. pandas
    # reads it as that time TODAY, which passes the year guard below and lands a
    # fabricated end date in the panel; seven rows of the IPA back-series carry
    # exactly that string. Rejected before the permissive parse.
    if _TIME_ONLY_RE.match(text):
        return None
    try:
        out = pd.to_datetime(
            text, dayfirst=(order == "day_first"), errors="coerce"
        )
    except Exception:  # noqa: BLE001 - pandas raises several exception types
        return None
    if pd.isna(out):
        return None
    stamp = pd.Timestamp(out)
    # Guard against a stray number being read as a date: the portfolio runs from
    # the 1990s to the 2090s and anything outside that is a parse artefact.
    if not (1990 <= stamp.year <= 2099):
        return None
    return stamp
