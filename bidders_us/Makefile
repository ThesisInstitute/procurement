# Run from the repository root: make -C bidders_us <target>
ROOT := ..
PY := $(ROOT)/.venv/bin/python

.PHONY: all exp1 exp3 fetch idvs evidence orders vmap exp2 test report

all: exp1 exp3 fetch idvs evidence orders vmap exp2 test report

# Experiment 1: contractor effect on slip, given the contract (existing panel).
exp1:
	cd $(ROOT) && .venv/bin/python -m bidders_us.src.shape_model
	cd $(ROOT) && .venv/bin/python -m bidders_us.src.exp1

# Experiment 3: bid-side signals on competed awards (existing panel).
exp3:
	cd $(ROOT) && .venv/bin/python -m bidders_us.src.exp3

# Experiment 2: delivery orders under multiple-award vehicles.
fetch:
	cd $(ROOT) && .venv/bin/python -m bidders_us.src.fetch_orders

# IDV records FY2005 to FY2026 through the bulk-download API (small: one job per year).
idvs:
	cd $(ROOT) && .venv/bin/python -m bidders_us.src.fetch_idvs --fy-start 2005 --fy-end 2026 --workers 4

# Saves the count-endpoint and data-dictionary responses the fetch docstring cites.
evidence:
	cd $(ROOT) && .venv/bin/python -m bidders_us.src.api_evidence

orders:
	cd $(ROOT) && .venv/bin/python -m bidders_us.src.orders_panel

# Sibling-contract programs from the IDV records; the vehicle definition Experiment 2 uses.
vmap:
	cd $(ROOT) && .venv/bin/python -m bidders_us.src.vehicle_map

exp2:
	cd $(ROOT) && .venv/bin/python -m bidders_us.src.exp2

report:
	cd $(ROOT) && .venv/bin/python -m bidders_us.src.report

# Runs pytest and records the exit code in results/tests.json for the report.
test:
	cd $(ROOT) && .venv/bin/python -m bidders_us.src.run_tests
