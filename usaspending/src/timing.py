"""Record how long each pipeline step took, so the report's wall time is measured.

Each step appends its own elapsed seconds to usaspending/results/timings.json.
The file accumulates across steps within a run and is overwritten per step, so a
re-run of one step updates only that step's entry.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def record(out_dir: Path, step: str, seconds: float, extra: dict | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "timings.json"
    data: dict = {}
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
