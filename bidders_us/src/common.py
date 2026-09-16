"""Paths, the forward-chained split, and small helpers shared by bidders_us.

The split is the one used by usaspending/src/models.py: train FY2010 to FY2017,
validate FY2018 to FY2019, test FY2020 to FY2022, by base action fiscal year.
Nothing in this workstream selects anything on the test years.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
USA_SRC = ROOT / "usaspending" / "src"
if str(USA_SRC) not in sys.path:
    sys.path.insert(0, str(USA_SRC))

PANEL = ROOT / "data" / "raw" / "usaspending" / "panel.parquet"
HISTORY_SOURCE = ROOT / "data" / "raw" / "usaspending" / "history_source.parquet"
D_PARQUET_DIR = ROOT / "data" / "raw" / "usaspending" / "parquet"
RAW = ROOT / "data" / "raw" / "bidders_us"
RESULTS = ROOT / "bidders_us" / "results"
LOGS = ROOT / "bidders_us" / "logs"

TRAIN_FY = (2010, 2017)
VAL_FY = (2018, 2019)
TEST_FY = (2020, 2022)

LABELS = ("schedule_slip_gt90", "schedule_slip_gt365")
HORIZONS = (24, 36)
CELLS = [(lab, h) for lab in LABELS for h in HORIZONS]


def make_logger(name: str):
    LOGS.mkdir(parents=True, exist_ok=True)
    handle = open(LOGS / f"{name}.log", "a")

    def log(msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}"
        print(line, flush=True)
        handle.write(line + "\n")
        handle.flush()

    return log


def split_of(base_fy: pd.Series) -> pd.Series:
    """'train', 'val', 'test' or <NA> from the base action fiscal year."""
    fy = pd.to_numeric(base_fy, errors="coerce")
    out = pd.Series(pd.NA, index=base_fy.index, dtype="string")
    out[(fy >= TRAIN_FY[0]) & (fy <= TRAIN_FY[1])] = "train"
    out[(fy >= VAL_FY[0]) & (fy <= VAL_FY[1])] = "val"
    out[(fy >= TEST_FY[0]) & (fy <= TEST_FY[1])] = "test"
    return out


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=_json_default))


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.ndarray,)):
        return o.tolist()
    if isinstance(o, (pd.Timestamp,)):
        return str(o)
    raise TypeError(f"not serialisable: {type(o)}")


def record_timing(step: str, seconds: float, extra: dict | None = None) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / "timings.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except ValueError:
            data = {}
    entry = {"seconds": round(float(seconds), 1),
             "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if extra:
        entry.update(extra)
    data[step] = entry
    path.write_text(json.dumps(data, indent=1))
