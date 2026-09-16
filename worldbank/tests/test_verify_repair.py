"""Tests for the ICRR ratings-table parser used to confirm the repair."""
import pytest

from worldbank.src.verify_repair import extract_outcome_pair as parse


def test_plain_table_layout():
    t = ("11. Ratings Reason for Ratings ICR IEG Disagreements/Comment "
         "Outcome Satisfactory Moderately Satisfactory Risk to Development")
    assert parse(t) == ("Satisfactory", "Moderately Satisfactory")


def test_two_word_ratings_in_both_columns():
    t = ("Ratings ICR IEG Outcome Highly Satisfactory Highly Unsatisfactory "
         "Bank Performance")
    assert parse(t) == ("Highly Satisfactory", "Highly Unsatisfactory")


def test_wrapped_qualifiers_stranded_before_the_row_label():
    """The observed P157035 / P122229 / P116696 layout.

    The PDF text layer wraps the two-word rating, so both "Moderately" tokens
    land before the word "Outcome". Naively reading the two tokens after
    "Outcome" gives "Unsatisfactory", which is one notch too harsh.
    """
    t = ("Ratings ICR IEG Disagreements/Comment Moderately Moderately "
         "Outcome Unsatisfactory Unsatisfactory Bank Performance")
    assert parse(t) == ("Moderately Unsatisfactory", "Moderately Unsatisfactory")


def test_mixed_wrap_only_prepends_where_missing():
    t = ("Ratings ICR IEG Highly Moderately Outcome Satisfactory "
         "Unsatisfactory Bank")
    assert parse(t) == ("Highly Satisfactory", "Moderately Unsatisfactory")


def test_single_stranded_qualifier_is_refused_not_guessed():
    """One stranded qualifier cannot be assigned to a column, so we decline."""
    t = "Ratings ICR IEG Moderately Outcome Unsatisfactory Unsatisfactory"
    assert parse(t) == (None, None)


def test_no_ratings_table_returns_none():
    assert parse("This document has no ratings table at all.") == (None, None)


def test_table_header_present_but_no_outcome_row():
    assert parse("Ratings ICR IEG Bank Performance Satisfactory Satisfactory "
                 "Quality of M&E Modest Modest") == (None, None)


def test_newlines_and_multiple_spaces_are_normalised():
    t = "Ratings\n  ICR\tIEG\n\nOutcome\n Satisfactory\n  Satisfactory\nRisk"
    assert parse(t) == ("Satisfactory", "Satisfactory")


def test_case_insensitive_header_and_titlecased_output():
    t = "RATINGS ICR IEG outcome satisfactory unsatisfactory Risk"
    assert parse(t) == ("Satisfactory", "Unsatisfactory")


def test_search_window_does_not_run_past_the_table():
    """An Outcome row far past the table must not be picked up."""
    t = "Ratings ICR IEG " + ("filler " * 400) + "Outcome Satisfactory Satisfactory"
    assert parse(t) == (None, None)


@pytest.mark.parametrize("pair", [
    ("Satisfactory", "Satisfactory"),
    ("Moderately Satisfactory", "Moderately Unsatisfactory"),
    ("Highly Unsatisfactory", "Unsatisfactory"),
])
def test_round_trip_for_every_scale_point(pair):
    t = f"Ratings ICR IEG Outcome {pair[0]} {pair[1]} Bank Performance"
    assert parse(t) == pair
