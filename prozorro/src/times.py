"""One way to turn Prozorro timestamps into datetimes.

Prozorro mixes two ISO spellings in the same field: `2021-12-24T14:21:59+02:00`
and `2020-11-12T16:54:16.166801+02:00`, and the offset is +02:00 or +03:00
depending on Ukrainian summer time.  `pd.to_datetime` infers a single format
from the first element, so a column that happens to start with a
whole-second stamp silently coerces every microsecond stamp to NaT.  On the
real sample that was 5,298 of 6,480 tenders, and because a NaN cutoff makes
every as-of history count return zero, it would have zeroed the history
features for most of the panel without raising anything.

`format="ISO8601"` parses each element on its own terms, which is what these
helpers exist to enforce.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def to_utc(values) -> pd.Series:
    """Parse a column of mixed-precision ISO timestamps to tz-aware UTC."""
    return pd.to_datetime(values, utc=True, errors="coerce", format="ISO8601")


def to_seconds(values) -> np.ndarray:
    """Seconds since the epoch as float, NaN where the timestamp is missing."""
    return (to_utc(values) - EPOCH).dt.total_seconds().to_numpy(dtype=float)


def to_kyiv_date(values) -> pd.Series:
    """The calendar date in Ukrainian local time, as a YYYY-MM-DD string."""
    return to_utc(values).dt.tz_convert("Europe/Kyiv").dt.strftime("%Y-%m-%d")
