"""Label construction on a synthetic fixture with hand-computed answers."""
import numpy as np
import pandas as pd
import pytest

import panel as P


def _tx(rows):
    """Build a transaction frame with the columns panel.py touches."""
    cols = {
        "contract_award_unique_key": [], "award_id_piid": [],
        "parent_award_id_piid": [], "modification_number": [],
        "transaction_number": [], "action_date": [], "action_type_code": [],
        "action_type": [], "award_type_code": [], "award_type": [],
        "federal_action_obligation": [], "total_dollars_obligated": [],
        "base_and_exercised_options_value": [], "current_total_value_of_award": [],
        "base_and_all_options_value": [], "potential_total_value_of_award": [],
        "period_of_performance_start_date": [],
        "period_of_performance_current_end_date": [],
        "period_of_performance_potential_end_date": [],
        "awarding_agency_code": [], "awarding_agency_name": [],
        "awarding_sub_agency_code": [], "awarding_office_code": [],
        "funding_agency_code": [], "recipient_uei": [], "recipient_duns": [],
        "recipient_name": [], "recipient_parent_uei": [],
        "contracting_officers_determination_of_business_size_code": [],
        "type_of_contract_pricing_code": [], "naics_code": [],
        "product_or_service_code": [], "extent_competed_code": [],
        "solicitation_procedures_code": [], "number_of_offers_received": [],
        "type_of_set_aside_code": [], "solicitation_identifier": [],
        "fed_biz_opps_code": [], "performance_based_service_acquisition_code": [],
        "multi_year_contract_code": [], "cost_or_pricing_data_code": [],
        "primary_place_of_performance_state_code": [],
        "prime_award_transaction_place_of_performance_state_fips_code": [],
        "last_modified_date": [], "source_fiscal_year": [],
    }
    df = pd.DataFrame(cols)
    recs = []
    for r in rows:
        rec = {k: None for k in cols}
        rec.update({
            "award_type_code": "D", "award_type": "DEFINITIVE CONTRACT",
            "transaction_number": "0", "awarding_agency_code": "097",
            "awarding_office_code": "OFF1", "recipient_uei": "UEI1",
            "naics_code": "541512", "product_or_service_code": "D302",
            "type_of_contract_pricing_code": "J", "extent_competed_code": "A",
            "source_fiscal_year": 2015,
        })
        rec.update(r)
        recs.append(rec)
    out = pd.concat([df, pd.DataFrame(recs)], ignore_index=True)
    for c in P.NUMERIC:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    for c in P.DATES:
        out[c] = pd.to_datetime(out[c], errors="coerce")
    out["mod_seq"] = P.mod_sequence(out["modification_number"])
    out["txn_seq"] = pd.to_numeric(out["transaction_number"],
                                   errors="coerce").fillna(0).astype("int64")
    out["is_base_mod"] = P.is_base_mod(out["modification_number"])
    return out.sort_values(
        ["contract_award_unique_key", "action_date", "mod_seq", "txn_seq"],
        kind="mergesort").reset_index(drop=True)


def _noop_log(msg):
    pass


# ---------------------------------------------------------------- primitives

def test_is_base_mod_accepts_zero_forms_and_rejects_real_mods():
    s = pd.Series(["0", "00", "0000", "P00000", "p00000", " 0 ",
                   "P00001", "1", "A1", "", None, "M001"])
    got = P.is_base_mod(s).tolist()
    assert got == [True, True, True, True, True, True,
                   False, False, False, False, False, False]


def test_mod_sequence_extracts_trailing_digits():
    s = pd.Series(["0", "P00001", "P00012", "MOD 7", "abc", None])
    assert P.mod_sequence(s).tolist() == [0, 1, 12, 7, -1, -1]


def test_fiscal_year_boundaries():
    d = pd.Series(pd.to_datetime(
        ["2009-09-30", "2009-10-01", "2010-09-30", "2010-10-01"]))
    assert P.fiscal_year(d).tolist() == [2009, 2010, 2010, 2011]


# ------------------------------------------------------------------- labels

def _award_with_growth_and_slip():
    """One award: base ceiling 1,000,000, end 2016-09-30.

    mods: +100,000 change order at 6 months (end pushed to 2016-12-31),
          +400,000 option exercise at 18 months (end pushed to 2018-06-30),
          +600,000 additional work at 30 months (end pushed to 2019-09-30).
    Potential total value is carried as the running ceiling on each action.
    """
    return _tx([
        dict(contract_award_unique_key="A1", modification_number="0",
             action_date="2015-01-15", action_type_code=None,
             federal_action_obligation=500_000,
             base_and_all_options_value=1_000_000,
             base_and_exercised_options_value=600_000,
             potential_total_value_of_award=1_000_000,
             current_total_value_of_award=500_000,
             period_of_performance_start_date="2015-02-01",
             period_of_performance_current_end_date="2016-09-30",
             period_of_performance_potential_end_date="2018-09-30"),
        dict(contract_award_unique_key="A1", modification_number="P00001",
             action_date="2015-07-15", action_type_code="D",
             federal_action_obligation=100_000,
             base_and_all_options_value=100_000,
             potential_total_value_of_award=1_100_000,
             current_total_value_of_award=600_000,
             period_of_performance_current_end_date="2016-12-31"),
        dict(contract_award_unique_key="A1", modification_number="P00002",
             action_date="2016-07-15", action_type_code="G",
             federal_action_obligation=400_000,
             base_and_all_options_value=400_000,
             potential_total_value_of_award=1_500_000,
             current_total_value_of_award=1_000_000,
             period_of_performance_current_end_date="2018-06-30"),
        dict(contract_award_unique_key="A1", modification_number="P00003",
             action_date="2017-07-15", action_type_code="A",
             federal_action_obligation=600_000,
             base_and_all_options_value=600_000,
             potential_total_value_of_award=2_100_000,
             current_total_value_of_award=1_600_000,
             period_of_performance_current_end_date="2019-09-30"),
    ])


def _labels(tx, data_end="2026-09-01"):
    """The labelled history-source frame: every well identified base award.

    This is the frame the in-scope filters are applied to, so it still holds
    awards that the panel will later drop. The label assertions below want that,
    because they check the arithmetic of a label, not whether the award is in
    scope.
    """
    _, labels, _, _ = P.build_panel(tx, pd.Timestamp(data_end), _noop_log)
    return labels


def _panel(tx, data_end="2026-09-01"):
    """The in-scope modelling panel, exactly as main() builds it."""
    panel, _, _, _ = P.build_panel(tx, pd.Timestamp(data_end), _noop_log)
    return panel


def _panel_and_steps(tx, data_end="2026-09-01"):
    panel, _, _, steps = P.build_panel(tx, pd.Timestamp(data_end), _noop_log)
    return panel, steps


def test_ceiling_growth_at_each_horizon():
    lab = _labels(_award_with_growth_and_slip()).set_index(
        "contract_award_unique_key")
    r = lab.loc["A1"]
    # H=12 -> cutoff 2016-01-15, last action is P00001, potential 1,100,000
    assert r["ceiling_growth_12"] == pytest.approx(0.10)
    # H=24 -> cutoff 2017-01-15, last action is P00002, potential 1,500,000
    assert r["ceiling_growth_24"] == pytest.approx(0.50)
    # H=36 -> cutoff 2018-01-15, last action is P00003, potential 2,100,000
    assert r["ceiling_growth_36"] == pytest.approx(1.10)


def test_ceiling_growth_binary_flags_use_strict_greater_than():
    lab = _labels(_award_with_growth_and_slip()).set_index(
        "contract_award_unique_key")
    r = lab.loc["A1"]
    # growth is exactly 0.10 at H=12, so the > 0.10 flag must be 0
    assert r["ceiling_growth_gt10_12"] == 0.0
    assert r["ceiling_growth_gt25_12"] == 0.0
    assert r["ceiling_growth_gt10_24"] == 1.0
    assert r["ceiling_growth_gt25_24"] == 1.0
    # growth is exactly 0.50 at H=24, so the > 0.50 flag must be 0
    assert r["ceiling_growth_gt50_24"] == 0.0
    assert r["ceiling_growth_gt50_36"] == 1.0


def test_schedule_slip_days_against_the_base_current_end_date():
    lab = _labels(_award_with_growth_and_slip()).set_index(
        "contract_award_unique_key")
    r = lab.loc["A1"]
    assert r["schedule_slip_days_12"] == (
        pd.Timestamp("2016-12-31") - pd.Timestamp("2016-09-30")).days == 92
    assert r["schedule_slip_gt90_12"] == 1.0
    assert r["schedule_slip_gt365_12"] == 0.0
    assert r["schedule_slip_days_24"] == (
        pd.Timestamp("2018-06-30") - pd.Timestamp("2016-09-30")).days
    assert r["schedule_slip_gt365_24"] == 1.0


def test_change_order_counts_only_codes_a_and_d():
    lab = _labels(_award_with_growth_and_slip()).set_index(
        "contract_award_unique_key")
    r = lab.loc["A1"]
    assert r["change_order_count_12"] == 1      # the D mod only
    assert r["change_order_count_24"] == 1      # G is an option, not a change order
    assert r["change_order_count_36"] == 2      # plus the A mod
    assert r["option_exercise_count_24"] == 1
    assert r["unplanned_growth_12"] == pytest.approx(0.10)
    assert r["unplanned_growth_24"] == pytest.approx(0.10)
    assert r["unplanned_growth_36"] == pytest.approx(0.70)


def test_termination_codes_and_default_only_variant():
    tx = _tx([
        dict(contract_award_unique_key="T1", modification_number="0",
             action_date="2015-01-15", federal_action_obligation=300_000,
             base_and_all_options_value=300_000,
             potential_total_value_of_award=300_000,
             period_of_performance_current_end_date="2016-01-15"),
        dict(contract_award_unique_key="T1", modification_number="P00001",
             action_date="2015-06-01", action_type_code="F",
             federal_action_obligation=-50_000,
             base_and_all_options_value=-50_000,
             potential_total_value_of_award=250_000,
             period_of_performance_current_end_date="2015-06-01"),
        dict(contract_award_unique_key="T2", modification_number="0",
             action_date="2015-01-15", federal_action_obligation=300_000,
             base_and_all_options_value=300_000,
             potential_total_value_of_award=300_000,
             period_of_performance_current_end_date="2016-01-15"),
        dict(contract_award_unique_key="T2", modification_number="P00001",
             action_date="2016-06-01", action_type_code="E",
             federal_action_obligation=0,
             base_and_all_options_value=0,
             potential_total_value_of_award=300_000,
             period_of_performance_current_end_date="2016-06-01"),
    ])
    lab = _labels(tx).set_index("contract_award_unique_key")
    assert lab.loc["T1", "terminated_12"] == 1
    assert lab.loc["T1", "terminated_default_12"] == 0   # F is convenience
    assert lab.loc["T2", "terminated_12"] == 0           # E lands after 12 months
    assert lab.loc["T2", "terminated_24"] == 1
    assert lab.loc["T2", "terminated_default_24"] == 1


def test_action_exactly_on_the_horizon_boundary_is_included():
    tx = _tx([
        dict(contract_award_unique_key="B1", modification_number="0",
             action_date="2015-01-15", federal_action_obligation=400_000,
             base_and_all_options_value=1_000_000,
             potential_total_value_of_award=1_000_000,
             period_of_performance_current_end_date="2016-01-15"),
        dict(contract_award_unique_key="B1", modification_number="P00001",
             action_date="2016-01-15", action_type_code="A",
             federal_action_obligation=500_000,
             base_and_all_options_value=500_000,
             potential_total_value_of_award=1_500_000,
             period_of_performance_current_end_date="2016-01-15"),
    ])
    lab = _labels(tx).set_index("contract_award_unique_key")
    assert lab.loc["B1", "ceiling_growth_12"] == pytest.approx(0.5)


def test_action_one_day_after_the_horizon_is_excluded():
    tx = _tx([
        dict(contract_award_unique_key="B2", modification_number="0",
             action_date="2015-01-15", federal_action_obligation=400_000,
             base_and_all_options_value=1_000_000,
             potential_total_value_of_award=1_000_000,
             period_of_performance_current_end_date="2016-01-15"),
        dict(contract_award_unique_key="B2", modification_number="P00001",
             action_date="2016-01-16", action_type_code="A",
             federal_action_obligation=500_000,
             base_and_all_options_value=500_000,
             potential_total_value_of_award=1_500_000,
             period_of_performance_current_end_date="2016-01-15"),
    ])
    lab = _labels(tx).set_index("contract_award_unique_key")
    assert lab.loc["B2", "ceiling_growth_12"] == pytest.approx(0.0)
    assert lab.loc["B2", "ceiling_growth_24"] == pytest.approx(0.5)


# ------------------------------------------------------------------- funnel

def test_population_filters_drop_small_awards_and_missing_end_dates():
    tx = _tx([
        dict(contract_award_unique_key="S1", modification_number="0",
             action_date="2015-01-15", federal_action_obligation=249_999,
             base_and_all_options_value=249_999,
             potential_total_value_of_award=249_999,
             period_of_performance_current_end_date="2016-01-15"),
        dict(contract_award_unique_key="S2", modification_number="0",
             action_date="2015-01-15", federal_action_obligation=250_000,
             base_and_all_options_value=250_000,
             potential_total_value_of_award=250_000,
             period_of_performance_current_end_date="2016-01-15"),
        dict(contract_award_unique_key="S3", modification_number="0",
             action_date="2015-01-15", federal_action_obligation=900_000,
             base_and_all_options_value=900_000,
             potential_total_value_of_award=900_000,
             period_of_performance_current_end_date=None),
        dict(contract_award_unique_key="S4", modification_number="0",
             action_date="2009-01-15", federal_action_obligation=900_000,
             base_and_all_options_value=900_000,
             potential_total_value_of_award=900_000,
             period_of_performance_current_end_date="2010-01-15"),
        dict(contract_award_unique_key="S5", modification_number="0",
             action_date="2023-01-15", federal_action_obligation=900_000,
             base_and_all_options_value=900_000,
             potential_total_value_of_award=900_000,
             period_of_performance_current_end_date="2024-01-15"),
    ])
    kept, steps = _panel_and_steps(tx)
    assert set(kept["contract_award_unique_key"]) == {"S2"}
    names = [s["filter"] for s in steps]
    assert names[0].startswith("start")
    assert all(steps[i]["awards_remaining"] >= steps[i + 1]["awards_remaining"]
               for i in range(len(steps) - 1))


def test_award_whose_mod_zero_is_not_the_first_action_is_excluded():
    tx = _tx([
        dict(contract_award_unique_key="X1", modification_number="P00001",
             action_date="2015-01-01", action_type_code="C",
             federal_action_obligation=900_000,
             base_and_all_options_value=900_000,
             potential_total_value_of_award=900_000,
             period_of_performance_current_end_date="2016-01-15"),
        dict(contract_award_unique_key="X1", modification_number="0",
             action_date="2015-06-01", federal_action_obligation=900_000,
             base_and_all_options_value=900_000,
             potential_total_value_of_award=900_000,
             period_of_performance_current_end_date="2016-01-15"),
    ])
    _, diag = P.pick_base_rows(tx, _noop_log)
    assert diag["awards_with_modification_zero_that_is_not_the_first_action"] == 1
    # and an award that simply has no modification zero is NOT counted here
    assert diag["awards_without_modification_number_zero"] == 0
    assert _panel(tx).empty


def test_award_without_any_mod_zero_is_counted_and_excluded():
    tx = _tx([
        dict(contract_award_unique_key="Y1", modification_number="P00004",
             action_date="2015-01-01", action_type_code="C",
             federal_action_obligation=900_000,
             base_and_all_options_value=900_000,
             potential_total_value_of_award=900_000,
             period_of_performance_current_end_date="2016-01-15"),
    ])
    _, diag = P.pick_base_rows(tx, _noop_log)
    assert diag["awards_without_modification_number_zero"] == 1
    assert _panel(tx).empty


def test_right_censoring_flags_horizons_beyond_the_data_end():
    tx = _award_with_growth_and_slip()
    lab = _labels(tx, data_end="2016-06-30").set_index("contract_award_unique_key")
    # base 2015-01-15; +12m = 2016-01-15 <= data end, +24m = 2017-01-15 > data end
    assert bool(lab.loc["A1", "qualifies_12"]) is True
    assert bool(lab.loc["A1", "qualifies_24"]) is False
    assert bool(lab.loc["A1", "qualifies_36"]) is False


def test_zero_or_missing_base_ceiling_yields_missing_growth():
    tx = _tx([
        dict(contract_award_unique_key="Z1", modification_number="0",
             action_date="2015-01-15", federal_action_obligation=900_000,
             base_and_all_options_value=0,
             potential_total_value_of_award=0,
             period_of_performance_current_end_date="2016-01-15"),
    ])
    lab = _labels(tx)
    assert bool(lab["base_ceiling_valid"].iloc[0]) is False
    # and the panel drops it, because ceiling growth is undefined for it
    assert _panel(tx).empty
    assert np.isnan(lab["ceiling_growth_12"].iloc[0])
    assert np.isnan(lab["ceiling_growth_gt25_12"].iloc[0])


def test_base_features_are_computed_from_the_base_row_only():
    tx = _award_with_growth_and_slip()
    lab = P.add_base_features(_labels(tx)).set_index("contract_award_unique_key")
    r = lab.loc["A1"]
    assert r["naics2"] == "54"
    assert r["psc1"] == "D"
    assert r["planned_duration_days"] == (
        pd.Timestamp("2016-09-30") - pd.Timestamp("2015-02-01")).days
    assert r["potential_extra_duration_days"] == (
        pd.Timestamp("2018-09-30") - pd.Timestamp("2016-09-30")).days
    # option heaviness uses the base row: 1,000,000 / 600,000
    assert r["option_heaviness"] == pytest.approx(1_000_000 / 600_000)
    assert r["log_base_ceiling"] == pytest.approx(6.0)


# ------------------------------------------------- the award-level value trap

def _award_with_pasted_end_state():
    """The shape actually seen in the feed.

    potential_total_value_of_award, current_total_value_of_award and
    total_dollars_obligated are award-level end-state values pasted onto every
    action, so every row carries the FINAL ceiling of 2,100,000 even the base
    action. Only base_and_all_options_value varies action to action.
    """
    final = 2_100_000
    return _tx([
        dict(contract_award_unique_key="L1", modification_number="0",
             action_date="2015-01-15", federal_action_obligation=500_000,
             base_and_all_options_value=1_000_000,
             base_and_exercised_options_value=600_000,
             potential_total_value_of_award=final,
             current_total_value_of_award=final,
             total_dollars_obligated=final,
             period_of_performance_start_date="2015-02-01",
             period_of_performance_current_end_date="2016-09-30"),
        dict(contract_award_unique_key="L1", modification_number="P00001",
             action_date="2015-07-15", action_type_code="D",
             federal_action_obligation=100_000,
             base_and_all_options_value=100_000,
             base_and_exercised_options_value=100_000,
             potential_total_value_of_award=final,
             current_total_value_of_award=final,
             total_dollars_obligated=final,
             period_of_performance_current_end_date="2016-12-31"),
        dict(contract_award_unique_key="L1", modification_number="P00002",
             action_date="2017-07-15", action_type_code="A",
             federal_action_obligation=1_000_000,
             base_and_all_options_value=1_000_000,
             base_and_exercised_options_value=1_000_000,
             potential_total_value_of_award=final,
             current_total_value_of_award=final,
             total_dollars_obligated=final,
             period_of_performance_current_end_date="2019-09-30"),
    ])


def test_ceiling_growth_ignores_the_pasted_award_level_end_state():
    """Regression test for the leak this backtest exists to avoid.

    Reading potential_total_value_of_award at a horizon would report 110 percent
    growth at 12 months, because the field already carries the award's final
    ceiling. The reconstruction from per-action deltas must report 10 percent,
    since only the 100,000 change order has happened by then.
    """
    lab = _labels(_award_with_pasted_end_state()).set_index(
        "contract_award_unique_key")
    r = lab.loc["L1"]
    assert r["ceiling_at_12"] == pytest.approx(1_100_000)
    assert r["ceiling_growth_12"] == pytest.approx(0.10)
    assert r["ceiling_growth_gt50_12"] == 0.0
    # the pasted value would have implied this, and must not
    leaked = 2_100_000 / 1_000_000 - 1
    assert r["ceiling_growth_12"] != pytest.approx(leaked)
    # by 36 months the second modification has landed and the two agree
    assert r["ceiling_at_36"] == pytest.approx(2_100_000)
    assert r["ceiling_growth_36"] == pytest.approx(leaked)


def test_award_level_value_is_kept_only_as_a_diagnostic():
    lab = _labels(_award_with_pasted_end_state()).set_index(
        "contract_award_unique_key")
    assert lab.loc["L1", "award_level_potential_total_value_diagnostic"] == \
        pytest.approx(2_100_000)


def test_reconstructed_exercised_value_uses_per_action_deltas():
    lab = _labels(_award_with_pasted_end_state()).set_index(
        "contract_award_unique_key")
    r = lab.loc["L1"]
    assert r["exercised_at_12"] == pytest.approx(700_000)
    assert r["exercised_at_36"] == pytest.approx(1_700_000)


def test_obligated_by_horizon_sums_the_action_obligations():
    lab = _labels(_award_with_pasted_end_state()).set_index(
        "contract_award_unique_key")
    assert lab.loc["L1", "obligated_by_12"] == pytest.approx(600_000)
    assert lab.loc["L1", "obligated_by_36"] == pytest.approx(1_600_000)


def test_negative_modifications_reduce_the_reconstructed_ceiling():
    tx = _tx([
        dict(contract_award_unique_key="N1", modification_number="0",
             action_date="2015-01-15", federal_action_obligation=900_000,
             base_and_all_options_value=1_000_000,
             base_and_exercised_options_value=1_000_000,
             period_of_performance_current_end_date="2016-01-15"),
        dict(contract_award_unique_key="N1", modification_number="P00001",
             action_date="2015-06-01", action_type_code="F",
             federal_action_obligation=-400_000,
             base_and_all_options_value=-400_000,
             base_and_exercised_options_value=-400_000,
             period_of_performance_current_end_date="2015-06-01"),
    ])
    lab = _labels(tx).set_index("contract_award_unique_key")
    assert lab.loc["N1", "ceiling_at_12"] == pytest.approx(600_000)
    assert lab.loc["N1", "ceiling_growth_12"] == pytest.approx(-0.4)
    assert lab.loc["N1", "schedule_slip_days_12"] < 0


def test_award_with_two_base_actions_is_excluded():
    tx = _tx([
        dict(contract_award_unique_key="M1", modification_number="0",
             transaction_number="0", action_date="2015-01-15",
             federal_action_obligation=900_000,
             base_and_all_options_value=900_000,
             period_of_performance_current_end_date="2016-01-15"),
        dict(contract_award_unique_key="M1", modification_number="0",
             transaction_number="1", action_date="2015-01-15",
             federal_action_obligation=500_000,
             base_and_all_options_value=500_000,
             period_of_performance_current_end_date="2016-01-15"),
    ])
    _, diag = P.pick_base_rows(tx, _noop_log)
    assert diag["awards_with_more_than_one_base_action"] == 1
    assert _panel(tx).empty


def test_history_growth_input_is_capped_but_the_label_is_not():
    import pandas as _pd
    rows = _pd.DataFrame([
        dict(action_date="2010-01-01", recipient_uei="U",
             awarding_office_code="O", ceiling_growth_36=10_000.0,
             terminated_36=0, schedule_slip_gt90_36=0.0),
        dict(action_date="2015-01-01", recipient_uei="U",
             awarding_office_code="O", ceiling_growth_36=0.0,
             terminated_36=0, schedule_slip_gt90_36=0.0),
    ])
    rows["action_date"] = _pd.to_datetime(rows["action_date"])
    out = P.add_history_features(rows).set_index("action_date")
    got = out.loc[pd.Timestamp("2015-01-01"),
                  "recipient_prior_mean_ceiling_growth_36"]
    assert got == pytest.approx(P.HISTORY_GROWTH_CAP)
    assert out["ceiling_growth_36"].max() == 10_000.0


# ------------------------------------------------ extract coverage guard

def test_check_year_coverage_finds_a_hole(tmp_path):
    """A missing fiscal year silently corrupts every label whose horizon crosses it."""
    for fy in (2010, 2011, 2013):
        (tmp_path / f"contracts_D_FY{fy}.parquet").write_bytes(b"")
    assert P.check_year_coverage(tmp_path) == [2012]
    assert P.fiscal_years_present(tmp_path) == [2010, 2011, 2013]


def test_check_year_coverage_is_clean_on_a_contiguous_run(tmp_path):
    for fy in range(2010, 2027):
        (tmp_path / f"contracts_D_FY{fy}.parquet").write_bytes(b"")
    assert P.check_year_coverage(tmp_path) == []


def test_load_transactions_refuses_an_extract_with_a_missing_year(tmp_path):
    tx = _tx([dict(contract_award_unique_key="A1", modification_number="0",
                   action_date="2015-01-15", federal_action_obligation=900_000,
                   base_and_all_options_value=900_000,
                   period_of_performance_current_end_date="2016-01-15")])
    for fy in (2010, 2012):
        tx.drop(columns=["mod_seq", "txn_seq", "is_base_mod"]).to_parquet(
            tmp_path / f"contracts_D_FY{fy}.parquet", index=False)
    with pytest.raises(ValueError, match=r"\[2011\]"):
        P.load_transactions(tmp_path, _noop_log)
    # the override exists, and says so loudly, but it does not raise
    got = P.load_transactions(tmp_path, _noop_log, allow_year_gaps=True)
    assert len(got) == 2


# ------------------------------------------ aggregate placeholder recipients

def test_aggregate_recipient_rule_matches_the_placeholders_and_not_real_firms():
    names = pd.Series([
        "MISCELLANEOUS FOREIGN AWARDEES",
        "FOREIGN AWARDEES (UNDISCLOSED)",
        "DOMESTIC AWARDEES (UNDISCLOSED)",
        "MULTIPLE RECIPIENTS",
        "REDACTED DUE TO PII",
        "HIGH DESERT AGGREGATE & PAVING, INC.",   # a real firm
        "EASTMAN AGGREGATE ENTERPRISES LLC",      # a real firm
        "RAYTHEON COMPANY",
        None,
    ])
    assert P.is_aggregate_recipient(names).tolist() == [
        True, True, True, True, True, False, False, False, False]


def test_aggregate_recipients_neither_accumulate_nor_receive_a_history():
    """A placeholder recipient must not become a contractor with a track record."""
    rows = pd.DataFrame({
        "action_date": pd.to_datetime(
            ["2010-01-01", "2011-01-01", "2015-01-01", "2015-06-01"]),
        "recipient_uei": ["AGG", "AGG", "AGG", "REAL"],
        "recipient_name": ["FOREIGN AWARDEES (UNDISCLOSED)"] * 3 + ["REAL CORP"],
        "awarding_office_code": ["O", "O", "O", "O"],
        "ceiling_growth_36": [5.0, 5.0, 5.0, 0.0],
        "terminated_36": [1, 1, 1, 0],
        "schedule_slip_gt90_36": [1.0, 1.0, 1.0, 0.0],
    })
    out = P.add_history_features(rows).set_index("recipient_uei")
    agg = out.loc["AGG"]
    assert agg["recipient_is_aggregate"].tolist() == [1, 1, 1]
    # null, not zero: the record does not say who the contractor is
    assert agg["recipient_prior_award_count"].isna().all()
    assert agg["recipient_prior_termination_rate_36"].isna().all()
    # the real firm has no prior award of its own, and must not inherit theirs
    real = out.loc["REAL"]
    assert real["recipient_prior_award_count"] == 0
    assert np.isnan(real["recipient_prior_termination_rate_36"])
    # the office history is a separate key and DOES see all four awards
    assert real["office_prior_award_count"] == 3
    assert real["office_prior_termination_rate_36"] == pytest.approx(1.0)


def test_a_missing_grouping_key_gets_a_null_history_not_a_pooled_one():
    rows = pd.DataFrame({
        "action_date": pd.to_datetime(["2010-01-01", "2011-01-01", "2015-01-01"]),
        "recipient_uei": [None, None, None],
        "recipient_name": ["FIRM ONE", "FIRM TWO", "FIRM THREE"],
        "awarding_office_code": ["O", "O", "O"],
        "ceiling_growth_36": [5.0, 5.0, 0.0],
        "terminated_36": [1, 1, 0],
        "schedule_slip_gt90_36": [1.0, 1.0, 0.0],
    })
    out = P.add_history_features(rows)
    assert out["recipient_prior_award_count"].isna().all()
    assert out["recipient_prior_mean_ceiling_growth_36"].isna().all()


def test_history_counts_prior_awards_of_any_size():
    """The history source is not filtered to the in-scope panel.

    A contractor's second contract is its second contract even when the first
    was below the simplified acquisition threshold, so a small prior award still
    counts. This is what building history before the scope filters buys.
    """
    tx = _tx([
        dict(contract_award_unique_key="SMALL", modification_number="0",
             action_date="2013-01-01", federal_action_obligation=10_000,
             base_and_all_options_value=10_000, recipient_uei="U9",
             period_of_performance_current_end_date="2014-01-01"),
        dict(contract_award_unique_key="BIG", modification_number="0",
             action_date="2018-01-01", federal_action_obligation=900_000,
             base_and_all_options_value=900_000, recipient_uei="U9",
             period_of_performance_current_end_date="2019-01-01"),
    ])
    panel, labels, _, _ = P.build_panel(tx, pd.Timestamp("2026-09-01"), _noop_log)
    # only the large award is in scope
    assert set(panel["contract_award_unique_key"]) == {"BIG"}
    # but it knows the contractor had an earlier, smaller contract
    assert panel.set_index("contract_award_unique_key").loc[
        "BIG", "recipient_prior_award_count"] == 1
    assert len(labels) == 2
