# usaspending workstream progress

## State

Data acquisition is complete: FY2010 through FY2026, definitive contracts only,
3,287,223 actions in 17 parquet files totalling 229 MB. The panel is built
(192,377 base awards, FY2010 to FY2022). Field evidence has been measured on the
full extract. The model ladder is running. Remaining: the quantile ladder, the
report, and a final clean re-run so every artifact comes from the final code.

## The finding that changed the design

The obvious way to build the ceiling-growth label, and the one the brief
specifies, is to read `potential_total_value_of_award` at the horizon. That field
cannot be used, for two separately sufficient reasons, both now measured on the
full extract rather than on a partial one.

1. Its availability moves with the split. It is populated on 0.26, 0.24, 0.24,
   0.22, 0.23, 0.25 and 0.28 of actions in FY2010 through FY2016, on 0.52 in
   FY2017, and on 1.00 of actions in every year from FY2018 on. Over all actions
   loaded it is 0.61. The training years are exactly where it is worst and the
   test years are where it is complete, so it is not the same label on both sides
   of the split. `base_and_all_options_value` is populated on 1.00 of actions in
   every single year.
2. Where it is fully populated it still carries restated values. On awards based
   in FY2019 or later with at least three actions (97,496 awards, 65,067 of which
   saw their ceiling change), a non-final action of an award whose ceiling moved
   already equals that award's eventual final value 0.377 of the time, and equals
   the contemporaneous reconstruction only 0.709 of the time. Reading it at a
   horizon imports the future.

The labels are therefore built from per-action deltas:

    ceiling(H) = base_and_all_options_value(base action)
               + sum of base_and_all_options_value over later actions dated at or
                 before base action date + H months

which the dictionary supports ("For modifications enter the CHANGE, positive or
negative") and which the data confirms: on an award's final action the
reconstruction equals the field 0.985 of the time, while the base ceiling read
alone equals it only 0.397 of the time.

`period_of_performance_current_end_date` was put through the same restatement
test and passes: on non-final actions of awards whose end date moved it equals
the award's final end date only 0.170 of the time. It is genuinely per action, so
the schedule-slip labels read it as it stands.

## Corrections made on the full extract

The earlier partial-data run produced three numbers that the full extract
contradicts, and all three had been written into module docstrings as mechanism
claims. They are now corrected to the measured values, which is the whole point
of keeping the evidence in a script:

- "populated on only a quarter of rows" -> 0.61 of all actions.
- "constant within an award about 80 percent of the time" -> 0.585.
- "fully populated from FY2019" -> fully populated from FY2018. The earlier run
  was missing FY2018 entirely, which is exactly why it looked like FY2019.

## Done

- Read the memo, the bulk download API contract, and the data dictionary.
- Acquisition validated two ways. The Custom Award Data Download API filters to
  definitive contracts server side and projects to 44 columns. Cross-checked
  against the monthly full archive for FY2010: streaming
  `FY2010_All_Contracts_Full_20260906.zip` (3,543,905 rows, all contract types)
  gives 253,528 rows of award_type_code D, exactly the API count.
- FY2018 refetched in four quarter windows after a server-side job failure, and
  the windows verified to tile the fiscal year exactly with no gap or overlap
  (a property test now covers splits 1 to 12 across FY2010 to FY2026).
- `bulk_fetch` now re-reads an existing parquet to build an honest manifest
  record instead of writing "skipped", and merges into the existing manifest
  instead of replacing it. All 17 fiscal years now carry real counts.
- `schema_check` reads back the parquet schema of every year and diffs it against
  the 44 requested columns. All 44 present in every year; nothing silently
  dropped.
- Panel built: 192,377 awards, data end 2026-09-13. Because the data end is later
  than the last base action plus 36 months, every award in the panel qualifies at
  every horizon, so the horizons are compared on the same population.
- Field evidence extended with the two fill-rate tables the scoreboard needs and
  with the per-action restatement test for both the ceiling and the end date.
- Timing instrumentation added, so the reported wall time is measured per step.
- 222 pytest tests pass.

## Bugs the tests and the evidence run caught

- A float comparison put an award with exactly 10 percent ceiling growth above the
  > 0.10 threshold.
- The GBM fit relied on a `shuffle` parameter HistGradientBoostingClassifier does
  not have, and its built-in early stopping would have drawn its validation split
  at random out of the training years, breaking forward chaining. Replaced with
  fit on train, iteration count chosen on validation by staged prediction, refit.
- Permutation importance was stored with the sign flipped.
- The ceiling label read the award-level value, described above.
- Retrying a failed bulk job with an identical body returns the same failed job,
  so the fetcher can now split a fiscal year into windows to force a fresh one.
- `quantile_models` referenced an undefined `t0` after timing was wired in.
- Three module docstrings asserted field behaviour that the full extract
  contradicts, and one described a shrinkage rule the code does not implement
  (the shrinkage is continuous in n, not a switch at n = 30). Both corrected.

## What the independent audit found, and what was done about it

Seven independent auditors were run over the code, one per dimension (label
leakage, as-of history, split discipline, scoring arithmetic, reference class,
population funnel, fetch integrity), each finding then put to two skeptics
briefed to refute it. Every finding below was independently reproduced here
before being acted on; the numbers are measurements, not the auditors' claims.

Fixed, changes a reported number:

- The sort key (award, action_date, mod_seq, txn_seq) is not total. 2,595
  actions, 0.079 percent of the extract, tie on it, and which one counts as "the
  latest at horizon H" was settled by the order the per-year files happened to be
  concatenated in; one auditor traced it to 44 panel awards whose schedule-slip
  label was decided that way. Adding the raw modification number to the key
  leaves zero ties, measured on the full extract.
- Three placeholder recipients (MISCELLANEOUS FOREIGN AWARDEES, FOREIGN AWARDEES
  (UNDISCLOSED), DOMESTIC AWARDEES (UNDISCLOSED)) accounted for 4,324 base awards,
  the largest of them more than any real contractor's UEI. They are now held out
  of contractor pooling and carry a null history and a flag.
- History was computed after the population filters, so a prior-award count meant
  "prior awards that also cleared the simplified acquisition threshold", and the
  single-base-row filter, which inspects actions dated after the base date, could
  reach back and change an earlier award's count. Labels, features and history are
  now built on a wider history source (474,512 awards) and the in-scope filters
  applied afterwards. The panel is unchanged at 192,377.
- calibration_table binned against np.linspace edges, whose fourth entry is
  0.30000000000000004, so a forecast of exactly 0.3, 0.6 or 0.7 landed one bin
  below the row it was labelled with. Replaced with floor(p * n_bins) after a
  rounding step. The top bin was also labelled "[0.9,1.0)" although it contains
  p = 1.0; it is now "[0.9,1.0]".

Fixed, latent rather than currently wrong:

- ReferenceClassModel.fit paired the frame and the outcomes by index label while
  the caller built the outcomes with a fresh 0..n-1 index. Those coincide only
  while nothing upstream has been filtered, which is true today. One filtered row
  would have raised or silently mislabelled. Pairing is now positional and
  length-checked.
- load_transactions accepted a gapped set of fiscal-year files. Since outcomes
  are read from later years, a hole would have silently removed real
  modifications rather than merely shrinking the sample. It now refuses. This is
  not hypothetical: an earlier run of this workstream was missing FY2018.
- A bulk-download window that returned short or empty was folded into the fiscal
  year without comment, the parquet written, and reused forever. Each window is
  now checked against the row count the service reports for it.
- A failed fiscal year exited zero and its error could vanish from the manifest
  behind an older good record. It now exits non-zero and the error is retained.
- download.py pre-sized the output file, which made both the resume check and the
  final size check vacuous: an interrupted download left a full-length file of
  mostly zeros that the next run treated as complete. It now assembles under a
  .part name, verifies the bytes actually written, and renames.
- The reference class exposed a min_cell_n argument that did nothing, and its only
  shrinkage test asserted a value with a tolerance wider than the quantity, so it
  passed for any shrink_k from 30 to 100. The argument is gone and the shrinkage
  is now pinned to 1e-12 against hand-computed arithmetic.
- Three module docstrings described mechanisms the code does not implement.

Judged correct and left alone, with reasoning recorded in the report:

- Each level's parent prior is computed from data that includes the child cell.
  That is ordinary hierarchical shrinkage without a leave-one-out correction, it
  is not leakage across the time split, and it is documented rather than
  restructured.
- base_fy is a feature whose test values lie outside the training range. A
  gradient booster puts them in the last bin, which is a constant shift, not a
  leak.

## Measured while auditing, and now in the report

- RAYTHEON COMPANY appears under 54 distinct UEIs, the largest holding 19 percent
  of its awards. 12.8 percent of panel awards sit under a recipient name carrying
  more than one UEI. Contractor history is understated worst for the largest
  primes, which is a candidate explanation for how little the history block adds.
- Text fields carry mis-transcoded characters at source, not from the decoding
  here: zero panel values contain the Unicode replacement character.

## Next

- Finish the model ladder, run the quantile ladder, write the report.
- Fold in whatever the independent leakage audit turns up.
- Final clean re-run so every published number comes from the final code.
