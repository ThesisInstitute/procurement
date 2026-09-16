# Thesify procurement

Registered, scored forecasts of public procurement outcomes, built the way Thesis scores bill forecasts: forecast at award, resolve against the official record, publish the skill.

Three workstreams, each in its own directory with its own README, tests, and `results/report.md`:

- `usaspending/` — US federal definitive contracts. Ex-ante features at the base award; labels from later FPDS modification rows (ceiling growth, schedule slip, termination). Forward-chained backtest with base-rate and reference-class baselines.
- `gmpp/` — UK Government Major Projects Portfolio. Rescoring the IPA/NISTA Delivery Confidence Assessments (2013 to 2024) against realised whole-life-cost growth, schedule slip, and later ratings.
- `worldbank/` — World Bank Project Appraisal Documents joined to IEG outcome ratings, leakage-controlled, plus a text baseline.

Conventions: Python 3.12+, `uv`, `pytest`. Raw downloads live under `data/raw/` (gitignored). Every number in a report traces to a script in this repo. Sentence case headings. No emoji.

Background memo: `~/chief-of-staff/state/procurement-thesify/memo.md` (2026-09-15).

## Results, first pass (2026-09-16)

Three backtests, each reproducible from its own directory. Full tables, calibration plots, caveats, and the list of what could not be verified are in each `results/report.md`.

### US federal definitive contracts (`usaspending/`)

192,377 definitive contracts with a base award of at least $250,000, base action FY2010 to FY2022, resolved against every later modification through 2026-09-13. Train FY2010 to FY2017, validate FY2018 to FY2019, test FY2020 to FY2022 (39,917 awards). Brier skill scores are against the training-period base rate; the reference class is the shrunken mean within agency, NAICS sector, pricing type, and size quintile.

| Label | Horizon (months) | Test base rate | BSS reference class | BSS GBM | BSS GBM without history | AUC GBM | AUC GBM, contractors unseen in training |
|---|---|---|---|---|---|---|---|
| ceiling_growth_gt10 | 12 | 0.122 | 0.030 | 0.097 | 0.096 | 0.730 | 0.652 |
| ceiling_growth_gt10 | 24 | 0.184 | 0.045 | 0.087 | 0.088 | 0.708 | 0.638 |
| ceiling_growth_gt10 | 36 | 0.213 | 0.051 | 0.085 | 0.085 | 0.705 | 0.638 |
| ceiling_growth_gt25 | 12 | 0.078 | 0.023 | 0.110 | 0.110 | 0.742 | 0.654 |
| ceiling_growth_gt25 | 24 | 0.115 | 0.031 | 0.102 | 0.100 | 0.719 | 0.648 |
| ceiling_growth_gt25 | 36 | 0.133 | 0.031 | 0.088 | 0.084 | 0.710 | 0.644 |
| ceiling_growth_gt50 | 12 | 0.053 | 0.019 | 0.111 | 0.116 | 0.750 | 0.656 |
| ceiling_growth_gt50 | 24 | 0.075 | 0.033 | 0.120 | 0.116 | 0.744 | 0.667 |
| ceiling_growth_gt50 | 36 | 0.086 | 0.030 | 0.108 | 0.104 | 0.737 | 0.666 |
| schedule_slip_gt90 | 12 | 0.287 | 0.109 | 0.314 | 0.314 | 0.844 | 0.827 |
| schedule_slip_gt90 | 24 | 0.456 | 0.169 | 0.352 | 0.352 | 0.839 | 0.818 |
| schedule_slip_gt90 | 36 | 0.502 | 0.205 | 0.355 | 0.355 | 0.838 | 0.815 |
| schedule_slip_gt365 | 12 | 0.056 | 0.035 | 0.096 | 0.097 | 0.832 | 0.834 |
| schedule_slip_gt365 | 24 | 0.207 | 0.129 | 0.363 | 0.364 | 0.860 | 0.853 |
| schedule_slip_gt365 | 36 | 0.281 | 0.163 | 0.384 | 0.383 | 0.856 | 0.852 |
| terminated | 12 | 0.008 | -0.002 | 0.004 | 0.004 | 0.649 | 0.643 |
| terminated | 24 | 0.013 | 0.001 | 0.005 | 0.006 | 0.642 | 0.636 |
| terminated | 36 | 0.019 | 0.005 | 0.006 | 0.005 | 0.636 | 0.604 |
| terminated_default | 12 | 0.000 | -0.008 | 0.000 | 0.001 | 0.640 | 0.600 |
| terminated_default | 24 | 0.001 | -0.006 | 0.000 | 0.000 | 0.615 | 0.589 |
| terminated_default | 36 | 0.001 | -0.006 | 0.003 | 0.002 | 0.786 | 0.803 |
| any_change_order | 12 | 0.116 | 0.041 | 0.077 | 0.078 | 0.747 | 0.714 |
| any_change_order | 24 | 0.166 | 0.077 | 0.118 | 0.116 | 0.755 | 0.722 |
| any_change_order | 36 | 0.187 | 0.087 | 0.124 | 0.125 | 0.754 | 0.719 |

What it says: schedule slip is forecastable at award (AUC 0.84 to 0.86, skill 0.31 to 0.38 over the base rate), ceiling growth is weakly forecastable (AUC 0.71 to 0.75, skill about 0.09 to 0.12), terminations are not (base rates below 2 percent, skill near zero). Contractor and office history adds almost nothing once contract type, competition, and scope are known, and the model holds up on contractors it never saw in training. One data finding changed the label definition: the cumulative ceiling field in FPDS is filled on only a quarter of actions before FY2017 and is restated after the fact, so ceiling growth is rebuilt from per-action deltas (see the report's field-evidence section).

### UK Government Major Projects Portfolio (`gmpp/`)

2,495 project-years across 708 projects and 14 snapshots (September 2012 to March 2026). The published Delivery Confidence Assessment, scored as a forecast of the next snapshot:

| Rating (five-point era, 2012 to 2021) | n | Whole-life cost up more than 10% next year | End date slipped more than 6 months | Rated Red next |
|---|---|---|---|---|
| Green | 26 | 7.7% | 6.5% | 0.0% |
| Amber/Green | 165 | 14.5% | 12.8% | 1.3% |
| Amber | 387 | 21.7% | 17.1% | 3.8% |
| Amber/Red | 222 | 34.7% | 28.6% | 6.1% |
| Red | 31 | 32.3% | 29.7% | 20.6% |

Rank discrimination for cost growth above 10 percent is 0.614 (95 percent interval 0.570 to 0.657) on the five-point scale and 0.552 (0.499 to 0.606) on the three-point scale that replaced it in March 2022, where Green projects now show a higher cost-growth rate than Amber ones. Read as probabilities, every rating overshoots on every cost and schedule outcome. The rating predicts its own successor best (AUC 0.712 for Red next year). Every outcome except portfolio exit is conditional on the project surviving to the next snapshot, and Green projects leave most (71 percent of Green project-years were the project's last) because they finish.

### World Bank appraisal documents to IEG outcome ratings (`worldbank/`)

4,253 rated projects with a qualifying Project Appraisal Document dated before board approval, joined on the P-number to the IEG rating written a median of eight years later. Forward-chained: test on 1,522 projects approved from 2011. A TF-IDF model on the appraisal text alone reaches AUC 0.624 pooled and 0.579 within country (permutation p = 0.009, uncorrected across a six-rung search), with Brier skill +0.024 against the realised test base rate. Country identity alone gives pooled AUC 0.570 and within-country 0.500. The joined table (`worldbank/results/pad_ieg_join.csv`) is the contribution; the text baseline is a weak positive awaiting a pre-registered replication.
