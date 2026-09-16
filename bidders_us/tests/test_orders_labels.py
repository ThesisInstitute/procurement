"""Order-level label construction and the conversion-time size filter, on fixtures."""
import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from bidders_us.src import fetch_orders as FO
from bidders_us.src import orders_panel as OP
import panel as UP


def _row(key, mod, date, oblig, ceiling, end, **kw):
    r = {c: None for c in FO.LEAN}
    r.update({
        "contract_award_unique_key": key, "award_id_piid": key.split("_")[0],
        "parent_award_id_piid": "VEH1", "parent_award_agency_id": "9700",
        "parent_award_type_code": "B", "parent_award_single_or_multiple_code": "M",
        "modification_number": mod, "transaction_number": "0", "action_date": date,
        "action_type_code": None if mod == "0" else "B", "award_type_code": "C",
        "federal_action_obligation": oblig, "base_and_exercised_options_value": ceiling,
        "base_and_all_options_value": ceiling, "potential_total_value_of_award": ceiling,
        "period_of_performance_start_date": date,
        "period_of_performance_current_end_date": end,
        "period_of_performance_potential_end_date": end,
        "awarding_agency_code": "097", "awarding_sub_agency_code": "9700",
        "awarding_office_code": "OFF1", "recipient_uei": "UEIA", "recipient_name": "A CO",
        "recipient_parent_uei": "UEIA", "type_of_contract_pricing_code": "J",
        "naics_code": "541512", "product_or_service_code": "D302",
        "extent_competed_code": "A", "number_of_offers_received": 3,
    })
    r.update(kw)
    return r


def _zip_with_rows(tmp_path, rows, name="FY2015_All_Contracts_Full_x.zip"):
    df = pd.DataFrame(rows)
    # the archive carries many more columns; add a couple so usecols is exercised
    df["extra_column_not_kept"] = "x"
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    zp = tmp_path / name
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("FY2015_All_Contracts_Full_x_1.csv", buf.getvalue())
    return zp


def test_fetch_keeps_large_orders_with_their_mods_and_drops_small(tmp_path):
    rows = [
        _row("BIG_1", "0", "2015-01-10", 300000.0, 300000.0, "2016-01-10"),
        _row("BIG_1", "P00001", "2015-06-01", 0.0, 0.0, "2016-08-01"),
        _row("SMALL_1", "0", "2015-02-01", 50000.0, 50000.0, "2015-12-01"),
        _row("SMALL_1", "P00001", "2015-03-01", 0.0, 0.0, "2015-12-01"),
        _row("OLD_1", "P00003", "2015-04-01", 1000.0, 0.0, "2016-01-01"),   # base kept in an earlier year
        _row("DCONTRACT", "0", "2015-01-01", 900000.0, 900000.0, "2016-01-01", award_type_code="D"),
    ]
    zp = _zip_with_rows(tmp_path, rows)
    keep = {"OLD_1"}
    log = lambda m: None  # noqa: E731
    rec = FO.run_year(2015, zp, tmp_path / "parquet", keep, log)
    out = pd.read_parquet(tmp_path / "parquet" / "orders_C_FY2015.parquet")
    assert rec["archive_rows_all_types"] == 6
    assert rec["rows_type_C"] == 5
    assert rec["base_actions"] == 2
    assert rec["base_actions_at_or_above_threshold"] == 1
    assert rec["new_orders_kept_this_year"] == 1
    assert sorted(out["contract_award_unique_key"].unique()) == ["BIG_1", "OLD_1"]
    assert len(out) == 3
    assert "extra_column_not_kept" not in out.columns
    assert out["vehicle"].iloc[0] == "VEH1|9700"
    vh = pd.read_parquet(tmp_path / "parquet" / "vehicle_holders_all_sizes_FY2015.parquet")
    # both base actions, large and small, count toward the all-sizes competition set
    assert vh["n_orders_all_sizes"].sum() == 2
    assert vh["n_orders_at_or_above_threshold"].sum() == 1
    assert "BIG_1" in set(pd.read_parquet(tmp_path / "parquet" / "kept_keys_FY2015.parquet")["contract_award_unique_key"])


def test_fetch_refuses_archive_without_required_columns(tmp_path):
    df = pd.DataFrame([{"contract_award_unique_key": "X", "award_type_code": "C"}])
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    zp = tmp_path / "bad.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("bad_1.csv", buf.getvalue())
    with pytest.raises(RuntimeError, match="lacks columns"):
        FO.stream_archive(zp, 2015, lambda m: None)


def test_vehicle_key_null_without_parent():
    df = pd.DataFrame({"parent_award_id_piid": ["P1", None, ""],
                       "parent_award_agency_id": ["A", "A", "A"]})
    k = FO.vehicle_key(df)
    assert k.iloc[0] == "P1|A"
    assert pd.isna(k.iloc[1]) and pd.isna(k.iloc[2])


def _write_year(tmp_path, fy, rows):
    df = pd.DataFrame(rows)
    df = FO.coerce(df)
    df["vehicle"] = FO.vehicle_key(df)
    df["source_fiscal_year"] = fy
    (tmp_path / "parquet").mkdir(exist_ok=True)
    df.to_parquet(tmp_path / "parquet" / f"orders_C_FY{fy}.parquet", index=False)
    pd.DataFrame({"contract_award_unique_key": []}).to_parquet(
        tmp_path / "parquet" / f"kept_keys_FY{fy}.parquet", index=False)
    pd.DataFrame({"vehicle": [], "recipient_uei": [], "n_orders_all_sizes": [],
                  "n_orders_at_or_above_threshold": [], "first_base_date": [],
                  "fiscal_year": []}).to_parquet(
        tmp_path / "parquet" / f"vehicle_holders_all_sizes_FY{fy}.parquet", index=False)


def test_order_slip_labels_from_later_actions(tmp_path):
    rows15 = [
        _row("SLIP_1", "0", "2015-01-10", 300000.0, 300000.0, "2016-01-10"),
        _row("SLIP_1", "P00001", "2015-09-01", 0.0, 0.0, "2016-06-10"),    # +152 days by 12 months
        _row("FLAT_1", "0", "2015-01-10", 300000.0, 300000.0, "2016-01-10", recipient_uei="UEIB"),
    ]
    rows16 = [
        _row("SLIP_1", "P00002", "2016-06-01", 0.0, 0.0, "2017-03-10"),    # +425 days, after 12 months
        _row("FLAT_1", "P00001", "2016-03-01", 0.0, 0.0, "2016-01-10", recipient_uei="UEIB"),
        _row("LATE_1", "0", "2016-05-01", 400000.0, 400000.0, "2017-05-01"),
    ]
    _write_year(tmp_path, 2015, rows15)
    _write_year(tmp_path, 2016, rows16)
    # a far-future action so every label qualifies at 36 months
    _write_year(tmp_path, 2017, [_row("LATE_1", "P00001", "2020-01-01", 0.0, 0.0, "2017-05-01")])
    tx = OP.load_transactions(tmp_path / "parquet", lambda m: None)
    assert (tx["award_type_code"] == "C").all()
    data_end = tx["action_date"].max()
    panel, labels, base_funnel, steps = UP.build_panel(tx, data_end, lambda m: None)
    p = panel.set_index("contract_award_unique_key")
    assert p.loc["SLIP_1", "schedule_slip_days_12"] == 152
    assert p.loc["SLIP_1", "schedule_slip_gt90_12"] == 1.0
    assert p.loc["SLIP_1", "schedule_slip_gt365_12"] == 0.0
    assert p.loc["SLIP_1", "schedule_slip_days_24"] == 425
    assert p.loc["SLIP_1", "schedule_slip_gt365_24"] == 1.0
    assert p.loc["FLAT_1", "schedule_slip_days_36"] == 0
    assert p.loc["FLAT_1", "schedule_slip_gt90_36"] == 0.0
    assert p.loc["LATE_1", "qualifies_36"] == True  # noqa: E712
    assert p.loc["SLIP_1", "vehicle"] == "VEH1|9700"
    assert set(p.index) == {"SLIP_1", "FLAT_1", "LATE_1"}


def test_load_transactions_refuses_a_gap(tmp_path):
    _write_year(tmp_path, 2015, [_row("A_1", "0", "2015-01-10", 300000.0, 300000.0, "2016-01-10")])
    _write_year(tmp_path, 2017, [_row("B_1", "0", "2017-01-10", 300000.0, 300000.0, "2018-01-10")])
    with pytest.raises(ValueError, match="missing"):
        OP.load_transactions(tmp_path / "parquet", lambda m: None)
