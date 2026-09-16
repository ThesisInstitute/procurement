"""Run the workstream's pytest suite and record the exit code next to the results.

The report prints the exit code from results/tests.json, so the number in the
report is the one this script observed rather than one typed in by hand.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from bidders_us.src.common import RESULTS, ROOT


def main() -> int:
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "bidders_us/tests", "-q"],
        cwd=ROOT, capture_output=True, text=True)
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    summary = lines[-1] if lines else ""
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "tests.json").write_text(json.dumps({
        "exit_code": proc.returncode, "summary": summary,
        "seconds": round(time.time() - t0, 1),
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, indent=1))
    (RESULTS / "pytest_output.txt").write_text(proc.stdout + proc.stderr)
    print(proc.stdout[-2000:])
    print(f"exit code {proc.returncode}")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
