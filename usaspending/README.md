# usaspending: forecasting a federal contract's outcome at award

A leakage-controlled backtest of "forecast the outcome of a United States federal
definitive contract at award, from public inputs". Base awards FY2010 through
FY2022, resolved at 12, 24 and 36 months against the later official record of
modifications to the same contract.

The written result is [`results/report.md`](results/report.md).

## Running it

One command, from the repository root, takes this from nothing to the report:

```
make -C usaspending all
```

That is `fetch`, `schema`, `panel`, `evidence`, `models`, `quantiles`, `report`
in order. It is safe to re-run: a fiscal year whose parquet is already on disk is
re-read rather than re-downloaded, and every step overwrites its own outputs.

```
make -C usaspending test     # pytest
```

`panel` can also write out the wider frame the history features are computed
over, which is what you want if you are checking a contractor's prior-award
count by hand:

```
.venv/bin/python -m usaspending.src.panel \
    --history-source data/raw/usaspending/history_source.parquet
```

Individual steps, each also runnable on its own from the repository root:

```
.venv/bin/python -m usaspending.src.bulk_fetch --fy-start 2010 --fy-end 2026 --workers 4
.venv/bin/python -m usaspending.src.schema_check
.venv/bin/python -m usaspending.src.panel
.venv/bin/python -m usaspending.src.field_evidence
.venv/bin/python -m usaspending.src.models
.venv/bin/python -m usaspending.src.quantile_models
.venv/bin/python -m usaspending.src.report
```

A fiscal year whose bulk job fails server side can be refetched in windows, which
forces the API to create a new job instead of returning the failed one (the API
keys a job on the request body, so an identical retry returns the same failure):

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
deleted after conversion to parquet. FY2010 to FY2026 is 3,287,223 actions and
about 229 MB of parquet.

## Layout

```
src/columns.py            the 44 columns kept, and their types
src/bulk_fetch.py         the primary fetch, one job per fiscal year
src/schema_check.py       diffs the delivered parquet schema against the request
src/download.py           parallel range downloader for the monthly full archive
src/archive_crosscheck.py independent count from the archive
src/panel.py              base rows, labels at 12/24/36 months, features, history
src/field_evidence.py     every field-behaviour claim, as a measurement
src/features.py           feature blocks and train-only category lumping
src/reference_class.py    shrunk cell means
src/scoring.py            Brier, skill score, AUC, calibration, pinball
src/models.py             the ladder for the binary labels
src/quantile_models.py    the ladder for the continuous labels
src/timing.py             per-step wall time, written to results/timings.json
src/report.py             assembles results/report.md and the charts
tests/                    pytest, on synthetic fixtures with hand-computed answers
```

## Two orderings that are load bearing

**The filters run in two stages, with the history in between.** The first stage
keeps awards that are well identified base awards at all; what survives is the
history source, the set of prior awards a contractor's or an office's record is
counted over. Labels, features and history are built on that. Only then do the
in-scope filters run. Computing history after the scope filters would have made
"this contractor's tenth contract" mean "tenth contract that also cleared the
simplified acquisition threshold", and would have let the single-base-row filter,
which inspects actions dated after the base date, reach back and change an
earlier award's prior-award count.

**Actions are sorted by modification number as well as by its numeric suffix.**
2,595 actions in the extract, 0.079 percent, tie on
(award, action date, mod sequence, transaction number). Without the raw
modification number in the key, which action counts as the latest at a horizon
would be decided by the order the per-year files happened to be concatenated in.
With it there are no ties at all.

## The one thing to know before reading the code

`potential_total_value_of_award` looks like the field the ceiling-growth label
should use, and it is not usable. Two measured reasons, both in
`results/report.md` and both produced by `src/field_evidence.py`:

1. It is populated on roughly a quarter of actions in FY2010 to FY2016, on half
   in FY2017 and on all of them from FY2018. The training years are where it is
   worst and the test years are where it is complete, so a label built from it is
   not the same label on both sides of the split.
2. Where it is complete it is restated. On awards whose ceiling moved, a
   non-final action already carries the award's eventual final ceiling 0.377 of
   the time.

The ceiling at a horizon is instead reconstructed from `base_and_all_options_value`,
which the dictionary defines as a level on the base action and a change on every
modification, and which is populated on every action in every year. On an award's
final action the reconstruction agrees with `potential_total_value_of_award`
0.985 of the time, which is the check that it arrives at the right number.

`period_of_performance_current_end_date` was put through the same test and
passes, so the schedule-slip labels read it as it stands.

## And one thing about contractors

`recipient_uei` is the contractor history key, and it is not one firm per UEI in
either direction. Three placeholder recipients stand for buckets of firms, the
largest of them the most frequent UEI in the panel; those are held out of the
pooling and carry a null history and a flag. In the other direction, RAYTHEON
COMPANY appears under 54 distinct UEIs. Both are measured in
`results/report.md`.
