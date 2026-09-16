"""Flatten cached Prozorro JSON into the tenders, bids and contracts tables.

Field mechanics observed directly in the cached documents (2026-09-16), not
assumed:

* A bid prices each lot through `lotValues[]` (`relatedLot`, `value.amount`,
  `status`) even when the tender has a single lot; a bare `bid.value` also
  occurs and is handled.  The `lotValues[].date` sits inside the auction
  period, so the stored amount is the post-auction price, not the sealed one.
* `awards[].bid_id` and `awards[].lotID` identify the winning bid per lot
  exactly, so winners never have to be matched on price.
* `contractChangeRationaleTypes` on a registry contract is a static vocabulary
  dictionary returned on every contract (all nine types appeared on all 89
  contracts in the 2026-09-16 probe).  It is NOT a record of applied changes.
  The applied changes are `changes[]`, each with its own `rationaleTypes`.
* Registry `status` is `terminated` for an ordinary completed contract
  (78 of 89 in that probe).  `cancelled` is the abnormal state.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw" / "prozorro"
OUT = REPO / "prozorro" / "data"

INVASION_DATE = "2022-02-24"

# Bid entries in these states never reached evaluation.
DEAD_BID_STATUS = {"deleted", "draft", "invalid.pre-qualification"}


def _num(obj: dict | None, key: str = "amount"):
    if not isinstance(obj, dict):
        return None
    v = obj.get(key)
    return float(v) if isinstance(v, (int, float)) else None


def _ident(obj: dict | None) -> tuple[str | None, str | None, str | None]:
    """(scheme, id, name) of a Prozorro organisation block."""
    if not isinstance(obj, dict):
        return None, None, None
    ident = obj.get("identifier") or {}
    return ident.get("scheme"), ident.get("id"), obj.get("name") or ident.get("legalName")


def cpv_for(items: list[dict], lot_id: str | None) -> tuple[str | None, str | None]:
    """Modal CPV code for a lot; falls back to all items when lots are absent."""
    codes = [
        (it.get("classification") or {}).get("id")
        for it in items
        if lot_id in (None, "") or it.get("relatedLot") == lot_id
    ]
    codes = [c for c in codes if c]
    if not codes and lot_id not in (None, ""):
        codes = [(it.get("classification") or {}).get("id") for it in items]
        codes = [c for c in codes if c]
    if not codes:
        return None, None
    top = Counter(codes).most_common(1)[0][0]
    return top[:2], top[:3]


def registry_row(doc: dict) -> dict:
    """Compact the live contract-registry document to the fields we score."""
    changes = doc.get("changes") or []
    rat: Counter[str] = Counter()
    for ch in changes:
        for r in ch.get("rationaleTypes") or []:
            rat[r] += 1
    active_changes = [c for c in changes if c.get("status") == "active"]
    period = doc.get("period") or {}
    val = doc.get("value") or {}
    paid = doc.get("amountPaid") or {}
    sup_scheme, sup_id, sup_name = _ident((doc.get("suppliers") or [{}])[0])
    return {
        "contract_id": doc.get("id"),
        "tender_id": doc.get("_tender_id") or doc.get("tender_id"),
        "reg_status": doc.get("status"),
        "reg_dateSigned": doc.get("dateSigned"),
        "reg_dateModified": doc.get("dateModified"),
        "reg_period_start": period.get("startDate"),
        "reg_period_end": period.get("endDate"),
        "reg_value": _num(val),
        "reg_value_net": _num(val, "amountNet"),
        "reg_value_vat_incl": val.get("valueAddedTaxIncluded"),
        "amount_paid": _num(paid),
        "amount_paid_net": _num(paid, "amountNet"),
        "amount_paid_present": bool(paid),
        "n_changes": len(changes),
        "n_changes_active": len(active_changes),
        "change_rationales": "|".join(sorted(rat)) if rat else "",
        "n_duration_extension": rat.get("durationExtension", 0),
        "n_fiscal_year_extension": rat.get("fiscalYearExtension", 0),
        "n_item_price_variation": rat.get("itemPriceVariation", 0),
        "n_volume_cuts": rat.get("volumeCuts", 0),
        "n_price_reduction": rat.get("priceReduction", 0),
        "n_quality_improvement": rat.get("qualityImprovement", 0),
        "n_tax_rate": rat.get("taxRate", 0),
        "n_third_party": rat.get("thirdParty", 0),
        "first_change_date": min((c.get("date") or "" for c in changes), default="") or None,
        "first_duration_change_date": min(
            (
                c.get("date") or ""
                for c in changes
                if "durationExtension" in (c.get("rationaleTypes") or [])
            ),
            default="",
        )
        or None,
        "reg_supplier_scheme": sup_scheme,
        "reg_supplier_id": sup_id,
        "reg_supplier_name": sup_name,
    }


def parse_tender(t: dict) -> tuple[dict, list[dict], list[dict]]:
    tid = t["id"]
    lots = t.get("lots") or []
    items = t.get("items") or []
    tender_value = t.get("value") or {}
    tp = t.get("tenderPeriod") or {}
    ap = t.get("awardPeriod") or {}
    pe = t.get("procuringEntity") or {}
    buyer_scheme, buyer_id, buyer_name = _ident(pe)
    region = ((pe.get("address") or {}).get("region") or "").strip()
    div, grp = cpv_for(items, None)

    # Lot-level expected value, keyed by lot id; "" is the synthetic single lot.
    lot_value: dict[str, float | None] = {}
    lot_vat: dict[str, bool | None] = {}
    lot_status: dict[str, str | None] = {}
    lot_cpv: dict[str, tuple[str | None, str | None]] = {}
    if lots:
        for lot in lots:
            lot_value[lot["id"]] = _num(lot.get("value"))
            lot_vat[lot["id"]] = (lot.get("value") or {}).get("valueAddedTaxIncluded")
            lot_status[lot["id"]] = lot.get("status")
            lot_cpv[lot["id"]] = cpv_for(items, lot["id"])
    else:
        lot_value[""] = _num(tender_value)
        lot_vat[""] = tender_value.get("valueAddedTaxIncluded")
        lot_status[""] = t.get("status")
        lot_cpv[""] = (div, grp)

    # An award without a lotID belongs to the tender's only lot when there is
    # exactly one, and to the synthetic lot "" when the tender has no lots[].
    default_lot = lots[0]["id"] if len(lots) == 1 else ""

    awards = t.get("awards") or []
    winning_bid: dict[str, str] = {}
    disqualified_bids: dict[str, list[str]] = {}
    award_by_id: dict[str, dict] = {}
    for a in awards:
        lot = a.get("lotID") or default_lot
        award_by_id[a.get("id")] = a
        if a.get("status") == "active" and a.get("bid_id"):
            winning_bid[lot] = a["bid_id"]
        elif a.get("status") == "unsuccessful" and a.get("bid_id"):
            disqualified_bids.setdefault(lot, []).append(a["bid_id"])

    bid_rows: list[dict] = []
    for bid in t.get("bids") or []:
        bid_id = bid.get("id")
        tenderers = bid.get("tenderers") or []
        b_scheme, b_id, b_name = _ident(tenderers[0] if tenderers else None)
        priced: list[tuple[str, float | None, str | None, bool | None]] = []
        if bid.get("lotValues"):
            for lv in bid["lotValues"]:
                priced.append(
                    (
                        lv.get("relatedLot") or "",
                        _num(lv.get("value")),
                        lv.get("status"),
                        (lv.get("value") or {}).get("valueAddedTaxIncluded"),
                    )
                )
        elif bid.get("value") is not None:
            priced.append(
                (
                    default_lot,
                    _num(bid.get("value")),
                    bid.get("status"),
                    (bid.get("value") or {}).get("valueAddedTaxIncluded"),
                )
            )
        for lot_id, amount, lv_status, vat in priced:
            exp = lot_value.get(lot_id)
            bid_rows.append(
                {
                    "tender_id": tid,
                    "lot_id": lot_id,
                    "bid_id": bid_id,
                    "bidder_scheme": b_scheme,
                    "bidder_id": b_id,
                    "bidder_name": b_name,
                    "n_tenderers": len(tenderers),
                    "bid_status": bid.get("status"),
                    "lot_value_status": lv_status,
                    "bid_date": bid.get("date"),
                    "amount": amount,
                    "vat_incl": vat,
                    "lot_expected_value": exp,
                    "lot_vat_incl": lot_vat.get(lot_id),
                    "discount": (1.0 - amount / exp) if (amount and exp) else None,
                    "won_lot": bid_id == winning_bid.get(lot_id),
                    "disqualified": bid_id in disqualified_bids.get(lot_id, []),
                    "lot_cpv_division": lot_cpv.get(lot_id, (None, None))[0],
                    "lot_cpv_group": lot_cpv.get(lot_id, (None, None))[1],
                }
            )

    # Rank by price within the lot, over live priced bids only, so a deleted or
    # draft entry cannot push a real bid down the order. Ties share the lower
    # rank, which is what "was the winner the cheapest bid" has to mean.
    for lot_id in {r["lot_id"] for r in bid_rows}:
        live = [
            r
            for r in bid_rows
            if r["lot_id"] == lot_id
            and r["amount"] is not None
            and r["bid_status"] not in DEAD_BID_STATUS
        ]
        live.sort(key=lambda r: r["amount"])
        rank = 0
        prev = None
        for i, r in enumerate(live, start=1):
            if prev is None or r["amount"] > prev:
                rank = i
                prev = r["amount"]
            r["rank_in_lot"] = rank
            r["n_live_bids_on_lot"] = len(live)
    for r in bid_rows:
        r.setdefault("rank_in_lot", None)
        r.setdefault("n_live_bids_on_lot", None)

    contract_rows: list[dict] = []
    for c in t.get("contracts") or []:
        award = award_by_id.get(c.get("awardID")) or {}
        lot = award.get("lotID") or default_lot
        cval = c.get("value") or {}
        cper = c.get("period") or {}
        s_scheme, s_id, s_name = _ident((c.get("suppliers") or [{}])[0])
        contract_rows.append(
            {
                "tender_id": tid,
                "contract_id": c.get("id"),
                "contractID": c.get("contractID"),
                "award_id": c.get("awardID"),
                "lot_id": lot,
                "tc_status": c.get("status"),
                "tc_dateSigned": c.get("dateSigned"),
                "tc_date": c.get("date"),
                "tc_period_start": cper.get("startDate"),
                "tc_period_end": cper.get("endDate"),
                "tc_value": _num(cval),
                "tc_value_net": _num(cval, "amountNet"),
                "tc_value_vat_incl": cval.get("valueAddedTaxIncluded"),
                "supplier_scheme": s_scheme,
                "supplier_id": s_id,
                "supplier_name": s_name,
                "award_value": _num(award.get("value")),
                "award_date": award.get("date"),
                "award_status": award.get("status"),
                "winning_bid_id": award.get("bid_id"),
            }
        )

    n_bids_live = sum(1 for b in (t.get("bids") or []) if b.get("status") not in DEAD_BID_STATUS)
    # Prozorro strips the price from bids that were withdrawn or rejected, so
    # some bid entries carry no amount at all and cannot be ranked. Counting
    # them here is what lets the report state the size of that hole instead of
    # letting those bids disappear silently.
    n_bids_no_price = sum(
        1
        for b in (t.get("bids") or [])
        if not b.get("lotValues") and b.get("value") is None
    )
    priced_bid_ids = {r["bid_id"] for r in bid_rows if r["amount"] is not None}
    award_status_counts = Counter(a.get("status") for a in awards)
    unsuccessful_award_bids = [
        a.get("bid_id") for a in awards if a.get("status") == "unsuccessful" and a.get("bid_id")
    ]
    start = (tp.get("startDate") or "")[:10]
    tender_row = {
        "tender_id": tid,
        "tenderID": t.get("tenderID"),
        "method": t.get("procurementMethodType"),
        "status": t.get("status"),
        "buyer_scheme": buyer_scheme,
        "buyer_id": buyer_id,
        "buyer_name": buyer_name,
        "buyer_kind": pe.get("kind"),
        "region": region,
        "cpv_division": div,
        "cpv_group": grp,
        "main_category": t.get("mainProcurementCategory"),
        "expected_value": _num(tender_value),
        "currency": tender_value.get("currency"),
        "vat_incl": tender_value.get("valueAddedTaxIncluded"),
        "n_lots": len(lots),
        "n_bids": n_bids_live,
        "n_bid_entries": len(t.get("bids") or []),
        "n_bids_no_price": n_bids_no_price,
        "n_awards": len(awards),
        "n_awards_active": award_status_counts.get("active", 0),
        "n_awards_unsuccessful": award_status_counts.get("unsuccessful", 0),
        "n_awards_cancelled": award_status_counts.get("cancelled", 0),
        "n_unsuccessful_awards": len(unsuccessful_award_bids),
        "n_unsuccessful_awards_priced": sum(
            1 for b in unsuccessful_award_bids if b in priced_bid_ids
        ),
        "n_contracts": len(t.get("contracts") or []),
        "tender_start": tp.get("startDate"),
        "tender_end": tp.get("endDate"),
        "award_start": ap.get("startDate"),
        "award_end": ap.get("endDate"),
        "date_created": t.get("dateCreated"),
        "date_modified": t.get("dateModified"),
        "created_date": start,
        "year": start[:4],
        "invasion": bool(start and start >= INVASION_DATE),
    }
    return tender_row, bid_rows, contract_rows


def attach_registry(contracts: pd.DataFrame, registry_rows: list[dict]) -> pd.DataFrame:
    """Left-join the live registry fields onto the tender copies.

    A contract with no registry record keeps NaN registry columns, which is how
    the labels stay missing instead of silently becoming zero.
    """
    cols = list(registry_row({}).keys())
    rd = pd.DataFrame(registry_rows, columns=cols) if registry_rows else pd.DataFrame(columns=cols)
    return contracts.merge(rd.drop(columns=["tender_id"]), on="contract_id", how="left")


def read_jsonl_gz(path: Path):
    """Yield objects, tolerating a final record truncated by an interrupted run."""
    n = 0
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    print(f"  {path.name}: skipped a truncated final record after {n:,}")
                    return
                n += 1
                yield obj
    except (EOFError, gzip.BadGzipFile, OSError) as exc:
        print(f"  {path.name}: stopped after {n:,} records ({exc})")


def build(raw: Path = RAW, out: Path = OUT) -> dict[str, pd.DataFrame]:
    reg: dict[str, dict] = {}
    for path in sorted((raw / "contracts").glob("contracts_w*.jsonl.gz")):
        for doc in read_jsonl_gz(path):
            row = registry_row(doc)
            reg[row["contract_id"]] = row

    tenders: list[dict] = []
    bids: list[dict] = []
    contracts: list[dict] = []
    seen: set[str] = set()
    for path in sorted((raw / "tenders").glob("tenders_w*.jsonl.gz")):
        for t in read_jsonl_gz(path):
            if t["id"] in seen:
                continue
            seen.add(t["id"])
            tr, br, cr = parse_tender(t)
            tenders.append(tr)
            bids.extend(br)
            contracts.extend(cr)

    td = pd.DataFrame(tenders)
    bd = pd.DataFrame(bids)
    cd = pd.DataFrame(contracts)
    if not cd.empty:
        cd = attach_registry(cd, list(reg.values()))
    out.mkdir(parents=True, exist_ok=True)
    td.to_parquet(out / "tenders.parquet", index=False)
    bd.to_parquet(out / "bids.parquet", index=False)
    cd.to_parquet(out / "contracts.parquet", index=False)
    return {"tenders": td, "bids": bd, "contracts": cd}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", default=str(RAW))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    tables = build(Path(args.raw), Path(args.out))
    for name, df in tables.items():
        print(f"{name}: {len(df):,} rows, {len(df.columns)} columns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
