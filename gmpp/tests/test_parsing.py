"""Money, percentage and date parsing on the published free-text conventions."""
from __future__ import annotations

import pandas as pd
import pytest

from gmpp.src.parsing import is_withheld, money_kind, parse_date, parse_money, parse_percent


@pytest.mark.parametrize(
    "text,expected",
    [
        ("558", 558.0),
        ("1443.7", 1443.7),
        ("24875", 24875.0),
        ("1,234.56", 1234.56),
        ("£1,234.56", 1234.56),
        ("(12.5)", -12.5),
        ("-3.2", -3.2),
        ("0", 0.0),
    ],
)
def test_parse_money_plain_numbers(text, expected):
    assert parse_money(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    [
        # The two published spellings of a Freedom of Information withholding.
        # The bare NISTA form is the one that used to parse as the number 43.
        "Section 43 - Commercial interests",
        "Exempt under Section 43 of the Freedom of Information Act 2000 (Commercial Interests)",
        "Exempt under Section 26 of Freedom of Information Act 2000 (Defence).",
        "Section 24 - National security",
        "Section 22 - Information intended for future publication",
        "Exempt under Sections 24, 26 and 27 of the Freedom of Information Act 2000",
        "The GMPP project is still at the planning stage (Pre-SOC or equivalent) and is "
        "not yet in a position to provide cost/schedule information",
        "Not Applicable",
    ],
)
def test_withheld_text_never_yields_a_number(text):
    assert is_withheld(text)
    assert parse_money(text) is None
    assert money_kind(text) == "withheld"


@pytest.mark.parametrize("text", ["", "   ", "nan", "n/a", "NA", "-", "TBC", None])
def test_blank_text_is_missing(text):
    assert parse_money(text) is None
    assert money_kind(text) == "missing"


@pytest.mark.parametrize(
    "text",
    [
        # The 2016 publications write prose in the variance column. A plain
        # number-grab reads the threshold out of the sentence.
        "Budget variance less than 5%.",
        "Budget variance less than 5%",
        "The Programme is currently forecasting a full spend for 2015/16",
        "Budget forecasts to date are accurate",
        "On track to deliver within the forecast whole life cost",
    ],
)
def test_prose_never_yields_a_number(text):
    assert parse_money(text) is None
    assert parse_percent(text) is None
    assert money_kind(text) == "prose"


@pytest.mark.parametrize(
    "text,expected",
    [
        # Decorations that are not prose and must still parse.
        ("\u00a358m", 58.0),
        ("58m", 58.0),
        ("\u01530.00", 0.0),  # a mis-decoded pound sign in one published file
        (">1000%", 1000.0),
        ("\u00a3 1,234.56", 1234.56),
    ],
)
def test_numeric_decorations_are_not_prose(text, expected):
    assert parse_money(text) == pytest.approx(expected)


def test_range_returns_the_mid_point():
    assert parse_money("Low: 2,750.00, Mid: 2,820.00, High: 3,100.00") == pytest.approx(2820.0)
    assert money_kind("Low: 2,750.00, Mid: 2,820.00, High: 3,100.00") == "range"


def test_range_without_a_mid_uses_the_average_of_low_and_high():
    assert parse_money("Low: 100, High: 300") == pytest.approx(200.0)


def test_range_with_only_a_low_uses_the_low():
    assert parse_money("Low: 797.93") == pytest.approx(797.93)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("5%", 5.0),
        ("-3.2%", -3.2),
        ("0.05", 5.0),  # spreadsheet-native fraction
        ("1.5", 1.5),  # already a percentage
        ("12", 12.0),
        ("0", 0.0),
    ],
)
def test_parse_percent(text, expected):
    assert parse_percent(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("01/12/2019", "2019-12-01"),  # day first, as UK files are written
        ("31/03/2024", "2024-03-31"),
        ("2024-03-31", "2024-03-31"),
        ("March 2024", "2024-03-01"),
        ("1 April 2016", "2016-04-01"),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text) == pd.Timestamp(expected)


@pytest.mark.parametrize("text", ["43", "TBC", "Exempt under Section 26", ""])
def test_parse_date_rejects_non_dates(text):
    assert parse_date(text) is None


def test_a_percent_cell_reports_whether_it_is_ambiguous():
    """The cell alone cannot say whether 0.64 is the fraction 0.0064 or a
    variance of 0.64 per cent, and both occur in the files, so the reading is
    settled by the caller against the row's baseline and forecast.
    """
    from gmpp.src.parsing import parse_percent_parts

    # Ambiguous: no percent sign, a decimal point, magnitude at most 1.
    assert parse_percent_parts("0.64") == (0.64, True)
    assert parse_percent_parts("-0.22") == (-0.22, True)
    # Not ambiguous: a percent sign settles it.
    assert parse_percent_parts("0.64%") == (0.64, False)
    # Not ambiguous: above 1, so it cannot be a fraction of a percent.
    assert parse_percent_parts("-22.00") == (-22.0, False)
    # Not ambiguous: a whole number with no decimal point.
    assert parse_percent_parts("1") == (1.0, False)
    # Withheld and prose stay unread.
    assert parse_percent_parts("Exempt under Section 43")[0] is None
    assert parse_percent_parts("Budget variance less than 5%.")[0] is None


def test_the_ambiguous_reading_defaults_to_the_fraction():
    """The fraction is right on 24 of the 43 ambiguous cells the rows can
    settle, so it stays the fallback where nothing settles the cell.
    """
    from gmpp.src.parsing import parse_percent

    assert parse_percent("0.64") == pytest.approx(64.0)
    assert parse_percent("0.64%") == pytest.approx(0.64)
    assert parse_percent("-22.00") == pytest.approx(-22.0)


@pytest.mark.parametrize(
    "cell",
    [
        "£9941.96",   # a correctly decoded pound sign
        "ÿ9941.96",   # the same byte read under a different code page
        "ú9941.96",
        "Â£9941.96",
        "£ 9,941.96",
    ],
)
def test_a_mis_decoded_pound_sign_does_not_turn_a_number_into_prose(cell):
    """One cell in the September 2017 MOD file carries a non-breaking space and
    a pound sign that the file's encoding renders as U+00FF. Reading it as prose
    deleted a GBP 9.94bn whole-life cost from the panel without a trace.
    """
    from gmpp.src.parsing import is_prose, parse_money

    assert not is_prose(cell)
    assert parse_money(cell) == pytest.approx(9941.96)


def test_genuine_prose_in_a_money_column_is_still_rejected():
    from gmpp.src.parsing import is_prose, parse_money

    for cell in (
        "Budget variance less than 5%.",
        "Section 43 - Commercial interests",
        "Within tolerance.",
    ):
        assert is_prose(cell) or parse_money(cell) is None


def test_a_published_range_takes_the_mid_point():
    """The two NISTA files publish some money figures as a range."""
    from gmpp.src.parsing import parse_money

    assert parse_money("Low: 2,750.00, Mid: 2,820.00, High: 3,100.00") == pytest.approx(
        2820.0
    )
    assert parse_money("Low: 797.93, Mid: 820.57") == pytest.approx(820.57)


def test_a_time_with_no_date_is_not_a_date():
    """Seven rows of the IPA back-series carry the literal "00:00:00" in the end
    date column. pandas reads that as that time TODAY, which passes any year
    guard and lands a fabricated end date in the data.
    """
    from gmpp.src.parsing import parse_date

    for cell in ("00:00:00", "0:00", "12:30:00"):
        assert parse_date(cell) is None
    assert parse_date("31/03/2025") is not None
