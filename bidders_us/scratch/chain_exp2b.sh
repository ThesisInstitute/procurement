#!/bin/zsh
cd /Users/maxghenis/ThesisInstitute/procurement
while pgrep -f "bidders_us.src.fetch_idvs" > /dev/null; do sleep 20; done
if ! grep -q "failed=\[\]" bidders_us/logs/fetch_idvs_run.out; then echo "idv fetch did not finish cleanly"; exit 1; fi
.venv/bin/python -m bidders_us.src.vehicle_map > bidders_us/logs/vehicle_map_run.out 2>&1 || exit 1
.venv/bin/python -m bidders_us.src.exp2 > bidders_us/logs/exp2_run.out 2>&1 || exit 1
.venv/bin/python -m bidders_us.src.report > bidders_us/logs/report_run.out 2>&1
echo "chain_exp2b done"
