"""Rating scales as observed in the data on 2026-09-15.

OBSERVED, not assumed. The value counts below were produced by reading
data/raw/worldbank/ieg/IEG_World_Bank_Project_Performance_Ratings.csv
(12,598 rows, "As of Date" 09/13/2026) and the Projects API rating blocks.

SIX-POINT OUTCOME SCALE
Finances One IEG bulk CSV, column `Outcome`, observed value set (7 distinct):
    Highly Satisfactory          397
    Satisfactory                5629
    Moderately Satisfactory     3143
    Moderately Unsatisfactory   1214
    Unsatisfactory              1870
    Highly Unsatisfactory        194
    Not Rated                    151
`Quality at Entry`, `Quality of Supervision` and `Bank Performance` use the same
six points plus "Not Rated".

FOUR-POINT SCALES, TWO VINTAGES
`M&E Quality` in the bulk CSV uses exactly one of:
    High 138, Substantial 2045, Modest 2398, Negligible 488, Not Rated 7529
The Projects API `iegapi_evaluation_riskdo` (risk to development outcome) uses
BOTH that vocabulary AND an older one, observed in the same column:
    newer: Negligible, Modest, Substantial, High
    older: Negligible To Low, Moderate, Significant, High
Both are four-point ordinals. Treating them as the same scale is a LABELLED
INFERENCE based on their ordering, not something a World Bank dictionary read
this session states. `to_four_point` therefore reports which vintage a value
came from via `risk_vintage`, so a caller can refuse to pool them.

ABBREVIATIONS ARE OPT-IN
The GovTech workbook writes ratings as HS / S / MS / MU / U / HU. Those letters
collide with other World Bank code sets in the same tables: `esrc_ovrl_risk_rate`
uses S for Substantial, `envassesmentcategorycode` uses U, and ISO country codes
include MU and HU. Expanding abbreviations is therefore OFF by default and must
be requested explicitly with `allow_abbrev=True`, which only the GovTech loader
does. Passing a bare "S" without that flag returns None rather than 5.
"""
from __future__ import annotations

import pandas as pd

# Six-point ordinal outcome scale, 1 = worst. "Not Rated" maps to None.
SIX_POINT = {
    "Highly Unsatisfactory": 1,
    "Unsatisfactory": 2,
    "Moderately Unsatisfactory": 3,
    "Moderately Satisfactory": 4,
    "Satisfactory": 5,
    "Highly Satisfactory": 6,
}

# Four-point scales. Keys are the canonical spellings of both vintages.
FOUR_POINT_NEW = {"Negligible": 1, "Modest": 2, "Substantial": 3, "High": 4}
FOUR_POINT_OLD = {"Negligible To Low": 1, "Moderate": 2, "Significant": 3,
                  "High": 4}
FOUR_POINT = {**FOUR_POINT_OLD, **FOUR_POINT_NEW}

NOT_RATED = {"Not Rated", "Not Applicable", "NR", ""}

# Sentinels observed in the GovTech workbook's rating columns. None is a rating.
SENTINELS = {"-", "?", "#", "#MULTIVALUE", "NV", "NA", "N/A", "0", "0.0",
             "NR", "TBD", "NONE"}

# Long-form spellings, always safe to expand.
_LONG = {
    "highly satisfactory": "Highly Satisfactory",
    "satisfactory": "Satisfactory",
    "moderately satisfactory": "Moderately Satisfactory",
    "moderately unsatisfactory": "Moderately Unsatisfactory",
    "unsatisfactory": "Unsatisfactory",
    "highly unsatisfactory": "Highly Unsatisfactory",
    "negligible": "Negligible",
    "negligible to low": "Negligible To Low",
    "negligible-to-low": "Negligible To Low",
    "modest": "Modest",
    "moderate": "Moderate",
    "substantial": "Substantial",
    "significant": "Significant",
    "high": "High",
}

# Abbreviations, expanded ONLY when the caller asserts the column is a rating.
_ABBREV = {
    "hs": "Highly Satisfactory",
    "s": "Satisfactory",
    "ms": "Moderately Satisfactory",
    "mu": "Moderately Unsatisfactory",
    "u": "Unsatisfactory",
    "hu": "Highly Unsatisfactory",
}


def canonicalise(value, allow_abbrev: bool = False) -> str | None:
    """Trim and normalise a rating string. Unknown values return None.

    `allow_abbrev` expands HS/S/MS/MU/U/HU. Leave it False unless the column is
    known to be a rating column; see the module docstring for the collisions.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s or s in NOT_RATED or s.upper() in SENTINELS:
        return None
    low = s.lower()
    if low in _LONG:
        return _LONG[low]
    if allow_abbrev and low in _ABBREV:
        return _ABBREV[low]
    return None


def to_six_point(value, allow_abbrev: bool = False) -> float | None:
    """Map a rating to 1..6. None for Not Rated, unknown, or off-scale."""
    c = canonicalise(value, allow_abbrev=allow_abbrev)
    if c is None:
        return None
    return SIX_POINT.get(c)


def risk_vintage(value) -> str | None:
    """Which four-point vocabulary a value belongs to: 'new', 'old', or None.

    'High' is shared by both vintages and reports 'both'.
    """
    c = canonicalise(value)
    if c is None:
        return None
    in_new, in_old = c in FOUR_POINT_NEW, c in FOUR_POINT_OLD
    if in_new and in_old:
        return "both"
    if in_new:
        return "new"
    if in_old:
        return "old"
    return None


def to_four_point(value) -> float | None:
    """Map a four-point rating to 1..4, across BOTH observed vintages.

    LABELLED INFERENCE: the old vocabulary (Negligible to Low / Moderate /
    Significant / High) is aligned to the new one (Negligible / Modest /
    Substantial / High) by ordinal position. Use `risk_vintage` to separate them.
    """
    c = canonicalise(value)
    if c is None:
        return None
    return FOUR_POINT.get(c)


# The two cut points used in this workstream, both on the observed six-point
# scale. MS_OR_BETTER is the pre-registered label; S_OR_BETTER is the robustness
# check in src/analysis.py. Naming them here keeps both cuts in the tested
# module instead of as bare integers at two call sites.
MS_OR_BETTER = 4   # Moderately Satisfactory, Satisfactory, Highly Satisfactory
S_OR_BETTER = 5    # Satisfactory, Highly Satisfactory


def label_at_least(value, minimum: int = MS_OR_BETTER,
                   allow_abbrev: bool = False) -> float | None:
    """Binary label: is the six-point rating at least `minimum`?

    Returns None for "Not Rated", for an unrecognised value, and for a value
    that is not on the six-point scale at all. A four-point value such as
    "Modest" therefore returns None rather than silently scoring as a 2, which
    is the failure the separate scales exist to prevent.
    """
    if minimum not in range(1, 7):
        raise ValueError(f"minimum must be 1..6 on the six-point scale, "
                         f"got {minimum!r}")
    s = to_six_point(value, allow_abbrev=allow_abbrev)
    if s is None:
        return None
    return 1.0 if s >= minimum else 0.0


def satisfactory_label(value, allow_abbrev: bool = False) -> float | None:
    """The pre-registered binary target: outcome at least Moderately Satisfactory.

    On the observed six-point scale that is {Moderately Satisfactory,
    Satisfactory, Highly Satisfactory} -> 1, and {Moderately Unsatisfactory,
    Unsatisfactory, Highly Unsatisfactory} -> 0. "Not Rated" -> None (dropped).
    """
    return label_at_least(value, MS_OR_BETTER, allow_abbrev=allow_abbrev)


def series_six_point(s: pd.Series, allow_abbrev: bool = False) -> pd.Series:
    return s.map(lambda v: to_six_point(v, allow_abbrev=allow_abbrev)).astype(
        "Float64")


def series_satisfactory(s: pd.Series, allow_abbrev: bool = False) -> pd.Series:
    return s.map(lambda v: satisfactory_label(v, allow_abbrev=allow_abbrev)
                 ).astype("Float64")


def series_label_at_least(s: pd.Series, minimum: int = MS_OR_BETTER,
                          allow_abbrev: bool = False) -> pd.Series:
    return s.map(lambda v: label_at_least(v, minimum, allow_abbrev=allow_abbrev)
                 ).astype("Float64")
