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

# Workstream: gmpp (directory `gmpp/`, disk budget 2 GB)

Goal: rescore the UK Government Major Projects Portfolio (GMPP) Delivery Confidence Assessments (DCAs) against what later happened. Nobody has published this. It is the first Thesis-style scoreboard on a government's own forecasts.

## Data acquisition
The gov.uk collection https://www.gov.uk/government/collections/major-projects-data lists one publication per department per year, 2013 to 2024 (about 195 documents; 2025 onward moved to NISTA dashboards, out of scope unless a CSV is available). Use the gov.uk content API: `GET https://www.gov.uk/api/content/government/collections/major-projects-data` returns `links.documents[]` with `base_path` and `title`; for each document `GET https://www.gov.uk/api/content<base_path>` returns `details.attachments[]` (or `details.documents` HTML containing attachment links) with `url`, `content_type`, `title`. Download every CSV/XLSX/XLS/ODS attachment whose title mentions "Government Major Projects Portfolio data" (and the transparency-policy guidance PDF for reference). Save under `data/raw/gmpp/<year>/<dept>/`. Log every URL. Some years publish one file per department; some are consolidated; handle both. Filenames and headers vary across years and departments; write a robust loader that maps column-name variants to a canonical schema and reports unmapped headers per file.

## Canonical panel (one row per project x reporting year)
Columns: gmpp_id, project_name, department, report_year (the March-of-year snapshot; e.g. the 2024 files are the March 2024 position), annual_report_category, description, dca_ipa (the IPA/MPA/NISTA Delivery Confidence Assessment as published), dca_sro (the SRO's assessment where present), dca_commentary, start_date, end_date (latest approved), schedule_narrative, fy_baseline_gbp_m, fy_forecast_gbp_m, fy_variance_pct, budget_narrative, wlc_baseline_gbp_m (total baseline whole-life cost), wlc_narrative, benefits_baseline_gbp_m, benefits_narrative, source_file.
Harmonise ratings to an ordered scale: Green, Amber/Green, Amber, Amber/Red, Red (5-point in earlier years) and Green, Amber, Red (3-point in later years; record the year the scale changed, from the data, and from the transparency policy document if it says so). Keep "Exempt", "Reset", and blanks as separate categories. Build a project identity across years using gmpp_id where present and a name+department fuzzy match otherwise; report how many project-years link and how many do not.

## Outcomes per project-year t (resolved from later snapshots)
1. wlc_growth_1y = wlc_baseline(t+1) / wlc_baseline(t) - 1; wlc_growth_2y likewise; flags > 0.10 and > 0.25. Also wlc growth vs the first-observed baseline for the project.
2. slip_1y_months = end_date(t+1) - end_date(t) in months; slip_2y; flags > 6 and > 12 months.
3. red_next = dca(t+1) == Red; red_or_amber_red_next for the 5-point era.
4. exit_next = project absent from t+1 snapshot; if the NISTA/IPA annual reports (HTML on gov.uk) list projects that left because they delivered vs were cancelled, classify exits; otherwise report exits unclassified.
Handle rebaselining: when wlc_baseline drops or jumps with a narrative mentioning "rebaselin", flag it; report results with and without rebaselined project-years.

## Scoring the DCA as a forecast
- Mapping-free: for each outcome, AUC of the DCA rank (Green best) as a predictor, per year and pooled. Also Spearman correlation with continuous growth and slip.
- Mapped: state an implied probability of "no material problem" per rating (Green 0.90, Amber/Green 0.75, Amber 0.50, Amber/Red 0.25, Red 0.10; and 0.85/0.50/0.15 for the 3-point era). Compute Brier score and its Murphy decomposition (reliability, resolution, uncertainty) for each outcome, and a calibration table: per rating, n, observed rate of each adverse outcome. Compare with (a) the base rate, (b) last year's rating as the forecast (persistence), (c) SRO DCA where present. Also fit an isotonic recalibration on 2013 to 2018 and evaluate on 2019 to 2024 to show what a calibrated DCA would look like.
- Report by department and by category (ICT, infrastructure, transformation, military capability) with n.
- Leakage: never use narrative columns from year t+1 or later; the year-t commentary is written knowing the year-t rating, which is fine because the DCA is the forecast being scored, but never feed it into a model. If you fit any model (optional), the only allowed inputs are year-t structured fields and prior ratings.

## Deliverables
- `gmpp/README.md`, code under `gmpp/src/`, tests under `gmpp/tests/` (loader canonicalisation on fixture headers, outcome construction, Brier decomposition), `gmpp/results/panel.csv` (the canonical panel; this is publishable), `gmpp/results/report.md` with: coverage table (departments x years, projects per year, link rate), rating distribution per year, the scale change, outcome tables, the calibration table per rating (the headline), Brier decomposition, AUCs, persistence comparison, department breakdown, and caveats. PNG: calibration chart per outcome; portfolio rating distribution over time; observed adverse-outcome rate by rating.
