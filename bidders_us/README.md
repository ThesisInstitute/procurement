# bidders_us: how much of schedule slip is the bidder?

Two follow-up experiments on the US federal contract data behind
`usaspending/`, asked on 2026-09-16: if forecasting the slip of each competing
bidder is the goal, does the identity of the bidder carry any slip information
once the contract itself is known? Plus one cheap look at the two pre-award
numbers that describe a winning bid without seeing the losing bids.

The written result is [`results/report.md`](results/report.md). The one
sentence answer is at its top.

## Running it

From the repository root:

```
make -C bidders_us all      # exp1, exp3, fetch, idvs, evidence, orders, vmap, exp2, test, report
make -C bidders_us test     # pytest through run_tests.py, exit code recorded in results/tests.json
```

The steps, each also runnable on its own from the repository root:

```
.venv/bin/python -m bidders_us.src.shape_model    # contract-shape GBMs, cross-fitted train predictions
.venv/bin/python -m bidders_us.src.exp1           # contractor residual persistence, decomposition, pairs, placebo
.venv/bin/python -m bidders_us.src.exp3           # offers received and relative size on competed awards
.venv/bin/python -m bidders_us.src.fetch_orders   # delivery orders FY2010-FY2026 from the monthly archive
.venv/bin/python -m bidders_us.src.fetch_idvs     # IDV records FY2005-FY2026 through the bulk-download API
.venv/bin/python -m bidders_us.src.api_evidence   # saves the count-endpoint and dictionary pulls the docstrings cite
.venv/bin/python -m bidders_us.src.orders_panel   # order-level base rows and slip labels
.venv/bin/python -m bidders_us.src.vehicle_map    # sibling-contract programs from the IDV records
.venv/bin/python -m bidders_us.src.exp2           # holders of the same program as a competition set
.venv/bin/python -m bidders_us.src.run_tests      # pytest with the exit code written to results/
.venv/bin/python -m bidders_us.src.report         # assembles results/report.md from the result files
```

Experiments 1 and 3 need only the existing definitive-contract panel at
`data/raw/usaspending/panel.parquet`, built by `make -C usaspending panel`.
Experiment 2 downloads the monthly full archive one fiscal year at a time
(each zip deleted after conversion) and keeps a size-filtered parquet extract
under `data/raw/bidders_us/`; the observed download and parquet sizes are in
the report's extract table.

## Layout

```
src/common.py          paths, the forward-chained split, helpers
src/shape_model.py     contract-shape GBM for slip with no contractor identity
src/persistence.py     residual persistence, variance decomposition, pairing (pure, tested)
src/exp1.py            Experiment 1 driver
src/exp3.py            Experiment 3 driver
src/fetch_orders.py    delivery-order extract from the monthly archive, size filter at conversion
src/fetch_idvs.py      IDV records through the bulk-download API, reusing usaspending/src/bulk_fetch.py
src/orders_panel.py    order panel; label logic imported unchanged from usaspending/src/panel.py
src/vehicle_map.py     the competition set: sibling IDV contracts that share a solicitation (tested)
src/holder_history.py  as-of history of a holder, vehicle, or holder within a vehicle (tested)
src/vehicle_scoring.py within-vehicle cross-holder AUC, holder rate tables, gaps (tested)
src/exp2.py            Experiment 2 driver
src/run_tests.py       pytest wrapper that records the exit code
src/api_evidence.py    saves the count-endpoint and data-dictionary pulls the fetch cites
src/report.py          assembles results/report.md (the PNGs are drawn by exp1, exp2, exp3)
tests/                 pytest on synthetic fixtures with hand-computed answers
```

## What is reused from usaspending/ and what is copied

Imported unchanged: the label construction (`panel.build_panel` and the
functions it calls), the feature blocks and category lumping (`features`), the
GBM fitting rule (`models.fit_gbm`, iteration count chosen on the validation
years), and the scoring rules (`scoring`). Copied with a one-line change, as
the brief allows: `panel.load_transactions` into `orders_panel.py` (award type
C instead of D, a different file pattern) and `panel._asof_group_stats` into
`holder_history.py` (it also returns the count of resolved events). Nothing
under `usaspending/` is modified.

## What a vehicle is here

An order's `parent_award_id_piid` names the holder's own contract: on the
order panel, 103,491 of 104,993 distinct parent PIIDs carry exactly one
recipient. A multiple-award vehicle in FPDS is one contract per awardee, so
the holders that compete for an order are the holders of the sibling
contracts awarded from the same solicitation. `vehicle_map.py` groups IDV
records whose multiple-or-single-award flag is M by (FPDS agencyID,
normalised solicitation identifier); a group with at least two contracts and
two recipients is a program, and Experiment 2's "vehicle" is that program.
The rule and its coverage are stated in the report.
