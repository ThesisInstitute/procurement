"""Linking project-years into projects across snapshots."""
from __future__ import annotations

import pandas as pd
import pytest

from gmpp.src.identity import (
    assign_project_keys,
    instalment_numbers,
    normalise_name,
    similarity,
)


def _rows(*specs) -> pd.DataFrame:
    """Fixture rows. A spec is (name, gmpp_id, department, snapshot) and may
    carry two more fields, (start_date, whole_life_cost), which only the
    rename-detection pass reads.
    """
    out = []
    for spec in specs:
        name, gmpp_id, dept, snapshot = spec[:4]
        start, wlc = (spec[4], spec[5]) if len(spec) > 5 else (None, None)
        out.append(
            {
                "project_name": name,
                "gmpp_id": gmpp_id,
                "department_norm": dept,
                "snapshot_date": pd.Timestamp(snapshot),
                "start_date": pd.Timestamp(start) if start else pd.NaT,
                "wlc_baseline_gbp_m": wlc,
            }
        )
    return pd.DataFrame(out)


def test_normalise_name_strips_brackets_case_and_punctuation():
    assert normalise_name("Type 26 Global Combat Ship (T26 GCS)") == (
        "type 26 global combat ship"
    )
    assert normalise_name("NHS.UK") == normalise_name("NHS UK")
    assert normalise_name("Health & Social Care Network") == (
        "health and social care network"
    )


@pytest.mark.parametrize(
    "name,expected",
    [
        ("PFI Prison Expiry and Transfer Tranche 3", {3}),
        ("Prison Competitions Phase Two", {2}),
        ("Prison Competitions Phase 2", {2}),
        ("Priority School Building Programme 2", {2}),
        ("Priority School Building Programme (PSBP)", set()),
        # 26 is a ship class, not an instalment, and is above the cut-off.
        ("Type 26 Global Combat Ship Programme", set()),
        # A financial year at the start of a name is not an instalment.
        ("16/17 New Property Model Programme", set()),
        ("100,000 Genomes Project", set()),
    ],
)
def test_instalment_numbers(name, expected):
    assert set(instalment_numbers(name)) == expected


def test_a_shared_gmpp_id_links_rows_whatever_the_name():
    frame = _rows(
        ("PHE Science Hub", "DH_0017_1112-Q1", "DH/DHSC", "2016-09-30"),
        ("UK Health Security Campus", "DH_0017_1112-Q1", "DH/DHSC", "2023-03-31"),
    )
    out, _, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 1
    assert out["project_key_source"].iloc[0] == "gmpp_id"


def test_an_exact_name_match_links_the_id_free_years_onto_the_id():
    frame = _rows(
        ("Lightning Programme", None, "MOD", "2017-09-30"),
        ("Lightning Programme", None, "MOD", "2018-09-30"),
        ("Lightning Programme", "MOD_0079_1213-Q1", "MOD", "2019-09-30"),
    )
    out, _, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 1
    assert set(out["project_key"]) == {"MOD_0079_1213-Q1"}


def test_the_numeric_core_of_an_id_alone_does_not_link():
    # BEIS_0004 is two different projects under two joining quarters.
    frame = _rows(
        ("Future Shared Services Programme", "BEIS_0004_1920-Q2", "BEIS/DBT", "2021-03-31"),
        ("Industrial Decarbonisation", "BEIS_0004_2122-Q2", "BEIS/DBT", "2023-03-31"),
    )
    out, _, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2


def test_different_instalments_of_a_series_are_never_merged():
    frame = _rows(
        ("PFI Prison Expiry and Transfer Tranche 1", None, "MOJ", "2023-03-31"),
        ("PFI Prison Expiry and Transfer Tranche 3", None, "MOJ", "2025-03-31"),
    )
    out, merges, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2
    assert merges.empty


def test_the_same_instalment_written_two_ways_is_merged():
    frame = _rows(
        ("Prison Competitions Phase Two", None, "MOJ", "2012-09-30"),
        ("Prison Competitions Phase 2", None, "MOJ", "2013-09-30"),
    )
    out, merges, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 1
    assert len(merges) == 1


def test_two_projects_present_in_the_same_snapshot_are_never_merged():
    # Both appear in September 2012, so however similar the names they are two
    # projects, not one project observed twice.
    frame = _rows(
        ("Crossrail Programme", None, "DFT", "2012-09-30"),
        ("Crossrail", None, "DFT", "2012-09-30"),
    )
    out, merges, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2
    assert merges.empty


def test_projects_in_different_departments_are_never_merged():
    frame = _rows(
        ("Smart Metering Implementation Programme", None, "BEIS/DBT", "2016-09-30"),
        ("Smart Meters Implementation Programme", None, "DFT", "2017-09-30"),
    )
    out, _, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2


def test_a_near_miss_below_the_threshold_is_not_merged():
    frame = _rows(
        ("Digital Identity", None, "CO", "2022-03-31"),
        ("Government Office Hubs Programme", None, "CO", "2023-03-31"),
    )
    out, merges, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2
    assert merges.empty


def test_an_explicitly_blocked_pair_stays_apart():
    frame = _rows(
        ("New Nuclear Programme", None, "DECC/DESNZ", "2012-09-30"),
        ("New Nuclear Project (Sizewell C)", None, "DECC/DESNZ", "2025-03-31"),
    )
    out, merges, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2
    assert merges.empty


def test_name_only_keys_are_prefixed_by_department():
    frame = _rows(("Some Project", None, "MOD", "2012-09-30"))
    out, _, _, _ = assign_project_keys(frame)
    assert out["project_key"].iloc[0].startswith("MOD::")
    assert out["project_key_source"].iloc[0] == "name"


def test_similarity_is_symmetric_and_bounded():
    a, b = "Crossrail Programme", "Crossrail"
    assert similarity(a, b) == similarity(b, a)
    assert 0.0 <= similarity(a, b) <= 1.0
    assert similarity("", "anything") == 0.0


@pytest.mark.parametrize(
    "a,b,same",
    [
        # A digit glued to the word and the same digit spaced off it name the
        # same instalment.
        ("NHSmail2", "NHSmail 2", True),
        ("PSBP1", "PSBP 1", True),
        ("NHSmail2", "NHSmail 3", False),
    ],
)
def test_a_glued_digit_reads_as_the_same_instalment(a, b, same):
    assert (instalment_numbers(a) == instalment_numbers(b)) is same


def test_nhsmail_two_spellings_link():
    frame = _rows(
        ("NHSmail2", None, "DH/DHSC", "2014-09-30"),
        ("NHSmail 2", None, "DH/DHSC", "2015-09-30"),
    )
    out, merges, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 1
    assert len(merges) == 1


def test_two_projects_whose_bracketed_qualifiers_differ_are_not_merged_by_name():
    """The real DH case: "BT LSP (London)" and "BT LSP (South)" normalise to the
    same string, and both are published in the same snapshot. Merging them would
    delete a project and invent a cost jump on the survivor, so the whole name
    group is left unmerged and reported.
    """
    frame = _rows(
        ("BT LSP (London)", None, "DH/DHSC", "2014-09-30"),
        ("BT LSP (South)", None, "DH/DHSC", "2014-09-30"),
    )
    out, _, collisions, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2
    assert len(collisions) == 1
    assert collisions["name_norm"].iloc[0] == "bt lsp"
    assert collisions["n_rows"].iloc[0] == 2


def test_a_name_group_with_no_within_snapshot_conflict_still_merges():
    """The guard must fire only on a genuine within-snapshot conflict, not on an
    ordinary repeated name across snapshots.
    """
    frame = _rows(
        ("BT LSP (London)", None, "DH/DHSC", "2014-09-30"),
        ("BT LSP (London)", None, "DH/DHSC", "2015-09-30"),
    )
    out, _, collisions, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 1
    assert collisions.empty


def test_an_id_bearing_row_rescues_a_colliding_name_group():
    """Two rows that collide on the normalised name inside one snapshot stay
    apart, and a later row carrying one of their ids still joins that one rather
    than being blocked along with the group.
    """
    frame = _rows(
        ("BT LSP (London)", "DH_0001_1112-Q1", "DH/DHSC", "2014-09-30"),
        ("BT LSP (South)", "DH_0002_1112-Q1", "DH/DHSC", "2014-09-30"),
        ("BT LSP London", "DH_0001_1112-Q1", "DH/DHSC", "2015-09-30"),
    )
    out, _, collisions, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2
    assert out["project_key"].tolist() == [
        "DH_0001_1112-Q1",
        "DH_0002_1112-Q1",
        "DH_0001_1112-Q1",
    ]
    assert len(collisions) == 1


def test_the_same_project_published_twice_in_one_snapshot_is_merged_not_flagged():
    """Defra has two gov.uk pages both carrying the September 2014 position, so
    every Defra project of that year appears twice with an identical raw name.
    That is one project published twice, and must not trip the collision guard.
    """
    frame = _rows(
        ("CAP Delivery Programme", None, "DEFRA", "2014-09-30"),
        ("CAP Delivery Programme", None, "DEFRA", "2014-09-30"),
        ("CAP Delivery Programme", None, "DEFRA", "2015-09-30"),
    )
    out, _, collisions, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 1
    assert collisions.empty


def test_the_fuzzy_pass_cannot_undo_the_collision_guard():
    """The September 2015 DH file publishes a single consolidated "BT LSP" row.
    It matches both September 2014 rows at similarity 1.0 and sits in a
    different snapshot, so nothing but the guard stops the fuzzy pass merging it
    into one of them and inventing a cost rise.
    """
    frame = _rows(
        ("BT LSP (London)", None, "DH/DHSC", "2014-09-30"),
        ("BT LSP (South)", None, "DH/DHSC", "2014-09-30"),
        ("BT LSP", None, "DH/DHSC", "2015-09-30"),
    )
    out, merges, collisions, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 3
    assert merges.empty
    assert len(collisions) == 1


def test_an_outright_rename_links_on_the_start_date_and_the_whole_life_cost():
    """MOD's "Successor SSBN" is published as "DREADNOUGHT" from the next
    snapshot. The names score 0.08, far below any safe threshold, so without
    this pass the old name reads as a permanent exit and the new one as a new
    project. The approved start date and the whole-life cost identify it.
    """
    frame = _rows(
        ("Successor SSBN", None, "MOD", "2015-09-30", "2011-04-14", 31614.29),
        ("DREADNOUGHT", None, "MOD", "2016-09-30", "2011-04-14", 31497.93),
    )
    out, _, _, renames = assign_project_keys(frame)
    assert out["project_key"].nunique() == 1
    assert len(renames) == 1
    assert renames["name_before"].iloc[0] == "Successor SSBN"
    assert renames["name_after"].iloc[0] == "DREADNOUGHT"


def test_a_rename_needs_the_start_dates_to_agree():
    frame = _rows(
        ("Successor SSBN", None, "MOD", "2015-09-30", "2011-04-14", 31614.29),
        ("DREADNOUGHT", None, "MOD", "2016-09-30", "2012-01-01", 31497.93),
    )
    out, _, _, renames = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2
    assert renames.empty


def test_a_rename_needs_the_whole_life_cost_to_agree_within_two_per_cent():
    frame = _rows(
        ("Successor SSBN", None, "MOD", "2015-09-30", "2011-04-14", 31614.29),
        ("DREADNOUGHT", None, "MOD", "2016-09-30", "2011-04-14", 45000.00),
    )
    out, _, _, renames = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2
    assert renames.empty


def test_a_rename_needs_the_snapshots_to_be_adjacent():
    """A project absent for a whole snapshot and then reappearing is not the
    rename this pass is for, and linking it would erase a real gap.
    """
    frame = _rows(
        ("Successor SSBN", None, "MOD", "2014-09-30", "2011-04-14", 31614.29),
        ("DREADNOUGHT", None, "MOD", "2016-09-30", "2011-04-14", 31497.93),
    )
    out, _, _, renames = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2
    assert renames.empty


def test_a_rename_never_crosses_a_department():
    frame = _rows(
        ("Successor SSBN", None, "MOD", "2015-09-30", "2011-04-14", 31614.29),
        ("DREADNOUGHT", None, "HO", "2016-09-30", "2011-04-14", 31497.93),
    )
    out, _, _, renames = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2
    assert renames.empty


def test_the_gmpp_id_prefix_is_not_part_of_the_project_identity():
    """The same health project is published as DH_0031_1314-Q1 and then
    DOH_0031_1314-Q1. The numeric core and the joining quarter are the identity.
    """
    frame = _rows(
        ("National Proton Beam Therapy", "DH_0031_1314-Q1", "DH/DHSC", "2016-09-30"),
        ("National Proton Beam Therapy", "DOH_0031_1314-Q1", "DH/DHSC", "2019-09-30"),
    )
    out, _, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 1


def test_the_same_id_core_in_different_departments_is_not_one_project():
    """0001_1112-Q1 is A400M at MOD, Crossrail at DfT and St Helena Airport at
    DFID. The core alone is not an identity across government.
    """
    frame = _rows(
        ("A400M", "MOD_0001_1112-Q1", "MOD", "2016-09-30"),
        ("Crossrail Programme", "DFT_0001_1112-Q1", "DFT", "2016-09-30"),
        ("St Helena Airport", "DFID_0001_1112-Q1", "FCO/FCDO", "2016-09-30"),
    )
    out, _, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 3


def test_decc_and_beis_link_across_the_2016_machinery_of_government_move():
    """DECC was abolished in 2016 and its projects moved to BEIS. The panel
    reports the two apart, so the linker has to be told they are one lineage.
    """
    frame = _rows(
        ("Urenco Future Options", None, "DECC/DESNZ", "2015-09-30"),
        ("Urenco Future Options", None, "BEIS/DBT", "2016-09-30"),
    )
    out, _, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 1


def test_two_unrelated_departments_still_do_not_link_by_name():
    frame = _rows(
        ("Shared Services", None, "MOD", "2015-09-30"),
        ("Shared Services", None, "HO", "2016-09-30"),
    )
    out, _, _, _ = assign_project_keys(frame)
    assert out["project_key"].nunique() == 2
