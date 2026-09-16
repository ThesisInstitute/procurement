"""Header canonicalisation, layout detection and table reading on fixtures.

The fixture headers are the real published spellings, copied from
`data/raw/gmpp/header_summary.csv`, which `gmpp.src.profile_headers` builds from
the 542 downloaded files.
"""
from __future__ import annotations

import pandas as pd
import pytest

from gmpp.src.orientation import detect_layout, normalise, transpose_to_wide
from gmpp.src.profile_headers import norm_header
from gmpp.src.readers import read_raw
from gmpp.src.schema import CANONICAL_COLUMNS, KNOWN_NON_DATA_HEADERS, map_header


@pytest.mark.parametrize(
    "raw,expected",
    [
        # The forecast being scored, under all four published names.
        ("MPA RAG rating (A Delivery Confidence Assessment of the project at a "
         "fixed point in time, using a five-point scale, Red – Amber/Red – "
         "Amber – Amber/Green – Green; definitions in the MPA Annual "
         "Report)", "dca_ipa"),
        ("IPA RAG rating (A Delivery Confidence Assessment ...)", "dca_ipa"),
        ("IPA Delivery Confidence Assessment (A Delivery Confidence Assessment of "
         "the project at a fixed point in time, using a three-point scale, Red – "
         "Amber – Green)", "dca_ipa"),
        ("IPA Delivery Confidence Assessment", "dca_ipa"),
        ("SRO Delivery Confidence Assessment", "dca_sro"),
        # Identity.
        ("GMPP ID Number", "gmpp_id"),
        ("GMPP ID", "gmpp_id"),
        ("Major Projects ID", "gmpp_id"),
        ("ID Numbers", "gmpp_id"),
        ("Project Name", "project_name"),
        ("Project name", "project_name"),
        ("Department", "department"),
        ("Annual Report Category", "annual_report_category"),
        # Description.
        ("Description / Aims (From GMPP data)", "description"),
        ("Detailed Description / Aims", "description"),
        ("Project Description", "description"),
        # Schedule.
        ("Project - Start Date (Latest approved start date)", "start_date"),
        ("Start Date", "start_date"),
        ("Project - End Date (Latest Approved End Date)", "end_date"),
        ("End Date", "end_date"),
        ("Departmental narrative on schedule, including any deviation from planned "
         "schedule (if necessary)", "schedule_narrative"),
        ("Schedule Narrative", "schedule_narrative"),
        # Whole-life cost, under every published spelling across 2013 to 2026.
        ("Total budgeted whole life costs (£million) (including non-government "
         "costs)", "wlc_baseline_gbp_m"),
        ("Whole Life Cost TOTAL Baseline £m (including Non-Government costs)",
         "wlc_baseline_gbp_m"),
        ("TOTAL Baseline Whole Life Costs (£m) (including Non-Government Costs)",
         "wlc_baseline_gbp_m"),
        ("Whole Life Cost (£m, Presented in 2024/25 Real Prices)",
         "wlc_baseline_gbp_m"),
        ("Departmental narrative on budgeted whole life costs", "wlc_narrative"),
        ("Costs Narrative", "wlc_narrative"),
        # In-year finance.
        ("2012/13 Budget (£million)", "fy_baseline_gbp_m"),
        ("2015/16 Budget (£million)", "fy_baseline_gbp_m"),
        ("2018/19 TOTAL Baseline £m (including Non-Government costs)",
         "fy_baseline_gbp_m"),
        ("Financial Year Baseline (£m)", "fy_baseline_gbp_m"),
        ("2012/13 Forecast (£million)", "fy_forecast_gbp_m"),
        ("Financial Year Forecast (£m)", "fy_forecast_gbp_m"),
        # "%age" is the published spelling of "percentage"; the same year also
        # publishes the variance in GBP million, and the two must not collide.
        ("2014/2015 Variance %age", "fy_variance_pct"),
        ("Financial Year Variance (%)", "fy_variance_pct"),
        ("Variance Budget / Forecast %age", "fy_variance_pct"),
        ("2014/2015 Variance (£million)", "fy_variance_gbp_m"),
        # The budget narrative header names the financial year, so it changes
        # spelling every year and is matched by prefix.
        ("Departmental narrative on budget/forecast variance for 2012/13",
         "budget_narrative"),
        ("Departmental narrative on budget/forecast variance for 2023/24",
         "budget_narrative"),
        ("Departmental narrative on budget/forecast variance for 2015/16 (where "
         "more than 5%)", "budget_narrative"),
        ("In Year Variance Narrative", "budget_narrative"),
        # Benefits and people.
        ("TOTAL Baseline Benefits (£m)", "benefits_baseline_gbp_m"),
        ("Benefits (£m, Presented in 2024/25 Real Prices)",
         "benefits_baseline_gbp_m"),
        ("Departmental Narrative on Budgeted Benefits", "benefits_narrative"),
        ("Benefits Narrative", "benefits_narrative"),
        ("Senior Responsible Owner (SRO) Name", "sro_name"),
    ],
)
def test_published_header_maps_to_the_right_canonical_column(raw, expected):
    assert map_header(norm_header(raw)) == expected
    assert expected in CANONICAL_COLUMNS


@pytest.mark.parametrize(
    "raw",
    [
        "Cells to be exempted",
        "D10-D16",
        "E4, E6, E9-16",
        "e.g. B3",
    ],
)
def test_spreadsheet_working_notes_are_known_and_not_mapped(raw):
    key = norm_header(raw)
    assert map_header(key) is None
    assert key in KNOWN_NON_DATA_HEADERS


@pytest.mark.parametrize(
    "raw",
    [
        "Does the project have an evaluation plan? (self reported)",
        "Evaluation Plan and Registry Link",
    ],
)
def test_the_evaluation_commitment_field_is_data_not_a_working_note(raw):
    """Both NISTA files publish whether a project has an evaluation plan, on
    every row. It was on the non-data list and so was dropped from the panel,
    which threw away the first evaluation-commitment field the portfolio has
    ever published.
    """
    key = norm_header(raw)
    assert map_header(key) == "evaluation_plan"
    assert key not in KNOWN_NON_DATA_HEADERS


def test_bracketed_definitions_do_not_change_the_key():
    # The same field with two different embedded scale definitions must land on
    # one key, because the definition wording changed while the field did not.
    five = norm_header(
        "IPA Delivery Confidence Assessment (using a five-point scale, Red – "
        "Amber/Red – Amber – Amber/Green – Green)"
    )
    three = norm_header(
        "IPA Delivery Confidence Assessment (using a three-point scale, Red – "
        "Amber – Green)"
    )
    assert five == three == "ipa delivery confidence assessment"


def test_the_two_variance_spellings_do_not_collide():
    assert norm_header("2014/2015 Variance %age") != norm_header(
        "2014/2015 Variance (£million)"
    )


# --- layout ---------------------------------------------------------------

TRANSPOSED = pd.DataFrame(
    [
        ["Project Name", "A400M", "Astute Boats 1-7"],
        ["Department", "MOD", "MOD"],
        ["IPA Delivery Confidence Assessment", "Amber", "Amber/Red"],
        ["Project - Start Date", "01/04/2010", "01/04/2011"],
        ["Project - End Date", "31/03/2030", "31/03/2026"],
        ["Total budgeted whole life costs", "3817", "10827"],
    ]
)

WIDE = pd.DataFrame(
    [
        ["GMPP ID Number", "Project Name", "Department",
         "IPA Delivery Confidence Assessment"],
        ["MOD_0001_1112-Q1", "A400M", "MOD", "Amber"],
        ["MOD_0076_1213-Q1", "Astute Boats 1-7", "MOD", "Amber/Red"],
    ]
)


def test_detects_the_transposed_layout_used_from_2013_to_2020():
    assert detect_layout(TRANSPOSED) == "transposed"


def test_detects_the_wide_layout_used_from_2021():
    assert detect_layout(WIDE) == "wide"


def test_transposing_puts_one_project_on_each_row():
    wide = transpose_to_wide(TRANSPOSED)
    assert list(wide["Project Name"]) == ["A400M", "Astute Boats 1-7"]
    assert list(wide["Department"]) == ["MOD", "MOD"]
    assert list(wide["IPA Delivery Confidence Assessment"]) == ["Amber", "Amber/Red"]


def test_both_layouts_normalise_to_the_same_shape_of_answer():
    t, layout_t = normalise(TRANSPOSED)
    w, layout_w = normalise(WIDE)
    assert layout_t == "transposed" and layout_w == "wide"
    assert list(t["Project Name"]) == list(w["Project Name"])


def test_duplicate_header_cells_are_made_unique():
    frame = pd.DataFrame(
        [["Project Name", "Department", "Department"], ["A", "MOD", "MOD"]]
    )
    out, _ = normalise(frame)
    assert len(set(out.columns)) == len(out.columns)


def test_blank_header_cells_get_placeholder_names(tmp_path):
    path = tmp_path / "f.csv"
    path.write_text("Project Name,,Department\nA400M,x,MOD\n")
    out, _ = normalise(read_raw(path).raw)
    assert any(c.startswith("_unnamed_") for c in out.columns)


def test_reader_skips_preamble_rows_above_the_header(tmp_path):
    path = tmp_path / "f.csv"
    path.write_text(
        "Some departmental title row,,\n"
        ",,\n"
        "GMPP ID Number,Project Name,IPA Delivery Confidence Assessment\n"
        "MOD_0001_1112-Q1,A400M,Amber\n"
    )
    out, layout = normalise(read_raw(path).raw)
    assert layout == "wide"
    assert list(out["Project Name"]) == ["A400M"]


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1252"])
def test_reader_handles_both_published_encodings(tmp_path, encoding):
    path = tmp_path / "f.csv"
    path.write_bytes(
        "Project Name,Total budgeted whole life costs (£million)\nA400M,3817\n".encode(
            encoding
        )
    )
    out, _ = normalise(read_raw(path).raw)
    assert list(out["Project Name"]) == ["A400M"]
