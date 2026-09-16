#!/bin/zsh
cd /Users/maxghenis/ThesisInstitute/procurement
while pgrep -f "bidders_us.src.fetch_orders" > /dev/null; do sleep 20; done
if ! grep -q "errors={}" bidders_us/logs/fetch_orders_run.out; then echo "fetch did not finish cleanly"; exit 1; fi
.venv/bin/python -m bidders_us.src.api_evidence > bidders_us/logs/api_evidence_run.out 2>&1
.venv/bin/python -m bidders_us.src.orders_panel > bidders_us/logs/orders_panel_run.out 2>&1 || exit 1
.venv/bin/python -m bidders_us.src.vehicle_map > bidders_us/logs/vehicle_map_run.out 2>&1 || exit 1
.venv/bin/python -m bidders_us.src.exp2 > bidders_us/logs/exp2_run.out 2>&1
