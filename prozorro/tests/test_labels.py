"""Label construction on synthetic tenders and registry records."""

import numpy as np
import pandas as pd
import pytest

from src.labels import add_labels, build_lots, days_between, value_change_ratio
from src.parse import attach_registry, parse_tender, registry_row
from tests.fixtures import (
    bare_value_tender,
    change,
    multi_lot_tender,
    registry,
    single_lot_tender,
)


def _tables(tenders, registries):
    trows, brows, crows = [], [], []
    for t in tenders:
        tr, br, cr = parse_tender(t)
        trows.append(tr)
        brows.extend(br)
        crows.extend(cr)
    cd = attach_registry(pd.DataFrame(crows), [registry_row(r) for r in registries])
    return pd.DataFrame(trows), pd.DataFrame(brows), cd


def test_days_between_and_value_ratio_helpers():
    assert days_between("2021-12-31T00:00:00+02:00", "2021-12-01T00:00:00+02:00") == pytest.approx(
        30.0
    )
    assert np.isnan(days_between(None, "2021-12-01T00:00:00+02:00"))
    # Net to net wins when both are present, even if the gross basis differs.
    assert value_change_ratio(120.0, 100.0, True, 60.0, 50.0, False) == pytest.approx(2.0)
    # Gross to gross only when the VAT flags agree.
    assert value_change_ratio(120.0, None, True, 100.0, None, True) == pytest.approx(1.2)
    assert np.isnan(value_change_ratio(120.0, None, True, 100.0, None, False))
    assert np.isnan(value_change_ratio(120.0, None, True, 0.0, None, True))


def test_duration_extension_comes_from_changes_and_days_from_the_period_diff():
    regs = [
        registry(
            "C1",
            "T1",
            changes=[change("2021-10-01T00:00:00+03:00", "durationExtension")],
            period={"startDate": "2021-03-25T00:00:00+02:00",
                    "endDate": "2022-06-30T00:00:00+03:00"},
            value={"amount": 96000.0, "valueAddedTaxIncluded": False},
            amountPaid={"amount": 70000.0, "valueAddedTaxIncluded": False},
        )
    ]
    t, b, c = _tables([single_lot_tender()], regs)
    lots = add_labels(build_lots(t, b, c))
    assert len(lots) == 1
    row = lots.iloc[0]
    assert row["duration_extension"] == 1.0
    # tender copy ends 2021-12-31, registry ends 2022-06-30.
    assert row["days_extended"] == pytest.approx(181.0, abs=1.0)
    assert row["days_extended_gt90"] == 1.0
    assert row["value_change_ratio"] == pytest.approx(1.2)
    assert row["value_growth_gt10"] == 1.0
    assert row["cancelled"] == 0.0
    assert row["paid_ratio"] == pytest.approx(70000.0 / 80000.0)
    assert row["underexecuted"] == 1.0
    assert row["winner_id"] == "111"
    assert bool(row["winner_is_lowest"]) is True


def test_terminated_registry_status_is_not_a_failure_label():
    """`terminated` is the ordinary completed state; only `cancelled` is not."""
    t, b, c = _tables([single_lot_tender()], [registry("C1", "T1", status="terminated")])
    lots = add_labels(build_lots(t, b, c))
    assert lots.iloc[0]["cancelled"] == 0.0
    t, b, c = _tables([single_lot_tender()], [registry("C1", "T1", status="cancelled")])
    lots = add_labels(build_lots(t, b, c))
    assert lots.iloc[0]["cancelled"] == 1.0


def test_labels_are_missing_not_zero_when_the_registry_record_is_absent():
    t, b, c = _tables([single_lot_tender()], [])
    lots = add_labels(build_lots(t, b, c))
    row = lots.iloc[0]
    assert np.isnan(row["duration_extension"])
    assert np.isnan(row["cancelled"])
    assert np.isnan(row["underexecuted"])
    assert bool(row["has_registry"]) is False


def test_lowest_disqualified_flag_and_winner_rank():
    t, b, c = _tables([bare_value_tender()], [registry("C10", "T2")])
    lots = add_labels(build_lots(t, b, c))
    row = lots.iloc[0]
    assert bool(row["lowest_disqualified"]) is True
    assert row["winner_id"] == "222"
    assert row["winner_rank"] == 2.0
    assert bool(row["winner_is_lowest"]) is False
    assert row["n_bids_lot"] == 2
    assert row["n_disqualified"] == 1


def test_multi_lot_tender_yields_one_row_per_lot_with_its_own_dispersion():
    regs = [
        registry("C20", "T3", changes=[change("2022-09-01T00:00:00+03:00", "durationExtension")]),
        registry("C21", "T3"),
    ]
    t, b, c = _tables([multi_lot_tender()], regs)
    lots = add_labels(build_lots(t, b, c)).set_index("lot_id")
    assert set(lots.index) == {"LA", "LB"}
    assert lots.loc["LA", "duration_extension"] == 1.0
    assert lots.loc["LB", "duration_extension"] == 0.0
    assert lots.loc["LA", "winner_id"] == "111"
    assert lots.loc["LB", "winner_id"] == "222"
    # Dispersion is computed within the lot, not across the tender.
    la = lots.loc["LA"]
    assert la["bid_spread"] == pytest.approx(180000.0 / 150000.0 - 1.0)
    assert la["bid_cv"] == pytest.approx(
        np.std([150000.0, 180000.0], ddof=1) / np.mean([150000.0, 180000.0])
    )
    assert lots.loc["LA", "cpv_division"] == "45"
    assert lots.loc["LB", "cpv_division"] == "33"
    assert bool(lots.loc["LA", "invasion"]) is True


def test_cancelled_contract_is_skipped_when_a_live_one_exists():
    tender = single_lot_tender()
    tender["contracts"] = [
        dict(tender["contracts"][0], id="C0", status="cancelled",
             dateSigned="2021-03-24T00:00:00+02:00"),
        tender["contracts"][0],
    ]
    regs = [registry("C0", "T1", status="cancelled"), registry("C1", "T1")]
    t, b, c = _tables([tender], regs)
    lots = add_labels(build_lots(t, b, c))
    assert len(lots) == 1
    assert lots.iloc[0]["contract_id"] == "C1"
    assert lots.iloc[0]["cancelled"] == 0.0
