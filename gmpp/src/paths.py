"""Filesystem locations for the GMPP workstream."""
from __future__ import annotations

from pathlib import Path

GMPP_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = GMPP_DIR.parent
RAW_DIR = REPO_DIR / "data" / "raw" / "gmpp"
RESULTS_DIR = GMPP_DIR / "results"
LOGS_DIR = GMPP_DIR / "logs"

MANIFEST_PATH = RAW_DIR / "manifest.csv"
COLLECTION_JSON = RAW_DIR / "collection.json"

for _p in (RAW_DIR, RESULTS_DIR, LOGS_DIR):
    _p.mkdir(parents=True, exist_ok=True)
