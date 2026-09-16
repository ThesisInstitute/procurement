"""Loud failures for results that would otherwise be silently empty.

WHY THIS MODULE EXISTS. A real bug in this workstream, live until 2026-09-15:
`report.py` mapped the GovTech workbook's abbreviated ratings (HS / S / MS / MU
/ U / HU) with `scales.to_six_point`, which refuses abbreviations by design
because those letters collide with other World Bank code sets. Every row mapped
to None, an inner join and a `dropna` reduced the table to zero rows, and the
report published "n = 0, exact agreement nan%" with an empty table under a
heading that claimed a verified result. Nothing raised. Nothing failed. The
number was simply absent and the prose around it still asserted it.

That is the failure mode this module exists to make impossible: a pipeline stage
that returns nothing, and a downstream stage that formats the nothing. An empty
result here is not a small result, it is a broken one, and a report is a
deliverable, so it must fail rather than publish a hole.

Every guard raises `EmptyResultError` with the context needed to debug it. None
of them is a validity check on the numbers; they only assert that a computation
produced any rows at all.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class EmptyResultError(RuntimeError):
    """A computation that must produce rows produced none."""


def require_rows(df: pd.DataFrame, name: str, minimum: int = 1,
                 hint: str = "") -> pd.DataFrame:
    """Return `df`, or raise if it has fewer than `minimum` rows."""
    n = 0 if df is None else len(df)
    if n < minimum:
        raise EmptyResultError(
            f"{name}: expected at least {minimum} row(s), got {n}."
            + (f" {hint}" if hint else ""))
    return df


def require_finite(value: float, name: str, hint: str = "") -> float:
    """Return `value`, or raise if it is NaN or infinite.

    A rate computed from an empty frame comes back as NaN and formats as "nan",
    which is exactly what reached the published report. This turns that into a
    failure at the point of computation.
    """
    v = float(value)
    if not np.isfinite(v):
        raise EmptyResultError(
            f"{name}: expected a finite value, got {v!r}."
            + (f" {hint}" if hint else ""))
    return v


def require_mapped(original: pd.Series, mapped: pd.Series, name: str,
                   min_share: float = 0.5, hint: str = "") -> pd.Series:
    """Assert that a value mapping did not silently discard most of a column.

    `min_share` is the share of ORIGINALLY NON-NULL values that must survive the
    mapping. This is the guard aimed directly at the abbreviation bug: the
    column was full, the mapping returned None for every row, and the share
    would have been 0.0.
    """
    n_in = int(original.notna().sum())
    if n_in == 0:
        raise EmptyResultError(
            f"{name}: the source column is entirely null before mapping."
            + (f" {hint}" if hint else ""))
    n_out = int(mapped.notna().sum())
    share = n_out / n_in
    if share < min_share:
        raise EmptyResultError(
            f"{name}: mapping kept {n_out} of {n_in} non-null values "
            f"({share:.1%}), below the required {min_share:.0%}. "
            f"Sample of unmapped inputs: "
            f"{sorted(set(original[mapped.isna() & original.notna()].astype(str)))[:8]}."
            + (f" {hint}" if hint else ""))
    return mapped


def require_overlap(left_keys, right_keys, name: str, minimum: int = 1,
                    hint: str = "") -> int:
    """Assert two key sets actually intersect before an inner join uses them."""
    n = len(set(left_keys) & set(right_keys))
    if n < minimum:
        raise EmptyResultError(
            f"{name}: expected at least {minimum} shared key(s), got {n}."
            + (f" {hint}" if hint else ""))
    return n
