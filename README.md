# Thesify procurement

Registered, scored forecasts of public procurement outcomes, built the way Thesis scores bill forecasts: forecast at award, resolve against the official record, publish the skill.

Three workstreams, each in its own directory with its own README, tests, and `results/report.md`:

- `usaspending/` — US federal definitive contracts. Ex-ante features at the base award; labels from later FPDS modification rows (ceiling growth, schedule slip, termination). Forward-chained backtest with base-rate and reference-class baselines.
- `gmpp/` — UK Government Major Projects Portfolio. Rescoring the IPA/NISTA Delivery Confidence Assessments (2013 to 2024) against realised whole-life-cost growth, schedule slip, and later ratings.
- `worldbank/` — World Bank Project Appraisal Documents joined to IEG outcome ratings, leakage-controlled, plus a text baseline.

Conventions: Python 3.12+, `uv`, `pytest`. Raw downloads live under `data/raw/` (gitignored). Every number in a report traces to a script in this repo. Sentence case headings. No emoji.

Background memo: `~/chief-of-staff/state/procurement-thesify/memo.md` (2026-09-15).
