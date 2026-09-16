PY := .venv/bin/python
MOD := gmpp.src
AT := cd ..

.PHONY: all data panel score report test clean

all: data panel score report

data:
	$(AT) && $(PY) -m $(MOD).discover
	$(AT) && $(PY) -m $(MOD).download
	$(AT) && $(PY) -m $(MOD).snapshots
	$(AT) && $(PY) -m $(MOD).profile_headers

panel:
	$(AT) && $(PY) -m $(MOD).panel
	$(AT) && $(PY) -m $(MOD).validate_calendar
	$(AT) && $(PY) -m $(MOD).outcomes

score:
	$(AT) && $(PY) -m $(MOD).score
	$(AT) && $(PY) -m $(MOD).crosscheck
	$(AT) && $(PY) -m $(MOD).charts

report:
	$(AT) && $(PY) -m $(MOD).report

test:
	$(AT) && $(PY) -m pytest gmpp/tests -q

clean:
	rm -f results/*.csv results/*.png results/report.md
