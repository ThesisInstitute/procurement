# GMPP: scoring the UK government's own delivery confidence forecasts

Since 2013 the UK Major Projects Authority, then the Infrastructure and Projects
Authority, and now NISTA, has published a Delivery Confidence Assessment for
every project on the Government Major Projects Portfolio: a Red/Amber/Green
judgment, made at a dated snapshot by people with access to the project, of
whether it will deliver. The same release carries the project's baseline
whole-life cost, its financial-year baseline, forecast and variance, and its
latest approved start and end dates.

Those ratings are forecasts. Nobody has scored them. This workstream treats each
one as a forecast made at its snapshot and resolves it against what the later
snapshots show happened.

The findings are in `results/report.md`. In short: the ratings order projects
correctly but weakly, they are badly miscalibrated in one direction if you read
a colour as a probability, and the only thing they predict well is next year's
rating. Read the "What this does and does not show" section before quoting any
of it: a rating is an input to what happens next, not a passive prediction.

## Reproducing

From the repository root:

```
.venv/bin/python -m gmpp.src.run_all --test
```

That rebuilds the panel, the outcomes, every table, every chart and the report,
then runs the tests. It re-downloads from gov.uk only when
`data/raw/gmpp/manifest.csv` is absent (`--fetch` forces it, `--no-fetch`
forbids it), stops at the first failing stage and exits with that stage's
status. `results/report.md` lists the individual stages.

## Layout

```
src/       acquisition, loading, panel construction, outcomes, scoring, charts, report
tests/     pytest over canonicalisation, dating, identity, labels and the scoring maths
results/   panel.csv, panel_outcomes.csv, table_*.csv, report.md, *.png
logs/      run logs
```

`results/panel.csv` is the canonical panel, one row per project per snapshot,
and is the publishable artifact independent of any of the scoring.

## Things about the source that are easy to get wrong

- **The publication year is not the snapshot date.** The 2015 publications carry
  the September 2014 position. Each publication is dated from its own statement
  of the position it carries, and the dating is cross-checked against the
  financial year the file names in its own money columns
  (`gmpp.src.validate_calendar`).
- **A narrative column can carry a stale financial year.** The September 2019
  files head their money columns with no year but carry "Departmental narrative
  on budget/forecast variance for 2018/19" from the previous year's template.
  Dating on that merges two snapshots into one.
- **The reporting date moved from September to March**, so one step in the
  series is 18 months and every other is 12.
- **The scale changed** from five points to three between March 2021 and March
  2022. The two eras are scored separately and never pooled.
- **The last file is in real prices** while every earlier one is nominal, so the
  final cost-growth step mixes price bases.

## Licence of the source data

The GMPP files are published on gov.uk under the Open Government Licence.
