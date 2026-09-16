#!/bin/zsh
# Wait for the running fetch (pid $1) to exit. If it failed, wait until the
# archive host answers a HEAD again, then relaunch the fetch and the chain.
cd /Users/maxghenis/ThesisInstitute/procurement
FETCH_PID=$1
while kill -0 $FETCH_PID 2>/dev/null; do sleep 15; done
if grep -q "errors={}" bidders_us/logs/fetch_orders_run.out; then echo "fetch finished clean; chain will run"; exit 0; fi
echo "fetch exited with errors at $(date); waiting for the host"
n=0
while true; do
  code=$(curl -sS -o /dev/null -I -m 20 -w "%{http_code}" "https://files.usaspending.gov/award_data_archive/FY2022_All_Contracts_Full_20260906.zip" 2>/dev/null)
  if [ "$code" = "200" ]; then break; fi
  n=$((n+1)); if [ $n -gt 240 ]; then echo "host still down after 4 hours"; exit 1; fi
  sleep 60
done
echo "host up at $(date); relaunching"
mv bidders_us/logs/fetch_orders_run.out bidders_us/logs/fetch_orders_run_$(date +%H%M).out
nohup .venv/bin/python -m bidders_us.src.fetch_orders --fy-start 2010 --fy-end 2026 > bidders_us/logs/fetch_orders_run.out 2>&1 &
sleep 3
nohup bidders_us/scratch/chain_exp2.sh > bidders_us/logs/chain_exp2.out 2>&1 &
echo "relaunched fetch and chain"
