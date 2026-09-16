# usaspending: forecasting a federal contract's outcome at award

A leakage-controlled backtest of "forecast the outcome of a United States federal
definitive contract at award, from public inputs". Base awards FY2010 through
FY2022, resolved at 12, 24 and 36 months against the later official record of
modifications to the same contract.

The written result is `results/report.md`.

## Running it

Everything runs from the repository root with the project virtualenv.

```
make -C usaspending all      # fetch, evidence, panel, models, quantiles, report
make -C usaspending test     # pytest
```

Individual steps, each also runnable on its own:

```
.venv/bin/python -m usaspending.src.bulk_fetch --fy-start 2010 --fy-end 2026 --workers 4
.venv/bin/python -m usaspending.src.field_evidence
.venv/bin/python -m usaspending.src.panel
.venv/bin/python -m usaspending.src.models
.venv/bin/python -m usaspending.src.quantile_models
.venv/bin/python -m usaspending.src.report
```

A fiscal year whose bulk job fails server side can be refetched in windows, which
forces the API to create a new job instead of returning the failed one:

```
.venv/bin/python -m usaspending.src.bulk_fetch --fy-start 2018 --fy-end 2018 --splits 4
```

The optional archive cross-check downloads one 1.17 GB monthly full archive,
streams it without extracting, counts definitive-contract rows independently of
the API, and deletes the zip:

```
make -C usaspending crosscheck
```

## Where the data comes from

`POST https://api.usaspending.gov/api/v2/bulk_download/awards/` with
`prime_award_types: ["D"]`, `date_type: "action_date"`, a fiscal-year
`date_range`, the all-agencies form
`{"type": "awarding", "tier": "toptier", "name": "All"}`, and an explicit
`columns` list. Rows are contract actions, one per modification. Downloads land in
`data/raw/usaspending/` at the repository root, which is gitignored; zips are
deleted after conversion to parquet.

## Layout

```
src/columns.py            the 44 columns kept, and their types
src/download.py           parallel range downloader for the monthly full archive
src/bulk_fetch.py         the primary fetch, one job per fiscal year
src/archive_crosscheck.py independent count from the archive
src/field_evidence.py     every field-behaviour claim, as a measurement
src/panel.py              base rows, labels at 12/24/36 months, features, history
src/features.py           feature blocks and train-only category lumping
src/reference_class.py    shrunk cell means
src/scoring.py            Brier, skill score, AUC, calibration, pinball
src/models.py             the ladder for the binary labels
src/quantile_models.py    the ladder for the continuous labels
src/report.py             assembles results/report.md and the charts
tests/                    pytest, on synthetic fixtures with hand-computed answers
```

## The one thing to know before reading the code

`potential_total_value_of_award` looks like the field the ceiling-growth label
should use, and it is not usable. It is sparse in the training years and complete
in the test years, and where it is complete it carries restated values that
already reflect the award's eventual ceiling. The ceiling at a horizon is instead
reconstructed from `base_and_all_options_value`, which the dictionary defines as a
level on the base action and a change on every modification, and which is
populated on every action in every year. The measurements behind that decision are
in `results/report.md` and are produced by `src/field_evidence.py`.
