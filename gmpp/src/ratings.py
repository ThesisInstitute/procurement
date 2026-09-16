"""Harmonise published Delivery Confidence Assessment strings.

Every mapped string below was observed in the downloaded CSVs on 2026-09-15 by
scanning the DCA column of all 196 CSV files. Two scales are in use, and the
scale in force is stated in the published header itself:

* Snapshots September 2012 to March 2021 (publication years 2013 to 2021) carry
  "using a five-point scale, Red - Amber/Red - Amber - Amber/Green - Green".
* Snapshots March 2022 to March 2024 (publication years 2022 to 2024) carry
  "using a three-point scale, Red - Amber - Green".
* The two NISTA files (March 2025 and March 2026) state no scale in the header;
  only GREEN, AMBER and RED appear in their data, so they are three-point.

Anything that is not a rating is kept as its own category rather than dropped:
EXEMPT (withheld under the Freedom of Information Act), RESET (the project was
rebaselined and not rated), NOT_RATED (an explicit "No DCA" or "Not Applicable"
or a departmental statement that the information is unavailable), and MISSING.
"""
from __future__ import annotations

import re

FIVE_POINT = ["Green", "Amber/Green", "Amber", "Amber/Red", "Red"]
THREE_POINT = ["Green", "Amber", "Red"]

# Rank: 0 is the most confident rating. Used for the mapping-free AUC and
# Spearman tests, which need only the order, not a probability.
FIVE_POINT_RANK = {name: i for i, name in enumerate(FIVE_POINT)}
THREE_POINT_RANK = {name: i for i, name in enumerate(THREE_POINT)}

NON_RATING = ("EXEMPT", "RESET", "NOT_RATED", "MISSING")

# Publication years whose header states the five-point scale. Read from the
# header text of the published files, not assumed.
FIVE_POINT_PUBLICATION_YEARS = frozenset(range(2013, 2022))

_NOT_RATED_MARKERS = (
    "no dca",
    "not applicable",
    "not in a position to provide",
    "still at the planning stage",
    "early planning gmpp project",
    "prevented the ipa from providing",
    "not yet in a position",
    "n/a",
)


# The exact compact spellings of every rating, tested before any substring
# marker so that a cell which simply IS a rating can never be bucketed as
# something else.
_EXACT_RATINGS = {
    "amber/red": "Amber/Red",
    "red/amber": "Amber/Red",
    "amber/green": "Amber/Green",
    "green/amber": "Amber/Green",
    "amber": "Amber",
    "green": "Green",
    "red": "Red",
}


def clean(value: object) -> str:
    text = str(value) if value is not None else ""
    text = text.replace(" ", " ").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def harmonise(value: object) -> str:
    """Published DCA string -> one of the scale labels or a NON_RATING label."""
    text = clean(value)
    if text == "" or text.lower() in ("nan", "none", "-"):
        return "MISSING"
    low = text.lower()

    # Normalise punctuation and spacing inside compound ratings so that
    # "Amber/ Red", "Amber/red" and "Amber / Red" all land on "Amber/Red".
    compact = re.sub(r"\s*/\s*", "/", low)
    compact = re.sub(r"\s*-\s*", "/", compact)
    compact = compact.strip(" .")

    # A cell that is exactly a rating is a rating, tested before the
    # not-rated markers. Those markers are substring tests, and "n/a" is a
    # substring of "green/amber", so the marker test run first silently
    # bucketed the spelling "Green/Amber" as NOT_RATED.
    if compact in _EXACT_RATINGS:
        return _EXACT_RATINGS[compact]

    if "exempt" in low or re.search(r"\bsection \d+", low):
        return "EXEMPT"
    if low.startswith("reset") or low == "reset":
        return "RESET"
    if any(marker in low for marker in _NOT_RATED_MARKERS):
        return "NOT_RATED"

    if compact in ("amber/red", "red/amber"):
        return "Amber/Red"
    if compact in ("amber/green", "green/amber"):
        return "Amber/Green"
    if compact == "amber":
        return "Amber"
    if compact == "green":
        return "Green"
    if compact == "red":
        return "Red"
    return "UNPARSED"


def scale_for_year(publication_year: int) -> str:
    return "five_point" if publication_year in FIVE_POINT_PUBLICATION_YEARS else "three_point"


def rank(rating: str, scale: str) -> float | None:
    """Ordinal rank of a rating within its scale; None for non-ratings.

    Ranks are NOT comparable across scales: "Amber" is the middle of five in the
    early era and the middle of three later, and the two eras are always scored
    separately.
    """
    table = FIVE_POINT_RANK if scale == "five_point" else THREE_POINT_RANK
    return float(table[rating]) if rating in table else None


def normalised_rank(rating: str, scale: str) -> float | None:
    """Rank rescaled to [0, 1], 0 = Green. Only for charts, never for scoring."""
    r = rank(rating, scale)
    if r is None:
        return None
    top = (len(FIVE_POINT) if scale == "five_point" else len(THREE_POINT)) - 1
    return r / top


# Implied probability that the project has no material problem, stated up front
# as the workstream brief requires. These are an assumption imposed on the
# published ratings, not something the IPA or NISTA ever published: neither body
# attaches a number to a colour. Every Brier result computed from them inherits
# that assumption, and the isotonic recalibration in `gmpp.src.score` exists to
# show what the ratings would be worth if the mapping were fitted instead.
IMPLIED_P_OK = {
    "five_point": {
        "Green": 0.90,
        "Amber/Green": 0.75,
        "Amber": 0.50,
        "Amber/Red": 0.25,
        "Red": 0.10,
    },
    "three_point": {"Green": 0.85, "Amber": 0.50, "Red": 0.15},
}


def implied_p_adverse(rating: str, scale: str) -> float | None:
    """Implied probability of the adverse outcome, i.e. 1 - P(no material problem)."""
    table = IMPLIED_P_OK[scale]
    if rating not in table:
        return None
    return 1.0 - table[rating]
