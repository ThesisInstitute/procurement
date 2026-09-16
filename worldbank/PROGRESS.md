# worldbank workstream progress

State file. Owner: worldbank build lane. Updated as work proceeds.

## Goal
Leakage-controlled join of World Bank Project Appraisal Documents (proposal text,
ex ante) to IEG outcome ratings (independent outcome, ex post), plus a text
baseline and the Bank-versus-IEG disagreement series.

## Done
- IEG ratings bulk CSV located and downloaded. The Finances One page is a JS app
  but the bulk URL is in the server-rendered HTML:
  financesonefiles.worldbank.org/f-one/DS00053/RS00055/IEG_World_Bank_Project_Performance_Ratings.csv
  3,305,163 bytes, 12,598 rows x 21 columns, "As of Date" 09/13/2026, CC BY 4.0.
- WDS metadata at 100 percent coverage: PAD 6,991 / 6,991, ICR 8,603 / 8,603,
  ICRR 7,815 / 7,815.
- Projects API at 100 percent coverage: 28,113 / 28,113, using fl=* (the default
  field set is only 15 fields and carries no ratings).
- Two data defects in the Projects API `icr_ratings` block found and measured
  (repeated elements in the block; "Substantial" emitted for "Satisfactory"). Both
  handled, and the second confirmed against the PRIMARY documents: 96 ICRR
  documents parsed, 27 of 27 rows where the API says "Substantial" say
  "Satisfactory" in the document (results/repair_document_summary.csv).
- GovTech workbook found (Data Catalog 0038056 / DR0095723). Only verified
  machine-readable source for the Bank's ICR self-rating AND the ORIGINAL
  closing date.
- Leakage-controlled join built: 4,253 projects, 4,198 with a usable label.
- PAD plain text downloaded: 4,162 of 4,251 ok, 1,287,494,121 bytes, sha256 per
  document in results/pad_text_manifest.csv.
- Pre-registered forward-chained cut points hold without adjustment:
  train <= 2005 n=1,703, validate 2006-2010 n=973, test >= 2011 n=1,522.
- First model ladder run complete. Headline at that point: PAD text alone
  reached within-country AUC 0.573 and no rung beat a constant at the realised
  test base rate on Brier. SUPERSEDED: after the corpus and feature fixes below,
  within-country AUC is 0.579 and the text-only rung does beat that constant
  (BSS +0.024). See "Final state".
- results/report.md and four PNG charts generate end to end.
- BUG FIXED: report.py mapped the GovTech workbook's abbreviated ratings
  (HS/S/MS/MU/U/HU) with `scales.to_six_point`, which refuses abbreviations by
  design, so disagreement Route 1 silently resolved to n=0 and printed "nan%".
  Now uses `govtech.six_point`. Regression test pending.

- Second model pass complete (src/analysis.py, `make analysis`). Findings:
  country identity alone gives pooled AUC 0.570 and within-country AUC exactly
  0.500; the exact within-country permutation null (2,000 draws) centres on
  0.500 and the observed 0.573 gives one-sided p = 0.017, uncorrected across a
  six-rung, nine-C search; 20 permuted-label pipeline refits mean 0.499 with a
  maximum of 0.555, so the pipeline does not manufacture skill but the effect is
  close to the noisiest null draw; discrimination survives the second label cut
  (>= Satisfactory, within-country 0.554) while calibration does not; evaluation
  coverage collapses after 2018 (27% for 2019, 5% for 2021) and the headline
  survives dropping those years.
- SECOND BUG FIXED: a test in test_analysis.py called a writing function without
  redirecting RESULTS and overwrote the real results/skill_by_test_year.csv with
  its 12-row synthetic fixture. tests/conftest.py now redirects every module's
  RESULTS at a temp directory suite-wide, and tests/test_results_protection.py
  asserts the protection is in force. Analysis re-run afterwards.
- src/guards.py added: require_rows / require_finite / require_mapped /
  require_overlap, so an empty intermediate raises instead of formatting as
  "nan". Wired into report.build_disagreement.
- Report rewritten with a "headline, stated plainly" section and a "Does the
  result survive" section carrying the whole second pass.

- Adversarial audit run: 6 dimensions, 39 findings raised, each one handed to an
  independent skeptic told to refute it; 21 survived. Fixes applied so far:

  CORRECTNESS (each changed a number or an artefact)
  - `ieg_country_fcs_status` removed from the feature set as POST-TREATMENT.
    src/feature_vintage.py measures it: fragile-state status varies within a
    country in 51 of 187 countries, and a best-single-threshold reproduction
    scores 0.923 from Final Closing FY against 0.878 from Approval FY, exact in
    22 countries against 7, better in 29 of 50 and worse in none. Burkina Faso
    is clean: non-FCS closes 1995-2019, FCS closes 2020-2025, approval years
    overlap. The headline rung (text only) uses no structured field, so the
    headline is untouched either way; the sensitivity is reported.
  - `join.parse_dt` now floors to calendar dates. WDS renders docdt at midnight
    US Eastern (04:00Z/05:00Z), the board date at 00:00, so `.dt.days` was one
    day short on 7,109 of 7,109 rows and the "30 day" grace was really 29d20h.
    No PAD sits between 27 and 32 days after approval, so inclusion did not
    change; the feature did.
  - Leakage filter now prefers the English version among documents that already
    passed the date test. 40 projects had been represented by a translation
    (often dated earlier than the English original) and an English PAD existed
    for 39. Corpus is now 4,252 English / 1 other, and re-fetching lifted usable
    documents from 4,162 to 4,213.
  - `pad_lead_days` plausibility bound. P152646's PAD is dated 2005-03-19 against
    a 2015-03-19 board date; 6 rows exceeded two years and the extreme sat at 48
    sigma, inflating the standardised feature's SD to 75 days against an IQR of
    10. Out-of-range values now go missing (raw kept in `pad_lead_days_raw`);
    SD is 27.9 and max |z| 23.5.
  - `make all` rewritten as ordered sub-makes. GNU make deduplicates a repeated
    prerequisite, so `all: ... dataset padtext dataset ...` ran dataset ONCE and
    a clean build shipped null text columns. run_all.sh added because make is
    not usable on this machine (Xcode licence).
  - CSV round-trip verified on every build: 11 pad_guid values lose a leading
    zero and 2 Namibia codes read as null under a bare read_csv.
    `dataset.read_release_table` is the documented reader.
  - Funnel reported the DEDUPLICATED row count as "rows in the bulk CSV"
    (12,597 against the file's 12,598); raw count and the dropped duplicate are
    now separate rows.
  - Reject reasons split: `same_date_duplicate_or_translation` against
    `later_version_within_grace_window`. 84.9% of non-selected rows share the
    kept document's date, so the old single label overstated the filter as
    removing post-hoc documents.

  CLAIMS (each was stated as fact and was wrong or unsourced)
  - "mean document is about 235,000 bytes" was wrong: it is 309,080, and
    80.6% of the corpus exceeds the 200,000-character truncation, not a tail.
  - "buff cover vs Final" editorial claim removed; no dictionary for
    `versiontyp` was found, and only docdt matters to the filter.
  - "PAD covers roughly 1996 onward" hid that the sample is IPF-only by
    construction (4,250 IPF against 3 DPF) and that coverage is 60-73% in every
    year FY2002-FY2019.
  - OCR-noise claim relabelled as an untested threat.
  - PPAR-selection claim relabelled as an inference.
  - Structured features are now listed in the report; a claim that inputs
    predate the outcome is empty unless the inputs are named.
  - Grid-boundary caveat made computed rather than hardcoded (with the cleaned
    corpus every tuned C is now interior: 10 / 3 / 1).
  - Under-claim corrected: the icr_ratings repair is confirmed against 96
    PRIMARY ICRR documents (97.9% match after repair; 27 of 27 "Substantial"
    rows say "Satisfactory" in the document), not only against a second dataset.
  - Dangling references fixed (src/checks.py, `make govtech`).

  SECOND BATCH, from the highest-severity confirmed findings
  - WITHDRAWN FALSE MECHANISM: the code claimed the Projects API's `curr_`
    prefix marks current values against approval-time un-prefixed ones. The
    API's own data falsifies it: lendprojectcost == curr_project_cost on
    27,477 of 27,477 rows (5,960 distinct values), idacommamt ==
    curr_ida_commitment on 13,650 of 13,650, totalamt == curr_ibrd + curr_ida on
    99.83%. The "23.4% differ" statistic that supported the claim measures the
    GRANT component, not drift: of the differing rows 100% have grantamt > 0 and
    94.6% have the gap equal to grantamt exactly. `log_commitment` is therefore
    of UNKNOWN vintage; it is kept, said so plainly, and analysis.py now scores
    the structured rungs without it.
  - MEASURED A CAVEAT THAT WAS BACKWARDS: src/text_quality.py measures OCR noise
    with two proxies. "Noisier before roughly 2005, which is exactly the
    training fold" is wrong twice. The noisy block is approval years 2004-2009;
    1996-2003 is the cleanest text in the corpus and 2010+ is clean again. And
    it lands in the VALIDATION fold (single-char token rate 0.0611) against
    0.0169 in train and 0.0157 in test. That is a live hazard, not a decorative
    caveat: C is tuned on the noisiest text in the corpus and applied to the
    cleanest. Stated in the report; not corrected for.
  - Integer tie-break in the leakage filter. WDS stores `id` as a string of
    digits, so ties compared lexicographically ("18082379" before "440661").
    27 projects still reach the tie-break after the language preference and 6
    change hands.
  - Test coverage added where the audit found none: the forward-chaining fold
    construction (test_model_folds.py), the vintage test (test_feature_vintage),
    the OCR proxies (test_text_quality), the CSV round-trip
    (test_dataset_roundtrip), the results-directory protection
    (test_results_protection). 244 tests.

## Refuted, and why it matters
26 of the 48 findings were refuted by the skeptic pass and NOT acted on, which
is the point of running it: without the refutation stage this lane would have
"fixed" two dozen things that were already handled, already disclosed, or
measurably false.

  THIRD BATCH
  - SCHEDULE SLIP CORRECTED AT SOURCE. The GovTech workbook's own Metadata sheet
    (row 28, row 29) defines `Org Closing Dt` as "Original Closing Date" and
    `Rev Closing Dt` as "ACTUAL Closing Date" -- not "revised", which is how the
    abbreviation reads and how this lane had named it. So `schedule_slip_days`
    had been a MIXED-SOURCE subtraction (Projects API `closingdate` minus the
    workbook's original). The two "actual" dates disagree on 11.1% of the 1,860
    rows where both exist and the mixed version overstated slip by 73.6 days
    (+15.6%): median 457 against 365, mean 545.1 against 471.5. The same-source
    figure is now `schedule_slip_days`; the mixed one is retained as
    `schedule_slip_days_api_actual` so the gap stays visible.
  - HEADLINE CLAIM WAS FALSIFIED BY THE LANE'S OWN FIXES AND IS NOW COMPUTED.
    "No rung beats a constant at the realised test base rate on Brier" was true
    before the corpus was cleaned and FALSE after: (d) PAD text only now scores
    BSS +0.0237 against the zero-information benchmark. The sentence is now
    derived from the model table at render time, in two places, so it cannot be
    asserted wrongly again. Same treatment for the grid-boundary note.
  - Calibration now covers the winning rung (d), not only (b2) and (c).

## Final state
- 244 tests pass (`make test`, exit 0).
- Full pipeline runs clean end to end (`./run_all.sh --no-fetch`, or `make all`).
- results/report.md is 1,100+ lines, standalone, 9 PNG charts, no nan and no
  empty tables; release table 4,253 rows x 178 columns with all 28 spec-required
  columns present and non-null.
- Disk: 1.3 GB under data/raw/worldbank, against an 8 GB budget.
- Headline: PAD text alone reaches within-country AUC 0.579 (exact permutation
  null 0.500, one-sided p = 0.009) and Brier skill +0.024 against a constant at
  the realised test base rate. Both are small, the p-value is uncorrected across
  a six-rung nine-C search, and the largest of 20 pure-noise pipeline refits
  reached 0.565. Reported as a weak positive needing one pre-registered
  replication, not as a finding.

## Next
- Nothing outstanding.

## Resolved open questions
- The IEG bulk CSV does not carry the Bank's ICR self-rating, Risk to
  Development Outcome, Borrower Performance or ICR Quality. Risk, borrower and
  ICR-quality ratings come from the Projects API `ieg_ratings` block; the Bank
  self-rating comes from the GovTech workbook and the repaired API block.

## Known limitations, all stated in the report
- No planned-versus-actual closing date exists API-wide, so schedule_slip_days is
  populated only for projects covered by the GovTech workbook.
- The lane does not git commit (the main session owns commits for this repo).
