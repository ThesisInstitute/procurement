# Scoring the UK government's own delivery confidence assessments

Since 2013 the UK Major Projects Authority, then the Infrastructure and Projects
Authority, and now the National Infrastructure and Service Transformation
Authority, has published a Delivery Confidence Assessment for every project on
the Government Major Projects Portfolio. It is a Red, Amber or Green judgment,
made at a dated snapshot by people with access to the project, of whether the
project will deliver. It is published alongside the project's baseline
whole-life cost, its financial-year baseline, forecast and variance, and its
latest approved start and end dates.

Those ratings are forecasts, and they have never been scored. This is what they
were worth.

The short answer: the ratings rank projects in roughly the right order, the
ordering is weak, and the probability a reader would naturally attach to each
colour is far too pessimistic. A green project was not 90 per cent safe and an
amber project was not a coin flip. Across 2,495 project-years, the published
rating beats a constant forecast of the base rate on no cost or schedule
outcome. Recalibrated and scored against the base rate a person could actually
have used, it adds between -0.007 and +0.021 on cost and schedule, which is to
say nothing. The one thing it predicts well is next year's rating, where
recalibration buys +0.178.

## What was found

**1. The ordering is real, small, and it stops one step short of Red.** On the
five-point scale in force from September 2012 to March 2021 a worse rating does
go with a worse record, up to Amber/Red. The share of projects whose baseline
whole-life cost rose by more than 10 per cent over the following year runs 7.7%
for Green, 14.5% for Amber/Green, 21.7% for Amber, 34.7% for Amber/Red and 32.3%
for Red: four rising steps and then a fall. Red is the smallest bucket on the
five-point scale (n=31 against 222 for Amber/Red), so the fall is not firm, but
it is there on both cost thresholds and it is worth saying that the worst rating
did not carry the worst cost record. The rank discrimination is 0.614 (95 per
cent bootstrap interval 0.570 to 0.657, n=831). For a slip of more than six
months it is 0.610. Both are better than chance and both are a long way from a
usable discriminator.

**2. Read as probabilities the colours are badly wrong, in one direction.** An
Amber rating on the five-point scale went with a 21.7% chance of a cost rise
above 10 per cent and a 17.1% chance of a slip beyond six months. Every single
rating on every cost and schedule outcome overshoots. The Brier score of the
rating read through the stated probability mapping is worse than a constant
forecast of the base rate on every one of those outcomes, and the whole of that
loss is reliability, not lost resolution.

**3. The three-point scale that replaced it in March 2022 discriminates less,
and on cost not measurably at all.** On the same cost outcome the rank
discrimination falls from 0.614 to 0.552, and its 95 per cent interval,
clustered on the project, 0.499 to 0.606, includes chance. Green projects now
have a *higher* observed cost-growth rate than Amber ones (24.3% against 21.3%).
Collapsing five categories into three put most of the portfolio into a single
Amber bucket: 77, 79, 76, 69 and 63 per cent at the 5 three-point snapshots.

**4. The rating predicts the rating.** The one thing the assessment forecasts
well is its own successor. On the three-point scale the discrimination for being
rated Red next year is 0.712 (0.657 to 0.758): a Red project had a 50.5% chance
of being Red again, against 1.7% for a Green one.

**5. Green projects leave the portfolio, and they leave because they finish.**
The discrimination for leaving permanently runs *backwards* (0.350 on the
five-point scale): 71.3% of Green project-years were the project's last, against
18.2% of Amber/Red ones. The published data does not say why a project left, but
the end dates point one way: a Green project that left had a median of 3.0
months left to run and 72% were past or within a year of their end date, against
17.0 months and 39% for Amber/Red. Projects that stayed had a median of 40.1
months to run. That is an inference from the end-date distribution, not a
published classification.

**6. Almost nothing here is a passive prediction, and the exit result is why.**
Whether a project is still on the portfolio next year is itself strongly
predicted by the rating, and every other outcome is only resolvable for projects
that stay. 500 of the 2,346 rated project-years have no row at the next snapshot
and therefore have no cost, schedule or next-rating outcome at all. Because
Green projects leave at 71% and Amber/Red ones at 18%, the rows that survive to
be scored are not a random sample of the rows that were rated, and they are
missing Green projects hardest. Every calibration and discrimination number
below is conditional on survival. This is not a defect that can be corrected
away: a project that has left has no next-year cost baseline to grow.

**7. The rating is worth more in some departments than others.** On the
five-point scale and the cost outcome, discrimination runs from 0.480 (DCMS) to
0.750 (HMRC) across the 9 departments with at least 40 resolvable project-years.
The Ministry of Defence, the largest single block of the portfolio, sits at
0.571 over 171 project-years. Departmental figures are computed within a scale
era and never across the change, because a rank of 2 is Amber on one scale and
Red on the other.

## The data

Everything comes from the gov.uk collection *Major projects data*
(`/government/collections/major-projects-data`), read through the content API on
15 September 2026. The collection lists 197 documents. 546 attachments were
downloaded, 23.5 MB in total, every one returning HTTP 200 and none failing;
every URL, byte count and SHA-256 is in `data/raw/gmpp/download_log.csv` and
every discovery decision is in `data/raw/gmpp/manifest.csv`.

Two things about the source were not obvious and change the shape of the study.

**The publication year is not the snapshot date.** The 2015 publications carry
the September 2014 position and the 2024 publications carry the March 2024
position. The transparency policy published alongside the first release states
that "the data for publication in May 2013 will be drawn from ... the second
quarter of 2012/13" and that "the annual updates will similarly be drawn from
the second quarter of the relevant financial year", so the first snapshot is 30
September 2012. The reporting date moved from September to March between the
2020 and 2021 publications, which leaves one 18-month gap in an otherwise
12-month series. Snapshot dates were parsed from attachment titles where they
are stated and from the publication body where they are not, and the source of
each is recorded in `data/raw/gmpp/snapshots.csv`. A month is accepted only when
it is one the portfolio actually reports on, September or March. Exactly one
publication in the collection names another month, the 2013 Home Office release
whose attachments are titled "MPA dashboard 14 May 2013", and that is the date
the dashboard was published rather than the position it carries.

That dating is confirmed against a source that is independent of anything the
publication page says. In the September era the files head their own money
columns with a financial year, "2018/19 TOTAL Baseline" and the like, and the
transparency policy fixes the position as quarter two of that year. 107 of the
197 files carry such a header, and all 107 of them agree with the dating above,
with none disagreeing (`.venv/bin/python -m gmpp.src.validate_calendar`, which
exits non-zero on any disagreement). The remaining 90 are the March-era files,
which head their money columns "Financial Year Baseline" with no year and so
cannot be checked this way.

One trap here is worth recording, because reading the financial year out of the
wrong column silently destroys a whole snapshot. The September 2019 files head
their money columns "Financial Year Baseline (GBPm)" with no year, but they
carry, left over from the previous year's template, a narrative column headed
"Departmental narrative on budget/forecast variance for 2018/19". A
financial-year rule that matches any header mentioning a budget or a variance
picks that one up and dates all 120 September 2019 project-years to September
2018, merging two snapshots into one and destroying the transition between them.
Narrative columns are excluded, and the exclusion is under test.

**The series does not stop in 2024.** The NISTA annual reports for 2024-25 and
2025-26 publish consolidated CSVs, and their gov.uk pages state that the data
"was reported to the IPA by departments on 31 March 2025" and "reported to the
NISTA by departments on 31 March 2026". Including them gives 14 snapshots and 13
resolvable transitions rather than 12 and 11.

Two file layouts exist and are detected rather than assumed: the 2013 to 2020
publications are transposed, with field names down the first column and one
column per project; the 2021 publications onward put one project on each row.
Header spellings vary continuously. Across the 197 files the panel reads there
are 86 distinct normalised headers; 78 of them are mapped onto 22 canonical
columns and the remaining 8 are declared non-data, which is what they are:
spreadsheet working notes, exemption bookkeeping, and long methodological
footnotes the publisher put in a header cell. Every one is listed in
`gmpp/src/schema.py`, and a test fails if any header in those files is neither
mapped nor declared, so a new spelling in a future publication cannot silently
drop a column. `results/unmapped_headers.csv` is the run-time record and holds 0
rows.

### Coverage

| Snapshot | Scale | Projects | Departments | With a published rating | Exempt | Not rated or blank | With whole-life cost | With end date | Rated by the IPA | Rated by the SRO | Linked to the next snapshot, % | Identity from the GMPP id | Identity from the name |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2012-09-30 | five_point | 181 | 15 | 160 | 0 | 21 | 153 | 175 | 160 | 0 | 68.5 | 27 | 154 |
| 2013-09-30 | five_point | 189 | 16 | 165 | 15 | 9 | 172 | 181 | 165 | 0 | 69.8 | 43 | 146 |
| 2014-09-30 | five_point | 178 | 16 | 174 | 4 | 0 | 164 | 170 | 174 | 0 | 56.7 | 52 | 125 |
| 2015-09-30 | five_point | 138 | 14 | 133 | 5 | 0 | 129 | 136 | 133 | 0 | 74.6 | 77 | 60 |
| 2016-09-30 | five_point | 139 | 13 | 133 | 5 | 1 | 130 | 136 | 133 | 0 | 76.3 | 111 | 28 |
| 2017-09-30 | five_point | 130 | 13 | 126 | 4 | 0 | 113 | 125 | 126 | 0 | 82.3 | 110 | 20 |
| 2018-09-30 | five_point | 131 | 13 | 128 | 3 | 0 | 116 | 125 | 128 | 0 | 79.4 | 116 | 15 |
| 2019-09-30 | five_point | 123 | 13 | 121 | 2 | 0 | 111 | 118 | 121 | 0 | 70.7 | 123 | 0 |
| 2021-03-31 | five_point | 181 | 16 | 173 | 5 | 3 | 161 | 175 | 173 | 0 | 86.2 | 181 | 0 |
| 2022-03-31 | three_point | 232 | 16 | 218 | 11 | 3 | 188 | 215 | 150 | 68 | 87.5 | 232 | 0 |
| 2023-03-31 | three_point | 244 | 21 | 232 | 11 | 1 | 193 | 214 | 111 | 121 | 78.3 | 244 | 0 |
| 2024-03-31 | three_point | 227 | 21 | 215 | 12 | 0 | 174 | 199 | 115 | 100 | 87.7 | 227 | 0 |
| 2025-03-31 | three_point | 213 | 20 | 196 | 14 | 3 | 157 | 183 | 86 | 110 | 80.8 | 213 | 0 |
| 2026-03-31 | three_point | 189 | 20 | 172 | 16 | 1 | 133 | 162 | 0 | 91 |  | 187 | 2 |

The panel is 2495 project-years covering 708 projects. Projects are linked
across snapshots by the GMPP ID Number where it is published, which is every row
from the September 2019 snapshot onward and 55 rows in September 2016, and by
name within a department group before that. The full id is the key, not its
numeric core: BEIS_0004 is "Future Shared Services Programme" under the 1920-Q2
joining quarter and "Industrial Decarbonisation and Hydrogen Revenue Support"
under 2122-Q2, so matching on the core alone would merge two unrelated projects.

Name matching is deliberately conservative. An exact normalised-name match
inside a department group links automatically. Beyond that, 34 pairs were merged
on a similarity threshold of 0.90, all of them listed with their scores in
`results/identity_fuzzy_merges.csv`, and a merge is refused whenever the two
names name different instalments of a series. That guard is what keeps "PFI
Prison Expiry and Transfer Tranche 1" apart from "Tranche 3" and "Priority
School Building Programme" apart from "Priority School Building Programme 2",
all of which a plain string-similarity rule merges. It also refuses some merges
that are probably correct, which is the intended direction of the error.

### An independent check on the reconstruction

The XLSX attachments of the 2020 publications carry a sheet named `SourceTable`
holding the IPA's own consolidated back-series: 1,255 project-years from the
September 2012 to the September 2019 snapshot, across every department, with the
id, the rating, the dates and the whole-life cost. It was never the published
product, so it is used only to check that the reconstruction from the
per-department files reproduces the same portfolio.

| Snapshot | Rows in the IPA back-series | Joined to this panel | Join rate | Rating agrees | Whole-life cost agrees | End date agrees |
|---|---|---|---|---|---|---|
| 2012-09-30 | 191 | 168 | 0.8796 | 0.875 | 0.8512 | 0.994 |
| 2013-09-30 | 199 | 180 | 0.9045 | 1 | 0.9944 | 1 |
| 2014-09-30 | 188 | 166 | 0.883 | 1 | 1 | 0.9277 |
| 2015-09-30 | 143 | 132 | 0.9231 | 1 | 0.9848 | 0.9924 |
| 2016-09-30 | 143 | 136 | 0.951 | 1 | 1 | 1 |
| 2017-09-30 | 133 | 127 | 0.9549 | 1 | 0.9843 | 1 |
| 2018-09-30 | 133 | 129 | 0.9699 | 1 | 1 | 0.9767 |
| 2019-09-30 | 125 | 123 | 0.984 | 1 | 0.9919 | 0.9919 |

Overall 1,161 of 1,255 rows join, and where they do the rating agrees on 98.2%,
the whole-life cost on 97.3% and the end date on 98.4%. All 21 rating
disagreements are September 2012 rows where the department file left the cell
blank and the IPA's own back-series records them as exempt. Both are treated
here as non-ratings, so nothing in the scoring turns on it.

The rows that do not join are the honest measure of this panel's coverage, and
they are not all the same thing. Four departments never published a departmental
GMPP file at all in the September era and appear only inside the IPA's
consolidated table: the Office for National Statistics, the National Crime
Agency, the Crown Prosecution Service and National Savings and Investments.
Their project-years are on the portfolio and are not in this panel, and no
amount of parsing recovers them from releases that do not exist. The rest are
name-match misses concentrated in the first three snapshots, where no file
publishes a project id.

| Department | Back-series rows with no panel row | Snapshots |
|---|---|---|
| ONS | 20 | 2012-09-30 2013-09-30 2014-09-30 2015-09-30 2016-09-30 |
| MOJ | 8 | 2012-09-30 2013-09-30 2014-09-30 |
| DEFRA | 7 | 2012-09-30 2013-09-30 |
| HO | 7 | 2012-09-30 2013-09-30 2014-09-30 2015-09-30 2016-09-30 |
| DFT | 6 | 2012-09-30 2013-09-30 2015-09-30 2016-09-30 |
| MOD | 6 | 2012-09-30 2013-09-30 2014-09-30 2015-09-30 |
| NCA | 6 | 2013-09-30 2014-09-30 2015-09-30 2016-09-30 |
| DH | 5 | 2012-09-30 2014-09-30 2016-09-30 |
| CPS | 3 | 2014-09-30 2015-09-30 2016-09-30 |
| DFE | 3 | 2013-09-30 2014-09-30 2015-09-30 |
| FCO | 3 | 2013-09-30 2014-09-30 2015-09-30 |
| NS&I | 3 | 2012-09-30 2013-09-30 2014-09-30 |
| BEIS | 2 | 2012-09-30 2013-09-30 |
| DWP | 2 | 2012-09-30 2014-09-30 |
| DCLG | 1 | 2012-09-30 |

One gap was recoverable and was recovered. The FCO's 2020 publication, which
carries the September 2019 position, exists on gov.uk at
`/government/publications/fco-government-major-projects-portfolio-data-2020` and
is simply not listed in the collection. Discovery therefore supplements the
collection with a gov.uk search for the publication title pattern; that search
returns exactly one publication the collection omits, and it is that one. Before
it was added, three FCO projects appeared to leave the portfolio in September
2018 and never return.

## The rating scale, and the year it changed

The scale in force is stated in the published header of every file, not
inferred. Publications from 2013 to 2021 carry "a five-point scale, Red -
Amber/Red - Amber - Amber/Green - Green"; publications from 2022 onward carry "a
three-point scale, Red - Amber - Green". The two NISTA files state no scale, and
only GREEN, AMBER and RED appear in their data. The change therefore falls
between the March 2021 and March 2022 snapshots. The five-point and three-point
eras are scored separately throughout and are never pooled, because Amber is the
middle of five in one era and the middle of three in the other.

Ratings are harmonised across their published spellings ("Amber/ Red",
"Amber/red", "AMBER"). Anything that is not a rating is kept as its own category
rather than dropped: EXEMPT for a Freedom of Information withholding, RESET,
NOT_RATED for an explicit "No DCA" or a departmental statement that the
information is unavailable, and MISSING for a blank.

| snapshot | Green | Amber/Green | Amber | Amber/Red | Red | EXEMPT | RESET | NOT_RATED | MISSING |
|---|---|---|---|---|---|---|---|---|---|
| 2012-09-30 | 31 | 46 | 55 | 22 | 6 | 0 | 0 | 0 | 21 |
| 2013-09-30 | 16 | 50 | 61 | 35 | 3 | 15 | 1 | 8 | 0 |
| 2014-09-30 | 25 | 42 | 60 | 39 | 8 | 4 | 0 | 0 | 0 |
| 2015-09-30 | 10 | 27 | 52 | 38 | 6 | 5 | 0 | 0 | 0 |
| 2016-09-30 | 5 | 22 | 68 | 34 | 4 | 5 | 1 | 0 | 0 |
| 2017-09-30 | 2 | 22 | 56 | 38 | 8 | 4 | 0 | 0 | 0 |
| 2018-09-30 | 4 | 18 | 64 | 38 | 4 | 3 | 0 | 0 | 0 |
| 2019-09-30 | 3 | 18 | 57 | 32 | 11 | 2 | 0 | 0 | 0 |
| 2021-03-31 | 12 | 29 | 81 | 44 | 7 | 5 | 0 | 3 | 0 |
| 2022-03-31 | 24 | 0 | 167 | 0 | 27 | 11 | 0 | 3 | 0 |
| 2023-03-31 | 26 | 0 | 183 | 0 | 23 | 11 | 0 | 1 | 0 |
| 2024-03-31 | 25 | 0 | 163 | 0 | 27 | 12 | 0 | 0 | 0 |
| 2025-03-31 | 30 | 0 | 135 | 0 | 31 | 14 | 0 | 3 | 0 |
| 2026-03-31 | 29 | 0 | 109 | 0 | 34 | 16 | 0 | 1 | 0 |

One mechanism worth stating, because it is easy to misread the files. From the
March 2022 snapshot the published table carries two rating columns, one headed
"IPA Delivery Confidence Assessment" and one headed "SRO Delivery Confidence
Assessment". They are not two forecasts of the same project.

Stated precisely, because the loose version of this claim is wrong: the two
columns are both non-empty on 117 of the 2,495 project-years, but on none of
them do both carry a rating. What the second column holds on those rows is an
exemption or a "Not Applicable", which is how a department says the other column
is the live one. Across the whole panel no project-year carries two ratings, and
the report build asserts it. The published assessment is therefore the coalesce
of the two, and which body made it is kept as a covariate.

Which body, exactly, changes at the end. The column is headed "IPA" throughout,
but the IPA ceased to exist on 1 April 2025: the 2024-25 publication states its
data was reported to the IPA on 31 March 2025, and the 2025-26 publication
states its data was reported to NISTA on 31 March 2026. The March 2026
assessments are recorded here as NISTA's, which is what they are.

## Outcomes

An outcome for a project-year at snapshot t is resolved from the snapshots after
t, and nothing from t+1 or later is ever used as an input. The year-t commentary
is not used as an input either, even though it is contemporaneous: it is written
knowing the rating, and feeding it to anything would be scoring the assessor's
own explanation.

| Outcome | Definition |
|---|---|
| Whole-life cost up more than 10% (25%) | The published TOTAL baseline whole-life cost at t+1 divided by the value at t, minus 1, exceeds 0.10 (0.25). A zero or negative baseline yields no ratio. |
| End date slipped more than 6 (12) months | The latest approved end date at t+1 minus the latest approved end date at t, in months of 30.4375 days, exceeds 6 (12). |
| Rated Red at the next snapshot | The published rating at t+1 is Red. Null when t+1 uses the other scale, because three-point Red absorbs part of what used to be Amber/Red. |
| Rating worse at the next snapshot | The rating at t+1 is a worse step on the same scale. A second version excludes projects already on the worst rating, which cannot worsen. |
| Left the portfolio and did not return | The project has no row at t+1 and none at any later snapshot, and its department did publish at a later snapshot. Null where the department published nothing later, because then the absence is a publication gap and not a departure. |

Two-snapshot versions of the cost and slip outcomes are built the same way and
are in `results/panel_outcomes.csv`.

An absence is only evidence of leaving if somebody was looking. A department
that published no file at a snapshot makes its projects unobservable there, not
departed, and counting them as exits manufactures departures out of a missing
release. 13 project-years are on that footing and carry a null exit outcome
rather than a true one. A project that simply moved department has not left
either, and presence is decided by the project key rather than by whether the
old department still exists, which matters for the DECC projects that continued
under BEIS after DECC was abolished in 2016.

Four data facts constrain the cost outcome and are handled explicitly rather
than quietly.

- **One published units error.** HM Treasury reports the Equitable Life Payment
Scheme whole-life cost as 59,173,700 in a column headed GBP million, while the
narrative in the same row says "total outturn of GBP 58m". The largest credible
figure anywhere in the panel is GBP 72,079m, so any value above GBP 200,000m is
treated as a units error and excluded from the cost outcomes. One row qualifies.
- **A price-base break at the end.** The March 2026 NISTA file spells its money
columns "(GBPm, Presented in 2024/25 Real Prices)"; every earlier file spells
them "(GBPm)". Any step that lands on that file mixes price bases, so the break
is flagged on each horizon separately: the one-year step from March 2025, the
two-year step from March 2024, and the March 2026 row itself for growth against
a project's first observed baseline. All three are excluded from the cost
outcomes by default. A single one-step flag would leave 101 two-year figures
comparing a nominal baseline with a real-price one without saying so. The
sensitivity table shows what including the one-year break does.
- **A sign change is not growth.** Two project-years publish a negative
baseline whole-life cost, both DfT rail franchising, where the narrative
explains the figure is net of the premium train operators pay the department. A
ratio is taken only when both ends are strictly positive.
- **Withheld values are not numbers.** Two spellings of a Freedom of Information
withholding appear: the department files write "Exempt under Section 43 of the
Freedom of Information Act 2000 (Commercial Interests)" and the NISTA files
write the bare "Section 43 - Commercial interests". A naive number-grab reads
the second as 43. Both are rejected before any digit is read, and 49 values in
the two NISTA files depend on that. The two NISTA files also introduce ranges
("Low: 2,750.00, Mid: 2,820.00, High: 3,100.00"), for which the mid point is
taken and the fact that it was a range is recorded.

## The calibration table

This is the headline. For each rating: how many resolvable project-years carried
it, what share of them met each adverse outcome, and what probability the rating
would imply if the colours were read the way a reader naturally reads them.

**The implied probabilities are this study's assumption and not the publisher's.**
Neither the IPA nor NISTA has ever attached a number to a colour. The mapping
used here is the one specified for this exercise: on the five-point scale, a
probability of no material problem of 0.90 for Green, 0.75 for Amber/Green, 0.50
for Amber, 0.25 for Amber/Red and 0.10 for Red; on the three-point scale, 0.85,
0.50 and 0.15. Every Brier number below inherits that assumption, which is why
the isotonic recalibration further down exists: it shows what the same ratings
are worth when the mapping is fitted instead of assumed.

### Five-point scale, September 2012 to March 2021

| Rating | n | Whole-life cost up more than 10% | Implied by the colour | Difference |
|---|---|---|---|---|
| Green | 26 | 7.7% | 10% | -2.3 points |
| Amber/Green | 165 | 14.5% | 25% | -10.4 points |
| Amber | 387 | 21.7% | 50% | -28.3 points |
| Amber/Red | 222 | 34.7% | 75% | -40.3 points |
| Red | 31 | 32.3% | 90% | -57.7 points |

| Rating | n | End date slipped more than 6 months | Implied by the colour | Difference |
|---|---|---|---|---|
| Green | 31 | 6.5% | 10% | -3.5 points |
| Amber/Green | 179 | 12.8% | 25% | -12.2 points |
| Amber | 427 | 17.1% | 50% | -32.9 points |
| Amber/Red | 245 | 28.6% | 75% | -46.4 points |
| Red | 37 | 29.7% | 90% | -60.3 points |

| Rating | n | Rated Red at the next snapshot | Implied by the colour | Difference |
|---|---|---|---|---|
| Green | 27 | 0.0% | 10% | -10.0 points |
| Amber/Green | 150 | 1.3% | 25% | -23.7 points |
| Amber | 366 | 3.8% | 50% | -46.2 points |
| Amber/Red | 213 | 6.1% | 75% | -68.9 points |
| Red | 34 | 20.6% | 90% | -69.4 points |

| Rating | n | Left the portfolio for good | Implied by the colour | Difference |
|---|---|---|---|---|
| Green | 108 | 71.3% | 10% | +61.3 points |
| Amber/Green | 274 | 33.9% | 25% | +8.9 points |
| Amber | 554 | 19.7% | 50% | -30.3 points |
| Amber/Red | 319 | 18.2% | 75% | -56.8 points |
| Red | 57 | 22.8% | 90% | -67.2 points |

### Three-point scale, March 2022 to March 2026

| Rating | n | Whole-life cost up more than 10% | Implied by the colour | Difference |
|---|---|---|---|---|
| Green | 37 | 24.3% | 15% | +9.3 points |
| Amber | 342 | 21.3% | 50% | -28.6 points |
| Red | 46 | 43.5% | 85% | -41.5 points |

| Rating | n | End date slipped more than 6 months | Implied by the colour | Difference |
|---|---|---|---|---|
| Green | 54 | 24.1% | 15% | +9.1 points |
| Amber | 499 | 25.7% | 50% | -24.3 points |
| Red | 79 | 39.2% | 85% | -45.8 points |

| Rating | n | Rated Red at the next snapshot | Implied by the colour | Difference |
|---|---|---|---|---|
| Green | 58 | 1.7% | 15% | -13.3 points |
| Amber | 544 | 10.3% | 50% | -39.7 points |
| Red | 97 | 50.5% | 85% | -34.5 points |

Every cost and schedule difference in the five-point era is negative and grows
with the severity of the rating: the colours overshoot, and they overshoot most
where they are most alarming. The three-point era breaks the ordering on cost
entirely, with Green above Amber.

The full table for all seven outcomes and both scales is
`results/table_calibration.csv`. Charts: `chart_calibration_five_point.png`,
`chart_calibration_three_point.png`,
`chart_adverse_rate_by_rating_five_point.png`,
`chart_adverse_rate_by_rating_three_point.png`.

## Discrimination

Discrimination asks only whether the ranking is right, so it does not depend on
the probability mapping at all. The statistic is the area under the ROC curve of
the rating's rank, with ties averaged, and a 95 per cent percentile bootstrap
over 2,000 resamples at a fixed seed.

The bootstrap resamples whole projects, not project-years. The same project
appears in up to fourteen snapshots carrying a similar rating and a similar
trajectory, so resampling rows would treat correlated observations as fresh
information and give intervals that are too narrow. Both versions are in
`results/table_discrimination.csv`; the columns below are the clustered ones. In
this panel the difference turns out to be small, which is itself worth knowing:
the correction widens the headline cost interval by about 0.01.

**0.50 is not the right reference for every outcome.** Two of the outcomes are
defined in terms of the rating being scored, and their arithmetic makes the
ranking run backwards before any information enters. A project already on the
worst rating cannot get worse, and a project one step off the worst can only
worsen by one step while a Green can worsen by four. So the "no skill" value for
"rating worse next year" is not 0.5. The null column below measures it directly:
the next rating is redrawn, independently of the current one, from the marginal
distribution actually observed on those rows, the outcome is rebuilt from that
draw, and the AUC is taken; 400 draws, fixed seed. That holds the arithmetic
fixed and removes only the information. For the cost, schedule and exit
outcomes, which are not defined in terms of the rating, the null is 0.5.

| Outcome | Scale | Project-years | Projects | Base rate | Discrimination | Low | High | No-skill reference | Above reference |
|---|---|---|---|---|---|---|---|---|---|
| Baseline whole-life cost up more than 10 per cent | five_point | 831 | 342 | 0.2371 | 0.6144 | 0.5701 | 0.6571 | 0.5 |  |
| Baseline whole-life cost up more than 10 per cent | three_point | 425 | 211 | 0.24 | 0.5521 | 0.4995 | 0.6059 | 0.5 |  |
| Baseline whole-life cost up more than 25 per cent | five_point | 831 | 342 | 0.1516 | 0.6177 | 0.5684 | 0.6679 | 0.5 |  |
| Baseline whole-life cost up more than 25 per cent | three_point | 425 | 211 | 0.16 | 0.5604 | 0.4934 | 0.625 | 0.5 |  |
| End date slipped more than 6 months | five_point | 919 | 368 | 0.1948 | 0.6098 | 0.5666 | 0.6521 | 0.5 |  |
| End date slipped more than 6 months | three_point | 632 | 250 | 0.2722 | 0.5406 | 0.5003 | 0.5805 | 0.5 |  |
| End date slipped more than 12 months | five_point | 919 | 368 | 0.136 | 0.6139 | 0.563 | 0.6617 | 0.5 |  |
| End date slipped more than 12 months | three_point | 632 | 250 | 0.1788 | 0.5563 | 0.5145 | 0.6023 | 0.5 |  |
| Rated Red at the next snapshot | five_point | 790 | 287 | 0.0456 | 0.6797 | 0.5981 | 0.754 | 0.5001 | 0.1796 |
| Rated Red at the next snapshot | three_point | 699 | 264 | 0.1516 | 0.7122 | 0.6566 | 0.7577 | 0.4986 | 0.2136 |
| Rating worse at the next snapshot | five_point | 790 | 287 | 0.1962 | 0.2968 | 0.2627 | 0.335 | 0.1862 | 0.1106 |
| Rating worse at the next snapshot | three_point | 699 | 264 | 0.1102 | 0.3367 | 0.2969 | 0.3762 | 0.2668 | 0.0698 |
| Rating worse at the next snapshot, excluding projects already on the worst rating | five_point | 756 | 283 | 0.205 | 0.3136 | 0.276 | 0.3527 | 0.1934 | 0.1202 |
| Rating worse at the next snapshot, excluding projects already on the worst rating | three_point | 602 | 252 | 0.1279 | 0.3989 | 0.3511 | 0.4472 | 0.2667 | 0.1322 |
| Left the portfolio and did not return | five_point | 1312 | 505 | 0.2668 | 0.3497 | 0.3174 | 0.3827 | 0.5 |  |
| Left the portfolio and did not return | three_point | 859 | 309 | 0.1711 | 0.3586 | 0.3175 | 0.4002 | 0.5 |  |

Read across. On cost and schedule the five-point scale sits around 0.61, clear
of chance on every measure, and the three-point scale around 0.55, with both
cost intervals crossing 0.50 and both slip intervals only just clearing it. On
next year's rating the ratings do much better, 0.680 and 0.712.

The two rating-transition outcomes look worse than chance and are not. "Rating
worse next year" scores 0.297 on the five-point scale against a no-skill
reference of 0.186, so it is +0.111 above its own null, not below chance.
Excluding the projects that cannot worsen at all leaves 0.314 against 0.193,
which is +0.120. The rating does carry information about whether a project will
be marked down; the sub-0.5 number is the ceiling, not the forecast.

Leaving the portfolio is different. Its null really is 0.5, because nothing in
the definition of leaving refers to the rating, and the observed 0.350 is
genuinely backwards: Green projects leave more often than Red ones, which is the
system working rather than failing, as sections 5 and 6 of the findings set out.

Rank correlation with the continuous outcomes tells the same story.

| Outcome | Scale | Project-years | Projects | Spearman rho | Low | High |
|---|---|---|---|---|---|---|
| Baseline whole-life cost growth | five_point | 831 | 342 | 0.1414 | 0.0745 | 0.2093 |
| Baseline whole-life cost growth | three_point | 425 | 211 | 0.0589 | -0.0578 | 0.1715 |
| End-date slip in months | five_point | 919 | 368 | 0.1191 | 0.0568 | 0.1853 |
| End-date slip in months | three_point | 632 | 250 | 0.0892 | 0.0086 | 0.1708 |

The correlations are positive but small, and both three-point intervals include
zero.

Year by year the picture is noisy: see `chart_auc_over_time.png` and
`results/table_discrimination_by_snapshot.csv`. Cost discrimination falls below
0.50 in 1 of the 12 individual snapshots that resolve it.

## Brier score and its decomposition

The Brier score is the mean squared error of a probability forecast, and
Murphy's decomposition splits it into

Brier = reliability - resolution + uncertainty

Reliability is the mean squared gap between what a bin forecast and what that
bin actually delivered, and zero is perfect calibration. Resolution is how far
the bins' outcome rates spread around the overall base rate, and more is better.
Uncertainty is the base rate's own variance, a property of the outcome rather
than of the forecaster. The identity is checked numerically on every row.

Four forecasts are compared on the same rows:

- **published DCA**: the rating read through the implied mapping above.
- **base rate (in sample)**: a constant equal to the realised rate on those rows.
This is the reference the skill score is defined against, but it uses the
answer, so nobody could have issued it.
- **climatology (prior snapshots only)**: for each snapshot, the outcome rate
over the earlier snapshots of the same scale era. Strictly backward looking, and
the forecast a person could actually have made.
- **persistence (previous DCA)**: the same project's rating one snapshot earlier,
read through the same mapping.

"Brier if recalibrated" is `uncertainty - resolution`: what the same forecast
would score if each bin were relabelled with its own observed rate. It separates
"the ranking carries nothing" from "the colours are read as the wrong numbers".

### Whole-life cost up more than 10 per cent

| Forecast | n | Brier | Brier if recalibrated | Reliability | Resolution | Uncertainty | Skill vs base rate |
|---|---|---|---|---|---|---|---|
| published DCA | 831 | 0.27 | 0.1747 | 0.0953 | 0.0061 | 0.1809 | -0.493 |
| base rate (in sample) | 831 | 0.1809 | 0.1809 | 0 | 0 | 0.1809 | -0 |
| climatology (prior snapshots only) | 738 | 0.1873 | 0.1842 | 0.0031 | 0.0016 | 0.1858 | -0.008 |
| published DCA (climatology rows) | 738 | 0.2785 | 0.1802 | 0.0983 | 0.0056 | 0.1858 | -0.499 |
| persistence (previous DCA) | 511 | 0.3007 | 0.1604 | 0.1403 | 0.0017 | 0.1621 | -0.855 |
| published DCA (persistence rows) | 511 | 0.2761 | 0.1572 | 0.1189 | 0.0049 | 0.1621 | -0.703 |

*Five-point scale.*

| Forecast | n | Brier | Brier if recalibrated | Reliability | Resolution | Uncertainty | Skill vs base rate |
|---|---|---|---|---|---|---|---|
| published DCA | 425 | 0.2632 | 0.1777 | 0.0855 | 0.0047 | 0.1824 | -0.443 |
| base rate (in sample) | 425 | 0.1824 | 0.1824 | 0 | 0 | 0.1824 | 0 |
| climatology (prior snapshots only) | 281 | 0.178 | 0.1744 | 0.0036 | 0.0015 | 0.1759 | -0.012 |
| published DCA (climatology rows) | 281 | 0.2702 | 0.1742 | 0.0961 | 0.0017 | 0.1759 | -0.536 |
| persistence (previous DCA) | 223 | 0.272 | 0.1733 | 0.0986 | 0.0006 | 0.1739 | -0.564 |
| published DCA (persistence rows) | 223 | 0.2721 | 0.1723 | 0.0998 | 0.0016 | 0.1739 | -0.564 |

*Three-point scale.*

### End date slipped more than 6 months

| Forecast | n | Brier | Brier if recalibrated | Reliability | Resolution | Uncertainty | Skill vs base rate |
|---|---|---|---|---|---|---|---|
| published DCA | 919 | 0.2778 | 0.1525 | 0.1253 | 0.0043 | 0.1568 | -0.771 |
| base rate (in sample) | 919 | 0.1568 | 0.1568 | 0 | 0 | 0.1568 | -0 |
| climatology (prior snapshots only) | 816 | 0.1624 | 0.1605 | 0.0019 | 0.0008 | 0.1613 | -0.007 |
| published DCA (climatology rows) | 816 | 0.2861 | 0.1572 | 0.1289 | 0.0041 | 0.1613 | -0.773 |
| persistence (previous DCA) | 555 | 0.3044 | 0.1607 | 0.1437 | 0.0015 | 0.1621 | -0.877 |
| published DCA (persistence rows) | 555 | 0.281 | 0.1582 | 0.1228 | 0.004 | 0.1621 | -0.733 |

*Five-point scale.*

### Rated Red at the next snapshot

| Forecast | n | Brier | Brier if recalibrated | Reliability | Resolution | Uncertainty | Skill vs base rate |
|---|---|---|---|---|---|---|---|
| published DCA | 699 | 0.2486 | 0.108 | 0.1407 | 0.0207 | 0.1286 | -0.933 |
| base rate (in sample) | 699 | 0.1286 | 0.1286 | 0 | 0 | 0.1286 | 0 |
| climatology (prior snapshots only) | 513 | 0.1365 | 0.1347 | 0.0018 | 0.0009 | 0.1356 | -0.006 |
| published DCA (climatology rows) | 513 | 0.2431 | 0.1083 | 0.1348 | 0.0273 | 0.1356 | -0.793 |
| persistence (previous DCA) | 435 | 0.2592 | 0.1346 | 0.1246 | 0.0096 | 0.1442 | -0.797 |
| published DCA (persistence rows) | 435 | 0.2385 | 0.1094 | 0.1292 | 0.0348 | 0.1442 | -0.654 |

*Three-point scale. This is the one outcome where the ratings carry real
information: resolution of 0.0207 against an uncertainty of 0.1286, so a
correctly calibrated reading of the colour would cut the Brier score by 16%
against the base rate.*

The pattern is the same everywhere. Reliability accounts for essentially the
whole of the published rating's loss, resolution is an order of magnitude
smaller, and persistence is no better than the current rating. The honest
reference, climatology, scores within about one per cent of the in-sample base
rate, which means the base-rate comparison is not doing the ratings an
injustice.

All 96 rows are in `results/table_brier.csv`.

## What a calibrated rating would be worth

The miscalibration above is a property of the mapping, not of the ratings. To
separate the two, an isotonic regression of the outcome on the rating's rank is
fitted on the earlier snapshots of a scale era and evaluated on the later ones.
It is never fitted and evaluated on the same rows and never fitted across the
scale change.

Two reference forecasts are reported and they are not the same thing. "Skill vs
the training base rate" compares against a constant equal to the outcome rate
over the training snapshots: that is the forecast a person standing at the split
with the same information would actually have issued, so it is the implementable
comparison and the one to read. "Skill vs the test base rate" compares against a
constant equal to the rate the test period turned out to have, which nobody
could have issued because it uses the answer. The two differ whenever the rate
moved between the periods.

| Outcome | Scale | Train n | Test n | Test base rate | Brier, stated mapping | Brier, recalibrated | Brier, training base rate | Skill recalibrated vs training base rate | Skill recalibrated vs test base rate | Fitted mapping |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline whole-life cost up more than 10 per cent | five_point | 547 | 284 | 0.2852 | 0.2776 | 0.2048 | 0.2092 | 0.0211 | -0.0046 | {'Green': 0.0, 'Amber/Green': 0.1157, 'Amber': 0.2282, 'Amber/Red': 0.2867, 'Red': 0.3158} |
| Baseline whole-life cost up more than 10 per cent | three_point | 282 | 143 | 0.2657 | 0.2725 | 0.1974 | 0.1966 | -0.0038 | -0.0115 | {'Green': 0.2, 'Amber': 0.2, 'Red': 0.4815} |
| Baseline whole-life cost up more than 25 per cent | five_point | 547 | 284 | 0.162 | 0.298 | 0.1355 | 0.136 | 0.0039 | 0.0021 | {'Green': 0.0, 'Amber/Green': 0.0579, 'Amber': 0.1618, 'Amber/Red': 0.2099, 'Red': 0.2099} |
| Baseline whole-life cost up more than 25 per cent | three_point | 282 | 143 | 0.1748 | 0.2823 | 0.1455 | 0.1448 | -0.0054 | -0.0089 | {'Green': 0.125, 'Amber': 0.1299, 'Red': 0.3704} |
| End date slipped more than 6 months | five_point | 599 | 320 | 0.2188 | 0.2919 | 0.1705 | 0.1723 | 0.01 | 0.0022 | {'Green': 0.0714, 'Amber/Green': 0.1069, 'Amber': 0.1805, 'Amber/Red': 0.2384, 'Red': 0.3913} |
| End date slipped more than 6 months | three_point | 332 | 300 | 0.3333 | 0.2576 | 0.2354 | 0.2358 | 0.0017 | -0.0593 | {'Green': 0.2162, 'Amber': 0.2162, 'Red': 0.2222} |
| End date slipped more than 12 months | five_point | 599 | 320 | 0.1625 | 0.299 | 0.1388 | 0.1377 | -0.0074 | -0.0196 | {'Green': 0.0357, 'Amber/Green': 0.0763, 'Amber': 0.1203, 'Amber/Red': 0.1457, 'Red': 0.3478} |
| End date slipped more than 12 months | three_point | 332 | 300 | 0.2233 | 0.2646 | 0.179 | 0.1806 | 0.009 | -0.0321 | {'Green': 0.1351, 'Amber': 0.1351, 'Red': 0.1667} |
| Rated Red at the next snapshot | five_point | 606 | 184 | 0.0652 | 0.3272 | 0.0588 | 0.0616 | 0.0465 | 0.0363 | {'Green': 0.0, 'Amber/Green': 0.0079, 'Amber': 0.0404, 'Amber/Red': 0.051, 'Red': 0.1667} |
| Rated Red at the next snapshot | three_point | 364 | 335 | 0.1821 | 0.2431 | 0.1253 | 0.1524 | 0.1776 | 0.1588 | {'Green': 0.0345, 'Amber': 0.0828, 'Red': 0.4444} |
| Rating worse at the next snapshot | five_point | 606 | 184 | 0.1848 | 0.3674 | 0.1509 | 0.1509 | 0 | -0.0015 | {'Green': 0.1997, 'Amber/Green': 0.1997, 'Amber': 0.1997, 'Amber/Red': 0.1997, 'Red': 0.1997} |
| Rating worse at the next snapshot | three_point | 364 | 335 | 0.1164 | 0.3183 | 0.103 | 0.103 | 0 | -0.0014 | {'Green': 0.1044, 'Amber': 0.1044, 'Red': 0.1044} |
| Rating worse at the next snapshot, excluding projects already on the worst rating | five_point | 582 | 174 | 0.1954 | 0.342 | 0.1574 | 0.1574 | 0 | -0.001 | {'Green': 0.2079, 'Amber/Green': 0.2079, 'Amber': 0.2079, 'Amber/Red': 0.2079, 'Red': 0.2079} |
| Rating worse at the next snapshot, excluding projects already on the worst rating | three_point | 319 | 283 | 0.1378 | 0.244 | 0.1192 | 0.1192 | 0 | -0.0029 | {'Green': 0.1191, 'Amber': 0.1191, 'Red': 0.1191} |
| Left the portfolio and did not return | five_point | 890 | 422 | 0.2038 | 0.3479 | 0.1709 | 0.1709 | 0 | -0.0531 | {'Green': 0.2966, 'Amber/Green': 0.2966, 'Amber': 0.2966, 'Amber/Red': 0.2966, 'Red': 0.2966} |
| Left the portfolio and did not return | three_point | 450 | 409 | 0.1614 | 0.3229 | 0.1357 | 0.1357 | 0 | -0.0026 | {'Green': 0.18, 'Amber': 0.18, 'Red': 0.18} |

Recalibration removes almost all of the loss and adds almost nothing. Against
the implementable reference, the training period's base rate, the recalibrated
rating scores between -0.007 and +0.021 on the eight cost and schedule rows: a
calibrated reading of the colour is worth about as much as knowing how often the
thing happens, and no more. The exception is next year's rating on the
three-point scale, where recalibration buys +0.178.

Where the isotonic fit collapses to a constant it reproduces the training base
rate exactly, so its skill against that reference is 0.000 rather than the
negative figure the test-base-rate column shows. That difference is the test
period's rate having moved, not the rating losing anything.

The fitted mappings are worth reading on their own. For "rating worse next year"
and for "left the portfolio" the isotonic fit collapses to a single constant for
every rating, which is the fit saying the rating carries no monotone information
about that outcome at all. For cost growth on the five-point scale it rises from
0.00 for Green to 0.32 for Red, which is the same ordering the published colours
assert, over a range a third as wide as the colours imply.

## By department and by category

Discrimination on the cost outcome, departments with at least 40 resolvable
project-years:

| Department | Scale | Project-years | Projects | Base rate | Discrimination | Brier | Skill vs base rate |
|---|---|---|---|---|---|---|---|
| MOD | five_point | 171 | 51 | 0.1988 | 0.571 | 0.2921 | -0.8334 |
| DH/DHSC | five_point | 98 | 46 | 0.2143 | 0.6636 | 0.2745 | -0.6302 |
| DFT | five_point | 95 | 30 | 0.1789 | 0.6546 | 0.2602 | -0.7709 |
| MOJ | five_point | 84 | 40 | 0.2857 | 0.6299 | 0.2744 | -0.3447 |
| HO | five_point | 66 | 25 | 0.3788 | 0.5176 | 0.3052 | -0.2968 |
| BEIS/DBT | five_point | 57 | 28 | 0.2105 | 0.5231 | 0.2642 | -0.5894 |
| CO | five_point | 46 | 22 | 0.3696 | 0.6237 | 0.249 | -0.0686 |
| HMRC | five_point | 45 | 21 | 0.3556 | 0.75 | 0.2044 | 0.108 |
| DCMS | five_point | 40 | 16 | 0.175 | 0.4805 | 0.3046 | -1.1095 |
| MOD | three_point | 67 | 27 | 0.2985 | 0.5255 | 0.2683 | -0.2812 |
| HO | three_point | 40 | 21 | 0.375 | 0.5773 | 0.2688 | -0.1469 |

And on the slip outcome:

| Department | Scale | Project-years | Projects | Base rate | Discrimination | Brier | Skill vs base rate |
|---|---|---|---|---|---|---|---|
| MOD | five_point | 220 | 64 | 0.1545 | 0.5746 | 0.3067 | -1.3472 |
| DH/DHSC | five_point | 104 | 49 | 0.1538 | 0.7102 | 0.2794 | -1.1461 |
| DFT | five_point | 97 | 31 | 0.1546 | 0.5289 | 0.2813 | -1.1515 |
| MOJ | five_point | 89 | 43 | 0.191 | 0.6234 | 0.2923 | -0.8916 |
| HO | five_point | 76 | 27 | 0.2895 | 0.6679 | 0.2719 | -0.3218 |
| BEIS/DBT | five_point | 58 | 29 | 0.2931 | 0.6815 | 0.2191 | -0.0574 |
| CO | five_point | 50 | 22 | 0.18 | 0.5921 | 0.2676 | -0.8127 |
| HMRC | five_point | 45 | 21 | 0.2444 | 0.6791 | 0.2377 | -0.2871 |
| DCMS | five_point | 41 | 16 | 0.2195 | 0.4688 | 0.3109 | -0.8144 |
| MOD | three_point | 144 | 42 | 0.2708 | 0.5516 | 0.2854 | -0.445 |
| MOJ | three_point | 54 | 28 | 0.4074 | 0.5739 | 0.2425 | -0.0046 |
| DFT | three_point | 53 | 19 | 0.2264 | 0.6646 | 0.2071 | -0.1823 |
| HO | three_point | 53 | 23 | 0.3774 | 0.6167 | 0.2513 | -0.0696 |
| HMRC | three_point | 42 | 22 | 0.3333 | 0.4515 | 0.29 | -0.305 |

Every row is computed inside one scale era. Pooling the eras, which an earlier
version of this analysis did, ranks a five-point Amber (rank 2) alongside a
three-point Red (rank 2) and produces a number that means nothing; it moved 79
of the 140 breakdown rows by 0.05 or more and reversed the sign of the
conclusion on 14 of them.

The spread across departments is wide, from 0.480 to 0.750 on the five-point
cost outcome, but so are the intervals at these sample sizes: the largest block,
the Ministry of Defence, has 171 project-years and most have well under a
hundred. No department row here should be read as establishing that one
department's assessors are better than another's. What the table does establish
is that the portfolio-wide figure is not hiding one department with a strong
signal.

By the portfolio's own annual-report category:

| Outcome | Category | Scale | Project-years | Projects | Base rate | Discrimination | Skill vs base rate |
|---|---|---|---|---|---|---|---|
| Baseline whole-life cost up more than 10 per cent | Government Transformation and Service Delivery | five_point | 113 | 77 | 0.3894 | 0.5967 | -0.1192 |
| Baseline whole-life cost up more than 10 per cent | Government Transformation and Service Delivery | three_point | 178 | 100 | 0.2865 | 0.5516 | -0.2927 |
| Baseline whole-life cost up more than 10 per cent | ICT | five_point | 53 | 32 | 0.3019 | 0.489 | -0.5723 |
| Baseline whole-life cost up more than 10 per cent | ICT | three_point | 57 | 26 | 0.2982 | 0.575 | -0.2004 |
| Baseline whole-life cost up more than 10 per cent | Infrastructure and Construction | five_point | 103 | 61 | 0.1845 | 0.6692 | -0.7351 |
| Baseline whole-life cost up more than 10 per cent | Infrastructure and Construction | three_point | 124 | 59 | 0.121 | 0.5416 | -1.4864 |
| Baseline whole-life cost up more than 10 per cent | Military Capability | five_point | 52 | 25 | 0.2692 | 0.5789 | -0.473 |
| Baseline whole-life cost up more than 10 per cent | Military Capability | three_point | 66 | 26 | 0.2879 | 0.528 | -0.31 |
| End date slipped more than 6 months | Government Transformation and Service Delivery | five_point | 117 | 81 | 0.1966 | 0.639 | -0.8235 |
| End date slipped more than 6 months | Government Transformation and Service Delivery | three_point | 231 | 110 | 0.2554 | 0.5054 | -0.4747 |
| End date slipped more than 6 months | ICT | five_point | 66 | 37 | 0.3182 | 0.6048 | -0.3584 |
| End date slipped more than 6 months | ICT | three_point | 85 | 34 | 0.3176 | 0.5338 | -0.2351 |
| End date slipped more than 6 months | Infrastructure and Construction | five_point | 106 | 65 | 0.2547 | 0.5818 | -0.3891 |
| End date slipped more than 6 months | Infrastructure and Construction | three_point | 182 | 71 | 0.2582 | 0.5674 | -0.3116 |
| End date slipped more than 6 months | Military Capability | five_point | 71 | 34 | 0.1408 | 0.5557 | -1.748 |
| End date slipped more than 6 months | Military Capability | three_point | 134 | 40 | 0.291 | 0.5607 | -0.3445 |
| Rated Red at the next snapshot | Government Transformation and Service Delivery | three_point | 235 | 112 | 0.1149 | 0.6861 | -1.5382 |
| Rated Red at the next snapshot | ICT | five_point | 47 | 31 | 0.0638 | 0.822 | -5.167 |
| Rated Red at the next snapshot | ICT | three_point | 90 | 34 | 0.1333 | 0.5929 | -1.4226 |
| Rated Red at the next snapshot | Infrastructure and Construction | five_point | 58 | 36 | 0.069 | 0.6019 | -3.5319 |
| Rated Red at the next snapshot | Infrastructure and Construction | three_point | 225 | 79 | 0.1511 | 0.7707 | -0.7658 |
| Rated Red at the next snapshot | Military Capability | five_point | 50 | 30 | 0.1 | 0.6867 | -2.5144 |
| Rated Red at the next snapshot | Military Capability | three_point | 149 | 45 | 0.2215 | 0.7126 | -0.439 |

Category is published only from the 2017 publication onward, so these cover the
later part of the series. Infrastructure and construction has the lowest
cost-growth base rate and the best discrimination; military capability has the
worst discrimination on both cost and slip.

## Who made the call

From March 2022 each row carries either an IPA assessment or the Senior
Responsible Owner's own. No project-year carries both, so this is a comparison
between two disjoint groups of projects and not a head-to-head on the same ones.

| Outcome | Assessed by | n | Base rate | Discrimination | Brier | Skill vs base rate |
|---|---|---|---|---|---|---|
| Baseline whole-life cost up more than 10 per cent | IPA | 238 | 0.2269 | 0.5927 | 0.2687 | -0.5317 |
| Baseline whole-life cost up more than 10 per cent | SRO | 187 | 0.2567 | 0.5154 | 0.2563 | -0.3432 |
| End date slipped more than 6 months | IPA | 345 | 0.2667 | 0.5511 | 0.2823 | -0.4434 |
| End date slipped more than 6 months | SRO | 287 | 0.2787 | 0.5332 | 0.2546 | -0.2662 |
| Rated Red at the next snapshot | IPA | 392 | 0.1786 | 0.7193 | 0.2643 | -0.802 |
| Rated Red at the next snapshot | SRO | 307 | 0.1173 | 0.6872 | 0.2286 | -1.2081 |

The IPA's own assessments discriminate better than the SRO's on cost (0.593
against 0.515) and about the same on slip. Whether that is the assessor or the
selection of which projects get which kind of assessment cannot be separated
from this data.

## Sensitivity

| Variant | Outcome | Scale | n | Base rate | Discrimination | Brier | Skill vs base rate |
|---|---|---|---|---|---|---|---|
| headline | wlc_growth_1y_gt_10 | five_point | 831 | 0.2371 | 0.6144 | 0.27 | -0.4931 |
| headline | wlc_growth_1y_gt_10 | three_point | 425 | 0.24 | 0.5521 | 0.2632 | -0.4431 |
| headline | slip_1y_gt_6m | five_point | 919 | 0.1948 | 0.6098 | 0.2778 | -0.7715 |
| headline | slip_1y_gt_6m | three_point | 632 | 0.2722 | 0.5406 | 0.2697 | -0.3615 |
| excluding project-years whose narrative mentions rebaselining | wlc_growth_1y_gt_10 | five_point | 776 | 0.2332 | 0.6079 | 0.2697 | -0.5083 |
| excluding project-years whose narrative mentions rebaselining | wlc_growth_1y_gt_10 | three_point | 384 | 0.2526 | 0.5472 | 0.2645 | -0.4009 |
| excluding project-years whose narrative mentions rebaselining | slip_1y_gt_6m | five_point | 862 | 0.1833 | 0.6161 | 0.2756 | -0.841 |
| excluding project-years whose narrative mentions rebaselining | slip_1y_gt_6m | three_point | 573 | 0.2705 | 0.5439 | 0.2691 | -0.3638 |
| 12-month steps only (drops September 2019 to March 2021) | wlc_growth_1y_gt_10 | five_point | 758 | 0.2322 | 0.6171 | 0.2681 | -0.5039 |
| 12-month steps only (drops September 2019 to March 2021) | wlc_growth_1y_gt_10 | three_point | 425 | 0.24 | 0.5521 | 0.2632 | -0.4431 |
| 12-month steps only (drops September 2019 to March 2021) | slip_1y_gt_6m | five_point | 839 | 0.1895 | 0.6167 | 0.2745 | -0.7875 |
| 12-month steps only (drops September 2019 to March 2021) | slip_1y_gt_6m | three_point | 632 | 0.2722 | 0.5406 | 0.2697 | -0.3615 |
| including the March 2025 to March 2026 price-base break | wlc_growth_1y_gt_10 | five_point | 831 | 0.2371 | 0.6144 | 0.27 | -0.4931 |
| including the March 2025 to March 2026 price-base break | wlc_growth_1y_gt_10 | three_point | 538 | 0.2509 | 0.5625 | 0.2625 | -0.3965 |
| including the March 2025 to March 2026 price-base break | slip_1y_gt_6m | five_point | 919 | 0.1948 | 0.6098 | 0.2778 | -0.7715 |
| including the March 2025 to March 2026 price-base break | slip_1y_gt_6m | three_point | 632 | 0.2722 | 0.5406 | 0.2697 | -0.3615 |
| excluding the final two snapshots (right censoring) | wlc_growth_1y_gt_10 | five_point | 831 | 0.2371 | 0.6144 | 0.27 | -0.4931 |
| excluding the final two snapshots (right censoring) | wlc_growth_1y_gt_10 | three_point | 282 | 0.227 | 0.5585 | 0.2585 | -0.4734 |
| excluding the final two snapshots (right censoring) | slip_1y_gt_6m | five_point | 919 | 0.1948 | 0.6098 | 0.2778 | -0.7715 |
| excluding the final two snapshots (right censoring) | slip_1y_gt_6m | three_point | 332 | 0.2169 | 0.4925 | 0.2806 | -0.6523 |

Nothing moves. Dropping the project-years whose narrative mentions rebaselining
changes the cost discrimination by less than 0.01. Dropping the one 18-month
step changes it by less than 0.01. Including the one-year price-base break at
the end changes the three-point cost discrimination from 0.552 to 0.562.

The last variant addresses right censoring, which matters only for the exit
outcome: a project last seen at the second-to-last snapshot has one later
snapshot of evidence that it did not come back, not several. Dropping the final
two snapshots so that every remaining row is followed by at least two more moves
the three-point exit discrimination from 0.359 to 0.386 and leaves the
five-point figure untouched. The conclusion that the rating predicts exit
backwards does not depend on the censoring.

The full table covers all seven outcomes.

## What this does and does not show

**The rating is not a forecast of these outcomes, and it does not claim to be.**
The IPA defines the Delivery Confidence Assessment as confidence in successful
delivery "to time, cost and quality", which is broader and vaguer than "the
baseline whole-life cost will rise by more than 10 per cent in the next twelve
months". A rating that is well calibrated against its own idea of a material
problem can look badly calibrated against a specific threshold. That is why the
discrimination results, which need no mapping, carry more weight here than the
Brier results, and why the isotonic recalibration is reported alongside.

**The rating is an input to what happens next.** A Red rating triggers
intervention, and intervention is supposed to change the outcome. A well-run
portfolio should therefore show *less* discrimination than a passive one, and
none of this can tell those two apart. The analogous point for the exit outcome
is stronger still: a Green project that finishes and leaves is the system
working.

**The baseline whole-life cost is a budget, not an actual.** Growth in it means
the approved budget was formally raised. A project that overspends without a
rebaseline shows no growth here; a project that is rebaselined for a scope
increase shows a lot. Excluding project-years whose narrative mentions
rebaselining moves nothing, which suggests the narratives do not reliably flag
it, not that rebaselining does not matter.

**The extreme values in the continuous outcomes are real and are definitional.**
The largest single-year cost growth in the panel is DECC's "FID Enabling for
Renewables", from GBP 3.7m in September 2013 to GBP 22.5bn in September 2014: a
preparatory phase being rebaselined as a full programme. The largest schedule
movements are Ministry of Defence projects whose end dates run to the 2060s and
2070s and then move by decades, which is a change in what the end date is taken
to mean. The binary flags are unaffected; the continuous outcomes are reported
only through rank statistics for this reason.

**The portfolio is not a fixed population.** Projects join and leave, and
selection into and out of the portfolio is not random. The published data gives
no departure reason and the collection carries no departure list, so the exit
classification in this report is an inference from end dates, clearly labelled.

**Every outcome except exit is conditional on survival, and survival depends on
the rating.** 500 of the 2,346 rated project-years have no row at the next
snapshot, so they have no cost, schedule or next-rating outcome to be scored
against. Leaving is not random with respect to the rating: Green project-years
are the project's last 71% of the time against 18% for Amber/Red. The scored
sample is therefore short of exactly the Green project-years a calibration table
most wants, which is one reason the Green row carries the smallest n in every
table here. Nothing in this report corrects for that, and no correction is
available: a project that has finished has no next-year baseline to grow.

**Project identity is reconstructed, not given, before September 2019.** No file
published a project id until then, so the early snapshots are linked by name, by
an exact normalised match first and then by a conservative similarity pass, a
GMPP id core pass and a rename pass that links on the approved start date and
the whole-life cost. 22 outright renames are caught that way and are listed in
`results/identity_rename_merges.csv`, and 27 similarity merges are listed with
their scores. Renames that changed both the name and the whole-life cost in the
same year are not caught by any of this, and they appear as an exit and a new
project. The exit base rate should be read as an upper bound on real departures
for that reason.

**The intervals are clustered on the project, but the point estimates still
pool.** The bootstrap resamples whole projects, so the intervals do not treat
fourteen snapshots of one project as fourteen independent observations. The
point estimates still pool project-years, so a department with a few long-lived
projects contributes many correlated rows to its own breakdown. The Brier and
calibration tables carry no intervals at all; their n columns are the guide.

**The three-point era has less data behind it than it looks.** It covers five
snapshots and four resolvable transitions, and between 63 and 79 per cent of the
rated portfolio sits in Amber at any snapshot, so the separating power available
is limited by construction.

## How this was checked, and what checking it changed

Nothing here is trustworthy because it was written carefully. It is trustworthy
to the extent it was attacked and survived. Three things were done, and all
three changed the numbers.

**The pipeline was audited against the raw files by independent readers.** Eight
readers took one dimension each, from header canonicalisation to the scoring
mathematics, and every finding they raised was handed to a separate reader whose
instructions were to refute it and who had to reproduce the defect before
confirming it. Eight findings were refuted that way and are not reflected here.
Twenty-nine survived. Twenty-seven were defects in this code and are fixed. The
other two are properties of the published data that cannot be fixed at all and
are now stated instead: that the outcomes are conditional on a project still
being on the portfolio, which is finding 6 above, and that four departments
never published a departmental file, which is in the coverage section.

**The scoring mathematics was reimplemented independently and compared.** Brier,
the Murphy three-term decomposition and the AUC were written a second time from
their definitions and run against this code on 400 random inputs. The largest
disagreement is 1.4e-16, floating-point noise. The Murphy identity, reliability
minus resolution plus uncertainty equals the Brier score, is checked numerically
on every row the report prints and the residual column is in
`results/table_brier.csv`.

**The dating was checked against a source independent of the publication
pages**, as the section on the data sets out: 107 files name a financial year in
a money header, all 107 agree, none disagrees.

The defects that mattered most, all of which were live when the first draft of
this report was written:

- **A whole snapshot was being destroyed.** The rule that dated each
publication preferred a financial year parsed out of a money column, and its
column filter also matched the narrative header "Departmental narrative on
budget/forecast variance for 2018/19". The September 2019 files carry that
string as a leftover from the previous year's template. All 120 September 2019
project-years were stamped September 2018, two snapshots were merged into one,
and the transition between them was lost.
- **The departmental and category breakdowns pooled the two rating scales.** A
rank of 2 is Amber on the five-point scale and Red on the three-point one. Every
row of both breakdowns spans both eras, so every number in them was computed on
incomparable ranks. Splitting by era moves 79 of the 140 rows by 0.05 or more
and reverses the sign of the conclusion on 14.
- **One conclusion was backwards.** "Rating worse next year" scored 0.30 and was
read as the rating mean-reverting. But a project on the worst rating cannot
worsen and a project one step off it can only worsen by one step, so the
no-skill value for that outcome is not 0.5. Measured, it is 0.19. The rating is
0.11 above its own null, not below chance.
- **Twenty-two renames were being counted as deaths.** "Successor SSBN" is
published as "DREADNOUGHT" from the next snapshot, and the names score 0.08 on
any similarity measure. Linking on the approved start date and the whole-life
cost instead recovers 22 of these, each one of which was previously a fabricated
permanent exit and a lost transition.
- **A department-year was missing from the source.** The FCO's 2020 publication
is not in the gov.uk collection, so three FCO projects appeared to leave the
portfolio in September 2018.
- **Twenty published variances were multiplied by a hundred.** A cell reading
"0.64" is the fraction 0.0064 far more often than it is a variance of 0.64 per
cent, and the parser assumed so unconditionally. The baseline and forecast
published in the same row settle it, and on 20 rows they say the blanket rule
turned a sub-one-per-cent variance into one of up to 97 per cent.
- **Smaller ones, each of which deleted or invented data.** A time-only cell,
"00:00:00", was read as today's date and fabricated seven end dates in the
cross-check. A pound sign that the file's encoding rendered as a different
character made one cell read as prose and deleted a GBP 9.94bn whole-life cost.
The spelling "Green/Amber" was bucketed as "not rated", because "n/a" is a
substring of "green/amber". A workbook no Excel engine could open was parsed as
text and its compressed bytes recorded as a successful read. Two columns the
NISTA files publish on every row, on whether a project has an evaluation plan,
were on the list of spreadsheet working notes and were being thrown away. The
March 2026 file renames the ICT category and the two spellings were being
counted as two categories.

Each of these is now covered by a test, and the suite is 256 tests.

## What could not be verified

- **Why any project left the portfolio.** The published files record no departure
reason and the collection contains no list of projects that completed against
projects that were cancelled. The end-date proxy in this report is an inference
and is labelled as one everywhere it appears.
- **What the IPA intends a colour to mean numerically.** No published document in
the collection attaches a probability to a rating. The implied mapping used here
is an assumption specified for this exercise.
- **Whether the blank ratings in the September 2012 snapshot are exemptions.**
The IPA's own back-series records 18 of them as exempt, which is strong
evidence, but the department files as published simply leave the cell blank.
Both are treated as non-ratings, so nothing turns on it.
- **Whether the scale change in March 2022 was announced anywhere in this
collection.** It is visible in the published headers and in the data. The
transparency policy PDF in the collection dates from May 2013 and predates it.
- **Whether project-level whole-life cost figures are on a consistent basis
across departments.** Two files carry publisher footnotes saying they are not: a
DECC file states its figures rest on DECC's own modelling projections, and 2019
and 2020 files carry a note that the whole-life-cost basis differs from the
National Infrastructure and Construction Pipeline.
- **The March 2026 snapshot's outcomes.** It is the last snapshot, so nothing
resolves from it. Its 189 project-years are in the panel and contribute to no
outcome.

## Reproducing every number

Everything in this report is rebuilt by one command from the repository root:

```
.venv/bin/python -m gmpp.src.run_all --test
```

It re-downloads from gov.uk only when `data/raw/gmpp/manifest.csv` is absent;
`--fetch` forces the download and `--no-fetch` runs the analysis alone. It stops
at the first stage that fails and exits with that stage's status. The stages it
runs, which can also be run one at a time:

```
.venv/bin/python -m gmpp.src.discover           # gov.uk content API -> manifest
.venv/bin/python -m gmpp.src.download           # every attachment
.venv/bin/python -m gmpp.src.snapshots          # snapshot date per publication
.venv/bin/python -m gmpp.src.profile_headers    # header inventory
.venv/bin/python -m gmpp.src.panel              # -> results/panel.csv
.venv/bin/python -m gmpp.src.validate_calendar  # dating vs the money headers
.venv/bin/python -m gmpp.src.outcomes           # -> results/panel_outcomes.csv
.venv/bin/python -m gmpp.src.score              # -> results/table_*.csv
.venv/bin/python -m gmpp.src.crosscheck         # -> results/table_crosscheck.csv
.venv/bin/python -m gmpp.src.charts             # -> results/*.png
.venv/bin/python -m gmpp.src.report             # -> results/report.md
.venv/bin/python -m pytest gmpp/tests -q        # 256 tests
```

`make -C gmpp all` runs the same stages where `make` is available.

### Files

| File | What it is |
|---|---|
| `results/panel.csv` | The canonical panel: 2495 project-years, 708 projects, 14 snapshots. Publishable. |
| `results/panel_outcomes.csv` | The panel with every forward-resolved outcome. |
| `results/table_calibration.csv` | Observed rate by rating for all seven outcomes, both scales. |
| `results/table_discrimination.csv` | Rank discrimination with bootstrap intervals. |
| `results/table_brier.csv` | Brier and the Murphy decomposition for four competing forecasts. |
| `results/table_isotonic.csv` | Forward-chained recalibration. |
| `results/table_by_department.csv`, `table_by_category.csv` | Breakdowns. |
| `results/table_sensitivity.csv` | Five analysis variants. |
| `results/table_crosscheck.csv` | Agreement with the IPA's own back-series. |
| `results/table_exit_diagnosis.csv` | End-date position of projects that left. |
| `results/identity_fuzzy_merges.csv` | Every name merge above an exact match, with its score, and every merge made on a GMPP id core. |
| `results/identity_rename_merges.csv` | Every project linked across an outright rename, with the start date and whole-life cost that identified it. |
| `results/table_crosscheck_gap.csv` | Back-series project-years with no panel row, by department. |
| `results/identity_name_collisions.csv` | Name groups left unmerged because two different projects share a normalised name inside one snapshot. |
| `results/table_calendar_validation.csv` | Each publication's dating against the financial year in its own money headers. |
| `results/unmapped_headers.csv` | Headers carrying data that were not mapped. Empty. |
| `results/panel_build_log.csv` | One row per source file read. |
| `data/raw/gmpp/manifest.csv`, `download_log.csv`, `snapshots.csv`, `header_summary.csv`, `file_profile.csv` | The acquisition record. |

Source data is published on gov.uk under the Open Government Licence.
