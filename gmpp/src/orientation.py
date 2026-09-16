"""Detect and normalise the two GMPP file layouts.

Observed directly in the downloaded files on 2026-09-15:

* 2013 to 2020 publications are TRANSPOSED. Column 0 holds the field names
  ("Project name", "Department", "MPA RAG rating", ...) and every other column
  is one project. Example: `data/raw/gmpp/2019/mod/MoD_Government_Major_
  Projects_Portfolio_data_September_2018.csv` starts `Project Name,A400M,
  Armed Forces People Programme,...`.
* 2021 to 2024 publications and both NISTA annual-report files are WIDE, one
  row per project. Example: `.../2024/mod/MOD_..._AR_Data_March_2024.csv`
  starts `GMPP ID Number,Project Name,Department,Annual Report Category,...`.

`normalise` returns a wide frame either way, plus the layout it detected.
"""
from __future__ import annotations

import re

import pandas as pd

# Field labels that appear in column 0 of a transposed file.
FIELD_LABEL_TOKENS = (
    "project name", "department", "rag rating", "delivery confidence",
    "whole life", "start date", "end date", "narrative", "baseline",
    "forecast", "variance", "description", "gmpp id", "category",
    "senior responsible", "benefits", "commentary",
)


def _looks_like_field_label(value: object) -> bool:
    text = re.sub(r"\s+", " ", str(value)).strip().lower()
    return any(tok in text for tok in FIELD_LABEL_TOKENS)


def detect_layout(raw: pd.DataFrame) -> str:
    """'wide' (one row per project) or 'transposed' (one row per field)."""
    if raw.empty or raw.shape[1] < 2:
        return "wide"
    first_col = raw.iloc[:, 0].astype(str).tolist()
    header_row = [str(v) for v in raw.iloc[0].tolist()]

    col_hits = sum(1 for v in first_col[:40] if _looks_like_field_label(v))
    row_hits = sum(1 for v in header_row[:60] if _looks_like_field_label(v))

    # A transposed file has many field labels running down column 0 and almost
    # none running across row 0 (row 0 is project names or GMPP ids).
    if col_hits >= 4 and col_hits > row_hits:
        return "transposed"
    return "wide"


def transpose_to_wide(raw: pd.DataFrame) -> pd.DataFrame:
    """Turn a field-per-row frame into a project-per-row frame."""
    body = raw.dropna(how="all").copy()
    labels = [re.sub(r"\s+", " ", str(v)).strip() for v in body.iloc[:, 0]]
    values = body.iloc[:, 1:]
    wide = values.T
    seen: dict[str, int] = {}
    cols: list[str] = []
    for i, name in enumerate(labels):
        if name in ("", "nan", "None"):
            name = f"_unnamed_{i}"
        if name in seen:
            seen[name] += 1
            name = f"{name}__{seen[name]}"
        else:
            seen[name] = 0
        cols.append(name)
    wide.columns = cols
    wide = wide.dropna(how="all").reset_index(drop=True)
    return wide


def normalise(raw: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    layout = detect_layout(raw)
    if layout == "transposed":
        return transpose_to_wide(raw), layout
    from .readers import _finalise, _pick_header  # local import avoids a cycle

    header_row = _pick_header(raw)
    return _finalise(raw, header_row), layout
