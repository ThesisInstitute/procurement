"""Write the released CSV tables and their column dictionary.

Only fields Prozorro itself publishes are released: legal-entity names, the
EDRPOU identifier, the buyer's region, classification codes, dates and amounts.
Contact blocks (person name, email, telephone) and street addresses are dropped
at parse time and never reach these files.

One thing a reader should know about the identifiers: a Ukrainian sole trader
(ФОП) bids under a personal name and a ten-digit individual taxpayer number
rather than an eight-digit company EDRPOU.  Prozorro publishes both, and both
are kept here, but the count of each is reported so the distinction is not
hidden.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

GZIP_ABOVE_MB = 20.0

DATA = Path(__file__).resolve().parents[1] / "data"
RESULTS = Path(__file__).resolve().parents[1] / "results"

TENDER_COLS = [
    "tender_id", "tenderID", "method", "status", "buyer_id", "buyer_name", "buyer_kind",
    "region", "cpv_division", "cpv_group", "main_category", "expected_value", "currency",
    "vat_incl", "n_lots", "n_bids", "n_bid_entries", "n_bids_no_price", "n_awards", "n_awards_active", "n_awards_unsuccessful", "n_awards_cancelled", "n_contracts", "tender_start", "tender_end",
    "award_start", "award_end", "created_date", "year", "invasion", "date_modified",
]
BID_COLS = [
    "tender_id", "lot_id", "bid_id", "bidder_id", "bidder_name", "n_tenderers", "bid_status",
    "lot_value_status", "bid_date", "amount", "vat_incl", "lot_expected_value", "lot_vat_incl",
    "discount", "rank_in_lot", "n_live_bids_on_lot", "won_lot", "disqualified",
    "lot_cpv_division", "lot_cpv_group",
]
CONTRACT_COLS = [
    "tender_id", "lot_id", "contract_id", "contractID", "award_id", "supplier_id",
    "supplier_name", "award_value", "award_date", "award_status", "winning_bid_id",
    "tc_status", "tc_dateSigned", "tc_period_start", "tc_period_end", "tc_value",
    "tc_value_net", "tc_value_vat_incl", "reg_status", "reg_dateSigned", "reg_dateModified",
    "reg_period_start", "reg_period_end", "reg_value", "reg_value_net", "reg_value_vat_incl",
    "amount_paid", "amount_paid_net", "n_changes", "change_rationales",
    "n_duration_extension", "n_fiscal_year_extension", "n_item_price_variation",
    "n_volume_cuts", "n_price_reduction", "n_quality_improvement", "n_tax_rate",
    "n_third_party", "first_change_date", "first_duration_change_date",
    "duration_extension", "days_extended", "days_extended_gt90", "value_change_ratio",
    "value_growth_gt10", "any_change", "cancelled", "paid_ratio", "underexecuted",
]
LOT_EXTRA = [
    "n_bids_lot", "min_bid", "max_bid", "mean_bid", "bid_cv", "bid_spread", "n_disqualified",
    "winner_id", "winner_name", "winner_amount", "winner_discount", "winner_rank",
    "winner_is_lowest", "lowest_disqualified", "duration_extension", "days_extended",
    "days_extended_gt90", "value_change_ratio", "value_growth_gt10", "any_change",
    "cancelled", "paid_ratio", "underexecuted",
]

DICTIONARY = {
    "tender_id": "Prozorro internal tender id, the key of /api/2.5/tenders/{id}",
    "tenderID": "human tender identifier, UA-YYYY-MM-DD-NNNNNN-x; the date is the creation date",
    "method": "procurementMethodType, one of aboveThreshold, aboveThresholdUA, aboveThresholdEU",
    "buyer_id": "procuringEntity.identifier.id (EDRPOU)",
    "region": "procuringEntity.address.region as published",
    "cpv_division": "first two digits of the modal item classification (ДК021 / CPV)",
    "expected_value": "tender value.amount, the buyer's expected value",
    "n_bids": "bid entries whose status is not deleted, draft or invalid.pre-qualification",
    "created_date": "date encoded in tenderID; the report measures its agreement with "
                    "tenderPeriod.startDate",
    "invasion": "true when the tender opened on or after 2022-02-24",
    "lot_id": "lot identifier; the empty string is the synthetic single lot of a tender "
              "published without a lots[] array",
    "bid_id": "bids[].id; awards[].bid_id points at it",
    "bidder_id": "first tenderer's identifier.id; eight digits is a company EDRPOU, ten digits "
                 "is a sole trader's individual taxpayer number",
    "n_tenderers": "number of legal entities in the bid; above one is a consortium",
    "amount": "post-auction price for this lot, from lotValues[].value.amount or bid.value.amount",
    "discount": "1 minus amount over lot_expected_value",
    "won_lot": "this bid is the bid_id of the lot's active award",
    "disqualified": "this bid is the bid_id of an award with status unsuccessful on this lot",
    "tc_*": "the tender document's own copy of the contract, which lags the live registry",
    "reg_*": "the live contract registry record, /api/2.5/contracts/{id}",
    "amount_paid": "registry amountPaid.amount",
    "n_changes": "length of registry changes[]",
    "change_rationales": "sorted distinct rationaleTypes across registry changes[]",
    "n_duration_extension": "registry changes[] whose rationaleTypes contain durationExtension",
    "duration_extension": "n_duration_extension above zero",
    "days_extended": "registry period.endDate minus the tender copy's period.endDate, in days",
    "value_change_ratio": "registry contract value over the value at signing, VAT basis matched",
    "cancelled": "registry status is cancelled; note that terminated is the ordinary end state",
    "underexecuted": "amount_paid below 0.9 of the value at signing",
    "winner_is_lowest": "the winning bid was the cheapest live priced bid on the lot",
    "lowest_disqualified": "the cheapest live priced bid on the lot was disqualified",
    "bid_cv": "standard deviation over mean of the live priced bids on the lot",
}


def write(data: Path, results: Path) -> dict:
    results.mkdir(parents=True, exist_ok=True)
    tenders = pd.read_parquet(data / "tenders.parquet")
    bids = pd.read_parquet(data / "bids.parquet")
    contracts = pd.read_parquet(data / "contracts.parquet")
    lots = pd.read_parquet(data / "lots.parquet")

    # The brief asks the released contracts table to carry the outcome labels,
    # which are computed once on the lot table; merge them back by contract id.
    label_cols = [
        "contract_id", "duration_extension", "days_extended", "days_extended_gt90",
        "value_change_ratio", "value_growth_gt10", "any_change", "cancelled",
        "paid_ratio", "underexecuted",
    ]
    have = [c for c in label_cols if c in lots.columns]
    if "contract_id" in have and len(have) > 1:
        contracts = contracts.merge(
            lots.loc[lots["contract_id"].notna(), have].drop_duplicates("contract_id"),
            on="contract_id",
            how="left",
        )

    out = {}
    for name, df, cols in [
        ("tenders", tenders, TENDER_COLS),
        ("bids", bids, BID_COLS),
        ("contracts", contracts, CONTRACT_COLS),
        ("lots", lots, ["tender_id", "lot_id", "tenderID", "method", "buyer_id", "region",
                        "cpv_division", "lot_expected_value", "created_date", "year",
                        "invasion", "contract_id"] + LOT_EXTRA),
    ]:
        keep = [c for c in cols if c in df.columns]
        sub = df[keep]
        path = results / f"{name}.csv"
        sub.to_csv(path, index=False)
        mb = path.stat().st_size / 1e6
        # Gzip anything big enough to be awkward in a git repository. A .csv.gz
        # is still a CSV to pandas, R and every spreadsheet that matters.
        if mb > GZIP_ABOVE_MB:
            gz = results / f"{name}.csv.gz"
            sub.to_csv(gz, index=False, compression="gzip")
            path.unlink()
            path = gz
            mb = path.stat().st_size / 1e6
        out[name] = {"file": path.name, "rows": int(len(sub)), "columns": len(keep),
                     "megabytes": round(mb, 1)}

    ids = bids["bidder_id"].dropna().astype(str)
    out["identifier_shape"] = {
        "bidders with an 8 digit company EDRPOU": int(ids[ids.str.len() == 8].nunique()),
        "bidders with a 10 digit individual taxpayer number": int(
            ids[ids.str.len() == 10].nunique()
        ),
        "bidders with another identifier length": int(
            ids[~ids.str.len().isin([8, 10])].nunique()
        ),
    }
    (results / "column_dictionary.json").write_text(json.dumps(DICTIONARY, ensure_ascii=False,
                                                              indent=1))
    (results / "release_manifest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--results", default=str(RESULTS))
    args = ap.parse_args()
    print(json.dumps(write(Path(args.data), Path(args.results)), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
