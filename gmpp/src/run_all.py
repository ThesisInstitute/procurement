"""Run the whole GMPP pipeline in order, from the gov.uk API to results/report.md.

One command, so every number in the report has a single reproduction path:

    .venv/bin/python -m gmpp.src.run_all

Acquisition is skipped when `data/raw/gmpp/manifest.csv` already exists, because
re-downloading 543 attachments from gov.uk on every run is rude to the
publisher. Force it with `--fetch`, or run only the analysis with `--no-fetch`.

Exit status is the first non-zero stage, so this is safe to use in a check.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

from .paths import MANIFEST_PATH, REPO_DIR

ACQUISITION = ["discover", "download", "snapshots", "profile_headers"]
ANALYSIS = [
    "panel",
    "validate_calendar",
    "outcomes",
    "score",
    "crosscheck",
    "charts",
    "report",
]


def run(module: str) -> int:
    started = time.monotonic()
    print(f"==> gmpp.src.{module}", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", f"gmpp.src.{module}"], cwd=str(REPO_DIR)
    )
    print(
        f"<== gmpp.src.{module} exit {result.returncode} "
        f"({time.monotonic() - started:.1f}s)",
        flush=True,
    )
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--fetch", action="store_true", help="re-download from gov.uk"
    )
    group.add_argument(
        "--no-fetch", action="store_true", help="analysis only, never download"
    )
    parser.add_argument(
        "--test", action="store_true", help="also run the test suite at the end"
    )
    args = parser.parse_args(argv)

    stages: list[str] = []
    if args.fetch or (not args.no_fetch and not MANIFEST_PATH.exists()):
        stages += ACQUISITION
    else:
        print(
            f"skipping acquisition, {MANIFEST_PATH} exists (use --fetch to force)",
            flush=True,
        )
    stages += ANALYSIS

    for module in stages:
        code = run(module)
        if code != 0:
            print(f"FAILED at gmpp.src.{module}", file=sys.stderr)
            return code

    if args.test:
        print("==> pytest", flush=True)
        code = subprocess.run(
            [sys.executable, "-m", "pytest", "gmpp/tests", "-q"], cwd=str(REPO_DIR)
        ).returncode
        print(f"<== pytest exit {code}", flush=True)
        if code != 0:
            return code

    print("\nall stages completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
