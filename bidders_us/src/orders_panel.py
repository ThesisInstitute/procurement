"""Build the delivery-order panel: base rows, slip labels at 12, 24 and 36 months.

The label logic is the definitive-contract panel's, imported unchanged from
usaspending/src/panel.py: pick_base_rows, apply_identity_filters, build_labels,
add_base_features, add_history_features and apply_population_filters run in the
same order for the same reasons (see build_panel there). One function is copied
here with changes, as the brief allows: load_transactions. The differences from
usaspending/src/panel.py are: it keeps award_type_code C instead of D; it reads
orders_C_FY*.parquet instead of contracts_D_FY*.parquet; it coerces the lean
column lists of fetch_orders.py instead of usaspending/src/columns.py (every
listed column is present, so the per-column guards are dropped); and the
year-gap check is inlined without the debugging-only allow_year_gaps switch.
The sort key that decides which action is the latest at a horizon is
identical.

Two things differ by construction and are stated in the report:

  - The extract holds only orders whose base action obligated at least 250,000
    dollars (see fetch_orders.py), so the history source here is not "every
    order" but "every order at or above the threshold". The all-sizes
    competition set of each vehicle is carried separately from the per-year
    vehicle_holders_all_sizes files.
  - The parent vehicle key `vehicle` (parent PIID plus referenced IDV agency
    identifier) is carried on every row so exp2.py can group orders by vehicle.

Writes data/raw/bidders_us/orders_panel.parquet (in-scope orders with labels
and features), data/raw/bidders_us/orders_history_source.parquet (the wider
labelled frame), data/raw/bidders_us/vehicle_holders_all_sizes.parquet and
results/orders_funnel.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

from bidders_us.src.common import RAW, RESULTS, USA_SRC, make_logger, record_timing
from bidders_us.src.fetch_orders import DATES, NUMERIC

sys.path.insert(0, str(USA_SRC))
import panel as UP  # noqa: E402

_FY_IN_NAME = re.compile(r"FY(\d{4})")


def fiscal_years_present(pdir: Path) -> list[int]:
    out = []
    for f in sorted(pdir.glob("orders_C_FY*.parquet")):
        m = _FY_IN_NAME.search(f.name)
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


def load_transactions(pdir: Path, log) -> pd.DataFrame:
    """Copy of usaspending/src/panel.py load_transactions for award type C.

    Refuses a gapped run of fiscal years for the reason given there: outcomes
    are read from the modification record of later years, and a hole would
    silently delete real modifications.
    """
    files = sorted(pdir.glob("orders_C_FY*.parquet"))
    if not files:
        raise FileNotFoundError(f"no parquet under {pdir}")
    years = fiscal_years_present(pdir)
    missing = [y for y in range(years[0], years[-1] + 1) if y not in years]
    if missing:
        raise ValueError(f"fiscal years {missing} are missing from {pdir}")
    log(f"fiscal years loaded: {years}")
    frames = []
    for f in files:
        df = pd.read_parquet(f)
        log(f"loaded {f.name} rows={len(df)}")
        frames.append(df)
    tx = pd.concat(frames, ignore_index=True)
    for c in NUMERIC:
        tx[c] = pd.to_numeric(tx[c], errors="coerce")
    for c in DATES:
        tx[c] = pd.to_datetime(tx[c], errors="coerce")
    tx = tx[tx["award_type_code"] == "C"].copy()          # the one-line change
    tx = tx[tx["action_date"].notna()].copy()
    tx["mod_seq"] = UP.mod_sequence(tx["modification_number"])
    tx["txn_seq"] = pd.to_numeric(tx["transaction_number"],
                                  errors="coerce").fillna(0).astype("int64")
    tx["is_base_mod"] = UP.is_base_mod(tx["modification_number"])
    tx["mod_str"] = tx["modification_number"].astype("string").fillna("")
    tx = tx.sort_values(
        ["contract_award_unique_key", "action_date", "mod_seq", "txn_seq", "mod_str"],
        kind="mergesort").reset_index(drop=True)
    log(f"transactions after type-C and action_date filters: {len(tx)}")
    return tx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdir", type=Path, default=RAW / "parquet")
    ap.add_argument("--out", type=Path, default=RAW / "orders_panel.parquet")
    ap.add_argument("--history-source", type=Path, default=RAW / "orders_history_source.parquet")
    a = ap.parse_args()
    log = make_logger("orders_panel")
    t0 = time.time()

    tx = load_transactions(a.pdir, log)
    data_end = tx["action_date"].max()
    log(f"data end (max action_date) = {data_end.date()}")
    panel, labels, base_funnel, steps = UP.build_panel(tx, data_end, log)
    log(f"history source {len(labels)} orders; panel {len(panel)} orders")

    # all-sizes competition set per vehicle, from the per-year fetch summaries
    vh = pd.concat([pd.read_parquet(f) for f in sorted(a.pdir.glob("vehicle_holders_all_sizes_FY*.parquet"))],
                   ignore_index=True)
    vh.to_parquet(RAW / "vehicle_holders_all_sizes.parquet", index=False)

    panel.to_parquet(a.out, index=False, compression="zstd")
    labels.to_parquet(a.history_source, index=False, compression="zstd")
    funnel = {
        "data_end": str(data_end.date()),
        "transactions_loaded": int(len(tx)),
        "fiscal_years_loaded": fiscal_years_present(a.pdir),
        "base_row_diagnostics": base_funnel,
        "history_source_orders": int(len(labels)),
        "history_source_aggregate_recipient_orders": int(labels["recipient_is_aggregate"].sum()),
        "funnel": steps,
        "panel_orders": int(len(panel)),
        "panel_orders_with_vehicle": int(panel["vehicle"].notna().sum()),
        "panel_distinct_vehicles": int(panel["vehicle"].nunique()),
        "all_sizes_vehicle_holder_rows": int(len(vh)),
        "seconds": round(time.time() - t0, 1),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "orders_funnel.json").write_text(json.dumps(funnel, indent=1))
    record_timing("orders_panel", time.time() - t0, {"orders": int(len(panel))})
    log(f"panel -> {a.out} rows={len(panel)} in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
