# Prozorro workstream. Run targets from the repository root:
#   make -C prozorro all
PY := ../.venv/bin/python
export PYTHONPATH := $(CURDIR)

.PHONY: all census census-months sample fetch parse labels experiments release report test clean-derived

all: parse labels experiments release report

# Systematic sample of whole days from the tender feed: every tender in the
# range has inclusion probability 1/5, whatever the volume of its day.
census:
	$(PY) src/census.py --mode day-sample --step 5 \
		--start 2019-01-01T00:00:00 --end 2024-01-01T00:00:00 \
		2>&1 | tee logs/daysample.log

# Optional: a complete month-by-month census of the feed, used only to describe
# what the feed is made of. Slow; not the sampling frame.
census-months:
	$(PY) src/census.py --mode months --out ../data/raw/prozorro/census_months \
		--start 2019-01-01T00:00:00 --end 2026-09-16T00:00:00 \
		2>&1 | tee logs/census_months.log

sample:
	$(PY) src/sample.py --n 45000

fetch:
	$(PY) src/fetch.py --max-seconds 11000 2>&1 | tee -a logs/fetch.log

parse:
	$(PY) src/parse.py

labels:
	$(PY) src/labels.py

experiments:
	$(PY) src/experiments.py --permutations 2000

release:
	$(PY) src/release.py

report:
	$(PY) src/report.py

test:
	$(PY) -m pytest tests -q

clean-derived:
	rm -f data/*.parquet results/*.csv results/*.png results/summary.json
