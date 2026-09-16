# World Bank PAD -> IEG outcome backtest.
# Every number in results/report.md is produced by one of these targets.
# Run from this directory. REPO is the repo root; the venv lives there.
REPO := $(abspath $(CURDIR)/..)
PY := $(REPO)/.venv/bin/python
MOD := worldbank.src

.PHONY: all fetch static wds projects padtext dataset dictionary model vintage textquality \
        analysis report disagreement verify test clean

# `all` is a RECIPE, not a prerequisite list, and that is deliberate.
# Written as `all: fetch dataset padtext dataset model ...`, GNU make
# deduplicates the repeated `dataset` prerequisite and builds it ONCE, so the
# second pass never runs and the release table ships with null text columns from
# a clean build. Sub-makes run the steps in the stated order, twice where twice
# is intended, and are immune to -j reordering.
all:
	$(MAKE) fetch
	$(MAKE) dataset
	$(MAKE) padtext
	$(MAKE) dataset
	$(MAKE) dictionary
	$(MAKE) vintage
	$(MAKE) textquality
	$(MAKE) model
	$(MAKE) analysis
	$(MAKE) report

fetch:
	$(MAKE) static
	$(MAKE) wds
	$(MAKE) projects

static:        ## IEG ratings CSV + GovTech workbook
	cd $(REPO) && $(PY) -m $(MOD).fetch_static

wds:           ## PAD / ICR / ICRR document metadata
	cd $(REPO) && $(PY) -m $(MOD).fetch_wds

projects:      ## all 28,113 projects with fl=*
	cd $(REPO) && $(PY) -m $(MOD).fetch_projects

dataset:       ## leakage-controlled join -> results/pad_ieg_join.csv
	cd $(REPO) && $(PY) -m $(MOD).dataset

padtext:       ## download qualifying PAD plain text
	cd $(REPO) && $(PY) -m $(MOD).fetch_pad_text

dictionary:    ## column dictionary for the release table
	cd $(REPO) && $(PY) -m $(MOD).dictionary

vintage:       ## which structured fields are ex ante -> results/feature_vintage.csv
	cd $(REPO) && $(PY) -m $(MOD).feature_vintage

textquality:   ## OCR noise by year and fold -> results/text_quality_*.csv
	cd $(REPO) && $(PY) -m $(MOD).text_quality

model:         ## forward-chained baselines -> results/model_table.csv
	cd $(REPO) && $(PY) -m $(MOD).model

analysis:      ## second pass: ablation, placebo, second cut, censoring
	cd $(REPO) && $(PY) -m $(MOD).analysis

report:        ## tables + charts -> results/report.md, results/*.png
	cd $(REPO) && $(PY) -m $(MOD).report

verify:        ## re-parse ICRR documents to confirm the icr_ratings repair
	cd $(REPO) && $(PY) -m $(MOD).verify_repair

disagreement:  ## Bank ICR self-rating vs IEG rating (also run by `report`)
	cd $(REPO) && $(PY) -c "from worldbank.src.report import build_disagreement as b; r=b(); print({k:v for k,v in r.items() if k.startswith('overall') or k.endswith('agreement')})"

test:
	cd $(REPO) && $(PY) -m pytest worldbank/tests -q

clean:
	rm -f results/*.csv results/*.png results/*.json results/*.parquet
