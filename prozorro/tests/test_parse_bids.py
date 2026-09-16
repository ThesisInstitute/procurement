"""Bid parsing across single-lot, bare-value and multi-lot tenders."""

import pandas as pd
import pytest

from src.parse import cpv_for, parse_tender, registry_row
from tests.fixtures import bare_value_tender, change, multi_lot_tender, registry, single_lot_tender


def _bids(tender):
    return pd.DataFrame(parse_tender(tender)[1])


def test_single_lot_lotvalues_parsed_with_rank_and_discount():
    t, bids, contracts = parse_tender(single_lot_tender())
    assert t["n_lots"] == 1
    # The deleted bid is still parsed as a row but is excluded from n_bids.
    assert t["n_bids"] == 2
    assert t["n_bid_entries"] == 3
    b = pd.DataFrame(bids).set_index("bid_id")
    assert set(b.index) == {"B1", "B2", "B3"}
    assert b.loc["B1", "lot_id"] == "L1"
    assert b.loc["B1", "amount"] == pytest.approx(80000.0)
    assert b.loc["B1", "discount"] == pytest.approx(0.2)
    assert bool(b.loc["B1", "won_lot"]) is True
    assert bool(b.loc["B2", "won_lot"]) is False
    assert b.loc["B1", "bidder_id"] == "111"
    assert contracts[0]["lot_id"] == "L1"
    assert contracts[0]["winning_bid_id"] == "B1"


def test_bare_value_bid_maps_to_the_synthetic_single_lot():
    t, bids, contracts = parse_tender(bare_value_tender())
    assert t["n_lots"] == 0
    b = pd.DataFrame(bids).set_index("bid_id")
    assert set(b["lot_id"]) == {""}
    assert b.loc["B10", "amount"] == pytest.approx(40000.0)
    assert b.loc["B10", "lot_expected_value"] == pytest.approx(50000.0)
    # Alpha was cheapest but disqualified; Beta won.
    assert bool(b.loc["B10", "disqualified"]) is True
    assert bool(b.loc["B10", "won_lot"]) is False
    assert bool(b.loc["B11", "won_lot"]) is True
    assert contracts[0]["lot_id"] == ""


def test_multi_lot_bid_produces_one_row_per_lot_with_its_own_lot_value():
    t, bids, contracts = parse_tender(multi_lot_tender())
    b = pd.DataFrame(bids)
    assert len(b) == 4
    assert t["n_bids"] == 2
    alpha_la = b[(b.bid_id == "B20") & (b.lot_id == "LA")].iloc[0]
    alpha_lb = b[(b.bid_id == "B20") & (b.lot_id == "LB")].iloc[0]
    assert alpha_la["lot_expected_value"] == pytest.approx(200000.0)
    assert alpha_lb["lot_expected_value"] == pytest.approx(100000.0)
    assert alpha_la["discount"] == pytest.approx(0.25)
    assert alpha_lb["discount"] == pytest.approx(0.05)
    # Alpha wins LA, Beta wins LB.
    assert bool(alpha_la["won_lot"]) is True
    assert bool(alpha_lb["won_lot"]) is False
    beta_lb = b[(b.bid_id == "B21") & (b.lot_id == "LB")].iloc[0]
    assert bool(beta_lb["won_lot"]) is True
    # Per-lot CPV, not the tender-level modal code.
    assert alpha_la["lot_cpv_division"] == "45"
    assert alpha_lb["lot_cpv_division"] == "33"
    assert {c["lot_id"] for c in contracts} == {"LA", "LB"}


def test_cpv_falls_back_to_all_items_when_the_lot_has_none():
    items = [{"classification": {"id": "45233000-9"}}]
    assert cpv_for(items, "LX") == ("45", "452")
    assert cpv_for([], "LX") == (None, None)


def test_registry_row_reads_changes_not_the_static_vocabulary():
    doc = registry(
        "C1",
        "T1",
        changes=[
            change("2021-10-01T00:00:00+03:00", "durationExtension"),
            change("2021-11-01T00:00:00+02:00", "itemPriceVariation", "volumeCuts"),
        ],
        amountPaid={"amount": 70000.0, "valueAddedTaxIncluded": False},
    )
    row = registry_row(doc)
    # Nine rationale types are present in the vocabulary dictionary; only the
    # two applied changes may be counted.
    assert len(doc["contractChangeRationaleTypes"]) == 9
    assert row["n_changes"] == 2
    assert row["n_duration_extension"] == 1
    assert row["n_item_price_variation"] == 1
    assert row["n_volume_cuts"] == 1
    assert row["n_tax_rate"] == 0
    assert row["change_rationales"] == "durationExtension|itemPriceVariation|volumeCuts"
    assert row["first_duration_change_date"] == "2021-10-01T00:00:00+03:00"
    assert row["amount_paid"] == 70000.0
    assert row["reg_supplier_id"] == "111"


def test_registry_row_with_no_changes_reports_zero():
    row = registry_row(registry("C1", "T1"))
    assert row["n_changes"] == 0
    assert row["n_duration_extension"] == 0
    assert row["change_rationales"] == ""
    assert row["first_duration_change_date"] is None
    assert row["amount_paid"] is None
    assert row["amount_paid_present"] is False


def test_award_without_a_lotid_maps_to_the_only_lot():
    """Some tenders carry a lots[] array but omit lotID on the award."""
    t = single_lot_tender()
    t["awards"][0].pop("lotID")
    t["bids"][0]["lotValues"][0].pop("relatedLot")
    t["bids"][0]["lotValues"] = None
    t["bids"][0]["value"] = {"amount": 80000.0, "valueAddedTaxIncluded": False}
    _, bids, contracts = parse_tender(t)
    b = pd.DataFrame(bids).set_index("bid_id")
    assert b.loc["B1", "lot_id"] == "L1"
    assert bool(b.loc["B1", "won_lot"]) is True
    assert b.loc["B1", "lot_expected_value"] == pytest.approx(100000.0)
    assert contracts[0]["lot_id"] == "L1"


def test_multi_lot_award_without_a_lotid_falls_back_to_the_synthetic_lot():
    t = multi_lot_tender()
    t["awards"][0].pop("lotID")
    _, _, contracts = parse_tender(t)
    lots = {c["lot_id"] for c in contracts}
    # With two lots there is no single lot to fall back on, so the award lands
    # on the synthetic lot and will simply not join to a real lot downstream.
    assert "" in lots


def test_rank_in_lot_ignores_dead_bids_and_shares_ranks_on_ties():
    t = single_lot_tender()
    # B3 is deleted and cheapest; it must not take rank 1 from B1.
    _, bids, _ = parse_tender(t)
    b = pd.DataFrame(bids).set_index("bid_id")
    assert b.loc["B1", "rank_in_lot"] == 1
    assert b.loc["B2", "rank_in_lot"] == 2
    assert pd.isna(b.loc["B3", "rank_in_lot"])
    assert b.loc["B1", "n_live_bids_on_lot"] == 2

    # A tie at the minimum: both bids get rank 1, the next gets rank 3.
    t2 = single_lot_tender()
    t2["bids"][1]["lotValues"][0]["value"]["amount"] = 80000.0
    t2["bids"][2]["status"] = "active"
    t2["bids"][2]["lotValues"][0]["status"] = "active"
    t2["bids"][2]["lotValues"][0]["value"]["amount"] = 95000.0
    _, bids2, _ = parse_tender(t2)
    b2 = pd.DataFrame(bids2).set_index("bid_id")
    assert b2.loc["B1", "rank_in_lot"] == 1
    assert b2.loc["B2", "rank_in_lot"] == 1
    assert b2.loc["B3", "rank_in_lot"] == 3


def test_rank_in_lot_is_per_lot_in_a_multi_lot_tender():
    _, bids, _ = parse_tender(multi_lot_tender())
    b = pd.DataFrame(bids)
    la = b[b.lot_id == "LA"].set_index("bid_id")
    lb = b[b.lot_id == "LB"].set_index("bid_id")
    assert la.loc["B20", "rank_in_lot"] == 1
    assert la.loc["B21", "rank_in_lot"] == 2
    # Beta is cheaper on LB, so the order flips.
    assert lb.loc["B21", "rank_in_lot"] == 1
    assert lb.loc["B20", "rank_in_lot"] == 2


def test_bid_with_no_price_is_counted_but_not_ranked():
    """Prozorro strips the price from withdrawn and rejected bids."""
    t = single_lot_tender()
    t["bids"][1]["lotValues"] = None
    t["bids"][1].pop("value", None)
    row, bids, _ = parse_tender(t)
    # Only B2 is priceless; B3 is deleted but still carries an amount.
    assert row["n_bids_no_price"] == 1
    b = pd.DataFrame(bids)
    # B2 produces no priced row at all, so it cannot enter the ranking.
    assert "B2" not in set(b["bid_id"])
    assert b[b.bid_id == "B1"].iloc[0]["rank_in_lot"] == 1
    assert b[b.bid_id == "B1"].iloc[0]["n_live_bids_on_lot"] == 1


def test_unsuccessful_award_counters_track_whether_the_bid_is_priced():
    row, _, _ = parse_tender(bare_value_tender())
    assert row["n_awards"] == 2
    assert row["n_awards_active"] == 1
    assert row["n_awards_unsuccessful"] == 1
    assert row["n_unsuccessful_awards"] == 1
    # Alpha's bid keeps its price, so the disqualification can be ranked.
    assert row["n_unsuccessful_awards_priced"] == 1

    t = bare_value_tender()
    t["bids"][0].pop("value")
    row2, _, _ = parse_tender(t)
    assert row2["n_unsuccessful_awards"] == 1
    assert row2["n_unsuccessful_awards_priced"] == 0
