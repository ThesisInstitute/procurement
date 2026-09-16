# usaspending workstream progress

## State
Data acquisition complete except FY2018, which is refetching in four windows after
a server-side job failure. Code and 71 tests written and passing. The panel and
model ladder have both been run end to end on partial data as smoke tests. The
full run and the report are next.

## The finding that changed the design
The obvious way to build the ceiling-growth label, and the one the brief
specifies, is to read `potential_total_value_of_award` at the horizon. That field
cannot be used, for two separately sufficient reasons, both measured:

1. It is populated on 22 to 28 percent of actions in FY2010 to FY2016, 52 percent
   in FY2017, and 100 percent from FY2019. The training years are exactly where it
   is worst and the test years are where it is complete, so it is not the same
   label on both sides of the split. `base_and_all_options_value` is populated on
   100 percent of actions in every year.
2. Where it is fully populated it still carries restated values. On awards based
   in FY2020 or later with at least three actions, the field on a non-final action
   equals the contemporaneous reconstruction only 72 percent of the time for
   awards whose ceiling changed, while it already equals the award's eventual
   final value 38 percent of the time. Reading it at a horizon imports the future.

The labels are therefore built from per-action deltas:

    ceiling(H) = base_and_all_options_value(base action)
               + sum of base_and_all_options_value over later actions dated at or
                 before base action date + H months

which the dictionary supports ("For modifications enter the CHANGE, positive or
negative") and which the data confirms: on an award's final action the
reconstruction equals the field 98.4 percent of the time. The signature of the fix
is visible in the label itself. Under the reconstruction the share of awards past
25 percent ceiling growth rises with the horizon, 7.8 then 11.1 then 12.5 percent;
under the award-level reading it barely moves, 12.6 then 13.2 then 13.7 percent,
because the same end state is being read at every horizon.

`period_of_performance_current_end_date` was tested the same way and is genuinely
per-action, so the schedule-slip labels are built as the brief specifies.

## Done
- Read the memo, the bulk download API contract, and the data dictionary.
- Chose and validated the acquisition path. The Custom Award Data Download API
  filters to definitive contracts server side and projects to 44 columns; one
  fiscal year is 107k to 254k actions and 9 to 16 MB of parquet. Cross-checked
  against the monthly full archive for FY2010: streaming
  `FY2010_All_Contracts_Full_20260906.zip` (3,543,905 rows, all contract types)
  gives 253,528 rows of award_type_code D, exactly the API count, with all 44
  columns present in both.
- Wrote the fetch, evidence, panel, feature, reference-class, scoring, model,
  quantile and report modules, plus a parallel range downloader for the archive.
- 71 pytest tests pass.

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

## Next
- Finish FY2018, run the panel, the model ladder, the quantile ladder, the report.
