# bidders_us workstream progress

Lane brief: `.lanes/prompt_B.md`. Lane started 2026-09-16. This file is
maintained by the lane; the main session commits.

## State

Experiments 1 and 3 are final: code audited, fixes applied, rerun, tests
passing (exit code 0), and their sections of `results/report.md` regenerated
with the one-sentence answer at the top. Experiment 2 is blocked on the
USAspending archive host: after about 15 GB had been downloaded at 20 MB/s
this morning, both api.usaspending.gov and files.usaspending.gov began
closing every connection from this machine right after the TLS handshake
(their web front end still answers). FY2010 to FY2021 are parsed; FY2022 to
FY2026 are outstanding. A relauncher polls the host once a minute and, when
it answers, restarts the fetch (which resumes at FY2022) and then runs the
API evidence pull, the order panel and Experiment 2 in order; the report
prints a warning if it is ever assembled from a panel that does not cover
the test horizon.

## Numbers

All numbers live in `results/report.md`, generated from the result JSON; this
file no longer repeats them, because an earlier version carried figures from
a superseded smoke run beside the final ones and an audit caught the
contradiction.

## Audit (2026-09-16, six dimensions, two skeptics per finding, 104 agents)

36 findings confirmed, 13 refuted; every confirmed finding is addressed below or by the rebuild of the order panel on the complete extract. The audit's own list of what it checked and found clean covers as-of leakage (8 checks), split discipline (12), scoring arithmetic (18), the fetch and panel (13), mechanism claims (15) and the statistics of the headline (14).

Fixed, changed a number: the shrinkage weight for the contractor residual was
chosen on validation and test outcomes pooled (validation rows were relabelled
without removing the test rows); the headline share mixed a per-contractor
numerator with a per-award denominator and reported a spread across cells as
if it were an interval; the within-test split-half share was reported gross
of its permutation null; the one-sided permutation p-value lacked the +1
correction; the pooled within-vehicle correlation was not centred with the
weights it used; the gap table broke ties differently at its two ends; the
two-way fixed-effects parameter count ignored disconnected components; the
ANOVA columns used a different denominator from the table text; the fetch
manifest double-counted orders whose qualifying base row appears in two
years.

Fixed, latent or wording: Experiment 3 did not filter on the qualification
flag (no row was affected on this panel); several typed constants in report
prose now come from result files; the order funnel labels said "type-D
award"; headings were not sentence case; the competition-code caveat cited
the memo as if measured; the fetcher started the next year's download before
checking the current year's error; the premise that orders are competed among
holders is now labelled as the brief's premise and eligibility requires the
multiple-award flag; the count-endpoint and dictionary pulls are saved by
`api_evidence.py`.

Recorded as caveats rather than fixed: the group bootstrap treats contractors
as independent although they nest in offices; the all-sizes competition set
counts base-action rows rather than orders; rows of an order dated before the
year its base action clears the threshold are not in the extract.

## Design change after the first Experiment 2 run (2026-09-16, 10:00)

On the first complete order panel (798,977 in-scope orders under 104,993
parent PIIDs), exactly one vehicle passed the eligibility rule, because
103,491 parent PIIDs have a single recipient: in FPDS a multiple-award
vehicle is one contract per holder, so the parent PIID is the holder's own
contract and not the program the holders compete in. The competition set is
rebuilt from the IDV records (`fetch_idvs.py`, bulk-download API, FY2005 to
FY2026): sibling contracts with the multiple-award flag that share a
solicitation identifier form a program (`vehicle_map.py`, tested), and
Experiment 2 groups orders by program. The match rate of order parents to
IDV records and the share of orders in a sibling set are measured and
reported; the map is an inference from two FPDS fields and is labelled so.

## Decisions

- Delivery orders are fetched from the monthly full archive, not the
  bulk-download API. The count endpoints put FY2020 at 4.1 million
  delivery-order actions against 0.19 million definitive-contract actions,
  and a one-month probe job took 375 seconds server side for 311,783 rows,
  so a single-year job could not finish inside the 60 minute cap. The
  archive is 1.2 to 1.9 GB per year, downloaded at 12 to 24 MB per second
  and parsed in about a minute.
- Orders are restricted at conversion time to those whose base action
  obligated at least 250,000 dollars, plus every later action of those
  orders. All-sizes counts per vehicle and holder are kept alongside.
- Two recipient-keyed columns are removed from the contract-shape model
  (the aggregate-recipient flag and the contracting officer's business size
  determination), so that nothing in it identifies the recipient.

## Next

- Orders panel, Experiment 2, report, README, final review.
