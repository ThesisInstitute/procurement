"""The scoreboard fill-rate tables and the per-action restatement tests.

Every expected value below is computed by hand from the fixture, not from a
previous run of the code.
"""
import pandas as pd
import pytest

import field_evidence as FE


def noop(_msg):
    return None


# --------------------------------------------------------- solicitation shape

@pytest.mark.parametrize("value,expected", [
    ("W91QUZ-10-R-0001", True),    # letters, digits, 16 chars
    ("SPE4A718R0123", True),       # letters, digits, 13 chars
    ("ABCDEFGH", False),           # 8 chars but no digit
    ("12345678", False),           # 8 chars but no letter
    ("AB123", False),              # has both but only 5 chars
    ("AB12345", False),            # 7 chars, one short of the rule
    ("AB123456", True),            # exactly 8 chars, the boundary
    ("  AB123456  ", True),        # whitespace is stripped before measuring
    ("NONE", False),
    ("0", False),
    (None, False),
])
def test_solicitation_shape_rule(value, expected):
    s = pd.Series([value], dtype="string")
    assert bool(FE.looks_like_a_solicitation_number(s).iloc[0]) is expected


def test_solicitation_shape_rule_boundary_is_exactly_eight():
    assert FE.SOLICITATION_MIN_LEN == 8


# ------------------------------------------------------------- fill rate table

def _base_frame():
    """Six base actions across two fiscal years, hand-built.

    FY2011 (dates in Oct-Dec 2010 and Jan 2011): 3 rows
        solicitation: "W91QUZ-10-R-0001" (shaped), "NONE" (present, not shaped),
                      None (absent)              -> 2/3 non-null, 1/3 shaped
        offers:       3, 1, None                 -> 2/3 non-null, median 2.0
        extent:       A, C, A
    FY2012 (dates in Oct 2011 onward): 3 rows
        solicitation: "SPE4A718R0123", "AB123456", "AB12345"
                                                 -> 3/3 non-null, 2/3 shaped
        offers:       5, 1, 1                    -> 3/3 non-null, median 1.0
        extent:       A, C, C
    """
    return pd.DataFrame({
        "action_date": pd.to_datetime([
            "2010-10-05", "2010-12-01", "2011-01-15",
            "2011-10-05", "2012-02-01", "2012-09-30"]),
        "solicitation_identifier": pd.array(
            ["W91QUZ-10-R-0001", "NONE", None,
             "SPE4A718R0123", "AB123456", "AB12345"], dtype="string"),
        "number_of_offers_received": [3, 1, None, 5, 1, 1],
        "extent_competed_code": pd.array(["A", "C", "A", "A", "C", "C"],
                                         dtype="string"),
    })


def test_fill_rate_tables_by_fiscal_year():
    out = FE.fill_rate_tables(_base_frame(), noop)
    sol = out["solicitation_identifier_by_base_fy"]
    assert sol["2011"]["base_actions"] == 3
    assert sol["2011"]["share_non_null"] == pytest.approx(2 / 3)
    assert sol["2011"]["share_matching_solicitation_number_shape"] == pytest.approx(1 / 3)
    assert sol["2012"]["share_non_null"] == pytest.approx(1.0)
    assert sol["2012"]["share_matching_solicitation_number_shape"] == pytest.approx(2 / 3)

    overall = out["solicitation_identifier_overall"]
    assert overall["base_actions"] == 6
    assert overall["share_non_null"] == pytest.approx(5 / 6)
    assert overall["share_matching_solicitation_number_shape"] == pytest.approx(3 / 6)


def test_fill_rate_tables_records_the_values_that_fail_the_shape_rule():
    out = FE.fill_rate_tables(_base_frame(), noop)
    failing = out["solicitation_identifier_most_common_values_failing_the_shape_rule"]
    assert failing["NONE"] == 1
    assert failing["AB12345"] == 1
    assert "W91QUZ-10-R-0001" not in failing


def test_offers_fill_rate_by_fiscal_year_and_by_extent_competed():
    out = FE.fill_rate_tables(_base_frame(), noop)
    by_fy = out["number_of_offers_received_by_base_fy"]
    assert by_fy["2011"]["share_non_null"] == pytest.approx(2 / 3)
    assert by_fy["2011"]["median_where_present"] == pytest.approx(2.0)  # median(3,1)
    assert by_fy["2012"]["share_non_null"] == pytest.approx(1.0)
    assert by_fy["2012"]["median_where_present"] == pytest.approx(1.0)  # median(5,1,1)

    by_ec = out["number_of_offers_received_by_extent_competed_code"]
    # code A holds rows with offers 3, None, 5 -> 2 of 3 present, none equal to 1
    assert by_ec["A"]["base_actions"] == 3
    assert by_ec["A"]["share_non_null"] == pytest.approx(2 / 3)
    assert by_ec["A"]["share_equal_to_one_where_present"] == pytest.approx(0.0)
    # code C holds offers 1, 1, 1 -> all present and all equal to one
    assert by_ec["C"]["base_actions"] == 3
    assert by_ec["C"]["share_equal_to_one_where_present"] == pytest.approx(1.0)
    assert by_ec["C"]["share_of_all_base_actions"] == pytest.approx(0.5)


def test_fill_rate_shares_are_computed_within_the_year_not_pooled():
    """Regression guard: the per-year share must use the year's own rows.

    A boolean mask built on the whole frame and then indexed by a group's
    positions rather than its labels would silently mix years. FY2012 has no
    null solicitation identifier, so a pooled computation would drop it below 1.
    """
    out = FE.fill_rate_tables(_base_frame(), noop)
    assert out["solicitation_identifier_by_base_fy"]["2012"]["share_non_null"] == 1.0


# ------------------------------------------------------------- restatement

def test_restatement_block_separates_a_restated_field_from_a_per_action_one():
    """Two non-final actions. The restated column equals the final value on both;
    the per-action column equals it on neither."""
    frame = pd.DataFrame({
        "restated": [300.0, 300.0],
        "per_action": [100.0, 200.0],
        "final": [300.0, 300.0],
        "base": [100.0, 100.0],
    })
    r = FE._restatement_block(frame, "restated", "final", "base")
    assert r["n_actions"] == 2
    assert r["share_equal_to_the_awards_final_value"] == pytest.approx(1.0)
    # the restated column sits at 300 on both actions, never at the base 100
    assert r["share_equal_to_the_base_action_value"] == pytest.approx(0.0)

    p = FE._restatement_block(frame, "per_action", "final", "base")
    assert p["share_equal_to_the_awards_final_value"] == pytest.approx(0.0)
    assert p["share_equal_to_the_base_action_value"] == pytest.approx(0.5)


def test_date_restatement_block_compares_dates_exactly():
    frame = pd.DataFrame({
        "end": pd.to_datetime(["2020-01-01", "2021-06-30", "2022-12-31"]),
        "final": pd.to_datetime(["2022-12-31"] * 3),
        "base": pd.to_datetime(["2020-01-01"] * 3),
    })
    r = FE._date_restatement_block(frame, "end", "final", "base")
    assert r["n_actions"] == 3
    assert r["share_equal_to_the_awards_final_value"] == pytest.approx(1 / 3)
    assert r["share_equal_to_the_base_action_value"] == pytest.approx(1 / 3)


def test_restatement_block_returns_none_on_an_empty_frame():
    empty = pd.DataFrame({"a": [], "b": [], "c": []})
    assert FE._restatement_block(empty, "a", "b", "c") is None
    assert FE._date_restatement_block(empty, "a", "b", "c") is None


def test_close_uses_a_relative_tolerance_on_large_values():
    """The restatement blocks compare money with close(), which allows 1 percent."""
    a = pd.Series([1_000_000.0, 1_000_000.0, 100.0])
    b = pd.Series([1_005_000.0, 1_100_000.0, 100.5])
    got = FE.close(a, b).tolist()
    assert got == [True, False, True]   # 0.5 pct ok, 10 pct not, 0.5 dollars ok
