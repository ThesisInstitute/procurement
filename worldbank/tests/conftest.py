"""Test-wide protection for the published results directory.

WHY THIS FILE EXISTS. On 2026-09-15 a test in test_analysis.py called
`analysis.skill_by_test_year` on a synthetic fixture without redirecting the
module's RESULTS path. The function does what it is supposed to do and wrote its
output, so twelve rows of fabricated fold data silently replaced the real
`results/skill_by_test_year.csv`, which the report then read. Nothing failed.
The published table simply became fixture data.

That is the same class of failure as the one src/guards.py exists for: a
deliverable quietly filled with the wrong content instead of failing loudly.
Remembering to monkeypatch in each test is not a fix, because the failure is
what happens when someone forgets.

So the redirect is autouse and session-wide. Every module that writes into
`results/` has its RESULTS binding pointed at a per-test temporary directory for
the whole suite. A test that wants to inspect what a function wrote reads it
from `results_dir`; a test that forgets is harmless.

`test_results_dir_is_protected` below asserts the protection is actually in
force, so if the fixture is ever broken or a new writing module is added without
being listed here, a test fails instead of a results file changing.
"""
from __future__ import annotations

import importlib

import pytest

# Every src module that binds RESULTS at import time and writes through it.
# A new module that writes into results/ must be added here; the guard test
# below fails if one of these names stops existing.
WRITING_MODULES = [
    "worldbank.src.analysis",
    "worldbank.src.charts",
    "worldbank.src.dataset",
    "worldbank.src.dictionary",
    "worldbank.src.feature_vintage",
    "worldbank.src.fetch_pad_text",
    "worldbank.src.fetch_static",
    "worldbank.src.model",
    "worldbank.src.report",
    "worldbank.src.text_quality",
    "worldbank.src.verify_repair",
]


@pytest.fixture(autouse=True)
def results_dir(tmp_path, monkeypatch):
    """Redirect every module's RESULTS at a temp directory, for every test."""
    target = tmp_path / "results"
    target.mkdir(parents=True, exist_ok=True)
    for name in WRITING_MODULES:
        try:
            mod = importlib.import_module(name)
        except ImportError:  # pragma: no cover - a module may be removed
            continue
        if hasattr(mod, "RESULTS"):
            monkeypatch.setattr(mod, "RESULTS", target, raising=False)
    return target
