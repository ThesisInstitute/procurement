# Run from the repository root: make -C usaspending <target>
PY := ../.venv/bin/python
ROOT := ..

.PHONY: all fetch evidence panel models quantiles report test clean crosscheck

all: fetch evidence panel models quantiles report

fetch:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.bulk_fetch --fy-start 2010 --fy-end 2026 --workers 4

crosscheck:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.download --fy 2010 \
		--out data/raw/usaspending/zips/FY2010.zip --workers 10 \
		--log usaspending/logs/download.log
	cd $(ROOT) && .venv/bin/python -m usaspending.src.archive_crosscheck \
		--zip data/raw/usaspending/zips/FY2010.zip --fy 2010 \
		--out usaspending/scratch/archive_D_FY2010.parquet \
		--log usaspending/logs/crosscheck.log
	rm -f $(ROOT)/data/raw/usaspending/zips/FY2010.zip

evidence:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.field_evidence

panel:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.panel

models:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.models

quantiles:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.quantile_models

report:
	cd $(ROOT) && .venv/bin/python -m usaspending.src.report

test:
	cd $(ROOT) && .venv/bin/python -m pytest usaspending/tests -q

clean:
	rm -rf $(ROOT)/data/raw/usaspending/zips/*
