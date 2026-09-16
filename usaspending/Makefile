# Run from the repository root: make -C usaspending <target>
ROOT := ..
PY := $(ROOT)/.venv/bin/python

.PHONY: all fetch schema evidence panel models quantiles report test clean crosscheck

# The whole workstream, in order, from nothing to results/report.md.
all: fetch schema panel evidence models quantiles report

# Fetches only the fiscal years whose parquet is missing; years already on disk
# are re-read to rebuild their manifest record, so this is safe to re-run.
fetch:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.bulk_fetch --fy-start 2010 --fy-end 2026 --workers 4

# Reads back the parquet schema and diffs it against the 44 requested columns.
schema:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.schema_check

panel:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.panel

evidence:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.field_evidence

models:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.models

quantiles:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.quantile_models

report:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.report

test:
	cd $(ROOT) && .venv/bin/python -m pytest usaspending/tests -q

# Optional: an independent count from the monthly full archive. Downloads one
# 1.17 GB zip, streams it without extracting, and deletes it.
crosscheck:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.download --fy 2010 \
		--out data/raw/usaspending/zips/FY2010.zip --workers 10 \
		--log usaspending/logs/download.log
	cd $(ROOT) && .venv/bin/python -m usaspending.src.archive_crosscheck \
		--zip data/raw/usaspending/zips/FY2010.zip --fy 2010 \
		--out usaspending/scratch/archive_D_FY2010.parquet \
		--log usaspending/logs/crosscheck.log
	rm -f $(ROOT)/data/raw/usaspending/zips/FY2010.zip

clean:
	rm -rf $(ROOT)/data/raw/usaspending/zips/*
