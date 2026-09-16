"""Lot-level analysis table and its outcome labels.

The unit of analysis is the (tender, lot) pair, because that is the unit a
bidder bids on: a bidder prices each lot separately through `lotValues[]`, and
each lot has its own award and its own contract.  A single-lot tender
contributes exactly one row, with the synthetic lot id "".

Label definitions, all from the live contract registry unless stated:

* `duration_extension` - at least one entry in `changes[]` whose
  `rationaleTypes` contains `durationExtension`.  This is the official record
  of an agreed extension and does not depend on any date arithmetic.
* `days_extended` - registry `period.endDate` minus the tender copy's
  `contracts[].period.endDate`.  The tender copy lags the registry (observed:
  tender copy `active` while the registry says `terminated`), so it is used as
  the at-signing end date.  The report measures how often the two agree and
  cross-tabulates the difference against `duration_extension`, because the
  assumption that the tender copy is frozen at signing is the weak link.
* `value_change_ratio` - registry `value` over the tender copy's contract
  `value`, compared like for like: net to net when both `amountNet` are
  populated, otherwise gross to gross when the two `valueAddedTaxIncluded`
  flags match, otherwise missing.
* `cancelled` - registry `status == "cancelled"`.  Registry `terminated` is the
  ordinary completed state and is NOT a failure label.
* `underexecuted` - registry `amountPaid` below 0.9 of the contract value at
  signing, on the same VAT basis.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.times import to_utc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUT = Path(__file__).resolve().parents[1] / "data"

DEAD_BID_STATUS = {"deleted", "draft", "invalid.pre-qualification"}


def days_between(later: object, earlier: object) -> float:
    """Whole days from `earlier` to `later`; NaN when either is missing."""
    a, b = to_utc(pd.Series([later, earlier]))
    if pd.isna(a) or pd.isna(b):
        return float("nan")
    return float((a - b).total_seconds() / 86400.0)


def days_between_columns(later: pd.Series, earlier: pd.Series) -> np.ndarray:
    """Vectorised `days_between` over two columns."""
    return ((to_utc(later) - to_utc(earlier)).dt.total_seconds() / 86400.0).to_numpy(dtype=float)


def value_change_ratio(
    reg_value: float | None,
    reg_net: float | None,
    reg_vat: object,
    sign_value: float | None,
    sign_net: float | None,
    sign_vat: object,
) -> float:
    """Registry value over at-signing value, on a matched VAT basis."""
    if reg_net and sign_net and sign_net > 0:
        return float(reg_net) / float(sign_net)
    if (
        reg_value
        and sign_value
        and sign_value > 0
        and (reg_vat is None or sign_vat is None or bool(reg_vat) == bool(sign_vat))
    ):
        return float(reg_value) / float(sign_value)
    return float("nan")


def live_bids(bids: pd.DataFrame) -> pd.DataFrame:
    """Bids that reached evaluation with a price, carrying their within-lot rank.

    The rank is the one `parse.parse_tender` wrote, so there is a single
    definition of "cheapest bid on the lot" in the codebase; it is recomputed
    here only if an older table is missing the column.
    """
    live = bids[~bids["bid_status"].isin(DEAD_BID_STATUS) & bids["amount"].notna()].copy()
    if "rank_in_lot" not in live.columns or live["rank_in_lot"].isna().all():
        live["rank_in_lot"] = live.groupby(["tender_id", "lot_id"])["amount"].rank(
            method="min", ascending=True
        )
    live["rank_in_lot"] = live["rank_in_lot"].astype(float)
    return live


def pick_contracts(contracts: pd.DataFrame) -> pd.DataFrame:
    """One contract per lot: prefer a live one, then the latest signed.

    A superseded contract is left in the tender document with status
    `cancelled`, so a lot can carry more than one contract row.
    """
    df = contracts.copy()
    df["_live"] = df["tc_status"].ne("cancelled") & df["reg_status"].ne("cancelled")
    df = df.sort_values(
        ["tender_id", "lot_id", "_live", "tc_dateSigned"], na_position="first", kind="stable"
    )
    df = df.drop_duplicates(["tender_id", "lot_id"], keep="last")
    return df.drop(columns=["_live"])


def build_lots(
    tenders: pd.DataFrame, bids: pd.DataFrame, contracts: pd.DataFrame
) -> pd.DataFrame:
    """Join tenders, their per-lot bid statistics and the winning contract."""
    live = live_bids(bids)

    grp = live.groupby(["tender_id", "lot_id"], dropna=False)
    stats = grp.agg(
        n_bids_lot=("bid_id", "nunique"),
        min_bid=("amount", "min"),
        max_bid=("amount", "max"),
        mean_bid=("amount", "mean"),
        std_bid=("amount", "std"),
        lot_expected_value=("lot_expected_value", "first"),
        lot_cpv_division=("lot_cpv_division", "first"),
        lot_cpv_group=("lot_cpv_group", "first"),
        n_disqualified=("disqualified", "sum"),
    ).reset_index()
    stats["bid_cv"] = np.where(
        (stats["mean_bid"] > 0) & stats["std_bid"].notna(),
        stats["std_bid"] / stats["mean_bid"],
        np.nan,
    )
    stats["bid_spread"] = np.where(
        stats["min_bid"] > 0, stats["max_bid"] / stats["min_bid"] - 1.0, np.nan
    )

    winners = live[live["won_lot"]].copy()
    winners = winners.sort_values("amount").drop_duplicates(["tender_id", "lot_id"], keep="first")
    winners = winners[
        [
            "tender_id",
            "lot_id",
            "bid_id",
            "bidder_id",
            "bidder_name",
            "amount",
            "discount",
            "rank_in_lot",
            "n_tenderers",
        ]
    ].rename(
        columns={
            "bid_id": "winner_bid_id",
            "bidder_id": "winner_id",
            "bidder_name": "winner_name",
            "amount": "winner_amount",
            "discount": "winner_discount",
            "rank_in_lot": "winner_rank",
            "n_tenderers": "winner_n_tenderers",
        }
    )

    lots = stats.merge(winners, on=["tender_id", "lot_id"], how="left")
    lots["winner_is_lowest"] = lots["winner_rank"].eq(1.0)

    # Lowest live bid disqualified and a higher bid taken instead.
    lowest = live[live["rank_in_lot"].eq(1.0)]
    lowest_flags = (
        lowest.groupby(["tender_id", "lot_id"])["disqualified"].max().rename("lowest_disqualified")
    )
    lots = lots.merge(lowest_flags, on=["tender_id", "lot_id"], how="left")

    tcols = [
        "tender_id",
        "tenderID",
        "method",
        "buyer_id",
        "buyer_name",
        "buyer_kind",
        "region",
        "cpv_division",
        "main_category",
        "expected_value",
        "currency",
        "n_lots",
        "n_bids",
        "tender_start",
        "award_end",
        "created_date",
        "year",
        "invasion",
    ]
    lots = lots.merge(tenders[tcols], on="tender_id", how="left")
    lots["cpv_division"] = lots["lot_cpv_division"].fillna(lots["cpv_division"])

    if len(contracts):
        picked = pick_contracts(contracts)
        lots = lots.merge(picked, on=["tender_id", "lot_id"], how="left", suffixes=("", "_c"))
    return lots


REGISTRY_COLUMNS = [
    "reg_status", "reg_period_end", "reg_value", "reg_value_net", "reg_value_vat_incl",
    "amount_paid", "amount_paid_net", "n_changes", "n_duration_extension",
    "first_duration_change_date", "tc_period_end", "tc_value", "tc_value_net",
    "tc_value_vat_incl", "contract_id", "tc_dateSigned",
]


def add_labels(lots: pd.DataFrame) -> pd.DataFrame:
    df = lots.copy()
    # A lot with no contract at all still needs the columns, so that its labels
    # come out missing rather than raising or silently reading as zero.
    for col in REGISTRY_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    df["has_contract"] = df["contract_id"].notna()
    df["has_registry"] = df["reg_status"].notna()

    df["duration_extension"] = (df["n_duration_extension"].fillna(0) > 0).astype(float)
    df.loc[~df["has_registry"], "duration_extension"] = np.nan
    df["any_change"] = (df["n_changes"].fillna(0) > 0).astype(float)
    df.loc[~df["has_registry"], "any_change"] = np.nan

    df["days_extended"] = days_between_columns(df["reg_period_end"], df["tc_period_end"])
    df["days_extended_gt90"] = np.where(
        df["days_extended"].notna(), (df["days_extended"] > 90).astype(float), np.nan
    )

    df["value_change_ratio"] = [
        value_change_ratio(rv, rn, rvat, sv, sn, svat)
        for rv, rn, rvat, sv, sn, svat in zip(
            df["reg_value"],
            df["reg_value_net"],
            df["reg_value_vat_incl"],
            df["tc_value"],
            df["tc_value_net"],
            df["tc_value_vat_incl"],
        )
    ]
    df["value_growth_gt10"] = np.where(
        df["value_change_ratio"].notna(), (df["value_change_ratio"] > 1.10).astype(float), np.nan
    )

    df["cancelled"] = np.where(
        df["has_registry"], (df["reg_status"] == "cancelled").astype(float), np.nan
    )

    both_net = df["amount_paid_net"].notna() & df["tc_value_net"].notna()
    paid_basis = df["amount_paid_net"].where(both_net)
    sign_basis = df["tc_value_net"].where(both_net)
    paid_basis = paid_basis.fillna(df["amount_paid"])
    sign_basis = sign_basis.fillna(df["tc_value"])
    ok = paid_basis.notna() & sign_basis.notna() & (sign_basis > 0) & (paid_basis > 0)
    df["paid_ratio"] = np.where(ok, paid_basis / sign_basis, np.nan)
    df["underexecuted"] = np.where(ok, (paid_basis / sign_basis < 0.9).astype(float), np.nan)

    df["log_value"] = np.log1p(df["lot_expected_value"].clip(lower=0))
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(OUT))
    args = ap.parse_args()
    d = Path(args.data)
    lots = add_labels(
        build_lots(
            pd.read_parquet(d / "tenders.parquet"),
            pd.read_parquet(d / "bids.parquet"),
            pd.read_parquet(d / "contracts.parquet"),
        )
    )
    lots.to_parquet(d / "lots.parquet", index=False)
    print(f"lots: {len(lots):,} rows")
    for lab in [
        "duration_extension",
        "days_extended_gt90",
        "value_growth_gt10",
        "cancelled",
        "underexecuted",
    ]:
        s = lots[lab]
        print(f"  {lab:22s} n={s.notna().sum():,} rate={s.mean():.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
