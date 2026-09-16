# Forecasting contract slip per competing bidder, Ukraine (Prozorro)

**Only weakly, and only on one of the three forecasting tests. The evidence, sharpest test first: with the lot held fixed, a bidder's own prior extension rate ranks its realised outcome at AUC 0.512 against a same-lot null of 0.501 (p = 0.016); the winner's raw price rank among the bids on that same lot, with no model between the price and the statistic, reaches AUC 0.513 (p = 0.011); a model given only the lot and the bidder's price reaches AUC 0.552 against 0.500 (p = 0.001); a bidder's mean forecast on the lots it lost ranks its realised rate on the lots it won at Spearman 0.273 against a within-division shuffled null of 0.212 (one-sided p = 0.000), against 0.287 for a lot-only placebo that knows nothing about the bidder and which it does not beat; outcomes nonetheless cluster by bidder beyond the buyer and the year (intraclass correlation 0.227 against a null of 0.151, one-sided p = 0.0020); and adding the winner's identity and record to the award-time model moves test AUC by -0.008.**

Prozorro is the only large procurement system that publishes every bidder's identity and price, so it is the only public place where the question can be asked at all. This report builds the panel, forecasts the winning contract's slip from award-time information, and then scores every losing bidder by transfer: what a bidder's forecast on the lots it lost says about the lots it won.

### The three tests, and why there are three

A losing bid never becomes a contract, so no forecast attached to one can ever be resolved. Everything below is an attempt to get at the same question without that resolution, and the three tests fail in different ways, which is why all three are reported.

| Test | What it compares | What could fake a positive result |
|---|---|---|
| Within-lot | the bidders on one lot, against each other, then the winner's own outcome | nothing about the lot: the buyer, the sector, the size and the year are identical for every bidder on it |
| Transfer | a bidder's mean forecast on lots it lost, against its realised rate on lots it won | the kinds of lot a bidder competes for, which is why the null shuffles within CPV division and a lot-only placebo is reported |
| Identity persistence | a bidder's rate in 2019-2020 against its rate in 2021-2022, won lots only | the sector a bidder works in, which is what the null holds fixed |

## What was built

A one-in-5 systematic sample of whole days from the Prozorro tender feed, every completed above-threshold tender it contains that was created in 2019 to 2022, each of those tenders' full documents (which is where the bids live), and the live contract-registry record for every contract they produced. From those, four released tables, a lot-level analysis table, a forward-chained model ladder, and the experiments below.

- Feed walked: 3,604,000 rows over 366 whole days, 3,604 listing requests.
- Completed above-threshold tenders found, all creation years: 121,036.
- Of those, created 2019-01-01 to 2022-12-31: 80,182.
- Queued for fetching: all of them. There is no second-stage subsample, so the only sampling step in the whole design is the one-in-5 day selection.
- Tender documents parsed: 80,182; bid rows: 238,228; lot rows: 92,802.
- Lots in the analysis set (at least two live priced bids, an identified winner, and a contract): 85,052 across 75,676 tenders, 20,768 distinct winning bidders, 39,553 distinct bidders overall, 12,121 buyers.
- HTTP requests issued during document fetching: contract 90,718, tender 80,182.

## The data and how the sample was drawn

The listing endpoint `/api/2.5/tenders` is ordered by `dateModified`, not by tender date, and each tender sits in it once at its current `dateModified`. Because `dateModified` only increases, a forward walk from a seed date visits every tender whose current `dateModified` is at or after that seed, and a tender created on or after the seed must have been modified on or after its creation. A walk from 2019-01-01 to the present would therefore be a complete census of everything created from 2019-01-01 onwards.

Walking every one of those rows to the present would have taken hours: feed volume rises from about 110,000 rows a month in 2019 to over 400,000 by late 2020. Instead the frame is a **systematic sample of whole days**: every 5th day of `dateModified` from 2019-01-01 to 2024-01-01, walked from midnight to midnight. Because whole days are taken and each selected day is walked completely, every tender in the range has inclusion probability exactly 0.20 whatever the volume of the day it happens to sit in. Sampling a fixed number of rows per day would instead have over-represented quiet days, and a step of 5 is coprime with 7 so the selected days rotate through the days of the week.

Covered `dateModified` span: 2019-01-01T00:00:10.310757+02:00 to 2024-01-01T10:10:30.344427+02:00; 3,604 listing requests over 366 whole days.

The only truncation the design can still cause is a tender whose feed position fell after the walk's end date. Measured on the fetched sample, the lag from the tenderID creation date to the tender's final `dateModified` has median 38 days, p99 115 days and a maximum of 1239 days; 54 of 80,182 tenders (0.067 percent) exceed a year and 54 exceed the 366 days of slack the walk allows after the last tender creation date in the window. That is the exact size of the hole. This is also why a tender's feed position is safe to use at all: a tender's `dateModified` freezes when its contract is published and does not move when the contract registry is later amended, so the walk does not select on the outcome being forecast.

What the feed is mostly made of (top procedure-and-status combinations):

| procedure and status | feed rows |
|---|---|
| reporting|complete | 2,992,260 |
| belowThreshold|complete | 142,264 |
| aboveThresholdUA|unsuccessful | 79,764 |
| belowThreshold|unsuccessful | 71,132 |
| aboveThresholdUA|complete | 67,843 |
| aboveThreshold|complete | 46,066 |
| aboveThreshold|unsuccessful | 29,901 |
| negotiation.quick|complete | 26,738 |
| reporting|active | 26,454 |
| negotiation|complete | 25,639 |
| belowThreshold|cancelled | 15,852 |
| aboveThresholdUA|cancelled | 14,294 |

Within that frame the sample is the completed tenders of the three above-threshold procedure types (`aboveThreshold`, `aboveThresholdUA`, `aboveThresholdEU`) whose tenderID creation date falls in 2019-01-01 to 2022-12-31, and every one of them was fetched, so there is no second sampling step to describe. The fetch order is shuffled across months, so even an interrupted fetch spans the whole window.

Tenders by creation year, and what survives into the analysis set:

| tender creation year | found in the 1-in-5 day sample | lots in the analysis set |
|---|---|---|
| 2019 | 20,859 | 23,733 |
| 2020 | 20,571 | 23,204 |
| 2021 | 25,955 | 29,070 |
| 2022 | 12,797 | 9,043 |

Above-threshold volume falls 50.7 percent from 2021 to 2022. That is the war, not a sampling artefact: the same one-in-5 day rule applies to every year. It is the main reason the 2022 test window is thin, and the reason a 2021-only test window is reported alongside it.

| procedure | lots in analysis set |
|---|---|
| aboveThresholdUA | 73,237 |
| aboveThresholdEU | 8,993 |
| aboveThreshold | 2,822 |

Lots whose tender opened on or after 2022-02-24, the full-scale invasion: 5,918 of 85,052. Every table that pools years is also reported on a 2021-only test window, which is entirely pre-invasion.

## Field evidence: what was checked in the data rather than assumed

Three things about the API changed the design, and all three were observed directly on 2026-09-16 rather than taken from documentation.

1. **`contractChangeRationaleTypes` is a vocabulary, not a record.** Every registry contract returns the same nine-entry dictionary (`durationExtension`, `fiscalYearExtension`, `itemPriceVariation`, `priceReduction`, `qualityImprovement`, `taxRate`, `thirdParty`, `volumeCuts`, `priceClarification`) whether or not any change was made: in an 89-contract probe all nine appeared on all 89. Applied changes live in `changes[]`, each entry carrying its own `rationaleTypes`, `date`, `dateSigned` and `status`. Every extension label here is built from `changes[]`.
2. **Registry `status: terminated` is the ordinary completed state.** In the same probe 78 of 89 contracts were `terminated`, 6 `active` and 5 `cancelled`. Treating `terminated` as a failure, as an English reading suggests, would have labelled almost the whole sample as failed. The abnormal state is `cancelled`, and that is what the `cancelled` label uses.
3. **`bids` and `awards` cannot be requested through `opt_fields`.** The listing endpoint honours `status`, `procurementMethodType`, `dateModified`, `tenderID`, `dateCreated`, `procuringEntity`, `awardPeriod`, `tenderPeriod` and `contracts`, and silently drops `bids`, `awards`, `lots`, `value`, `items`, `title` and `mainProcurementCategory`. Bidder identities therefore require one full tender fetch each, which is what sets the size of the sample.

Contract status in the analysis set, registry record against the tender's own copy:

| status | registry record | tender copy |
|---|---|---|
| terminated | 76,116 | 0 |
| active | 8,827 | 84,943 |
| pending | 109 | 109 |

That table is itself evidence that the tender copy is frozen at signing: the registry has moved most of these contracts to `terminated` while the tender copy still shows every one of them as it stood when the contract was published. It also shows why the `cancelled` label carries no information in this sample: there are 0 cancelled contracts among the lots scored. A tender only reaches status `complete` once it has a live contract, and where a lot has both a cancelled contract and a live replacement the live one is the one scored, so contract cancellation is essentially unobservable inside a completed-tender sample. It is reported rather than dropped, and the ladder refuses to score it.

The date encoded in the human `tenderID` matches the date part of `tenderPeriod.startDate` on 100.00 percent of the fetched tenders, which is why the sampling frame can be stratified on the tenderID without fetching every tender first.

Bid entry statuses across the whole fetched sample (238,228 entries): `active` 234,085, `deleted` 2,458, `unsuccessful` 1,615, `invalid` 70. Entries with status `deleted`, `draft` or `invalid.pre-qualification` never reached evaluation and are excluded from the bid counts, the price ranks and the dispersion statistics.

Consortium bids, meaning more than one tenderer on a single bid: 0. Prozorro records one legal entity per bid in this sample, so a bidder identity is unambiguous.

Disqualification is recorded as an award with status `unsuccessful` against a specific bid, not as a status on the bid itself: across the fetched sample there are 26,739 unsuccessful awards against 90,035 active ones. Prozorro strips the price from a bid that was withdrawn or rejected outright, and 13,345 bid entries in the sample carry no amount at all, so they cannot be ranked. Of the 26,739 unsuccessful awards, 100.0 percent point at a bid that does still carry a price and can therefore be placed in the price order. Experiment 3 is restricted to those.

The tender document's copy of a contract lags the live registry: it is written when the tender was last touched, and in the sample it agrees with the registry on the contract end date 79.2 percent of the 84,672 lots where both dates are present. The registry end date is later in 19.1 percent of them, by a median of 90 days. Conditioning on the registry's own `durationExtension` change, the two dates differ in 64.8 percent of extended contracts and 16.5 percent of unextended ones, and of the contracts whose end date did move, 27.7 percent carry a `durationExtension` change. So the end date moves considerably more often than an extension is registered against it. Some of that is a genuinely different event, an administrative edit to the period rather than an agreed extension, and some of it is the tender copy having been written after a change rather than at signing. Either way `days_extended` is the broader and noisier of the two signals, and `duration_extension`, which needs no date arithmetic at all, is the primary label for that reason.

## Fill rates

Field presence, over every parsed lot and over the analysis set. The analysis set is lots with at least two live priced bids, an identified winning bid and a contract.

| field | lots | share | lots, analysis set | share, analysis set |
|---|---|---|---|---|
| at least two live priced bids on the lot | 85,947 | 0.926 | 85,052 | 1.000 |
| an identified winning bid | 90,027 | 0.970 | 85,052 | 1.000 |
| lot has a contract in the tender document | 90,392 | 0.974 | 85,052 | 1.000 |
| contract found in the live registry | 85,857 | 0.925 | 85,052 | 1.000 |
| registry amountPaid present | 76,993 | 0.830 | 76,585 | 0.900 |
| registry amountPaid present and positive | 74,347 | 0.801 | 73,948 | 0.869 |
| registry period.endDate present | 85,207 | 0.918 | 84,768 | 0.997 |
| tender-copy contract period.endDate present | 89,646 | 0.966 | 84,672 | 0.996 |
| both period end dates present | 85,111 | 0.917 | 84,672 | 0.996 |
| registry changes[] non-empty | 47,533 | 0.512 | 47,352 | 0.557 |
| value_change_ratio computable | 85,153 | 0.918 | 84,348 | 0.992 |
| winner discount computable | 90,027 | 0.970 | 85,052 | 1.000 |
| bid dispersion computable | 85,947 | 0.926 | 85,052 | 1.000 |
| lots (denominator) | 92,802 | 1.000 | 85,052 | 1.000 |

## Labels

All labels are on the winning contract of a lot. A lot is one (tender, lot) pair; a single-lot tender contributes one row.

| Label | Definition | Source |
|---|---|---|
| `duration_extension` | at least one entry in `changes[]` whose `rationaleTypes` contains `durationExtension` | live contract registry |
| `days_extended_gt90` | registry `period.endDate` minus the tender copy's `contracts[].period.endDate`, above 90 days | registry and tender copy |
| `value_growth_gt10` | registry contract value over the value at signing, above 1.10, compared net to net where both `amountNet` are present and gross to gross otherwise | registry and tender copy |
| `any_change` | `changes[]` non-empty | live contract registry |
| `underexecuted` | registry `amountPaid` below 0.9 of the value at signing | live contract registry |
| `cancelled` | registry `status == "cancelled"` | live contract registry |

### Base rates by tender creation year

| year | lots | tenders | still running at the snapshot | duration extension recorded | end date moved out more than 90 days | contract value up more than 10 percent | any registered change | paid less than 90 percent of the signed value | contract cancelled |
|---|---|---|---|---|---|---|---|---|---|
| 2019 | 23,733 | 20,859 | 0.126 | 0.081 | 0.141 | 0.081 | 0.543 | 0.234 | 0.000 |
| 2020 | 23,204 | 20,571 | 0.092 | 0.090 | 0.078 | 0.073 | 0.570 | 0.278 | 0.000 |
| 2021 | 29,070 | 25,955 | 0.101 | 0.102 | 0.081 | 0.062 | 0.561 | 0.318 | 0.000 |
| 2022 | 9,043 | 8,289 | 0.085 | 0.066 | 0.054 | 0.042 | 0.544 | 0.389 | 0.000 |
| 2023 | 2 | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.500 | 0.500 | 0.000 |

Every label is read at one snapshot, so cohorts differ in how long they have had to accumulate changes. The fourth column measures what is left of that: the share of lots whose contract the registry still calls `active` runs from 0.0 percent to 12.6 percent, and it falls with the cohort year, so the test cohorts are if anything less censored than the training cohorts and the models are not being flattered by it. The oldest cohort carrying the most still-running contracts is not what exposure alone would predict, and no explanation for it is established here.

## Experiment 1: forecasting the winner's slip from award-time features

Forward-chained throughout. Training is every lot whose tender opened in 2019 or 2020; the test windows are later and disjoint. Every history feature is evaluated at the tender's own `tenderPeriod.startDate` and counts only events dated strictly before it, so a contract signed before the cutoff but extended after it contributes to the denominator and not the numerator. Brier skill is against the training-window base rate, which is a number a forecaster could have quoted in advance, never against the realised test rate.

Rungs, nested, so that each step answers one question: the training base rate; a shrunken CPV-division by region cell mean; gradient boosting on the lot alone with no identity of any kind in it; the same plus the buyer's as-of record; the same plus the winner's price position on that lot; the same plus the winner's as-of record.

Before any of the bidder questions, the plain one: how forecastable are these outcomes at all? Best rung on the primary test window, by skill against the training base rate: duration extension recorded AUC 0.759 with skill +0.149 on a 9.4 percent base rate; end date moved out more than 90 days AUC 0.756 with skill +0.117 on a 7.5 percent base rate; contract value up more than 10 percent AUC 0.763 with skill +0.048 on a 5.7 percent base rate; any registered change AUC 0.759 with skill +0.191 on a 55.7 percent base rate; paid less than 90 percent of the signed value AUC 0.787 with skill +0.230 on a 33.5 percent base rate. For comparison the US panel in this repository reaches AUC 0.84 to 0.86 on schedule slip, so Ukrainian above-threshold contracts are the harder forecasting problem, on outcomes that are not quite the same outcomes.

One detail worth stating rather than hiding: the gradient booster's own early-stopping validation split is a random 15 percent of the training window, not a temporal one. The test window is strictly later than the whole training window either way, so no test information enters the fit.

### test 2021-2022

| label | model | test lots | test base rate | train base rate | Brier | skill vs train base rate | AUC |
|---|---|---|---|---|---|---|---|
| duration extension recorded | base rate | 38,113 | 0.094 | 0.085 | 0.0849 | 0.000 | 0.500 |
| duration extension recorded | reference class | 38,113 | 0.094 | 0.085 | 0.0793 | 0.066 | 0.704 |
| duration extension recorded | GBM lot, no buyer history | 38,113 | 0.094 | 0.085 | 0.0750 | 0.117 | 0.728 |
| duration extension recorded | GBM lot, plus buyer history | 38,113 | 0.094 | 0.085 | 0.0735 | 0.135 | 0.749 |
| duration extension recorded | GBM plus the bidder's price | 38,113 | 0.094 | 0.085 | 0.0722 | 0.149 | 0.759 |
| duration extension recorded | GBM plus the bidder's price and history | 38,113 | 0.094 | 0.085 | 0.0740 | 0.128 | 0.751 |
| end date moved out more than 90 days | base rate | 38,000 | 0.075 | 0.110 | 0.0704 | 0.000 | 0.500 |
| end date moved out more than 90 days | reference class | 38,000 | 0.075 | 0.110 | 0.0691 | 0.018 | 0.658 |
| end date moved out more than 90 days | GBM lot, no buyer history | 38,000 | 0.075 | 0.110 | 0.0652 | 0.074 | 0.720 |
| end date moved out more than 90 days | GBM lot, plus buyer history | 38,000 | 0.075 | 0.110 | 0.0630 | 0.105 | 0.739 |
| end date moved out more than 90 days | GBM plus the bidder's price | 38,000 | 0.075 | 0.110 | 0.0625 | 0.112 | 0.749 |
| end date moved out more than 90 days | GBM plus the bidder's price and history | 38,000 | 0.075 | 0.110 | 0.0621 | 0.117 | 0.756 |
| contract value up more than 10 percent | base rate | 38,113 | 0.057 | 0.077 | 0.0544 | 0.000 | 0.500 |
| contract value up more than 10 percent | reference class | 38,113 | 0.057 | 0.077 | 0.0528 | 0.030 | 0.711 |
| contract value up more than 10 percent | GBM lot, no buyer history | 38,113 | 0.057 | 0.077 | 0.0518 | 0.048 | 0.763 |
| contract value up more than 10 percent | GBM lot, plus buyer history | 38,113 | 0.057 | 0.077 | 0.0530 | 0.027 | 0.726 |
| contract value up more than 10 percent | GBM plus the bidder's price | 38,113 | 0.057 | 0.077 | 0.0527 | 0.032 | 0.735 |
| contract value up more than 10 percent | GBM plus the bidder's price and history | 38,113 | 0.057 | 0.077 | 0.0524 | 0.037 | 0.742 |
| any registered change | base rate | 38,113 | 0.557 | 0.557 | 0.2467 | 0.000 | 0.500 |
| any registered change | reference class | 38,113 | 0.557 | 0.557 | 0.2183 | 0.115 | 0.703 |
| any registered change | GBM lot, no buyer history | 38,113 | 0.557 | 0.557 | 0.2008 | 0.186 | 0.755 |
| any registered change | GBM lot, plus buyer history | 38,113 | 0.557 | 0.557 | 0.2013 | 0.184 | 0.755 |
| any registered change | GBM plus the bidder's price | 38,113 | 0.557 | 0.557 | 0.1997 | 0.191 | 0.758 |
| any registered change | GBM plus the bidder's price and history | 38,113 | 0.557 | 0.557 | 0.1995 | 0.191 | 0.759 |
| paid less than 90 percent of the signed value | base rate | 33,026 | 0.335 | 0.256 | 0.2289 | 0.000 | 0.500 |
| paid less than 90 percent of the signed value | reference class | 33,026 | 0.335 | 0.256 | 0.1933 | 0.156 | 0.736 |
| paid less than 90 percent of the signed value | GBM lot, no buyer history | 33,026 | 0.335 | 0.256 | 0.1762 | 0.230 | 0.788 |
| paid less than 90 percent of the signed value | GBM lot, plus buyer history | 33,026 | 0.335 | 0.256 | 0.1763 | 0.230 | 0.785 |
| paid less than 90 percent of the signed value | GBM plus the bidder's price | 33,026 | 0.335 | 0.256 | 0.1761 | 0.230 | 0.787 |
| paid less than 90 percent of the signed value | GBM plus the bidder's price and history | 33,026 | 0.335 | 0.256 | 0.1766 | 0.229 | 0.786 |

### test 2021 only (pre-invasion)

| label | model | test lots | test base rate | train base rate | Brier | skill vs train base rate | AUC |
|---|---|---|---|---|---|---|---|
| duration extension recorded | base rate | 29,070 | 0.102 | 0.085 | 0.0920 | 0.000 | 0.500 |
| duration extension recorded | reference class | 29,070 | 0.102 | 0.085 | 0.0856 | 0.070 | 0.711 |
| duration extension recorded | GBM lot, no buyer history | 29,070 | 0.102 | 0.085 | 0.0802 | 0.129 | 0.739 |
| duration extension recorded | GBM lot, plus buyer history | 29,070 | 0.102 | 0.085 | 0.0782 | 0.150 | 0.761 |
| duration extension recorded | GBM plus the bidder's price | 29,070 | 0.102 | 0.085 | 0.0764 | 0.169 | 0.772 |
| duration extension recorded | GBM plus the bidder's price and history | 29,070 | 0.102 | 0.085 | 0.0786 | 0.145 | 0.760 |
| end date moved out more than 90 days | base rate | 28,971 | 0.081 | 0.110 | 0.0754 | 0.000 | 0.500 |
| end date moved out more than 90 days | reference class | 28,971 | 0.081 | 0.110 | 0.0735 | 0.026 | 0.662 |
| end date moved out more than 90 days | GBM lot, no buyer history | 28,971 | 0.081 | 0.110 | 0.0679 | 0.099 | 0.733 |
| end date moved out more than 90 days | GBM lot, plus buyer history | 28,971 | 0.081 | 0.110 | 0.0669 | 0.114 | 0.747 |
| end date moved out more than 90 days | GBM plus the bidder's price | 28,971 | 0.081 | 0.110 | 0.0661 | 0.124 | 0.758 |
| end date moved out more than 90 days | GBM plus the bidder's price and history | 28,971 | 0.081 | 0.110 | 0.0654 | 0.133 | 0.768 |
| contract value up more than 10 percent | base rate | 29,070 | 0.062 | 0.077 | 0.0586 | 0.000 | 0.500 |
| contract value up more than 10 percent | reference class | 29,070 | 0.062 | 0.077 | 0.0560 | 0.044 | 0.728 |
| contract value up more than 10 percent | GBM lot, no buyer history | 29,070 | 0.062 | 0.077 | 0.0530 | 0.096 | 0.784 |
| contract value up more than 10 percent | GBM lot, plus buyer history | 29,070 | 0.062 | 0.077 | 0.0564 | 0.038 | 0.734 |
| contract value up more than 10 percent | GBM plus the bidder's price | 29,070 | 0.062 | 0.077 | 0.0560 | 0.044 | 0.747 |
| contract value up more than 10 percent | GBM plus the bidder's price and history | 29,070 | 0.062 | 0.077 | 0.0557 | 0.049 | 0.757 |
| any registered change | base rate | 29,070 | 0.561 | 0.557 | 0.2463 | 0.000 | 0.500 |
| any registered change | reference class | 29,070 | 0.561 | 0.557 | 0.2152 | 0.126 | 0.710 |
| any registered change | GBM lot, no buyer history | 29,070 | 0.561 | 0.557 | 0.1967 | 0.201 | 0.763 |
| any registered change | GBM lot, plus buyer history | 29,070 | 0.561 | 0.557 | 0.1965 | 0.202 | 0.764 |
| any registered change | GBM plus the bidder's price | 29,070 | 0.561 | 0.557 | 0.1955 | 0.206 | 0.766 |
| any registered change | GBM plus the bidder's price and history | 29,070 | 0.561 | 0.557 | 0.1953 | 0.207 | 0.767 |
| paid less than 90 percent of the signed value | base rate | 25,276 | 0.318 | 0.256 | 0.2207 | 0.000 | 0.500 |
| paid less than 90 percent of the signed value | reference class | 25,276 | 0.318 | 0.256 | 0.1867 | 0.154 | 0.742 |
| paid less than 90 percent of the signed value | GBM lot, no buyer history | 25,276 | 0.318 | 0.256 | 0.1644 | 0.255 | 0.806 |
| paid less than 90 percent of the signed value | GBM lot, plus buyer history | 25,276 | 0.318 | 0.256 | 0.1677 | 0.240 | 0.797 |
| paid less than 90 percent of the signed value | GBM plus the bidder's price | 25,276 | 0.318 | 0.256 | 0.1676 | 0.241 | 0.799 |
| paid less than 90 percent of the signed value | GBM plus the bidder's price and history | 25,276 | 0.318 | 0.256 | 0.1676 | 0.240 | 0.798 |

### test 2022 post-invasion

| label | model | test lots | test base rate | train base rate | Brier | skill vs train base rate | AUC |
|---|---|---|---|---|---|---|---|
| duration extension recorded | base rate | 5,916 | 0.073 | 0.085 | 0.0678 | 0.000 | 0.500 |
| duration extension recorded | reference class | 5,916 | 0.073 | 0.085 | 0.0655 | 0.034 | 0.647 |
| duration extension recorded | GBM lot, no buyer history | 5,916 | 0.073 | 0.085 | 0.0638 | 0.060 | 0.680 |
| duration extension recorded | GBM lot, plus buyer history | 5,916 | 0.073 | 0.085 | 0.0639 | 0.058 | 0.704 |
| duration extension recorded | GBM plus the bidder's price | 5,916 | 0.073 | 0.085 | 0.0643 | 0.051 | 0.703 |
| duration extension recorded | GBM plus the bidder's price and history | 5,916 | 0.073 | 0.085 | 0.0645 | 0.050 | 0.717 |
| end date moved out more than 90 days | base rate | 5,912 | 0.057 | 0.110 | 0.0564 | 0.000 | 0.500 |
| end date moved out more than 90 days | reference class | 5,912 | 0.057 | 0.110 | 0.0573 | -0.016 | 0.629 |
| end date moved out more than 90 days | GBM lot, no buyer history | 5,912 | 0.057 | 0.110 | 0.0557 | 0.012 | 0.683 |
| end date moved out more than 90 days | GBM lot, plus buyer history | 5,912 | 0.057 | 0.110 | 0.0533 | 0.056 | 0.699 |
| end date moved out more than 90 days | GBM plus the bidder's price | 5,912 | 0.057 | 0.110 | 0.0533 | 0.055 | 0.710 |
| end date moved out more than 90 days | GBM plus the bidder's price and history | 5,912 | 0.057 | 0.110 | 0.0535 | 0.051 | 0.713 |
| contract value up more than 10 percent | base rate | 5,916 | 0.040 | 0.077 | 0.0394 | 0.000 | 0.500 |
| contract value up more than 10 percent | reference class | 5,916 | 0.040 | 0.077 | 0.0407 | -0.033 | 0.650 |
| contract value up more than 10 percent | GBM lot, no buyer history | 5,916 | 0.040 | 0.077 | 0.0405 | -0.028 | 0.687 |
| contract value up more than 10 percent | GBM lot, plus buyer history | 5,916 | 0.040 | 0.077 | 0.0392 | 0.006 | 0.713 |
| contract value up more than 10 percent | GBM plus the bidder's price | 5,916 | 0.040 | 0.077 | 0.0394 | 0.001 | 0.705 |
| contract value up more than 10 percent | GBM plus the bidder's price and history | 5,916 | 0.040 | 0.077 | 0.0394 | 0.001 | 0.703 |
| any registered change | base rate | 5,916 | 0.499 | 0.557 | 0.2533 | 0.000 | 0.500 |
| any registered change | reference class | 5,916 | 0.499 | 0.557 | 0.2254 | 0.110 | 0.713 |
| any registered change | GBM lot, no buyer history | 5,916 | 0.499 | 0.557 | 0.2034 | 0.197 | 0.760 |
| any registered change | GBM lot, plus buyer history | 5,916 | 0.499 | 0.557 | 0.2056 | 0.188 | 0.761 |
| any registered change | GBM plus the bidder's price | 5,916 | 0.499 | 0.557 | 0.2028 | 0.199 | 0.765 |
| any registered change | GBM plus the bidder's price and history | 5,916 | 0.499 | 0.557 | 0.2037 | 0.196 | 0.763 |
| paid less than 90 percent of the signed value | base rate | 5,313 | 0.298 | 0.256 | 0.2108 | 0.000 | 0.500 |
| paid less than 90 percent of the signed value | reference class | 5,313 | 0.298 | 0.256 | 0.1858 | 0.118 | 0.711 |
| paid less than 90 percent of the signed value | GBM lot, no buyer history | 5,313 | 0.298 | 0.256 | 0.1872 | 0.112 | 0.727 |
| paid less than 90 percent of the signed value | GBM lot, plus buyer history | 5,313 | 0.298 | 0.256 | 0.1893 | 0.102 | 0.723 |
| paid less than 90 percent of the signed value | GBM plus the bidder's price | 5,313 | 0.298 | 0.256 | 0.1883 | 0.107 | 0.726 |
| paid less than 90 percent of the signed value | GBM plus the bidder's price and history | 5,313 | 0.298 | 0.256 | 0.1889 | 0.104 | 0.724 |

Reading the nested rungs on duration extension recorded, each step against the one above it: adding the buyer's own record moves AUC +0.022; adding the winner's price position moves AUC +0.009; adding the winner's own record moves AUC -0.008.

Reading the nested rungs on end date moved out more than 90 days, each step against the one above it: adding the buyer's own record moves AUC +0.019; adding the winner's price position moves AUC +0.010; adding the winner's own record moves AUC +0.006.

Labels refused by the ladder, because a label with almost no positives on one side of the split produces skill and AUC numbers that are noise dressed as results:

| split | label | reason |
|---|---|---|
| test 2021-2022 | cancelled | cancelled: 0 positives in train, 0 in test |
| test 2021 only (pre-invasion) | cancelled | cancelled: 0 positives in train, 0 in test |
| test 2022 post-invasion | cancelled | cancelled: 0 positives in train, 0 in test |

Calibration of the top rung on duration extension, test 2021-2022, in equal-count bins of the forecast:

| lots | mean forecast | observed rate |
|---|---|---|
| 3,812 | 0.0081 | 0.0262 |
| 3,811 | 0.0179 | 0.0391 |
| 3,811 | 0.0254 | 0.0352 |
| 3,811 | 0.0329 | 0.0446 |
| 3,812 | 0.0418 | 0.0459 |
| 3,811 | 0.0529 | 0.0622 |
| 3,811 | 0.0682 | 0.0743 |
| 3,811 | 0.0919 | 0.1273 |
| 3,811 | 0.1470 | 0.1204 |
| 3,812 | 0.4169 | 0.3610 |

Murphy decomposition of that Brier score: reliability 0.00062, resolution 0.00903, uncertainty 0.08485. Reliability is the calibration penalty and smaller is better; resolution is how far the forecasts move away from the base rate in the right direction and larger is better.

![Calibration, duration extension](calibration_duration_extension.png)

## Experiment 2: the competing-bidder test

A losing bid never produces a contract, so its forecast can never be resolved directly. Instead every bidder on every test lot is scored as if it had won: the lot block is held fixed and the bidder block is replaced by that bidder's own price on that lot and its own as-of record. Each bidder's mean forecast over the lots it LOST is then compared with the rate it actually realised on the lots it WON, in the same test window and the same CPV division, for cells with at least three wins.

One circularity has to be closed before any of this means anything. A bidder's as-of history on a lot it lost in late 2021 already contains the outcome of a lot it won in early 2021, and that same early win is on the realised side of the comparison. The headline rows therefore freeze every bidder-history feature at the first day of the test window, so nothing that happens inside the resolution window can reach the forecast; the price features still come from the lot's own auction, because that is what a forecaster registering at award time would have. The two rows labelled "history as of each tender" are the leaky version, reported so the size of the circularity is visible rather than argued about.

Four forecasts are transferred. The last is a placebo: the lot-only model knows nothing about the bidder, so if its mean over a bidder's lost lots also ranks that bidder's realised rate, the correlation is about which lots the bidder competes for and not about the bidder. The null shuffles bidder identity within CPV division; because that shuffle keeps the between-division association, the null is not centred on zero, and its mean is the correlation that composition alone produces. The headline test is the right-tail probability against that null.

### duration extension recorded

| forecast transferred | cells | bidders | lost lots | won lots | Spearman | null mean | null sd | excess | p one-sided |
|---|---|---|---|---|---|---|---|---|---|
| full model (price and identity) | 2,318 | 2,170 | 23,350 | 20,894 | 0.273 | 0.212 | 0.015 | 0.060 | 0.0004 |
| price only | 2,318 | 2,170 | 23,350 | 20,894 | 0.287 | 0.214 | 0.015 | 0.073 | 0.0002 |
| prior extension rate only | 2,318 | 2,170 | 23,350 | 20,894 | 0.122 | 0.069 | 0.019 | 0.054 | 0.0014 |
| lot only (placebo) | 2,318 | 2,170 | 23,350 | 20,894 | 0.287 | 0.210 | 0.015 | 0.077 | 0.0002 |
| full model, history as of each tender (overlaps the resolution window) | 2,318 | 2,170 | 23,350 | 20,894 | 0.291 | 0.214 | 0.015 | 0.077 | 0.0002 |
| prior extension rate, history as of each tender (overlaps) | 2,318 | 2,170 | 23,350 | 20,894 | 0.288 | 0.094 | 0.018 | 0.194 | 0.0002 |

Read the placebo row first. It excesses the null by +0.077 against +0.060 for the bidder-aware forecast, so whatever correlation there is here is produced by which lots a bidder competes for and not by the bidder. A significant p-value on the full model would mean nothing while a forecast that cannot see the bidder at all does at least as well.

What this test could have found: the null has a standard deviation of 0.015, so the smallest excess over the null it could have declared significant at one-sided 5 percent is about 0.024. An effect smaller than that would not show up here whether or not it exists, and the number of cells is what sets it.

Pooled across divisions, ignoring the CPV cell: Spearman 0.274 over 2,631 bidders with at least three wins in the test window.

![Transfer scatter](transfer_scatter_duration_extension.png)

### end date moved out more than 90 days

| forecast transferred | cells | bidders | lost lots | won lots | Spearman | null mean | null sd | excess | p one-sided |
|---|---|---|---|---|---|---|---|---|---|
| full model (price and identity) | 2,314 | 2,166 | 23,340 | 20,812 | 0.291 | 0.132 | 0.016 | 0.159 | 0.0002 |
| price only | 2,314 | 2,166 | 23,340 | 20,812 | 0.286 | 0.131 | 0.016 | 0.155 | 0.0002 |
| prior extension rate only | 2,314 | 2,166 | 23,340 | 20,812 | 0.059 | 0.049 | 0.019 | 0.010 | 0.3051 |
| lot only (placebo) | 2,314 | 2,166 | 23,340 | 20,812 | 0.285 | 0.137 | 0.016 | 0.147 | 0.0002 |
| full model, history as of each tender (overlaps the resolution window) | 2,314 | 2,166 | 23,340 | 20,812 | 0.289 | 0.133 | 0.016 | 0.156 | 0.0002 |
| prior extension rate, history as of each tender (overlaps) | 2,314 | 2,166 | 23,340 | 20,812 | 0.116 | 0.061 | 0.019 | 0.055 | 0.0038 |

The bidder-aware forecast excesses the null by +0.159 against +0.147 for the lot-only placebo, so the difference between them is what is attributable to the bidder rather than to the lots it chooses.

What this test could have found: the null has a standard deviation of 0.016, so the smallest excess over the null it could have declared significant at one-sided 5 percent is about 0.026. An effect smaller than that would not show up here whether or not it exists, and the number of cells is what sets it.

Pooled across divisions, ignoring the CPV cell: Spearman 0.292 over 2,628 bidders with at least three wins in the test window.

![Transfer scatter](transfer_scatter_days_extended_gt90.png)

### The within-lot test

The transfer test above still compares a bidder across different lots. This one does not: it holds the lot fixed. Everything that makes a lot slip-prone - the buyer, the sector, the size, the year, the number of bidders - is identical for every bidder on that lot, so ranking the bidders against each other removes all of it by construction. For each test lot the winner's percentile rank among that lot's bidders is taken under each forecast, and the table reports the AUC of that percentile against the winner's own realised outcome. The null replaces the winner with a uniformly random bidder from the same lot, which is why it centres on 0.5 even though the winner's percentile is not uniform (winners are chosen largely on price).

| label | sample | forecast | test lots | mean percentile when it slipped | mean percentile when it did not | AUC | null mean | null sd | p two-sided |
|---|---|---|---|---|---|---|---|---|---|
| duration_extension | all test lots | raw price rank on the lot, no model | 38,113 | 0.153 | 0.137 | 0.513 | 0.500 | 0.005 | 0.011 |
| duration_extension | all test lots | full model (price and identity) | 38,113 | 0.561 | 0.465 | 0.555 | 0.500 | 0.005 | 0.001 |
| duration_extension | all test lots | price only | 38,113 | 0.596 | 0.504 | 0.552 | 0.500 | 0.005 | 0.001 |
| duration_extension | all test lots | prior extension rate only | 38,113 | 0.457 | 0.439 | 0.512 | 0.501 | 0.005 | 0.016 |
| duration_extension | all test lots | lot only (degenerate control) | 38,113 | 0.500 | 0.500 | 0.500 | 0.500 | 0.000 | 1.000 |
| duration_extension | pre-invasion test lots only | raw price rank on the lot, no model | 32,197 | 0.148 | 0.133 | 0.512 | 0.500 | 0.005 | 0.018 |
| duration_extension | pre-invasion test lots only | full model (price and identity) | 32,197 | 0.570 | 0.469 | 0.558 | 0.500 | 0.005 | 0.001 |
| duration_extension | pre-invasion test lots only | price only | 32,197 | 0.613 | 0.516 | 0.554 | 0.500 | 0.005 | 0.001 |
| duration_extension | pre-invasion test lots only | prior extension rate only | 32,197 | 0.454 | 0.436 | 0.512 | 0.501 | 0.005 | 0.019 |
| duration_extension | pre-invasion test lots only | lot only (degenerate control) | 32,197 | 0.500 | 0.500 | 0.500 | 0.500 | 0.000 | 1.000 |
| days_extended_gt90 | all test lots | raw price rank on the lot, no model | 38,000 | 0.141 | 0.138 | 0.501 | 0.500 | 0.005 | 0.897 |
| days_extended_gt90 | all test lots | full model (price and identity) | 38,000 | 0.511 | 0.485 | 0.514 | 0.500 | 0.005 | 0.007 |
| days_extended_gt90 | all test lots | price only | 38,000 | 0.485 | 0.482 | 0.501 | 0.500 | 0.005 | 0.940 |
| days_extended_gt90 | all test lots | prior extension rate only | 38,000 | 0.460 | 0.439 | 0.514 | 0.501 | 0.005 | 0.007 |
| days_extended_gt90 | all test lots | lot only (degenerate control) | 38,000 | 0.500 | 0.500 | 0.500 | 0.500 | 0.000 | 1.000 |
| days_extended_gt90 | pre-invasion test lots only | raw price rank on the lot, no model | 32,088 | 0.137 | 0.134 | 0.501 | 0.500 | 0.006 | 0.856 |
| days_extended_gt90 | pre-invasion test lots only | full model (price and identity) | 32,088 | 0.513 | 0.481 | 0.518 | 0.500 | 0.006 | 0.002 |
| days_extended_gt90 | pre-invasion test lots only | price only | 32,088 | 0.492 | 0.484 | 0.504 | 0.500 | 0.005 | 0.440 |
| days_extended_gt90 | pre-invasion test lots only | prior extension rate only | 32,088 | 0.465 | 0.436 | 0.519 | 0.501 | 0.006 | 0.001 |
| days_extended_gt90 | pre-invasion test lots only | lot only (degenerate control) | 32,088 | 0.500 | 0.500 | 0.500 | 0.500 | 0.000 | 1.000 |

The first row needs no model at all: it is the winner's own price rank among the bids on its lot, at AUC 0.513 (p = 0.011). Above 0.5 means the more expensive the winner was relative to its rivals, the more likely the extension. It points the same way as the discount deciles further down, where the extension rate falls as the discount deepens (Spearman -0.48 across deciles), and it clears its own null. What does clear it is the model that sees the size of the discount and not only its rank (AUC 0.552, p = 0.001), which says the relationship between price and slip is not simply monotone in the price order within a lot.

Dropping every lot whose tender opened on or after the full-scale invasion moves no AUC in that table by more than 0.003. The answer does not depend on the war.

### Whose identity carries the signal

Each of these is used on its own as the whole forecast, scored on the same test rows, so the comparison is like for like. The US panel in this repository found that the contracting office mattered more than the contractor; this is the same question asked where the bidders are visible. Rank discrimination only, because a raw rate used as a probability is not calibrated and the Brier score would be measuring the calibration rather than the ranking.

Pooled against stratified, on duration extension. A stratified column never compares two lots from different strata, so a predictor that ranks well only because it tracks which buyer, sector or year a lot belongs to loses that advantage there. Only strata containing both outcomes can contribute, which is what the `used` columns count; a stratified AUC resting on fewer than 20 strata is left blank rather than printed.

| predictor | AUC pooled | AUC within buyer | buyers used | AUC within CPV division and year | cells used |
|---|---|---|---|---|---|
| buyer's as-of extension rate | 0.684 | 0.552 | 1,127 | 0.657 | 80 |
| winner's as-of extension rate | 0.584 | 0.437 | 1,127 | 0.566 | 80 |
| winner's as-of win rate | 0.488 | 0.521 | 1,127 | 0.493 | 80 |
| winner's price as a share of the expected value | 0.541 | 0.587 | 1,127 | 0.521 | 80 |
| log lot value | 0.712 | 0.663 | 1,127 | 0.688 | 80 |

Three readings follow. First the sanity check: the buyer's own rate goes from 0.684 pooled to 0.552 within buyer, because it is nearly constant inside a buyer and has nothing left to rank with once the buyer is fixed. It keeps 0.657 within CPV division and year, so it is not a sector effect either. Second, the winner's price goes from 0.541 pooled to 0.587 within buyer, so the price signal is not a buyer effect wearing a price costume.

Third, and this is the one to be careful with: the winner's own record reads 0.584 pooled, 0.437 within buyer and 0.566 within CPV division and year. Those sit on both sides of chance and span 0.146. A signal that changes sign depending on what is held fixed is not a signal; the honest reading is that the bidder's own record is close to uninformative and that the direction of the residue is not stable enough to name.

| predictor | duration extension recorded | end date moved out more than 90 days | contract value up more than 10 percent | any registered change | paid less than 90 percent of the signed value |
|---|---|---|---|---|---|
| buyer's as-of extension rate | 0.684 | 0.596 | 0.429 | 0.566 | 0.549 |
| log lot value | 0.712 | 0.723 | 0.504 | 0.628 | 0.602 |
| winner's as-of extension rate | 0.584 | 0.579 | 0.497 | 0.490 | 0.478 |
| winner's as-of win rate | 0.488 | 0.497 | 0.505 | 0.478 | 0.473 |
| winner's price as a share of the expected value | 0.541 | 0.529 | 0.518 | 0.488 | 0.484 |

On duration extension the buyer's own record reaches AUC 0.684 and the winner's reaches 0.584. Both are visible in this dataset and only one of them carries the signal. That is the same answer the US panel in this repository gave from the other direction: there the contracting office mattered and the contractor added almost nothing, but US data never shows the losing offers, so it could not rule out that the bidder's identity mattered and was simply unobserved. Here it is observed, and it does not.

A thin record is the obvious alternative explanation for a null bidder result, so the same comparison restricted to the lots where the record is already substantial, on duration extension. These are pooled AUCs: the experienced-winner subset leaves too few buyers holding both outcomes for a within-buyer version to mean anything, which is itself a finding about how concentrated experienced bidders are:

| subset | buyer's as-of extension rate | winner's as-of extension rate | lots |
|---|---|---|---|
| all test lots | 0.684 | 0.584 | 38,113 |
| buyer has 10 or more prior lots | 0.744 | 0.557 | 19,507 |
| winner has 10 or more prior wins | 0.732 | 0.517 | 13,685 |

Restricting to winners with at least ten prior wins, where the bidder's own rate is estimated from a real sample rather than two or three contracts, it barely moves, 0.584 to 0.517. Thin histories are not what is holding the bidder result down.

The same question without any model in it. The intraclass correlation asks how much of the variance in an outcome sits between groups rather than within them, using nothing but the outcome and the grouping. Groups with fewer than three lots are dropped, because a group of one contributes no within-group variance and would inflate the statistic. The null shuffles the outcome across the retained rows, which destroys real clustering while keeping the group sizes and the base rate.

| label | grouping | lots | groups | mean group size | ICC | null mean | null sd | p one-sided |
|---|---|---|---|---|---|---|---|---|
| duration extension recorded | the buyer | 76,669 | 5,816 | 13.1824 | 0.2086 | -0.0000 | 0.0017 | 0.0020 |
| duration extension recorded | the winning bidder | 67,322 | 6,891 | 9.7696 | 0.2374 | -0.0000 | 0.0023 | 0.0020 |
| duration extension recorded | the CPV division | 85,052 | 46 | 1848.9565 | 0.0796 | 0.0000 | 0.0001 | 0.0020 |
| duration extension recorded | the buyer's region | 85,040 | 73 | 1164.9315 | 0.0045 | -0.0000 | 0.0002 | 0.0020 |
| end date moved out more than 90 days | the buyer | 76,284 | 5,812 | 13.1253 | 0.2120 | -0.0000 | 0.0016 | 0.0020 |
| end date moved out more than 90 days | the winning bidder | 66,955 | 6,861 | 9.7588 | 0.2023 | 0.0001 | 0.0021 | 0.0020 |
| end date moved out more than 90 days | the CPV division | 84,672 | 46 | 1840.6957 | 0.0311 | -0.0000 | 0.0001 | 0.0020 |
| end date moved out more than 90 days | the buyer's region | 84,660 | 73 | 1159.7260 | 0.0145 | -0.0000 | 0.0002 | 0.0020 |
| any registered change | the buyer | 76,669 | 5,816 | 13.1824 | 0.1971 | -0.0000 | 0.0014 | 0.0020 |
| any registered change | the winning bidder | 67,322 | 6,891 | 9.7696 | 0.3044 | 0.0000 | 0.0017 | 0.0020 |
| any registered change | the CPV division | 85,052 | 46 | 1848.9565 | 0.1459 | 0.0000 | 0.0001 | 0.0020 |
| any registered change | the buyer's region | 85,040 | 73 | 1164.9315 | 0.0171 | 0.0000 | 0.0001 | 0.0020 |
| paid less than 90 percent of the signed value | the buyer | 66,517 | 5,101 | 13.0400 | 0.2071 | -0.0002 | 0.0015 | 0.0020 |
| paid less than 90 percent of the signed value | the winning bidder | 57,350 | 6,005 | 9.5504 | 0.3118 | -0.0001 | 0.0020 | 0.0020 |
| paid less than 90 percent of the signed value | the CPV division | 73,944 | 46 | 1607.4783 | 0.1643 | 0.0000 | 0.0001 | 0.0020 |
| paid less than 90 percent of the signed value | the buyer's region | 73,923 | 67 | 1103.3284 | 0.0172 | 0.0000 | 0.0002 | 0.0020 |

On duration extension the buyer explains 0.209 of the variance and the winning bidder 0.237. No model is involved in those two numbers.

The raw figures above cannot separate the two, because a bidder usually wins repeatedly from the same handful of buyers, so clustering by bidder partly restates clustering by buyer. This next table holds one of them fixed. The null permutes the grouping label among lots that share the same block value, which keeps every group's size exactly and keeps each block's mix of groups, and destroys only the pairing between a particular group and a particular outcome. An excess over that null is clustering the block cannot account for.

| label | sample | clustering by | holding fixed | lots | groups | blocks | ICC | null mean | null sd | excess | p one-sided |
|---|---|---|---|---|---|---|---|---|---|---|---|
| duration extension recorded | all lots | the winning bidder | the buyer | 67,322 | 6,891 | 10,801 | 0.2374 | 0.1308 | 0.0028 | 0.1066 | 0.0020 |
| duration extension recorded | all lots | the buyer | the winning bidder | 76,669 | 5,816 | 19,260 | 0.2086 | 0.1201 | 0.0020 | 0.0885 | 0.0020 |
| duration extension recorded | all lots | the winning bidder | the CPV division | 67,322 | 6,891 | 46 | 0.2374 | 0.0813 | 0.0025 | 0.1561 | 0.0020 |
| duration extension recorded | all lots | the buyer | the CPV division | 76,669 | 5,816 | 46 | 0.2086 | 0.0314 | 0.0020 | 0.1772 | 0.0020 |
| duration extension recorded | all lots | the winning bidder | the buyer within the year | 67,322 | 6,891 | 20,059 | 0.2374 | 0.1548 | 0.0026 | 0.0826 | 0.0020 |
| duration extension recorded | one lot per bidder and tender | the winning bidder | the buyer | 60,885 | 6,532 | 10,764 | 0.2266 | 0.1298 | 0.0029 | 0.0968 | 0.0020 |
| duration extension recorded | one lot per bidder and tender | the winning bidder | the buyer within the year | 60,885 | 6,532 | 19,962 | 0.2266 | 0.1512 | 0.0029 | 0.0754 | 0.0020 |
| duration extension recorded | one lot per bidder and tender | the buyer | the winning bidder | 70,394 | 5,675 | 19,209 | 0.2019 | 0.1173 | 0.0020 | 0.0846 | 0.0020 |
| duration extension recorded | pre-invasion lots only | the winning bidder | the buyer within the year | 62,174 | 6,485 | 18,138 | 0.2434 | 0.1599 | 0.0027 | 0.0835 | 0.0020 |
| duration extension recorded | pre-invasion lots only | the buyer | the winning bidder | 71,048 | 5,485 | 18,249 | 0.2177 | 0.1258 | 0.0020 | 0.0919 | 0.0020 |
| end date moved out more than 90 days | all lots | the winning bidder | the buyer | 66,955 | 6,861 | 10,798 | 0.2023 | 0.0996 | 0.0027 | 0.1026 | 0.0020 |
| end date moved out more than 90 days | all lots | the buyer | the winning bidder | 76,284 | 5,812 | 19,215 | 0.2120 | 0.0816 | 0.0018 | 0.1304 | 0.0020 |
| end date moved out more than 90 days | all lots | the winning bidder | the CPV division | 66,955 | 6,861 | 46 | 0.2023 | 0.0349 | 0.0022 | 0.1673 | 0.0020 |
| end date moved out more than 90 days | all lots | the buyer | the CPV division | 76,284 | 5,812 | 46 | 0.2120 | 0.0054 | 0.0016 | 0.2066 | 0.0020 |
| end date moved out more than 90 days | all lots | the winning bidder | the buyer within the year | 66,955 | 6,861 | 20,039 | 0.2023 | 0.1246 | 0.0026 | 0.0777 | 0.0020 |
| end date moved out more than 90 days | one lot per bidder and tender | the winning bidder | the buyer | 60,580 | 6,503 | 10,760 | 0.1817 | 0.0901 | 0.0029 | 0.0916 | 0.0020 |
| end date moved out more than 90 days | one lot per bidder and tender | the winning bidder | the buyer within the year | 60,580 | 6,503 | 19,941 | 0.1817 | 0.1123 | 0.0028 | 0.0695 | 0.0020 |
| end date moved out more than 90 days | one lot per bidder and tender | the buyer | the winning bidder | 70,074 | 5,673 | 19,161 | 0.1976 | 0.0763 | 0.0018 | 0.1213 | 0.0020 |
| end date moved out more than 90 days | pre-invasion lots only | the winning bidder | the buyer within the year | 61,815 | 6,456 | 18,118 | 0.2057 | 0.1273 | 0.0028 | 0.0784 | 0.0020 |
| end date moved out more than 90 days | pre-invasion lots only | the buyer | the winning bidder | 70,667 | 5,481 | 18,203 | 0.2189 | 0.0855 | 0.0020 | 0.1334 | 0.0020 |
| any registered change | all lots | the winning bidder | the buyer | 67,322 | 6,891 | 10,801 | 0.3044 | 0.1168 | 0.0020 | 0.1876 | 0.0020 |
| any registered change | all lots | the buyer | the winning bidder | 76,669 | 5,816 | 19,260 | 0.1971 | 0.1176 | 0.0016 | 0.0795 | 0.0020 |
| any registered change | all lots | the winning bidder | the CPV division | 67,322 | 6,891 | 46 | 0.3044 | 0.1344 | 0.0016 | 0.1700 | 0.0020 |
| any registered change | all lots | the buyer | the CPV division | 76,669 | 5,816 | 46 | 0.1971 | 0.0407 | 0.0016 | 0.1563 | 0.0020 |
| any registered change | all lots | the winning bidder | the buyer within the year | 67,322 | 6,891 | 20,059 | 0.3044 | 0.1581 | 0.0020 | 0.1463 | 0.0020 |
| any registered change | one lot per bidder and tender | the winning bidder | the buyer | 60,885 | 6,532 | 10,764 | 0.2875 | 0.1107 | 0.0022 | 0.1767 | 0.0020 |
| any registered change | one lot per bidder and tender | the winning bidder | the buyer within the year | 60,885 | 6,532 | 19,962 | 0.2875 | 0.1483 | 0.0020 | 0.1392 | 0.0020 |
| any registered change | one lot per bidder and tender | the buyer | the winning bidder | 70,394 | 5,675 | 19,209 | 0.1857 | 0.1105 | 0.0015 | 0.0752 | 0.0020 |
| any registered change | pre-invasion lots only | the winning bidder | the buyer within the year | 62,174 | 6,485 | 18,138 | 0.3041 | 0.1578 | 0.0020 | 0.1464 | 0.0020 |
| any registered change | pre-invasion lots only | the buyer | the winning bidder | 71,048 | 5,485 | 18,249 | 0.2009 | 0.1203 | 0.0017 | 0.0805 | 0.0020 |
| paid less than 90 percent of the signed value | all lots | the winning bidder | the buyer | 57,350 | 6,005 | 9,436 | 0.3118 | 0.1191 | 0.0022 | 0.1927 | 0.0020 |
| paid less than 90 percent of the signed value | all lots | the buyer | the winning bidder | 66,517 | 5,101 | 17,553 | 0.2071 | 0.1185 | 0.0018 | 0.0886 | 0.0020 |
| paid less than 90 percent of the signed value | all lots | the winning bidder | the CPV division | 57,350 | 6,005 | 46 | 0.3118 | 0.1524 | 0.0019 | 0.1593 | 0.0020 |
| paid less than 90 percent of the signed value | all lots | the buyer | the CPV division | 66,517 | 5,101 | 46 | 0.2071 | 0.0534 | 0.0020 | 0.1537 | 0.0020 |
| paid less than 90 percent of the signed value | all lots | the winning bidder | the buyer within the year | 57,350 | 6,005 | 17,259 | 0.3118 | 0.1660 | 0.0022 | 0.1457 | 0.0020 |
| paid less than 90 percent of the signed value | one lot per bidder and tender | the winning bidder | the buyer | 51,752 | 5,693 | 9,394 | 0.3012 | 0.1142 | 0.0025 | 0.1870 | 0.0020 |
| paid less than 90 percent of the signed value | one lot per bidder and tender | the winning bidder | the buyer within the year | 51,752 | 5,693 | 17,151 | 0.3012 | 0.1583 | 0.0022 | 0.1429 | 0.0020 |
| paid less than 90 percent of the signed value | one lot per bidder and tender | the buyer | the winning bidder | 61,067 | 4,989 | 17,499 | 0.1979 | 0.1133 | 0.0020 | 0.0846 | 0.0020 |
| paid less than 90 percent of the signed value | pre-invasion lots only | the winning bidder | the buyer within the year | 52,855 | 5,650 | 15,520 | 0.3166 | 0.1691 | 0.0025 | 0.1475 | 0.0020 |
| paid less than 90 percent of the signed value | pre-invasion lots only | the buyer | the winning bidder | 61,515 | 4,810 | 16,583 | 0.2120 | 0.1223 | 0.0019 | 0.0896 | 0.0020 |

On the strictest variant, one lot per bidder per tender with the buyer held fixed within the year, the bidder's clustering survives: ICC 0.227 against a null of 0.151, an excess of 0.075 (one-sided p = 0.0020). Read that next to the head-to-head table above, where a bidder's own past rate barely ranks its future one. Outcomes do cluster by bidder; the clustering is not stable enough over time to forecast with.

## Does a bidder's own record persist at all?

The transfer test above has nothing to transfer unless a bidder's record is stable over time in the first place. This check uses only lots the bidder WON, on both sides: its rate over lots whose tender opened in 2019 or 2020 against its rate over lots whose tender opened in 2021 or 2022, for bidders with at least the stated number of wins in each window. Nothing counterfactual is involved. The null shuffles the later rate among bidders that share a modal CPV division, so a correlation produced purely by the sector a bidder works in sits inside the null rather than in the result.

| label | wins each side | bidders | earlier lots | later lots | Spearman | null mean | null sd | excess | p one-sided |
|---|---|---|---|---|---|---|---|---|---|
| duration extension recorded | 2 | 2,558 | 24,010 | 20,377 | 0.254 | 0.100 | 0.018 | 0.154 | 0.0002 |
| duration extension recorded | 3 | 1,546 | 20,255 | 16,961 | 0.276 | 0.104 | 0.022 | 0.172 | 0.0002 |
| duration extension recorded | 5 | 800 | 15,634 | 13,326 | 0.280 | 0.115 | 0.030 | 0.165 | 0.0002 |
| end date moved out more than 90 days | 2 | 2,546 | 23,880 | 20,274 | 0.307 | 0.057 | 0.019 | 0.250 | 0.0002 |
| end date moved out more than 90 days | 3 | 1,535 | 20,151 | 16,845 | 0.334 | 0.079 | 0.025 | 0.256 | 0.0002 |
| end date moved out more than 90 days | 5 | 798 | 15,568 | 13,262 | 0.328 | 0.095 | 0.033 | 0.233 | 0.0002 |
| contract value up more than 10 percent | 2 | 2,535 | 23,779 | 20,307 | 0.398 | 0.093 | 0.020 | 0.305 | 0.0002 |
| contract value up more than 10 percent | 3 | 1,528 | 20,070 | 16,882 | 0.417 | 0.118 | 0.024 | 0.299 | 0.0002 |
| contract value up more than 10 percent | 5 | 797 | 15,527 | 13,294 | 0.409 | 0.145 | 0.032 | 0.264 | 0.0002 |
| any registered change | 2 | 2,558 | 24,010 | 20,377 | 0.474 | 0.261 | 0.014 | 0.213 | 0.0002 |
| any registered change | 3 | 1,546 | 20,255 | 16,961 | 0.546 | 0.321 | 0.018 | 0.225 | 0.0002 |
| any registered change | 5 | 800 | 15,634 | 13,326 | 0.660 | 0.388 | 0.022 | 0.272 | 0.0002 |
| paid less than 90 percent of the signed value | 2 | 2,234 | 20,339 | 16,680 | 0.507 | 0.258 | 0.017 | 0.249 | 0.0002 |
| paid less than 90 percent of the signed value | 3 | 1,318 | 17,050 | 14,037 | 0.590 | 0.337 | 0.019 | 0.253 | 0.0002 |
| paid less than 90 percent of the signed value | 5 | 685 | 13,106 | 10,997 | 0.715 | 0.419 | 0.023 | 0.297 | 0.0002 |
| contract cancelled | 2 | 2,558 | 24,010 | 20,377 |  |  |  |  |  |
| contract cancelled | 3 | 1,546 | 20,255 | 16,961 |  |  |  |  |  |
| contract cancelled | 5 | 800 | 15,634 | 13,326 |  |  |  |  |  |

## Experiment 3: the lowest bidder disqualified

Treated lots are those where the cheapest live bid was disqualified (an award with status `unsuccessful` against that bid) and a dearer bid won. Control lots are those where the cheapest bid won and nothing at the bottom was disqualified; a lot where a bid at the minimum price won despite a disqualification at the minimum belongs to neither group. The control group is reweighted onto the treated group's CPV-division by year cell mix before the difference is taken, and the interval is a 1,000-draw bootstrap over lots.

| label | treated lots | control lots | treated, matched | control, matched | treated rate, raw | control rate, raw | treated rate, matched | control rate, standardised | difference | 95% low | 95% high |
|---|---|---|---|---|---|---|---|---|---|---|---|
| duration extension recorded | 17,843 | 67,016 | 17,842 | 66,954 | 0.106 | 0.084 | 0.106 | 0.092 | 0.014 | 0.009 | 0.019 |
| end date moved out more than 90 days | 17,754 | 66,727 | 17,753 | 66,666 | 0.097 | 0.093 | 0.097 | 0.097 | -0.000 | -0.005 | 0.005 |
| contract value up more than 10 percent | 17,681 | 66,474 | 17,679 | 66,412 | 0.064 | 0.069 | 0.064 | 0.065 | -0.001 | -0.005 | 0.003 |
| any registered change | 17,843 | 67,016 | 17,842 | 66,954 | 0.572 | 0.553 | 0.572 | 0.555 | 0.017 | 0.008 | 0.024 |
| paid less than 90 percent of the signed value | 15,436 | 58,350 | 15,435 | 58,270 | 0.277 | 0.295 | 0.277 | 0.294 | -0.017 | -0.025 | -0.010 |

Differences whose interval excludes zero: duration extension recorded +1.4 points (+0.9 to +1.9); any registered change +1.7 points (+0.8 to +2.4); paid less than 90 percent of the signed value -1.7 points (-2.5 to -1.0).

### Winner's discount and the outcome

Deciles of the winner's discount against the expected lot value, with the realised rate of each label.

| decile | lots | discount min | discount median | discount max | duration extension recorded | end date moved out more than 90 days | contract value up more than 10 percent | any registered change | paid less than 90 percent of the signed value |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 8,506 | -0.044 | 0.000 | 0.001 | 0.088 | 0.107 | 0.078 | 0.558 | 0.303 |
| 1 | 8,612 | 0.001 | 0.002 | 0.004 | 0.096 | 0.095 | 0.070 | 0.526 | 0.254 |
| 2 | 8,398 | 0.004 | 0.006 | 0.009 | 0.080 | 0.086 | 0.076 | 0.536 | 0.257 |
| 3 | 8,505 | 0.009 | 0.013 | 0.018 | 0.097 | 0.105 | 0.069 | 0.534 | 0.258 |
| 4 | 8,505 | 0.018 | 0.027 | 0.040 | 0.093 | 0.105 | 0.074 | 0.549 | 0.280 |
| 5 | 8,505 | 0.040 | 0.057 | 0.079 | 0.108 | 0.119 | 0.067 | 0.563 | 0.296 |
| 6 | 8,505 | 0.079 | 0.104 | 0.136 | 0.090 | 0.093 | 0.063 | 0.582 | 0.303 |
| 7 | 8,505 | 0.136 | 0.171 | 0.212 | 0.085 | 0.086 | 0.062 | 0.596 | 0.335 |
| 8 | 8,505 | 0.212 | 0.261 | 0.325 | 0.078 | 0.074 | 0.059 | 0.587 | 0.337 |
| 9 | 8,506 | 0.325 | 0.428 | 1.000 | 0.074 | 0.071 | 0.064 | 0.535 | 0.291 |

The relationship runs the opposite way to the winner's-curse intuition: the extension rate falls from 8.8 percent in the decile that won at essentially the expected value to 7.4 percent in the deepest-discount decile (Spearman across deciles -0.48). A bidder that cut its price hard is not the one whose contract gets extended in this sample.

![Extension rate by discount decile](extension_by_discount_decile.png)

## Experiment 4: bid dispersion within the lot

Bins of the coefficient of variation of the live priced bids on the lot, with the winner's realised outcome rates.

| decile | lots | dispersion min | dispersion median | dispersion max | duration extension recorded | end date moved out more than 90 days | contract value up more than 10 percent | any registered change | paid less than 90 percent of the signed value |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 14,176 | 0.000 | 0.000 | 0.001 | 0.102 | 0.106 | 0.073 | 0.569 | 0.312 |
| 1 | 14,175 | 0.001 | 0.002 | 0.004 | 0.084 | 0.092 | 0.069 | 0.535 | 0.262 |
| 2 | 14,192 | 0.004 | 0.007 | 0.014 | 0.082 | 0.096 | 0.075 | 0.543 | 0.278 |
| 3 | 14,158 | 0.014 | 0.028 | 0.048 | 0.088 | 0.098 | 0.069 | 0.569 | 0.298 |
| 4 | 14,175 | 0.048 | 0.075 | 0.115 | 0.093 | 0.090 | 0.063 | 0.590 | 0.310 |
| 5 | 14,176 | 0.115 | 0.183 | 1.732 | 0.085 | 0.082 | 0.061 | 0.534 | 0.289 |

For comparison, the same rates by the number of live priced bids on the lot:

| live priced bids | lots | duration extension recorded | end date moved out more than 90 days | contract value up more than 10 percent | any registered change | paid less than 90 percent of the signed value |
|---|---|---|---|---|---|---|
| 2 | 55,747 | 0.084 | 0.096 | 0.071 | 0.552 | 0.290 |
| 3 | 16,412 | 0.095 | 0.094 | 0.066 | 0.573 | 0.300 |
| 4 | 6,952 | 0.101 | 0.093 | 0.066 | 0.565 | 0.289 |
| 5 | 3,104 | 0.099 | 0.084 | 0.055 | 0.556 | 0.283 |
| 6 | 1,342 | 0.114 | 0.084 | 0.046 | 0.522 | 0.266 |
| 7 | 682 | 0.103 | 0.078 | 0.043 | 0.559 | 0.270 |
| 8 | 813 | 0.092 | 0.041 | 0.038 | 0.583 | 0.291 |

## Caveats

- Wartime. Tenders opening on or after 2022-02-24 run under martial-law procurement rules, and one of the observed `durationExtension` rationales is explicitly the martial-law resolution (Cabinet of Ministers 12.10.2022 No. 1178). Every headline number is also reported on a 2021-only test window, which is entirely pre-invasion.
- Inflation. Values are nominal hryvnia. Consumer inflation in Ukraine ran above 20 percent in 2022, so `value_growth_gt10` in 2022 is not the same event as in 2019, and no deflator has been applied here.
- Reporting compliance. A change is only in the data if the buyer registered it. An extension agreed and not registered is invisible, and nothing in this dataset measures how often that happens. The extension labels are therefore a lower bound.
- The tender copy of a contract is not a snapshot taken at signing. It is the state as of the last write to the tender document, which is why the agreement rates above are reported. `days_extended` inherits that uncertainty; `duration_extension` does not.
- Bid amounts are post-auction. The `lotValues[].date` sits inside the auction period, so the stored price is the one the bidder ended at, not the sealed bid it opened with. That is the price available at award time, which is what the forecast needs, but it is not the bidder's initial offer.
- Transfer scoring is not counterfactual scoring. A bidder's forecast on a lot it lost is never resolved on that lot. The test asks whether the forecast ranks the bidder's realised record elsewhere, which is a weaker claim and is the only honest one available.
- Right censoring. Every label is read at a single snapshot, so a contract still running at that moment may yet acquire a change that this panel will never see. The share still running is reported by cohort in the base-rate table so the size of that is visible rather than assumed.
- One country, one period. Nothing here says the result carries to systems where the winner is not chosen mostly on price.
- Contract cancellation is not measurable in this sample. The sample is completed tenders, and a tender only reaches status `complete` once it has a live contract, so the `cancelled` label is near-empty by construction and the ladder refuses to score it. A study of contract failure would have to start from a different tender status.
- Prices are stripped from withdrawn and rejected bids, so the price order on a lot is the order among the bids that survived. The share of unsuccessful awards that still point at a priced bid is reported above, and it is high, but this is a property of the publication rules rather than of the procurement.
- A null result is not proof of absence. The transfer test's minimum detectable excess is stated with the test, and the within-lot test's null standard deviation is in its table. An effect smaller than those would not have shown up here.
- Only outcomes the registry records are measured. If the identity of a bidder shows up in delivered quality, in disputes, or in anything that never becomes a registered contract change, none of these tests would see it.
- A bidder that has never won has no record, so the identity features are missing or shrunk to the global rate for exactly the bidders a procurement officer would most want information about.

## What could not be verified

- Whether the tender document's copy of a contract is ever rewritten after signing. It clearly lags (contract status differs from the registry), but nothing observed proves it is frozen, so `days_extended` is reported with its agreement rate rather than treated as exact.
- Whether `amountPaid` is a settled figure or a running total. It is populated on most terminated contracts, but the API returns no field saying the payment record is final, so `underexecuted` may include contracts still being paid.
- Whether a `durationExtension` change always moves `period.endDate`. The cross-tab above measures how often the two move together in this sample; it does not establish a rule.
- Whether disqualification of the cheapest bid is recorded consistently across buyers. The signal used is an award with status `unsuccessful`, which is what the data shows; no external source was consulted on buyer practice.
- The Ukrainian legal vocabulary behind each rationale type beyond the English `title_en` and `description_en` that the API itself returns.
- Whether a bid is ever revised after the auction closes. The stored price carries a date inside the auction period, which is consistent with it being the final auction price, but nothing observed rules out a later edit.
- Whether the same legal entity ever appears under more than one identifier. Bidders are keyed on the published identifier as it stands; no entity resolution was attempted, so a firm that changed its registration would look like two bidders.
- Why the buyer's record carries signal and the bidder's does not. The measurement is solid; the mechanism is not established here, and buyer capacity, buyer sector mix and buyer-specific reporting habits would all produce the same pattern.

## Reproduction

From the repository root, in order. The first two steps make several hundred thousand HTTP requests and take hours; everything after them runs from the cache.

```
make -C prozorro census   # systematic one-in-5 day sample of the tender feed
make -C prozorro sample   # select the tenders to fetch, fixed seed
make -C prozorro fetch    # tender documents and contract registry records
make -C prozorro all      # parse, labels, experiments, release tables, this report
make -C prozorro test     # pytest
```

`prozorro/run_pipeline.sh` runs everything downstream of the fetch in one go. Cached JSON lives under `data/raw/prozorro/` (gitignored), so nothing after `fetch` touches the network.

Released tables, with `column_dictionary.json` beside them:

| file | rows | columns | MB |
|---|---|---|---|
| tenders.csv.gz | 80,182 | 31 | 11.1 |
| bids.csv.gz | 238,228 | 20 | 19.7 |
| contracts.csv.gz | 95,272 | 49 | 19.2 |
| lots.csv.gz | 92,802 | 35 | 13.7 |

These carry legal-entity names and the published identifier, both of which Prozorro publishes itself, and nothing else about any person: no contact name, no email, no telephone, no street address. One thing to know about the identifiers: 25,979 bidders carry an 8 digit company EDRPOU; 13,488 bidders carry a 10 digit individual taxpayer number; 86 bidders carry another identifier length. A Ukrainian sole trader bids under a personal name and a ten-digit individual taxpayer number rather than an eight-digit company EDRPOU, and both are kept here as published.

