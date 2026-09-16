# Prozorro: forecasting contract slip per competing bidder

Ukraine's Prozorro is the only large procurement system that publishes every
bidder's identity and every bidder's price on a completed tender. That makes it
the only public place where the question behind this workstream can be asked at
all: does the identity of the bidder, and the price it bid, carry information
about how the resulting contract will slip, over and above what the tender
itself already says?

The US panel in `../usaspending` answered the first half of the question:
schedule slip is the most forecastable outcome at award (AUC 0.84 to 0.86), and
contractor history added almost nothing over contract shape and contracting
office. But US data never shows the losing offers, so it cannot say whether the
bidder matters. Prozorro can.

The answer, the tables and every caveat are in
[`results/report.md`](results/report.md).

## What is here

| Path | What it is |
|---|---|
| `src/api.py` | polite Prozorro client: 4 concurrent requests, exponential backoff, request accounting |
| `src/census.py` | walks the tender feed; `--mode day-sample` draws a systematic sample of whole days, `--mode months` walks a complete census |
| `src/sample.py` | proportional stratified sample by tenderID creation month, fixed seed |
| `src/fetch.py` | full tender documents (where the bids live) and live contract-registry records |
| `src/parse.py` | tenders, bids and contracts tables from the cached JSON |
| `src/labels.py` | lot-level analysis table and the six outcome labels |
| `src/features.py` | award-time features with strictly as-of buyer and bidder history |
| `src/models.py`, `src/scoring.py` | forward-chained model ladder and proper scoring rules |
| `src/transfer.py` | experiment 2, the competing-bidder transfer test, the within-lot conditional test, and the identity-persistence check |
| `src/contrasts.py` | experiments 3 and 4, plus the model-free intraclass correlations |
| `src/experiments.py` | one command that produces every result table and chart |
| `src/release.py` | the released CSV tables and their column dictionary |
| `src/report.py` | renders `results/report.md` from those artifacts |
| `src/times.py` | one place that parses Prozorro's mixed-precision ISO timestamps |
| `tests/` | 61 pytest tests, including a full synthetic end-to-end run with a planted bidder effect that the transfer and within-lot tests recover and the placebos do not |

## Running it

```bash
make -C prozorro census      # systematic day sample of the feed (about 20 minutes)
make -C prozorro sample      # draw the tender sample, fixed seed
make -C prozorro fetch       # tender documents and contract registry records (hours)
make -C prozorro all         # parse, labels, experiments, release tables, report
make -C prozorro test        # pytest
```

Raw JSON is cached gzipped under `../data/raw/prozorro/` (gitignored), so a
rerun of anything downstream of `fetch` needs no network.

## Things that changed the design

All observed in the data on 2026-09-16, not taken from documentation.

1. `contractChangeRationaleTypes` on a contract is a **static vocabulary**
   returned on every contract, not a record of applied changes. The applied
   changes are `changes[]`, each with its own `rationaleTypes`.
2. Registry `status: terminated` is the **ordinary completed state** of a
   contract, not a failure. `cancelled` is the abnormal one, and inside a
   completed-tender sample it is essentially unobservable.
3. `bids` and `awards` are **not available through `opt_fields`** on the
   listing endpoint, so every tender has to be fetched in full. That is what
   sets the size of the sample.
4. A tender's `dateModified` **freezes when its contract is published** and
   does not move when the contract registry is later amended. That is what
   makes a walk of the feed safe: it does not select on the outcome being
   forecast.
5. `pd.to_datetime` infers one format from the first element of a column, and
   Prozorro mixes whole-second and microsecond ISO stamps in the same field.
   Parsing naively coerced most timestamps to NaT and silently zeroed every
   as-of history feature. `src/times.py` exists to stop that happening again.
