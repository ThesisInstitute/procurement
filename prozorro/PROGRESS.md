# Prozorro workstream progress

## State

Fetching the full 2019-2022 population (80,182 completed above-threshold
tenders plus their contract-registry records) at about 9 documents a second.
Code is frozen. Everything downstream is written, tested (64 pytest tests, ruff clean) and already
validated end to end on a growing partial cache, so the final run is
`prozorro/run_pipeline.sh`.

## Done

### Data mechanics, all verified in the data on 2026-09-16

- `contractChangeRationaleTypes` is a **static vocabulary** returned on every
  contract, not a record of applied changes. Applied changes are `changes[]`.
- Registry `status: terminated` is the **ordinary completed state**; the tender
  document's own copy of the contract never shows it, which is direct evidence
  the tender copy is frozen at signing.
- `cancelled` is unobservable inside a completed-tender sample: a tender only
  reaches status `complete` once it has a live contract. The ladder refuses to
  score the label rather than reporting noise.
- `bids` and `awards` are **not available through `opt_fields`**, so every
  tender must be fetched in full.
- A tender's `dateModified` **freezes when its contract is published** and does
  not track later registry changes, so walking the feed does not select on the
  outcome being forecast.
- The registry end date moves on about 19 percent of lots, but only about 27
  percent of those moves carry a `durationExtension` change, so `days_extended`
  is the broader and noisier signal and `duration_extension` is the primary
  label.
- Disqualification is an award with status `unsuccessful`, not a bid status.
  Prozorro strips the price from withdrawn and rejected bids, but essentially
  all unsuccessful awards still point at a priced bid that can be ranked.

### Three bugs the trial runs caught, all silent

- `pd.to_datetime` infers one format from the first element, so a column mixing
  `...T14:21:59+02:00` and `...T16:54:16.166801+02:00` coerced 5,298 of 6,480
  timestamps to NaT. A NaN cutoff makes every as-of history count return zero,
  so this would have zeroed the history features for most of the panel without
  raising anything. Fixed in `src/times.py`, with a regression test that also
  documents the failure mode.
- The transfer test was circular: a bidder's as-of history on a lot it lost in
  late 2021 already contained the outcome of a lot it won in early 2021, which
  is on the realised side of the comparison. The headline now freezes bidder
  history at the first day of the test window; the leaky variant is reported
  beside it.
- The transfer test's p-value was being read as evidence about the bidder even
  when the lot-only placebo scored higher. The verdict now requires beating the
  placebo before it will call a transfer result positive.

### Sampling design

A systematic sample of whole days: every fifth day of `dateModified` from
2019-01-01 to 2024-01-01, each selected day walked completely, so every tender
in the range has inclusion probability exactly 1/5 whatever the volume of its
day. 3,604 listing requests, 3,604,000 feed rows, 706 MB, 15 minutes. 121,036
completed above-threshold tenders found, 80,182 created 2019-2022, all of them
queued for fetching, so the day selection is the only sampling step in the
design. Above-threshold volume falls 51 percent from 2021 to 2022, which is the
war and not an artefact.

### Conditioning, and why there are several versions of each number

A bidder's record looks informative or useless depending on what is held
fixed, so every identity result is reported under more than one conditioning:
pooled, within buyer, within CPV division and year, on lots whose winner
already has ten or more wins, and before the invasion. On the partial cache the
winner's own extension rate reads 0.519 pooled, 0.393 within buyer and 0.538
within CPV division and year. A number that changes sign with the conditioning
is not a signal, and the report says so rather than picking the flattering one.
A stratified AUC resting on fewer than twenty strata is left blank rather than
printed.

### Experiments

Forward-chained ladder with six nested rungs so each step answers one question: what the lot
says, what the buyer's identity adds, what the winning price adds, and what the
winner's identity adds on top of all of it; the
competing-bidder transfer test with a within-division permutation null and a
lot-only placebo; a within-lot conditional test holding the lot fixed; a
bidder identity-persistence check on won lots only; a model-free intraclass
correlation and a conditional version that permutes the bidder within buyer and
year, including a variant taking one lot per bidder per tender; a head-to-head
of buyer identity against bidder identity; pre-invasion-only variants of the
headline tests; a right-censoring measurement by cohort; the
lowest-bidder-disqualified contrast with CPV-by-year standardisation; discount
deciles; bid dispersion bins.

On the partial cache the answer is already stable across tests: the winner's
price position within its own lot ranks slip (AUC 0.568, p = 0.001) while its
own prior extension rate does not (AUC 0.505, p = 0.64); the transfer test's
lot-only placebo outscores every bidder-aware forecast; the buyer's own record
reaches AUC 0.64 against the winner's 0.52; and yet outcomes do cluster by
bidder beyond the buyer and the year. Outcomes cluster by bidder; the
clustering is not stable enough over time to forecast with. Final numbers await
the full fetch.

## Next

- Finish the fetch, then `prozorro/run_pipeline.sh`.
- Final `results/report.md`.
