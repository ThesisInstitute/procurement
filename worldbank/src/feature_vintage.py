"""Which structured fields could actually have been known at board approval.

The backtest's whole claim is that its inputs existed before the outcome did.
The PAD text satisfies that by construction: the document is dated on or before
approval. The STRUCTURED fields do not, because they come from two tables
published in 2026 (the Finances One IEG extract and the Projects API), and a
2026 table can carry a 2026 value against a 1998 project.

This module measures, for each candidate field, whether its value tracks the
project's APPROVAL period or its CLOSING period. A field that tracks the closing
period is post-treatment and cannot be an ex-ante input.

METHOD. For each country where the field takes more than one value, find the
best single threshold on Approval FY, and the best single threshold on Final
Closing FY, for reproducing the field. Compare the two accuracies. A field that
is genuinely keyed to approval is reproduced better by an approval threshold; a
field keyed to the closing period is reproduced better by a closing threshold.
This is a discriminating test, not a proof: both fiscal years are correlated, so
the comparison is reported with the margin rather than as a verdict.

WHAT WAS FOUND (2026-09-15, reproduce with `make vintage`):

  Country / Economy FCS Status
    varies within 51 of 187 countries. Best-threshold accuracy 0.903 from
    Approval FY against 0.923 from Final Closing FY; the closing threshold is
    exact in 22 countries against 8 for approval, and beats approval in 26 of
    51. Burkina Faso is the clean case: every non-FCS project closes 1995 to
    2019 and every FCS project closes 2020 to 2025, while the approval years of
    the two groups overlap almost completely (1969-2018 against 2009-2022).
    CONCLUSION: consistent with a status carried at the project's closing
    period. Not established as ex ante, so it is excluded from the feature set.

  Country / Economy Lending Group
    varies within 4 of 187 countries, so it is effectively one value per country
    in this snapshot. That is a 2026 country attribute stamped on projects of
    every vintage, but because it is constant inside a country it cannot move
    the within-country statistic. Kept, and documented.

LIMIT OF THE CLAIM. No World Bank field dictionary stating the as-of date of
either column was found or read. What is established is the association between
the field and the two fiscal years in the published data. The cause is not
claimed.

Run:  .venv/bin/python -m worldbank.src.feature_vintage
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .paths import IEG_CSV, RESULTS

FIELDS = ["Country / Economy FCS Status", "Country / Economy Lending Group",
          "Country / Economy FCS Lending Group", "Practice Group",
          "Global Practice", "Agreement Type", "Lending Instrument Type"]
MIN_ROWS = 10


def _best_threshold_accuracy(years: np.ndarray, target: np.ndarray) -> float:
    """Best accuracy reproducing a binary target from one threshold on `years`.

    Both directions of the threshold are tried, so the statistic is symmetric
    and cannot be gamed by the coding of the target.
    """
    best = 0.0
    for t in np.unique(years):
        ge = years >= t
        best = max(best, (ge == target).mean(), (~ge == target).mean())
    return float(best)


def field_report(raw: pd.DataFrame, field: str) -> dict:
    """Approval-keyed against closing-keyed accuracy for one field."""
    rows = []
    for _country, sub in raw.groupby("Country / Economy"):
        d = sub[[field, "Approval FY", "Final Closing FY"]].dropna()
        if len(d) < MIN_ROWS or d[field].nunique() < 2:
            continue
        # one-vs-rest on the most common value keeps this binary and symmetric
        top = d[field].value_counts().index[0]
        target = (d[field] == top).values
        a = _best_threshold_accuracy(d["Approval FY"].values, target)
        c = _best_threshold_accuracy(d["Final Closing FY"].values, target)
        rows.append({"country": _country, "n": len(d),
                     "approval_fy_accuracy": a, "closing_fy_accuracy": c})
    t = pd.DataFrame(rows)
    within = raw.groupby("Country / Economy")[field].nunique()
    out = {
        "field": field,
        "countries_total": int(len(within)),
        "countries_varying": int((within > 1).sum()),
        "countries_tested": int(len(t)),
    }
    if len(t):
        out.update({
            "mean_approval_fy_accuracy": float(t["approval_fy_accuracy"].mean()),
            "mean_closing_fy_accuracy": float(t["closing_fy_accuracy"].mean()),
            "closing_better_in": int((t["closing_fy_accuracy"]
                                      > t["approval_fy_accuracy"]).sum()),
            "approval_better_in": int((t["approval_fy_accuracy"]
                                       > t["closing_fy_accuracy"]).sum()),
            "closing_exact_in": int((t["closing_fy_accuracy"] == 1.0).sum()),
            "approval_exact_in": int((t["approval_fy_accuracy"] == 1.0).sum()),
        })
    else:
        for k in ("mean_approval_fy_accuracy", "mean_closing_fy_accuracy",
                  "closing_better_in", "approval_better_in",
                  "closing_exact_in", "approval_exact_in"):
            out[k] = np.nan
    return out


def run() -> pd.DataFrame:
    raw = pd.read_csv(IEG_CSV, encoding="utf-8-sig", dtype=str)
    for c in ("Approval FY", "Final Closing FY", "Evaluation FY"):
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    out = pd.DataFrame([field_report(raw, f) for f in FIELDS
                        if f in raw.columns])
    out["verdict"] = np.where(
        out["countries_tested"].eq(0), "constant within country in this snapshot",
        np.where(out["mean_closing_fy_accuracy"]
                 > out["mean_approval_fy_accuracy"],
                 "tracks the closing period; NOT established as ex ante",
                 "tracks the approval period"))
    out.to_csv(RESULTS / "feature_vintage.csv", index=False)
    print(out.to_string(index=False))
    return out


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
