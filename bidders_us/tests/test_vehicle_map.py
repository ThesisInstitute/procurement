"""Sibling-contract grouping from IDV records, on a fixture."""
import pandas as pd

from bidders_us.src import vehicle_map as VM


def _tx():
    rows = [
        # program X: two sibling contracts from one solicitation, two holders
        ("CONT_IDV_A100_4732", "A100", "2014-01-01", "M", "B", "UEI1", "GS-00Q-14-OAD-U-1"),
        ("CONT_IDV_A100_4732", "A100", "2015-01-01", "M", "B", "UEI1", None),
        ("CONT_IDV_A101_4732", "A101", "2014-01-01", "M", "B", "UEI2", "gs00q14oadu1"),
        # single-award IDV with the same solicitation string: not grouped
        ("CONT_IDV_S1_4732", "S1", "2014-01-01", "S", "B", "UEI3", "GS00Q14OADU1"),
        # multiple-award but placeholder solicitation: own key
        ("CONT_IDV_P1_9700", "P1", "2014-01-01", "M", "B", "UEI4", "NONE"),
        # multiple-award, usable solicitation, but alone in its program: own key
        ("CONT_IDV_L1_9700", "L1", "2014-01-01", "M", "B", "UEI5", "W91ZLK14R0001"),
        # PIID containing underscores: agency id still parsed from the tail
        ("CONT_IDV_AB_CD_3600", "AB_CD", "2014-01-01", "S", "C", "UEI6", None),
    ]
    return pd.DataFrame(rows, columns=["contract_award_unique_key", "award_id_piid", "action_date",
                                       "multiple_or_single_award_idv_code", "idv_type_code",
                                       "recipient_uei", "solicitation_identifier"]).assign(
        recipient_name="x", awarding_agency_code="047", awarding_sub_agency_code="4732",
        action_date=lambda d: pd.to_datetime(d["action_date"]))


def test_programs_group_siblings_and_leave_others_alone():
    t = VM.assign_programs(VM.build_idv_table(_tx())).set_index("idv_key")
    assert t.loc["A100|4732", "program_key"] == t.loc["A101|4732", "program_key"] == "SOL|4732|GS00Q14OADU1"
    assert t.loc["A100|4732", "n_siblings"] == 2 and t.loc["A100|4732", "n_sibling_recipients"] == 2
    assert bool(t.loc["A100|4732", "in_sibling_set"]) is True
    assert t.loc["S1|4732", "program_key"] == "S1|4732"
    assert t.loc["P1|9700", "program_key"] == "P1|9700"
    assert t.loc["L1|9700", "program_key"] == "L1|9700"
    assert bool(t.loc["L1|9700", "in_sibling_set"]) is False
    assert "AB_CD|3600" in t.index


def test_solicitation_taken_from_first_non_null_action():
    t = VM.build_idv_table(_tx()).set_index("idv_key")
    assert t.loc["A100|4732", "solicitation"] == "GS00Q14OADU1"
    assert t.loc["A100|4732", "n_actions"] == 2


def test_map_orders_falls_back_to_parent_key():
    t = VM.assign_programs(VM.build_idv_table(_tx()))
    orders = pd.Series(["A100|4732", "A101|4732", "S1|4732", "ZZZ|1111", None], dtype="string")
    mapped, diag = VM.map_orders(orders, t)
    assert mapped.tolist()[:3] == ["SOL|4732|GS00Q14OADU1", "SOL|4732|GS00Q14OADU1", "S1|4732"]
    assert mapped.iloc[3] == "ZZZ|1111"
    assert pd.isna(mapped.iloc[4])
    assert diag == {"orders": 5, "orders_with_parent": 4, "orders_parent_matched_to_idv_record": 3,
                    "orders_in_sibling_set": 2}


def test_solicitation_shape_rule():
    s = pd.Series(["GS00Q14OADU1", "NONE", "ABCDEFGH", "12345678", "A1B2C3D", None], dtype="string")
    assert VM.solicitation_usable(s).tolist() == [True, False, False, False, False, False]
