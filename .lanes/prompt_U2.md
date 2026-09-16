# Shared context (read first)

Date: 2026-09-15. You are a build lane for Max Ghenis (Thesis Institute). Repo: ~/ThesisInstitute/procurement (git initialised; main session commits, you do not). Python env: `.venv/bin/python` (Python 3.12, pandas, pyarrow, numpy, scikit-learn, requests, matplotlib, openpyxl, odfpy, xlrd, tqdm, pytest already installed; use `uv pip install --python .venv/bin/python <pkg>` if you need more). Use `uv`, never pip; `pytest`, never unittest. Raw downloads go under `data/raw/<workstream>/` (gitignored). Keep your total disk use under the budget stated below; delete zips after converting to parquet. Disk is tight (about 75 GB free on the machine).

Background: Thesis (app.thesisinstitute.org) publishes pre-registered forecasts of official statistics and scores them against first prints. Max wants to do the same for procurement: forecast a contract's outcome at award, resolve against the official later record, publish the skill. The research memo is at ~/chief-of-staff/state/procurement-thesify/memo.md (read it; it has the verified data mechanics). Your job is one of the three first backtests.

Rules:
- Work only inside your own directory (stated below) plus `data/raw/<your workstream>/`. Do not touch the other workstreams. Do not `git commit`.
- Every number in your report must be produced by a script in your directory and reproducible with one command (`make` target or `.venv/bin/python -m <module>`). Write `results/report.md` in your directory with the tables, and save PNG charts next to it. Sentence case headings. No emoji. No em dashes.
- Never fabricate a mechanism: if you state how a field behaves, you observed it in the data or read the official dictionary this session. Label inferences.
- Write pytest tests for the label construction and the scoring functions on small synthetic fixtures. Run them and report the exit code. Do not chain a commit to a piped test.
- Forward-chained evaluation only (train on earlier years, test on later years). Never random splits across time.
- Report honestly: if the model does not beat the base rate or the reference class, say so plainly. Negative results are publishable here.
- Finish with a `results/report.md` that a reader can use standalone: what was built, the data, the labels, the exact definitions, the numbers (tables), the caveats, and what you could not verify.
- Long-running downloads: run them in the foreground of your own session with progress to a log file under your directory; if a download endpoint returns an async job, poll it with a sleep loop of 30 seconds and a hard cap of 60 minutes per job.

# Workstream: usaspending (directory `usaspending/`, disk budget 15 GB)

Goal: a leakage-controlled backtest of "forecast the outcome of a federal definitive contract at award, from public inputs".

## Data acquisition
Use the USAspending bulk award download API (contract read this session: https://raw.githubusercontent.com/fedspendingtransparency/usaspending-api/master/usaspending_api/api_contracts/contracts/v2/bulk_download/awards.md). `POST https://api.usaspending.gov/api/v2/bulk_download/awards/` with body:
{"filters": {"prime_award_types": ["D"], "date_type": "action_date", "date_range": {"start_date": "2009-10-01", "end_date": "2010-09-30"}, "agencies": [{"type": "awarding", "tier": "toptier", "name": "All"}]}, "file_format": "csv"}
Check the contract for the exact `agencies` shape for "all agencies" (the docs show a subtier example; the Custom Award Data Download page's "all" request uses a specific form; read the contract file and adapt; if the all-agencies form is rejected, loop over toptier agencies from `GET /api/v2/references/toptier_agencies/`). Prime award type "D" = definitive contract (B = purchase order, C = delivery order, A = BPA call). Fetch fiscal years FY2010 through FY2025 (action_date windows Oct 1 to Sep 30). Poll `status_url` until `status` is `finished`, then download `file_url`. Convert each zip's CSV(s) to parquet under `data/raw/usaspending/parquet/`, keeping only the columns you need (see below), then delete the zip. Log every request and file size in `usaspending/logs/`.

If the bulk API proves unusable (job failures, hours of queueing), fall back to the monthly full archive `https://files.usaspending.gov/award_data_archive/FY{YYYY}_All_Contracts_Full_{YYYYMMDD}.zip` (list via `POST /api/v2/bulk_download/list_monthly_files/` with {"agency":"all","fiscal_year":YYYY,"type":"contracts"}), stream-filter to award_type_code == "D" while converting, and delete each zip before fetching the next. Those files are several GB each; never hold more than one on disk.

Columns to keep (names are the USAspending download column names; confirm against the header of the first file and record the mapping): contract_award_unique_key, award_id_piid, parent_award_id_piid, modification_number, transaction_number, action_date, action_type_code, action_type, award_type_code, award_type, federal_action_obligation, total_dollars_obligated, base_and_exercised_options_value, current_total_value_of_award, base_and_all_options_value, potential_total_value_of_award, period_of_performance_start_date, period_of_performance_current_end_date, period_of_performance_potential_end_date, awarding_agency_code, awarding_agency_name, awarding_sub_agency_code, awarding_office_code, funding_agency_code, recipient_uei, recipient_duns, recipient_name, recipient_parent_uei, contracting_officers_determination_of_business_size_code, type_of_contract_pricing_code, naics_code, product_or_service_code, extent_competed_code, solicitation_procedures_code, number_of_offers_received, type_of_set_aside_code, solicitation_identifier, fed_biz_opps_code, performance_based_service_acquisition_code, multi_year_contract_code, cost_or_pricing_data_code, primary_place_of_performance_state_code, prime_award_transaction_place_of_performance_state_fips_code (if present), last_modified_date.

## Panel construction (verified mechanics, from the USAspending data dictionary read 2026-09-15)
- One award = one contract_award_unique_key (equivalently award_id_piid + awarding agency; PIIDs are only unique within an agency).
- The base award row = the action with modification_number "0" (or the earliest action_date if "0" is absent; record how many awards lack a "0" row).
- action_type_code is the FPDS Reason for Modification: A additional work; B supplemental agreement within scope; C funding only; D change order; E terminate for default; F terminate for convenience; G exercise an option; H definitize letter contract; J novation; K close out; L definitize change order; M other administrative; N legal contract cancellation; P/R/S/T/V/W/Y administrative. Verify the code list against the data dictionary endpoint `GET https://api.usaspending.gov/api/v2/references/data_dictionary/` (row "ActionType") and record the codes you actually see in the data with counts.
- base_and_all_options_value on the base row = agreed ceiling incl. options; on modifications it is the CHANGE. potential_total_value_of_award = cumulative ceiling. current_total_value_of_award = obligated to date incl. exercised options. period_of_performance_current_end_date = scheduled completion, revised by mods. Confirm each of these behaviours on a sample of 20 awards with many mods and print the evidence in the report (this is required: do not assert field semantics you have not observed).

## Labels (at horizons H = 12, 24, 36 months after the base action_date; use the latest action with action_date <= base + H)
1. ceiling_growth_H = potential_total_value_of_award(H) / base_and_all_options_value(base) - 1 (continuous); binary flags for > 0.10, > 0.25, > 0.50. Exclude bases with base value <= 0 or missing; record counts.
2. schedule_slip_days_H = period_of_performance_current_end_date(H) - period_of_performance_current_end_date(base) (continuous); binary > 90 days and > 365 days.
3. terminated_H = any action with action_type_code in {E, F, X} by H; also report E-only (default) separately.
4. change_order_count_H = count of action_type_code in {A, D} by H; unplanned_growth_H = sum of base_and_all_options_value changes on A and D actions by H, over base value.
Right-censoring: an award qualifies for horizon H only if the data extend at least H months past its base action_date (data end = the last action_date in your files). Report the qualifying N per FY and H.

## Population
Base awards with award_type_code D, base action_date in FY2010 to FY2022, base federal_action_obligation >= 250000 (the simplified acquisition threshold), non-null base current end date. Exclude awards whose base row is not the first action. Report the funnel (rows at each filter).

## Features (strictly as of the base row)
type_of_contract_pricing_code; extent_competed_code; solicitation_procedures_code; number_of_offers_received (and a missing flag); type_of_set_aside_code; naics_code (2-digit and 6-digit); product_or_service_code (first char and full); awarding agency and sub-agency; log base value; option heaviness = base_and_all_options_value / base_and_exercised_options_value; planned duration days = current end date - start date; potential extra duration = potential end - current end; business size code; performance-based flag; multi-year flag; cost-or-pricing-data flag; place of performance state; fiscal year. History features computed only from awards with base action_date strictly before this base date: recipient_uei prior award count, prior mean ceiling_growth_36 and prior termination rate (both using only outcomes that had resolved by this base date, i.e. base + 36 months <= this date); same for awarding_office_code. Document the as-of logic in code and test it.

## Models (the ladder), for each label and horizon
0. Unconditional base rate (train period).
1. Reference class: mean of the label within cells of (awarding agency, NAICS 2-digit, pricing code, log-value quintile), with shrinkage to the parent cell when n < 30.
2. Gradient boosting (sklearn HistGradientBoostingClassifier / Regressor) on all features incl. history.
3. Model 2 without the history features (ablation).
Split: train FY2010 to FY2017, validate FY2018 to FY2019, test FY2020 to FY2022 (base action_date FY). Do not tune on test. Group awareness: report test metrics also restricted to recipients unseen in training.
Metrics: binary labels: Brier score, Brier skill score vs base rate, AUC, calibration table (10 bins) and reliability plot; continuous: CRPS is optional; report MAE and pinball loss at the 10/50/90 quantiles if you fit quantile GBMs, otherwise report the binary flags only. Also report feature importance (permutation) for model 2 on the validation set.

## Deliverables
- `usaspending/README.md` (how to run), code under `usaspending/src/`, tests under `usaspending/tests/`, `usaspending/results/report.md` with: data funnel; field-behaviour evidence; label distributions by FY (tables); model table (rows = label x horizon, columns = base rate, reference class, GBM, GBM no-history: Brier, BSS, AUC); calibration tables; the unseen-recipient slice; top features; caveats; disk used; wall time.
- Also write `usaspending/results/base_rates.csv`: label x horizon x FY base rates, and `usaspending/results/reference_class_table.csv` (the cell means), since these are the first things the public scoreboard will show.


# RESUME NOTICE (read this before anything else)

You are continuing a lane that died at 23:06 ET on 2026-09-15 from a local DNS outage (the Anthropic API and files.usaspending.gov both failed to resolve for a few minutes), not from a logic error. Its work is intact in `usaspending/` and committed (c37dd40). Read `usaspending/PROGRESS.md` first: it records the acquisition path, a real finding (potential_total_value_of_award is sparse before FY2019 and restated afterwards, so ceiling labels are built from per-action base_and_all_options_value deltas), the modules written, and 71 passing tests (`.venv/bin/python -m pytest usaspending/tests -q`). Do not rewrite what exists; extend it.

State when you start:
- `data/raw/usaspending/parquet/contracts_D_FY{2010..2017,2019..2026}.parquet` exist. FY2018 was being refetched in four quarter windows by a detached process (`.venv/bin/python -m usaspending.src.bulk_fetch --fy-start 2018 --fy-end 2018 --workers 1 --splits 4 --manifest usaspending/results/fetch_manifest_fy2018.json`, pid 78939 at 23:20). Check `pgrep -fl bulk_fetch`, `usaspending/logs/bulk_fetch.log`, and `data/raw/usaspending/extract/` and `parquet/` for FY2018 parts. If the process is still running, wait for it (poll every 60 s, cap 45 min); if it died, rerun only the missing windows with the existing fetcher (the log says retrying a failed job with an identical body returns the same failed job; the fetcher's split option forces a fresh one). Then merge the FY2018 parts into `contracts_D_FY2018.parquet` if the fetcher does not already do so, and record FY2018 in `usaspending/results/fetch_manifest.json` like the other years.
- Network hiccups may recur: wrap downloads and API calls in retry with exponential backoff (up to 10 minutes total) and log every retry.

Then finish the workstream as specified above, with these additions:
1. Full panel: base awards with base action_date in FY2010 to FY2022, outcomes resolved from all actions through the last action_date in the FY2026 file; report the data end date and the right-censoring rule applied per horizon.
2. Run the model ladder (base rate, reference class, GBM, GBM without history) for every label x horizon; the quantile ladder for the continuous labels if the module exists; the unseen-recipient slice; permutation importance on validation.
3. Field-evidence section in the report: the potential_total_value_of_award finding with the measured fill rates by FY and the restatement rates, the 98.4 percent reconstruction agreement on final actions, and the per-action behaviour check for period_of_performance_current_end_date, each with the exact script that produced it.
4. Two fill-rate tables the public scoreboard needs: solicitation_identifier non-null share by FY on base rows (and the share matching the pattern of a SAM.gov solicitation number, e.g. containing letters and digits with length >= 8), and number_of_offers_received non-null share by FY and by extent_competed_code.
5. Base rates: `usaspending/results/base_rates.csv` (label x horizon x base FY) and `usaspending/results/reference_class_table.csv` (cell means with n), regenerated on the full panel.
6. `usaspending/results/report.md` as specified: funnel, field evidence, label distributions by FY, model table (rows = label x horizon; columns = base rate, reference class, GBM, GBM no-history; Brier, BSS, AUC), calibration tables for the GBM on test, unseen-recipient slice, top 15 permutation importances per label, quantile results if any, caveats, disk used, wall time. Every number from a script; name the script and command next to each table.
7. Update `usaspending/PROGRESS.md` and `usaspending/README.md` (one-command reproduction: fetch, panel, models, report). Run the tests at the end and print the exit code in your final message. Do not git commit.
