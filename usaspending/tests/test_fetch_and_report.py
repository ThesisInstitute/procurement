"""Acquisition integrity and the report-side tables computed from the panel."""
import json

import pandas as pd
import pytest

import bulk_fetch as BF
import columns as C
import report as R
import schema_check as SC


# ------------------------------------------------------------- fiscal windows

def test_fy_window_runs_october_to_september():
    assert BF.fy_window(2018) == ("2017-10-01", "2018-09-30")
    assert BF.fy_window(2010) == ("2009-10-01", "2010-09-30")


@pytest.mark.parametrize("fy", list(range(2010, 2027)))
@pytest.mark.parametrize("splits", [1, 2, 3, 4, 5, 6, 12])
def test_fy_windows_tile_the_year_with_no_gap_and_no_overlap(fy, splits):
    """A one-day gap here would silently drop a day of contract actions.

    Includes leap years (FY2012, FY2016, FY2020, FY2024 each contain a 29
    February) and split counts that do not divide the year evenly.
    """
    windows = BF.fy_windows(fy, splits)
    assert len(windows) == splits
    start, end = BF.fy_window(fy)
    assert windows[0][0] == start
    assert windows[-1][1] == end

    covered = 0
    prev_end = None
    for a, b in windows:
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        assert a <= b, f"empty window {a}..{b}"
        if prev_end is not None:
            assert a == prev_end + pd.Timedelta(days=1), (
                f"gap or overlap between {prev_end} and {a}")
        covered += (b - a).days + 1
        prev_end = b
    expected_days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    assert covered == expected_days


def test_fy_windows_with_one_split_is_the_whole_year():
    assert BF.fy_windows(2018, 1) == [("2017-10-01", "2018-09-30")]
    assert BF.fy_windows(2018, 0) == [("2017-10-01", "2018-09-30")]


# --------------------------------------------------------- manifest reuse path

def _tiny_extract(tmp_path, rows=None):
    rows = rows or [
        {"contract_award_unique_key": "K1", "award_type_code": "D"},
        {"contract_award_unique_key": "K1", "award_type_code": "D"},
        {"contract_award_unique_key": "K2", "award_type_code": "D"},
        {"contract_award_unique_key": "K3", "award_type_code": "C"},
    ]
    p = tmp_path / "contracts_D_FY2019.parquet"
    pd.DataFrame(rows).to_parquet(p, index=False)
    return p


def test_describe_existing_counts_type_d_rows_and_distinct_awards(tmp_path):
    p = _tiny_extract(tmp_path)
    info = BF.describe_existing(2019, p)
    assert info["fiscal_year"] == 2019
    assert info["reused_existing_parquet"] is True
    assert info["rows_type_D"] == 3        # the C row is not counted
    assert info["unique_awards"] == 3      # K1, K2, K3 are the distinct keys
    assert info["parquet_bytes"] == p.stat().st_size


# --------------------------------------------------------------- schema check

def test_schema_check_reports_a_column_the_feed_did_not_deliver(tmp_path):
    """A column requested but absent must be named, not silently tolerated."""
    kept = [c for c in C.KEEP if c != "solicitation_identifier"]
    df = pd.DataFrame({c: pd.Series(["x"], dtype="string") for c in kept})
    df["extra_column_we_did_not_ask_for"] = pd.Series(["y"], dtype="string")
    df.to_parquet(tmp_path / "contracts_D_FY2019.parquet", index=False)

    info = SC.check(tmp_path)
    assert info["columns_requested"] == len(C.KEEP)
    assert info["columns_absent_from_some_year"] == ["solicitation_identifier"]
    year = info["per_year"]["2019"]
    assert year["requested_columns_absent"] == ["solicitation_identifier"]
    assert year["extra_columns_not_requested"] == ["extra_column_we_did_not_ask_for"]


def test_schema_check_is_clean_when_every_requested_column_is_present(tmp_path):
    df = pd.DataFrame({c: pd.Series(["x"], dtype="string") for c in C.KEEP})
    df.to_parquet(tmp_path / "contracts_D_FY2020.parquet", index=False)
    info = SC.check(tmp_path)
    assert info["columns_absent_from_some_year"] == []
    assert len(info["columns_present_in_every_year"]) == len(C.KEEP)


def test_schema_check_raises_when_there_is_nothing_to_check(tmp_path):
    with pytest.raises(FileNotFoundError):
        SC.check(tmp_path)


# ------------------------------------------------------------ censoring table

def test_censoring_table_counts_qualifying_awards_per_year_and_horizon(tmp_path):
    """Three FY2011 awards and two FY2012 awards, with hand-set qualify flags."""
    panel = pd.DataFrame({
        "base_fy": [2011, 2011, 2011, 2012, 2012],
        "action_date": pd.to_datetime(["2010-10-01", "2011-03-01", "2011-09-30",
                                       "2011-10-01", "2012-09-30"]),
        "qualifies_12": [True, True, True, True, True],
        "qualifies_24": [True, True, True, True, False],
        "qualifies_36": [True, True, False, False, False],
    })
    p = tmp_path / "panel.parquet"
    panel.to_parquet(p, index=False)

    out = R.censoring_table(p).set_index("base_fy")
    assert out.loc[2011, "awards_in_panel"] == 3
    assert out.loc[2011, "qualifying_H12"] == 3
    assert out.loc[2011, "qualifying_H36"] == 2
    assert out.loc[2011, "share_qualifying_H36"] == pytest.approx(2 / 3)
    assert out.loc[2011, "earliest_base_action"] == "2010-10-01"
    assert out.loc[2011, "latest_base_action"] == "2011-09-30"
    assert out.loc[2012, "qualifying_H24"] == 1
    assert out.loc[2012, "qualifying_H36"] == 0
    assert out.loc["ALL", "awards_in_panel"] == 5
    assert out.loc["ALL", "qualifying_H12"] == 5
    assert out.loc["ALL", "qualifying_H36"] == 2


def test_censoring_table_is_empty_when_there_is_no_panel(tmp_path):
    assert R.censoring_table(tmp_path / "absent.parquet").empty


# --------------------------------------------------------- report formatting

def test_fmt_renders_missing_values_as_not_available():
    assert R.fmt(None) == "n/a"
    assert R.fmt(float("nan")) == "n/a"
    assert R.fmt(0.123456, 3) == "0.123"
    assert R.fmt("already text") == "already text"


def test_md_table_emits_a_header_separator_row():
    t = R.md_table([[1, 2]], ["a", "b"]).splitlines()
    assert t[0] == "| a | b |"
    assert t[1] == "|---|---|"
    assert t[2] == "| 1 | 2 |"


def test_src_note_names_the_script_and_the_command():
    note = R.src_note("panel.py", ".venv/bin/python -m usaspending.src.panel")
    assert "usaspending/src/panel.py" in note
    assert ".venv/bin/python -m usaspending.src.panel" in note


def test_timing_record_accumulates_steps_without_losing_earlier_ones(tmp_path):
    import timing
    timing.record(tmp_path, "panel", 25.5, {"awards": 10})
    timing.record(tmp_path, "models", 1500.0)
    data = json.loads((tmp_path / "timings.json").read_text())
    assert set(data) == {"panel", "models"}
    assert data["panel"]["seconds"] == 25.5
    assert data["panel"]["awards"] == 10
    assert data["models"]["seconds"] == 1500.0
    timing.record(tmp_path, "panel", 26.0)
    data = json.loads((tmp_path / "timings.json").read_text())
    assert data["panel"]["seconds"] == 26.0
    assert data["models"]["seconds"] == 1500.0     # untouched by the re-record
