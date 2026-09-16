"""Robust table reading for GMPP spreadsheets.

Filenames, encodings, sheet names, preamble rows, layout and header spellings
all vary across 2013 to 2026. `read_raw` returns the best raw (header-free)
block found in a file; `gmpp.src.orientation.normalise` then turns it into a
project-per-row frame. Every parsing decision is reported in `ReadResult.notes`
so nothing is silent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# Tried in order. Guessing a DOS code page here was tried and made things worse:
# it recovered the September 2017 MOD file's pound signs and broke the September
# 2019 MoJ file's, turning every one of its money cells into "u580.50". The
# encodings stay as they are and the mis-decoded currency bytes are absorbed in
# `gmpp.src.parsing.is_prose`, which is where the damage actually lands.
ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")

# Tokens that appear in GMPP header rows. Used only to locate the header row
# inside a sheet that may carry title or preamble rows above it.
HEADER_TOKENS = (
    "project", "department", "gmpp", "dca", "delivery confidence",
    "whole life", "whole-life", "baseline", "forecast", "variance",
    "start date", "end date", "narrative", "category", "annual report",
    "budget", "benefit", "schedule", "description", "rag rating",
)


@dataclass
class ReadResult:
    raw: pd.DataFrame
    path: Path
    sheet: str | None = None
    encoding: str | None = None
    notes: list[str] = field(default_factory=list)


def _score_header(values: list) -> int:
    joined = " | ".join(str(v).lower() for v in values if v is not None)
    if joined.strip(" |") in ("", "nan"):
        return -1
    hits = sum(1 for tok in HEADER_TOKENS if tok in joined)
    non_empty = sum(1 for v in values if str(v).strip() not in ("", "nan", "None"))
    return hits * 10 + min(non_empty, 40)


def _pick_header(raw: pd.DataFrame, max_scan: int = 12) -> int:
    best_row, best_score = 0, -2
    for r in range(min(max_scan, len(raw))):
        score = _score_header(list(raw.iloc[r].values))
        if score > best_score:
            best_row, best_score = r, score
    return best_row


def _finalise(raw: pd.DataFrame, header_row: int) -> pd.DataFrame:
    header = [str(v).strip() for v in raw.iloc[header_row].values]
    body = raw.iloc[header_row + 1 :].copy()
    seen: dict[str, int] = {}
    cols: list[str] = []
    for i, name in enumerate(header):
        name = re.sub(r"\s+", " ", name).strip()
        if name in ("", "nan", "None"):
            name = f"_unnamed_{i}"
        if name in seen:
            seen[name] += 1
            name = f"{name}__{seen[name]}"
        else:
            seen[name] = 0
        cols.append(name)
    body.columns = cols
    return body.dropna(how="all").reset_index(drop=True)


def _read_csv_raw(path: Path) -> tuple[pd.DataFrame, str]:
    last: Exception | None = None
    for enc in ENCODINGS:
        try:
            raw = pd.read_csv(
                path,
                header=None,
                dtype=str,
                encoding=enc,
                engine="python",
                on_bad_lines="skip",
                skip_blank_lines=False,
            )
            return raw, enc
        except Exception as exc:  # noqa: BLE001 - try the next encoding
            last = exc
    raise RuntimeError(f"cannot decode {path}: {last}")


def _excel_sheets(path: Path) -> dict[str, pd.DataFrame]:
    suffix = path.suffix.lower()
    engines = {
        ".xlsx": ["openpyxl"],
        ".xls": ["xlrd", "openpyxl"],
        ".ods": ["odf"],
    }.get(suffix, ["openpyxl", "odf", "xlrd"])
    last: Exception | None = None
    for engine in engines:
        try:
            return pd.read_excel(
                path, sheet_name=None, header=None, dtype=str, engine=engine
            )
        except Exception as exc:  # noqa: BLE001 - try the next engine
            last = exc
    # Some ".xls" attachments are really CSV, and reading them as text is right.
    # A file that is really a ZIP, though, is a workbook no engine could open,
    # and parsing its compressed bytes as text produces rows of binary noise
    # that look like a successful read. One file in the corpus does this: the
    # March 2025 NISTA workbook, whose first cell comes back as "PK\x03\x04\x14".
    # Refuse it, so the build log records a failure instead of the noise.
    with open(path, "rb") as handle:
        magic = handle.read(4)
    if magic[:2] in (b"PK", b"\xd0\xcf"):
        raise ValueError(
            f"{path.name} is a workbook no available engine could open "
            f"({type(last).__name__}: {last})"
        )
    raw, _enc = _read_csv_raw(path)
    return {"__as_csv__": raw}


def _sheet_score(raw: pd.DataFrame) -> int:
    if raw is None or raw.empty:
        return -100
    head_score = max(
        (_score_header(list(raw.iloc[r].values)) for r in range(min(8, len(raw)))),
        default=-1,
    )
    col_score = _score_header(list(raw.iloc[:, 0].values)) if raw.shape[1] else -1
    # The size bonus is a tie-breaker, not a vote. It used to be large enough to
    # outweigh the header evidence: in seven of the September 2019 workbooks it
    # selected the analytical `SourceTable` back-series over the department's
    # own published table, purely because that sheet is bigger. Capped well
    # below the header score so a sheet that looks like the published table
    # always wins.
    return max(head_score, col_score) * 10 + min(
        raw.shape[0] * raw.shape[1] // 200, 5
    )


def read_raw(path: Path) -> ReadResult:
    path = Path(path)
    notes: list[str] = []
    if path.suffix.lower() == ".csv":
        raw, enc = _read_csv_raw(path)
        return ReadResult(raw, path, None, enc, notes)

    sheets = _excel_sheets(path)
    best_name, best_raw, best_score = None, None, -1000
    for name, raw in sheets.items():
        score = _sheet_score(raw)
        if score > best_score:
            best_name, best_raw, best_score = name, raw, score
    if best_raw is None:
        raise RuntimeError(f"no usable sheet in {path}")
    if len(sheets) > 1:
        notes.append(f"chose sheet '{best_name}' of {len(sheets)}: {sorted(sheets)}")
    return ReadResult(best_raw, path, best_name, None, notes)
