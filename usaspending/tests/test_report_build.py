"""The report builder runs end to end on synthetic artifacts.

report.py is the largest module and every number a reader sees passes through
it, so a template error there is a silent failure: the section just does not
appear. These tests build a minimal results directory and assert that each
section is present and carries the values it was given.
"""
import json

import pandas as pd
import pytest

import report as R


def _write_artifacts(res, panel_path, *, with_models=True):
    res.mkdir(parents=True, exist_ok=True)
    (res / "funnel.json").write_text(json.dumps({
        "data_end": "2026-09-13",
        "transactions_loaded": 3_287_223,
        "fiscal_years_loaded": [2010, 2011],
        "base_row_diagnostics": {"awards_type_D_total": 631431,
                                 "awards_without_modification_number_zero": 72424},
        "history_source_awards": 474512,
        "history_source_aggregate_recipient_awards": 25040,
        "funnel": [{"filter": "start", "awards_remaining": 100},
                   {"filter": "size", "awards_remaining": 100},
                   {"filter": "ceiling", "awards_remaining": 90}],
        "seconds": 48.0,
    }))
    (res / "field_evidence.json").write_text(json.dumps({
        "claim_value_state_fields_are_award_level": {"per_field": {
            "potential_total_value_of_award": {
                "share_of_all_actions_populated": 0.6104,
                "awards_with_more_than_one_populated_action": 10,
                "share_constant_within_award": 0.5846},
            "base_and_all_options_value": {
                "share_of_all_actions_populated": 1.0,
                "awards_with_more_than_one_populated_action": 10,
                "share_constant_within_award": 0.0344}}},
        "potential_value_population_rate_by_action_fy": {"2010": 0.26, "2020": 1.0},
        "base_and_all_options_population_rate_by_action_fy": {"2010": 1.0, "2020": 1.0},
        "claim_ceiling_field_behaviour_where_fully_populated": {
            "base_fiscal_year_at_or_after": 2019, "awards_tested": 97496,
            "awards_whose_ceiling_changed": 65067,
            "final_actions": {"n_actions": 1, "share_equal_to_contemporaneous_reconstruction": 0.9846,
                              "share_equal_to_the_awards_final_value": 1.0,
                              "share_equal_to_the_base_level": 0.3974},
            "non_final_actions_on_awards_whose_ceiling_changed": {
                "n_actions": 2, "share_equal_to_contemporaneous_reconstruction": 0.7086,
                "share_equal_to_the_awards_final_value": 0.3774,
                "share_equal_to_the_base_level": 0.3058}},
        "per_action_restatement": {
            "ceiling_field_restatement": {
                "non_final_actions_on_awards_whose_ceiling_changed": {
                    "n_actions": 525900,
                    "share_equal_to_the_awards_final_value": 0.3774,
                    "share_equal_to_the_base_action_value": 0.3058}},
            "current_end_date_restatement": {
                "non_final_actions_on_awards_whose_end_date_changed": {
                    "n_actions": 600913,
                    "share_equal_to_the_awards_final_value": 0.1702,
                    "share_equal_to_the_base_action_value": 0.3309}}},
        "fill_rates_for_the_scoreboard": {
            "solicitation_identifier_overall": {
                "base_actions": 559007, "share_non_null": 0.5446,
                "share_matching_solicitation_number_shape": 0.5374,
                "shape_rule": "letters and digits, at least eight characters"},
            "solicitation_identifier_by_base_fy": {
                "2010": {"base_actions": 5, "share_non_null": 0.43,
                         "share_matching_solicitation_number_shape": 0.41}},
            "number_of_offers_received_by_base_fy": {
                "2010": {"base_actions": 5, "share_non_null": 1.0,
                         "median_where_present": 3.0,
                         "share_equal_to_one_where_present": 0.2}},
            "number_of_offers_received_by_extent_competed_code": {
                "A": {"base_actions": 5, "share_of_all_base_actions": 1.0,
                      "share_non_null": 1.0, "median_where_present": 3.0,
                      "share_equal_to_one_where_present": 0.2}}},
        "action_type_code_counts": {"C": 10, "G": 5},
        "base_row_fill_rate": {"naics_code": 1.0, "solicitation_identifier": 0.54},
    }))
    (res / "column_mapping.json").write_text(json.dumps({
        "parquet_files": 17, "columns_requested": 44,
        "columns_present_in_every_year": ["a"] * 44,
        "columns_absent_from_some_year": []}))
    (res / "fetch_manifest.json").write_text(json.dumps([
        {"fiscal_year": 2010, "rows_type_D": 253528, "unique_awards": 106922,
         "parquet_bytes": 16_132_423}]))
    (res / "timings.json").write_text(json.dumps({
        "panel": {"seconds": 48.0, "finished_at": "2026-09-15T23:51:08"},
        "models": {"seconds": 900.0, "finished_at": "2026-09-16T00:10:00"}}))
    pd.DataFrame([
        {"label": "terminated", "horizon_months": 36, "base_fy": 2010,
         "n": 50, "base_rate": 0.02},
        {"label": "terminated", "horizon_months": 36, "base_fy": "ALL",
         "n": 100, "base_rate": 0.017},
    ]).to_csv(res / "base_rates.csv", index=False)
    pd.DataFrame([{"horizon_months": 36, "n_qualifying": 100,
                   "rate_reconstructed": 0.136, "rate_award_level": 0.118}]
                 ).to_csv(res / "leak_comparison.csv", index=False)
    pd.DataFrame([{"label": "ceiling_growth", "horizon_months": 36, "n": 100,
                   "mean": 0.2, "sd": 1.0, "p10": 0.0, "p25": 0.0, "median": 0.0,
                   "p75": 0.1, "p90": 0.5, "p99": 3.0, "share_zero": 0.5}]
                 ).to_csv(res / "continuous_label_summary.csv", index=False)
    if with_models:
        (res / "model_results.json").write_text(json.dumps([{
            "label": "terminated", "horizon": 36, "n_train": 60, "n_val": 20,
            "n_test": 20, "train_base_rate": 0.02, "test_base_rate": 0.03,
            "models": {
                "base_rate": {"brier": 0.03, "bss_vs_train_base_rate": 0.0,
                              "auc": float("nan"), "ece": 0.01},
                "reference_class": {"brier": 0.029, "bss_vs_train_base_rate": 0.02,
                                    "auc": 0.6, "ece": 0.01},
                "gbm": {"brier": 0.028, "bss_vs_train_base_rate": 0.05,
                        "auc": 0.66, "ece": 0.01},
                "gbm_no_history": {"brier": 0.0281, "bss_vs_train_base_rate": 0.049,
                                   "auc": 0.65, "ece": 0.01}},
            "calibration_test": [{"bin": "[0.0,0.1)", "n": 20,
                                  "mean_forecast": 0.03, "observed_rate": 0.03}],
            "calibration_test_reference_class": [
                {"bin": "[0.0,0.1)", "n": 20, "mean_forecast": 0.03,
                 "observed_rate": 0.03}],
            "unseen_recipient_test": {
                "n": 100, "share_of_test": 0.2,
                "base_rate": {"bss_vs_train_base_rate": 0.0, "observed_rate": 0.03},
                "reference_class": {"bss_vs_train_base_rate": 0.01,
                                    "observed_rate": 0.03},
                "gbm": {"bss_vs_train_base_rate": 0.04, "auc": 0.62,
                        "observed_rate": 0.03}},
            "permutation_importance_computed": True,
            "permutation_importance_val": [
                {"feature": "log_base_ceiling", "mean_brier_increase": 0.002,
                 "std": 0.0001}],
        }]))
        (res / "quantile_results.json").write_text(json.dumps([{
            "label": "ceiling_growth", "horizon": 36, "n_train": 60, "n_val": 20,
            "n_test": 20, "train_winsor_low": -0.5, "train_winsor_high": 5.0,
            "quantiles": {"0.50": {"train_constant": 0.0, "pinball_constant": 0.1,
                                   "pinball_gbm": 0.09,
                                   "pinball_skill_vs_constant": 0.1,
                                   "mae_constant": 0.2, "mae_gbm": 0.18}}}]))
    pd.DataFrame({
        "base_fy": [2010] * 4 + [2011] * 4,
        "action_date": pd.to_datetime(["2010-01-01"] * 4 + ["2011-01-01"] * 4),
        "qualifies_12": [True] * 8, "qualifies_24": [True] * 8,
        "qualifies_36": [True] * 8,
        "ceiling_growth_12": [0.0, 0.2, 0.4, 0.1] * 2,
        "ceiling_growth_24": [0.0, 0.4, 0.7, 0.15] * 2,
        "ceiling_growth_36": [0.0, 0.5, 1.0, 0.2] * 2,
        "ceiling_at_12": [100.0, 120.0, 140.0, 110.0] * 2,
        "ceiling_at_24": [100.0, 140.0, 170.0, 115.0] * 2,
        "ceiling_at_36": [100.0, 150.0, 200.0, 120.0] * 2,
        "schedule_slip_days_36": [0, 100, 400, 20] * 2,
        "unplanned_growth_36": [0.0, 0.1, 0.2, 0.0] * 2,
        "recipient_uei": ["U1", "U1", "U2", "AGG"] * 2,
        "recipient_name": ["FIRM A", "FIRM A", "FIRM B",
                           "FOREIGN AWARDEES (UNDISCLOSED)"] * 2,
        "recipient_is_aggregate": [0, 0, 0, 1] * 2,
    }).to_parquet(panel_path, index=False)


def test_report_builds_every_section_from_artifacts(tmp_path):
    res = tmp_path / "results"
    panel = tmp_path / "panel.parquet"
    _write_artifacts(res, panel)
    text = R.build(res, panel, tmp_path, wall_seconds=1.0)

    for heading in [
        "## What was built", "## The data", "### The columns actually delivered",
        "## Field behaviour, observed",
        "### Is a field carried per action, or restated across the award?",
        "### Fill rates the public scoreboard depends on", "## Data funnel",
        "### Right censoring", "### Who counts as one contractor",
        "## Label definitions", "## Label distributions", "## Model results",
        "### What the table says", "## Calibration",
        "## Test rows whose contractor never appears in training",
        "## Feature importance", "## Continuous labels, quantile forecasts",
        "### What the reconstruction cannot fix",
        "## Where this departs from the specification, and why",
        "## Caveats", "## What could not be verified",
        "## Reproduction, disk and wall time",
    ]:
        assert heading in text, f"missing section: {heading}"


def test_report_carries_the_values_it_was_given(tmp_path):
    res = tmp_path / "results"
    panel = tmp_path / "panel.parquet"
    _write_artifacts(res, panel)
    text = R.build(res, panel, tmp_path, wall_seconds=1.0)

    assert "3,287,223" in text                  # transactions loaded
    assert "2026-09-13" in text                 # data end
    assert "474,512" in text                    # history source size
    assert "253,528" in text                    # fetch manifest row count
    assert "0.3774" in text or "0.377" in text  # the restatement rate
    assert "FOREIGN AWARDEES (UNDISCLOSED)" in text
    assert "log_base_ceiling" in text           # permutation importance feature
    # the wall time table must add the steps up, not assert a number
    assert "948" in text                        # 48 + 900


def test_report_survives_missing_model_results(tmp_path):
    """A partial run must still produce a readable document, not a traceback."""
    res = tmp_path / "results"
    panel = tmp_path / "panel.parquet"
    _write_artifacts(res, panel, with_models=False)
    text = R.build(res, panel, tmp_path, wall_seconds=1.0)
    assert "## Data funnel" in text
    assert "## Caveats" in text
    assert len(text) > 5000


def test_report_never_describes_the_ceiling_label_as_the_award_level_field(tmp_path):
    """Regression guard on a claim the report used to make and the code never did.

    An earlier version of the label table defined ceiling_growth_H as
    potential_total_value_of_award read at the horizon. The code has never done
    that, and the whole field-behaviour section exists to explain why it must not.
    """
    res = tmp_path / "results"
    panel = tmp_path / "panel.parquet"
    _write_artifacts(res, panel)
    text = R.build(res, panel, tmp_path, wall_seconds=1.0)
    start = text.index("| Label | Definition |")
    table = text[start:start + 3000]
    ceiling_row = [ln for ln in table.splitlines()
                   if ln.startswith("| ceiling_growth_H")]
    assert len(ceiling_row) == 1
    row = ceiling_row[0]
    assert "reconstructed ceiling" in row
    assert "NOT" in row and "potential_total_value_of_award" in row


def test_the_deviation_count_in_the_prose_matches_the_number_of_deviations(tmp_path):
    """The sentence said "Five things" while six were listed. Now it counts them."""
    res = tmp_path / "results"
    panel = tmp_path / "panel.parquet"
    _write_artifacts(res, panel)
    text = R.build(res, panel, tmp_path, wall_seconds=1.0)
    section = text.split("## Where this departs from the specification, and why")[1]
    section = section.split("## Caveats")[0]
    bullets = [ln for ln in section.splitlines() if ln.startswith("- **")]
    words = {1: "One thing is", 2: "Two things are", 3: "Three things are",
             4: "Four things are", 5: "Five things are", 6: "Six things are",
             7: "Seven things are", 8: "Eight things are"}
    assert words[len(bullets)] in section, (
        f"{len(bullets)} deviations listed but the prose does not say so")


def test_every_table_in_the_report_is_well_formed(tmp_path):
    """A markdown table whose rows do not match its header renders as garbage."""
    res = tmp_path / "results"
    panel = tmp_path / "panel.parquet"
    _write_artifacts(res, panel)
    text = R.build(res, panel, tmp_path, wall_seconds=1.0)
    lines = text.splitlines()
    tables = 0
    for i, ln in enumerate(lines):
        if not (ln.startswith("|") and i + 1 < len(lines)
                and set(lines[i + 1].replace("|", "").strip()) <= {"-"}
                and lines[i + 1].startswith("|")):
            continue
        tables += 1
        width = ln.count("|")
        assert lines[i + 1].count("|") == width, f"separator width at line {i}"
        j = i + 2
        while j < len(lines) and lines[j].startswith("|"):
            assert lines[j].count("|") == width, (
                f"row {j} has {lines[j].count('|')} pipes, header has {width}: "
                f"{lines[j][:120]}")
            j += 1
    assert tables > 10, f"expected many tables, found {tables}"
