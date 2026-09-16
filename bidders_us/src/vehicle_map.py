"""Map each order's parent contract to the multiple-award program it belongs to.

Observed on the order panel (orders_panel.py, 2026-09-16): 103,491 of 104,993
distinct parent PIIDs carry exactly one recipient, because in FPDS a
multiple-award vehicle is one contract per awardee. The set of holders that
compete for an order is therefore the set of SIBLING contracts awarded from
the same solicitation, and the link between siblings is on the IDV records:
`solicitation_identifier` and `multiple_or_single_award_idv_code`.

Rule, stated so it can be argued with:
  - an IDV's key is award_id_piid plus the FPDS agencyID embedded in its
    contract_award_unique_key (CONT_IDV_<PIID>_<agencyID>), which is what an
    order's parent_award_id_piid plus parent_award_agency_id refers to;
  - an IDV's solicitation is the first non-null solicitation_identifier over
    its actions, upper-cased with every non-alphanumeric character removed;
    a value is usable when it is at least 8 characters long and contains
    both a letter and a digit (the shape test the usaspending report applied
    to the same field on contracts), which drops placeholders such as NONE;
  - an IDV whose modal multiple_or_single_award_idv_code is M and whose
    solicitation is usable belongs to the program keyed on
    (agencyID, solicitation); a program is a sibling set when it holds at
    least two distinct IDV PIIDs with at least two distinct recipient UEIs;
  - every other IDV is its own single-contract vehicle.

The map is an inference from those two fields. It is not FPDS's own notion
of a vehicle, and its coverage (share of orders whose parent is matched, and
share of those in a sibling set) is measured and written to
results/vehicle_map_diagnostics.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from bidders_us.src.common import RAW, RESULTS, make_logger, record_timing

PLACEHOLDERS = {"NONE", "NA", "N/A", "NULL", "0", "NOSOLICITATION"}


def normalise_solicitation(s: pd.Series) -> pd.Series:
    out = s.astype("string").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
    return out.where(out.notna() & (out != ""), pd.NA)


def solicitation_usable(s: pd.Series) -> pd.Series:
    n = s.astype("string")
    ok = n.notna() & (n.str.len() >= 8) & n.str.contains(r"[A-Z]", regex=True, na=False) \
        & n.str.contains(r"[0-9]", regex=True, na=False) & ~n.isin(PLACEHOLDERS)
    return ok.fillna(False).astype(bool)


def agency_id_from_key(key: pd.Series) -> pd.Series:
    """FPDS agencyID from CONT_IDV_<PIID>_<agencyID>; the PIID itself may contain underscores."""
    k = key.astype("string")
    return k.str.extract(r"_([^_]+)$", expand=False)


def modal(s: pd.Series):
    vc = s.dropna().value_counts()
    return vc.index[0] if len(vc) else pd.NA


def build_idv_table(tx: pd.DataFrame) -> pd.DataFrame:
    """One row per IDV with the fields the program rule needs."""
    d = tx.copy()
    d["sol_norm"] = normalise_solicitation(d["solicitation_identifier"])
    d = d.sort_values(["contract_award_unique_key", "action_date"], kind="mergesort")
    g = d.groupby("contract_award_unique_key", sort=False)
    t = g.agg(
        piid=("award_id_piid", "first"),
        first_action_date=("action_date", "min"),
        flag=("multiple_or_single_award_idv_code", modal),
        idv_type=("idv_type_code", modal),
        recipient_uei=("recipient_uei", modal),
        recipient_name=("recipient_name", modal),
        awarding_agency_code=("awarding_agency_code", modal),
        awarding_sub_agency_code=("awarding_sub_agency_code", modal),
        n_actions=("award_id_piid", "size"),
    )
    t["solicitation"] = g["sol_norm"].agg(lambda s: s.dropna().iloc[0] if s.notna().any() else pd.NA)
    t["agency_id"] = agency_id_from_key(pd.Series(t.index, index=t.index))
    t["idv_key"] = t["piid"].astype("string").str.strip() + "|" + t["agency_id"].astype("string").fillna("")
    t["solicitation_usable"] = solicitation_usable(t["solicitation"])
    return t.reset_index()


def assign_programs(t: pd.DataFrame) -> pd.DataFrame:
    """Program key for multiple-award IDVs with a usable solicitation; own key otherwise."""
    d = t.copy()
    multi = (d["flag"].astype("string") == "M") & d["solicitation_usable"]
    prog = "SOL|" + d["agency_id"].astype("string").fillna("") + "|" + d["solicitation"].astype("string")
    d["program_key"] = prog.where(multi, d["idv_key"])
    grp = d[multi].groupby("program_key").agg(n_siblings=("piid", "nunique"),
                                              n_sibling_recipients=("recipient_uei", "nunique"))
    d = d.join(grp, on="program_key")
    d["n_siblings"] = d["n_siblings"].fillna(1).astype(int)
    d["n_sibling_recipients"] = d["n_sibling_recipients"].fillna(1).astype(int)
    d["in_sibling_set"] = (d["n_siblings"] >= 2) & (d["n_sibling_recipients"] >= 2)
    # an IDV in a program that turned out to have one contract keeps its own key
    d.loc[multi & ~d["in_sibling_set"], "program_key"] = d.loc[multi & ~d["in_sibling_set"], "idv_key"]
    return d


def map_orders(panel_vehicle: pd.Series, table: pd.DataFrame) -> tuple[pd.Series, dict]:
    """Program key for each order's parent key; the parent key itself where unmatched."""
    m = table.drop_duplicates("idv_key").set_index("idv_key")["program_key"]
    mapped = panel_vehicle.map(m)
    diag = {
        "orders": int(len(panel_vehicle)),
        "orders_with_parent": int(panel_vehicle.notna().sum()),
        "orders_parent_matched_to_idv_record": int(mapped.notna().sum()),
        "orders_in_sibling_set": int(mapped.astype("string").str.startswith("SOL|").fillna(False).sum()),
    }
    out = mapped.where(mapped.notna(), panel_vehicle)
    return out.astype("string"), diag


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--idv-dir", type=Path, default=RAW / "idv")
    ap.add_argument("--panel", type=Path, default=RAW / "orders_panel.parquet")
    ap.add_argument("--out", type=Path, default=RAW / "vehicle_map.parquet")
    a = ap.parse_args()
    log = make_logger("vehicle_map")
    t0 = time.time()
    files = sorted(a.idv_dir.glob("idv_FY*.parquet"))
    if not files:
        raise FileNotFoundError(f"no IDV parquet under {a.idv_dir}")
    tx = pd.concat([pd.read_parquet(f, columns=[
        "contract_award_unique_key", "award_id_piid", "action_date", "multiple_or_single_award_idv_code",
        "idv_type_code", "recipient_uei", "recipient_name", "awarding_agency_code",
        "awarding_sub_agency_code", "solicitation_identifier"]) for f in files], ignore_index=True)
    log(f"IDV actions {len(tx)} from {len(files)} files")
    t = assign_programs(build_idv_table(tx))
    log(f"IDVs {len(t)}; flag M {int((t['flag'].astype('string') == 'M').sum())}; "
        f"usable solicitation {int(t['solicitation_usable'].sum())}; in sibling set {int(t['in_sibling_set'].sum())}")
    t.to_parquet(a.out, index=False, compression="zstd")
    diag = {
        "idv_files": [f.name for f in files],
        "idv_actions": int(len(tx)),
        "idvs": int(len(t)),
        "flag_counts": t["flag"].astype("string").fillna("NA").value_counts().to_dict(),
        "idv_type_counts": t["idv_type"].astype("string").fillna("NA").value_counts().to_dict(),
        "solicitation_filled": int(t["solicitation"].notna().sum()),
        "solicitation_usable": int(t["solicitation_usable"].sum()),
        "idvs_in_sibling_set": int(t["in_sibling_set"].sum()),
        "sibling_sets": int(t.loc[t["in_sibling_set"], "program_key"].nunique()),
        "siblings_per_set": t.loc[t["in_sibling_set"]].groupby("program_key")["piid"].nunique().describe().to_dict(),
        "recipients_per_set": t.loc[t["in_sibling_set"]].groupby("program_key")["recipient_uei"].nunique().describe().to_dict(),
    }
    if a.panel.exists():
        pv = pd.read_parquet(a.panel, columns=["vehicle"])["vehicle"]
        _, d2 = map_orders(pv, t)
        diag["orders"] = d2
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "vehicle_map_diagnostics.json").write_text(json.dumps(diag, indent=1, default=str))
    record_timing("vehicle_map", time.time() - t0, {"idvs": int(len(t))})
    log(f"-> {a.out}; {json.dumps(diag.get('orders', {}))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
