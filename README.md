# Thesify procurement

Registered, scored forecasts of public procurement outcomes, built the way Thesis scores bill forecasts: forecast at award, resolve against the official record, publish the skill.

Three workstreams, each in its own directory with its own README, tests, and `results/report.md`:

- `usaspending/` — US federal definitive contracts. Ex-ante features at the base award; labels from later FPDS modification rows (ceiling growth, schedule slip, termination). Forward-chained backtest with base-rate and reference-class baselines.
- `gmpp/` — UK Government Major Projects Portfolio. Rescoring the IPA/NISTA Delivery Confidence Assessments (2013 to 2024) against realised whole-life-cost growth, schedule slip, and later ratings.
- `worldbank/` — World Bank Project Appraisal Documents joined to IEG outcome ratings, leakage-controlled, plus a text baseline.

Conventions: Python 3.12+, `uv`, `pytest`. Raw downloads live under `data/raw/` (gitignored). Every number in a report traces to a script in this repo. Sentence case headings. No emoji.

Background: [who has tried this, and what public data supports it](docs/landscape.md).

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

## Competing bidders: is the slip forecast about the bidder or the contract? (2026-09-16)

Max asked whether slip can be forecast per competing bidder. Two workstreams answer it where a competition set is observable. Full tables, nulls, and caveats in `bidders_us/results/report.md` and `prozorro/results/report.md`.

### United States (`bidders_us/`)

- **Contractor residual persistence.** On the definitive-contract panel, fit the slip model with nothing that identifies the contractor, then check whether a contractor's leftover slip in FY2010 to FY2017 predicts its leftover slip in FY2020 to FY2022. Roughly 1 to 2 percent of the forecastable slip signal is the contractor (persistence r 0.07 to 0.18 depending on the record window; AUC of the contractor's history alone 0.53 to 0.58; placebo r 0.005). The contracting office carries about twice that.
- **Vehicle holders as the competition set.** 798,977 delivery orders of $250,000 or more under multiple-award vehicles, FY2010 to FY2022, with vehicles defined as sibling contracts from one solicitation (81 eligible vehicles, 21,605 test orders, 2,671 holders). A holder's prior slip rate alone ranks orders within a vehicle at AUC 0.60 to 0.62 and persists across periods (Spearman 0.23 to 0.24 against a shuffled-identity null of 0.02), but adding it to the contract-shape model moves within-vehicle AUC by at most 0.002 and Brier skill by 0.003. Ranking holders by their record recovers 7 to 12 percent of the realised best-to-worst gap between holders on the same vehicle.
- **The two numbers a losing bid would have carried.** Number of offers has AUC 0.47 for slip on competed awards and a flat partial dependence from 2 to 30 offers; award size relative to its agency and product cell has AUC 0.56 and adds 0.0002 skill.

### Ukraine, Prozorro (`prozorro/`)

The only large system that publishes every bidder's identity and price. A systematic one-in-five-day sample of the tender feed: 80,182 completed above-threshold tenders created 2019 to 2022, 238,228 bids, 95,272 contracts, labels from the contract registry's typed change records. Forward-chained: train on tenders opened in 2019 to 2020, test on 2021 to 2022 (38,113 lots).

| Forecast of a recorded duration extension | AUC | Brier skill |
|---|---|---|
| Base rate (9.4 percent) | 0.500 | 0.000 |
| Reference class (sector by region) | 0.704 | 0.066 |
| GBM on the lot alone | 0.728 | 0.117 |
| plus the buyer's record | 0.749 | 0.135 |
| plus the winner's price position | 0.759 | 0.149 |
| plus the winner's identity and record | 0.751 | 0.128 |

The bidder's price position among its rivals on the same lot carries signal; the bidder's identity and past record do not add any once the lot and the buyer are known, and outcomes cluster by bidder (intraclass correlation 0.227 against a null of 0.151) without that clustering being usable in advance. Transfer scoring of bidder-level forecasts (forecasts on lost lots against realised rates on won lots) reaches Spearman 0.273 but does not beat a lot-only placebo at 0.287. When the cheapest bid was disqualified and a dearer bid won, recorded extensions ran 1.4 points higher (0.9 to 1.9) than matched controls. Deeper winner discounts go with slightly fewer extensions, the opposite of the winner's-curse intuition.

## Licensing

Code is released under the MIT License (see `LICENSE`). Reports, charts, and the derived tables under each `results/` directory are released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): reuse them with attribution to the Thesis Institute. Upstream data keep their own terms: USAspending and FPDS records are US government works; the IEG project ratings are published by the World Bank under CC BY 4.0; the UK Government Major Projects Portfolio files are published under the Open Government Licence v3.0; World Bank project documents and Prozorro tender records are reproduced under the terms their publishers state.
