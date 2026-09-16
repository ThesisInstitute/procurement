# GMPP workstream progress

Rescoring the UK Government Major Projects Portfolio Delivery Confidence
Assessments against what the later snapshots show happened.

## State

Complete. Pipeline, tests, charts and report all rebuild from one command and
all findings from the adversarial audit are folded in.

    .venv/bin/python -m gmpp.src.run_all --test     # from the repo root

Panel: 2,495 project-years, 708 projects, 14 snapshots (September 2012 to
March 2026). Tests: 256, all passing. Disk: 24 MB of 2 GB budget.

## Session 2, what happened

Session 1's lane was killed by a usage limit at 23:24 on 2026-09-15, mid-edit.
It left three source files edited after the last successful run, so `results/`
was stale and 11 tests were red. Repairing that uncovered a snapshot-dating bug
that invalidated every session-1 number, and an eight-dimension adversarial
audit of the code against the raw files then found 29 verified defects.

### Repairs to the broken state
1. Test suite red: `assign_project_keys` had gained a third return value and
   the tests were never updated. Fixed, with tests added for the guard that
   edit introduced.
2. That guard had never once executed. Running it showed it assigned the two
   components it separates the same project key, silently undoing itself.
3. `panel.py` crashed on `.astype(str).agg("|".join)`: pandas 3.0.5 keeps a
   missing value missing under `.astype(str)`.

### The dating bug
`calendar_map.snapshot_for` preferred a financial year parsed from a money
header, and its filter also matched the narrative column "Departmental
narrative on budget/forecast variance for 2018/19", which the September 2019
files carry as a template leftover. All 120 September 2019 project-years were
stamped September 2018. Publications are now dated from their own statement of
the position they carry, accepting only the portfolio's reporting months.
Independent confirmation: 107 of the 197 files name a financial year in a money
header and all 107 agree (`gmpp.src.validate_calendar`, exit 0).

### Audit findings folded in
27 defects fixed in code, 2 documented as properties of the data. The ones that
moved numbers: the department and category breakdowns pooled the two rating
scales (79 of 140 rows moved by 0.05 or more, 14 reversed sign); the
`worsened_next` conclusion was backwards, because its no-skill reference is
0.19 rather than 0.5; 22 renames were counted as permanent exits; the FCO's
September 2019 publication is missing from the gov.uk collection and is now
recovered by searching gov.uk directly; 20 published variances were multiplied
by 100; a time-only cell became today's date; a mis-decoded pound sign deleted
a GBP 9.94bn cost; "Green/Amber" was bucketed as not-rated.

The full list, with what each one changed, is the "How this was checked" section
of `results/report.md`.

### Independent checks that hold
- Brier, the Murphy decomposition and AUC reimplemented from their definitions
  and compared on 400 random inputs: largest disagreement 1.4e-16.
- IPA back-series cross-check: 1,161 of 1,255 rows join, rating agrees 98.2 per
  cent, whole-life cost 97.3 per cent, end date 98.4 per cent.
- Dating cross-check: 107 agree, 0 disagree.

## What is left undone

Nothing blocking. Two limits are inherent and are stated in the report rather
than worked around: outcomes are conditional on a project still being on the
portfolio, and four departments (ONS, NCA, CPS, NS&I) never published a
departmental file so their project-years are outside this panel.
