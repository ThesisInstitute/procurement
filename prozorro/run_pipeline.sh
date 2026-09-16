#!/bin/zsh
# Everything downstream of the fetch, in order, from the cached JSON.
set -e
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/prozorro"
PY=.venv/bin/python
echo "=== parse   $(date +%H:%M) ==="; $PY prozorro/src/parse.py
echo "=== labels  $(date +%H:%M) ==="; $PY prozorro/src/labels.py
echo "=== experiments $(date +%H:%M) ==="; $PY prozorro/src/experiments.py --permutations 5000
echo "=== release $(date +%H:%M) ==="; $PY prozorro/src/release.py
echo "=== report  $(date +%H:%M) ==="; $PY prozorro/src/report.py
echo "=== done    $(date +%H:%M) ==="
