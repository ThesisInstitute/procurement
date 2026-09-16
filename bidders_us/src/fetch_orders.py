"""Fetch delivery-order (award_type_code C) contract actions, FY2010 to FY2026.

Why the monthly archive and not the bulk-download API. The definitive-contract
extract in usaspending/ came from POST /api/v2/bulk_download/awards/, one job per
fiscal year of about 200,000 actions, each job taking 150 to 500 seconds server
side. Delivery orders are about twenty times that volume: the search count
endpoint (POST /api/v2/search/spending_by_award_count/, called 2026-09-16)
reports 1.4 million orders with activity in FY2010, 2.8 million in FY2016 and
3.6 million in FY2020, and the transaction count endpoint reports 4.1 million
delivery-order actions in FY2020 against 0.19 million definitive-contract
actions. A single-year job would not finish inside the 60 minute cap the brief
sets: the one-month probe job submitted this session (logged in
logs/size_probe.log) took 375 seconds server side for 311,783 rows, with the
row count reported as zero until it finished, so a year of about thirteen
such months is an inference from that one measurement, not a job that was
run. The count-endpoint figures above are re-pulled and saved by
api_evidence.py into results/api_evidence.json, which is the record for
them. The monthly full archive
(files.usaspending.gov/award_data_archive/FY<year>_All_Contracts_Full_<stamp>.zip)
is the same data as a file, downloaded here with usaspending/src/download.py
and streamed without extraction, exactly the path
usaspending/src/archive_crosscheck.py used to validate the API extract. Each
year's zip size is recorded in results/orders_fetch_manifest.json
(zip_bytes) and the report prints the observed range.

Disk. The budget for this workstream is 6 GB. All delivery-order actions would
be roughly 3 GB of parquet on their own, and one zip is held on disk while it is
parsed, so the extract is restricted at conversion time, as the brief allows:
an order is kept when its base action (modification number zero, see
usaspending/src/panel.py is_base_mod) carries federal_action_obligation of at
least 250,000 dollars, and every later action of a kept order is kept with it.
Fiscal years are processed in order so that the set of kept orders is known
before the later years that carry their modifications are parsed. Orders whose
base action predates FY2010 are never kept, which is the same left truncation
the definitive-contract panel has.

So that the restriction is visible rather than silent, two things are counted
on EVERY delivery-order action before the filter is applied and written next to
the parquet: per fiscal year, the number of actions, base actions and base
actions at or above the threshold; and per parent vehicle and holder, the number
of base actions of any size. The second table is the competition set of a
vehicle measured on all of its orders, not only the ones large enough to be
labelled.

Parent vehicle. Verified in the USAspending data dictionary, pulled through
GET /api/v2/references/data_dictionary/ in this session and saved by
api_evidence.py into results/api_evidence.json: the download column
`parent_award_id_piid` is the FPDS Referenced PIID and `parent_award_agency_id`
is the FPDS Referenced IDV Agency Identifier; together they identify the
vehicle. `parent_award_type_code` is the referenced IDV type (A GWAC, B IDC,
C FSS, D BOA, E BPA) and `parent_award_single_or_multiple_code` is M or S.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from bidders_us.src.common import LOGS, RAW, RESULTS, USA_SRC, make_logger, write_json

sys.path.insert(0, str(USA_SRC))
import download as DL  # noqa: E402
from panel import fiscal_year, is_base_mod  # noqa: E402

THRESHOLD = 250_000.0
FY_START, FY_END = 2010, 2026

# Columns kept from the archive CSV. A subset of usaspending/src/columns.py KEEP
# (the text description columns, the agency names, the award-level running
# totals other than the diagnostic one, and the DUNS are dropped) plus the
# parent-vehicle columns.
LEAN = [
    "contract_award_unique_key", "award_id_piid", "parent_award_id_piid",
    "parent_award_agency_id", "parent_award_agency_name", "parent_award_type_code",
    "parent_award_single_or_multiple_code", "parent_award_modification_number",
    "modification_number", "transaction_number", "action_date", "action_type_code",
    "award_type_code", "federal_action_obligation",
    "base_and_exercised_options_value", "base_and_all_options_value",
    "potential_total_value_of_award", "period_of_performance_start_date",
    "period_of_performance_current_end_date", "period_of_performance_potential_end_date",
    "awarding_agency_code", "awarding_sub_agency_code", "awarding_office_code",
    "recipient_uei", "recipient_name", "recipient_parent_uei", "recipient_parent_name",
    "contracting_officers_determination_of_business_size_code",
    "type_of_contract_pricing_code", "naics_code", "product_or_service_code",
    "extent_competed_code", "solicitation_procedures_code", "number_of_offers_received",
    "type_of_set_aside_code", "fed_biz_opps_code",
    "performance_based_service_acquisition_code", "multi_year_contract_code",
    "cost_or_pricing_data_code", "primary_place_of_performance_state_code",
    "undefinitized_action_code",
]
NUMERIC = ["federal_action_obligation", "base_and_exercised_options_value",
           "base_and_all_options_value", "potential_total_value_of_award",
           "number_of_offers_received"]
DATES = ["action_date", "period_of_performance_start_date",
         "period_of_performance_current_end_date",
         "period_of_performance_potential_end_date"]


def coerce(df: pd.DataFrame) -> pd.DataFrame:
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    for c in DATES:
        df[c] = pd.to_datetime(df[c], errors="coerce", format="mixed")
    for c in df.columns:
        if c not in NUMERIC and c not in DATES:
            df[c] = df[c].astype("string")
    return df


def vehicle_key(df: pd.DataFrame) -> pd.Series:
    """Parent PIID joined to the referenced IDV agency identifier; <NA> if no parent."""
    piid = df["parent_award_id_piid"].astype("string").str.strip()
    ag = df["parent_award_agency_id"].astype("string").str.strip().fillna("")
    out = piid + "|" + ag
    return out.where(piid.notna() & (piid != ""), pd.NA)


def stream_archive(zip_path: Path, fy: int, log) -> tuple[pd.DataFrame, dict]:
    """All award_type_code C rows of the archive, lean columns, plus counts."""
    frames, n_all, header = [], 0, None
    missing = None
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        log(f"FY{fy} archive members {members}")
        for m in members:
            with zf.open(m) as fh:
                raw = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
                for chunk in pd.read_csv(raw, dtype=str, chunksize=250_000,
                                         usecols=lambda c: c in set(LEAN),
                                         low_memory=False):
                    if header is None:
                        header = list(chunk.columns)
                        missing = [c for c in LEAN if c not in header]
                        if missing:
                            raise RuntimeError(f"FY{fy}: archive lacks columns {missing}")
                    n_all += len(chunk)
                    frames.append(chunk[chunk["award_type_code"] == "C"][LEAN])
                    if n_all % 2_000_000 < 250_000:
                        log(f"FY{fy} scanned {n_all} rows")
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=LEAN)
    return df, {"archive_rows_all_types": int(n_all), "rows_type_C": int(len(df)),
                "archive_members": members}


def summarise_all_orders(df: pd.DataFrame, fy: int) -> tuple[dict, pd.DataFrame]:
    """Counts over every delivery-order action, before the size filter."""
    base = df[df["is_base_mod"]]
    ob = base["federal_action_obligation"]
    counts = {
        "base_actions": int(len(base)),
        "base_actions_at_or_above_threshold": int((ob >= THRESHOLD).sum()),
        "base_actions_with_parent": int(base["vehicle"].notna().sum()),
        "distinct_vehicles_all_sizes": int(base["vehicle"].nunique()),
    }
    vh = (base[base["vehicle"].notna()]
          .groupby(["vehicle", "recipient_uei"], dropna=False)
          .agg(n_orders_all_sizes=("contract_award_unique_key", "size"),
               n_orders_at_or_above_threshold=("federal_action_obligation",
                                               lambda s: int((s >= THRESHOLD).sum())),
               first_base_date=("action_date", "min"))
          .reset_index())
    vh["fiscal_year"] = fy
    return counts, vh


def run_year(fy: int, zip_path: Path, pdir: Path, keep: set, log) -> dict:
    t0 = time.time()
    zip_bytes = int(zip_path.stat().st_size)
    df, counts = stream_archive(zip_path, fy, log)
    counts["zip_bytes"] = zip_bytes
    df = coerce(df)
    df["is_base_mod"] = is_base_mod(df["modification_number"])
    df["vehicle"] = vehicle_key(df)
    df["action_fy"] = fiscal_year(df["action_date"])
    c2, vh = summarise_all_orders(df, fy)
    counts.update(c2)

    qual = df["is_base_mod"] & (df["federal_action_obligation"] >= THRESHOLD)
    qual_keys = set(df.loc[qual, "contract_award_unique_key"].dropna().unique())
    # Keys already kept from an earlier year are not new: an order can carry a
    # qualifying modification-zero row in two fiscal years (measured: four
    # orders in FY2010 to FY2021), and the panel's single-base-row filter
    # drops those later. The manifest records both counts.
    new_keys = qual_keys - keep
    keep |= new_keys
    kept_before = df[df["contract_award_unique_key"].isin(keep)].copy()
    kept = kept_before.drop_duplicates(subset=["contract_award_unique_key",
                                               "modification_number", "transaction_number",
                                               "action_date"])
    kept["source_fiscal_year"] = fy
    pdir.mkdir(parents=True, exist_ok=True)
    out = pdir / f"orders_C_FY{fy}.parquet"
    kept.drop(columns=["is_base_mod", "action_fy"]).to_parquet(
        out, index=False, compression="zstd")
    vh.to_parquet(pdir / f"vehicle_holders_all_sizes_FY{fy}.parquet", index=False)
    pd.DataFrame({"contract_award_unique_key": sorted(new_keys)}).to_parquet(
        pdir / f"kept_keys_FY{fy}.parquet", index=False)
    counts.update({
        "fiscal_year": fy,
        "orders_with_qualifying_base_row_this_year": int(len(qual_keys)),
        "new_orders_kept_this_year": int(len(new_keys)),
        "duplicate_rows_removed": int(len(kept_before) - len(kept)),
        "rows_kept": int(len(kept)),
        "rows_kept_base": int(kept["is_base_mod"].sum()),
        "parquet_bytes": int(out.stat().st_size),
        "seconds_parse": round(time.time() - t0, 1),
    })
    log(f"FY{fy} {json.dumps(counts)}")
    return counts


def load_keep(pdir: Path, before_fy: int) -> set:
    keep = set()
    for f in sorted(pdir.glob("kept_keys_FY*.parquet")):
        fy = int(f.stem[-4:])
        if fy < before_fy:
            keep |= set(pd.read_parquet(f)["contract_award_unique_key"])
    return keep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fy-start", type=int, default=FY_START)
    ap.add_argument("--fy-end", type=int, default=FY_END)
    ap.add_argument("--zdir", type=Path, default=RAW / "zips")
    ap.add_argument("--pdir", type=Path, default=RAW / "parquet")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--keep-zips", action="store_true")
    a = ap.parse_args()
    log = make_logger("fetch_orders")
    t0 = time.time()
    years = list(range(a.fy_start, a.fy_end + 1))
    a.zdir.mkdir(parents=True, exist_ok=True)

    # One year downloads ahead while the current one parses, so at most two
    # zips are on disk at once (about 4 GB), and the parse stays in fiscal-year
    # order because the kept-order set is built cumulatively.
    zips = {fy: a.zdir / f"FY{fy}_All_Contracts_Full.zip" for fy in years}
    errors: dict[int, str] = {}

    def fetch(fy: int, attempts: int = 40) -> None:
        # files.usaspending.gov drops connections and refuses HEAD requests
        # intermittently (observed twice in one run on 2026-09-16: "could not
        # size" and "Remote end closed connection without response"), so a
        # whole-year download is retried with a growing pause before the year
        # is declared failed. A failed year stops the loop, because later
        # years cannot be parsed without the kept-order set from this one.
        for attempt in range(attempts):
            try:
                DL.download(fy, zips[fy], a.workers, log)
                errors.pop(fy, None)
                return
            except Exception as exc:  # noqa: BLE001
                errors[fy] = str(exc)
                log(f"FY{fy} DOWNLOAD ERROR attempt {attempt + 1}/{attempts}: {exc}")
                part = zips[fy].with_name(zips[fy].name + ".part")
                part.unlink(missing_ok=True)
                # Both usaspending hosts closed every connection from this
                # machine for a stretch on 2026-09-16 after about 15 GB had
                # been pulled at 20 MB/s, so the pause grows to five minutes
                # and the year is given up only after about three hours.
                time.sleep(min(60 * (attempt + 1), 300))

    manifest_path = RESULTS / "orders_fetch_manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = {int(r["fiscal_year"]): r for r in json.loads(manifest_path.read_text())}

    thread = None
    for i, fy in enumerate(years):
        out = a.pdir / f"orders_C_FY{fy}.parquet"
        nxt = years[i + 1] if i + 1 < len(years) else None
        if out.exists() and (a.pdir / f"kept_keys_FY{fy}.parquet").exists():
            log(f"FY{fy} parquet already present, reusing")
            continue
        if thread is None:
            fetch(fy)
        else:
            thread.join()
            thread = None
        if fy in errors:
            log(f"FY{fy} skipped after download error; stopping so later years "
                f"are not parsed without this year's kept orders")
            break
        if nxt is not None and not (a.pdir / f"orders_C_FY{nxt}.parquet").exists():
            thread = threading.Thread(target=fetch, args=(nxt,), daemon=True)
            thread.start()
        keep = load_keep(a.pdir, fy)
        log(f"FY{fy} kept-order set from earlier years: {len(keep)}")
        rec = run_year(fy, zips[fy], a.pdir, keep, log)
        manifest[fy] = rec
        write_json(manifest_path, [manifest[k] for k in sorted(manifest)])
        if not a.keep_zips:
            zips[fy].unlink(missing_ok=True)
            log(f"FY{fy} zip deleted")
    if thread is not None:
        thread.join()
    log(f"done in {time.time()-t0:.0f}s; errors={errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
