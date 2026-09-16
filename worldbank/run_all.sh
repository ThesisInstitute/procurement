#!/usr/bin/env bash
# The whole pipeline, in order, without make.
#
# This exists for two reasons. First, `make` is not available on every machine
# (on the box this was built on it refuses to run until the Xcode licence is
# accepted), and the pipeline should not depend on that. Second, it states the
# step order explicitly, including the fact that `dataset` runs TWICE: the first
# pass writes the download queue that fetch_pad_text consumes, the second folds
# the text sha256 and byte size back into the release table.
#
# Usage:
#   ./run_all.sh              full pipeline, including the network fetches
#   ./run_all.sh --no-fetch   everything downstream of the raw data already on disk
#
# Every step is a module, so any one of them can be re-run on its own with
#   .venv/bin/python -m worldbank.src.<module>
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PY="$REPO/.venv/bin/python"

[ -x "$PY" ] || { echo "no interpreter at $PY" >&2; exit 1; }

run() {
  echo "=== $1 ==="
  ( cd "$REPO" && "$PY" -m "worldbank.src.$1" )
}

if [ "${1:-}" != "--no-fetch" ]; then
  run fetch_static      # IEG ratings CSV + GovTech workbook
  run fetch_wds         # PAD / ICR / ICRR document metadata
  run fetch_projects    # all projects, fl=*
fi

run dataset             # first pass: builds the PAD download queue
if [ "${1:-}" != "--no-fetch" ]; then
  run fetch_pad_text    # the long one: PAD plain text, 4 concurrent requests
fi
run dataset             # second pass: folds text sha256 and bytes into the table
run dictionary          # column dictionary for the release table
run feature_vintage     # which structured fields are ex ante
run text_quality        # OCR noise by approval year and fold
run model               # the forward-chained ladder
run analysis            # the second pass that stresses the ladder
run report              # results/report.md and the PNGs

echo "=== done: see worldbank/results/report.md ==="
