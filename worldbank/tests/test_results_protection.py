"""Assert the results-directory protection in conftest.py is actually in force.

pytest treats conftest.py as a plugin and does not collect tests defined inside
it, so these live in their own module. Without them, a broken fixture or a newly
added writing module would silently drop out of the protection and the next
forgetful test would overwrite a published results file again.
"""
from __future__ import annotations

import importlib

from .conftest import WRITING_MODULES


def test_results_dir_is_protected(results_dir):
    """The fixture must actually be rebinding, not silently doing nothing."""
    from worldbank.src import analysis, paths
    assert analysis.RESULTS == results_dir
    assert analysis.RESULTS != paths.RESULTS
    assert results_dir.is_dir()


def test_every_listed_module_still_binds_results():
    """Catch a module that was renamed, or one that dropped its RESULTS import.

    Without this, a typo in WRITING_MODULES would silently remove a module from
    the protection and the next forgetful test would write to the real
    directory again.
    """
    missing = []
    for name in WRITING_MODULES:
        mod = importlib.import_module(name)
        if not hasattr(mod, "RESULTS"):
            missing.append(name)
    assert not missing, f"listed but no RESULTS binding: {missing}"


def test_a_writing_function_lands_in_the_temp_dir(results_dir):
    """End to end: the exact call that corrupted the real file is now contained."""
    import numpy as np
    import pandas as pd

    from worldbank.src import analysis

    te = pd.DataFrame({
        "approval_year": [2011] * 6 + [2012] * 6,
        "y_satisfactory": [0.0, 1, 1, 1, 1, 1] * 2,
        "ieg_country": ["A"] * 12,
    })
    analysis.skill_by_test_year(te, np.linspace(0, 1, 12))
    written = results_dir / "skill_by_test_year.csv"
    assert written.exists()
    assert len(pd.read_csv(written)) == 2
