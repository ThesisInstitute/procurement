"""Tests for the leakage filter and the join, on synthetic fixtures."""
import pandas as pd
import pytest

from worldbank.src import join


def _pad(rows):
    """rows: list of (id, projectid, docdt, txturl)."""
    return pd.DataFrame(rows, columns=["id", "projectid", "docdt", "txturl"])


def _pad_lang(rows):
    """rows: list of (id, projectid, docdt, txturl, lang)."""
    return pd.DataFrame(rows, columns=["id", "projectid", "docdt", "txturl",
                                       "lang"])


def _approval(rows):
    df = pd.DataFrame(rows, columns=["projectid", "boardapprovaldate"])
    df["boardapprovaldate"] = pd.to_datetime(df["boardapprovaldate"])
    return df


# ---------------------------------------------------------------- explode

def test_explode_splits_multi_project_documents():
    pad = _pad([("d1", "P111,P222", "2010-01-01", "u1")])
    out = join.explode_projectids(pad)
    assert sorted(out["projectid"]) == ["P111", "P222"]
    assert len(out) == 2
    assert set(out["id"]) == {"d1"}


def test_explode_drops_null_and_malformed_projectids():
    pad = _pad([
        ("d1", None, "2010-01-01", "u1"),
        ("d2", "not-a-pnumber", "2010-01-01", "u2"),
        ("d3", "P333", "2010-01-01", "u3"),
    ])
    out = join.explode_projectids(pad)
    assert out["projectid"].tolist() == ["P333"]


def test_explode_normalises_case_and_whitespace():
    pad = _pad([("d1", " p444 , P555 ", "2010-01-01", "u1")])
    out = join.explode_projectids(pad)
    assert sorted(out["projectid"]) == ["P444", "P555"]


# ------------------------------------------------- the leakage filter core

def test_additional_financing_pad_after_approval_is_excluded():
    """The core leakage case: a second PAD filed years after board approval."""
    pad = _pad([
        ("orig", "P100", "2005-03-01", "u_orig"),
        ("addfin", "P100", "2009-06-01", "u_addfin"),
    ])
    approval = _approval([("P100", "2005-04-15")])
    kept, rejected = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert kept["id"].tolist() == ["orig"]
    assert rejected.loc[rejected["id"] == "addfin", "reject_reason"].tolist() == [
        "docdt_after_approval_plus_grace"
    ]


def test_earliest_qualifying_pad_wins_when_two_qualify():
    pad = _pad([
        ("later", "P100", "2005-03-20", "u2"),
        ("earlier", "P100", "2005-01-10", "u1"),
    ])
    approval = _approval([("P100", "2005-04-15")])
    kept, rejected = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert kept["id"].tolist() == ["earlier"]
    assert rejected["reject_reason"].tolist() == [
        "later_version_within_grace_window"]


@pytest.mark.parametrize("docdt,kept_expected", [
    ("2005-04-15", True),   # exactly on the board date
    ("2005-05-15", True),   # exactly at approval + 30 days
    ("2005-05-16", False),  # one day past the grace window
])
def test_grace_window_boundary_is_inclusive_at_30_days(docdt, kept_expected):
    pad = _pad([("d", "P100", docdt, "u")])
    approval = _approval([("P100", "2005-04-15")])
    kept, rejected = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert (len(kept) == 1) is kept_expected
    if not kept_expected:
        assert rejected["reject_reason"].tolist() == [
            "docdt_after_approval_plus_grace"
        ]


def test_grace_window_is_configurable():
    pad = _pad([("d", "P100", "2005-06-01", "u")])
    approval = _approval([("P100", "2005-04-15")])
    kept0, _ = join.qualifying_pad(join.explode_projectids(pad), approval,
                                   grace_days=30)
    kept1, _ = join.qualifying_pad(join.explode_projectids(pad), approval,
                                   grace_days=60)
    assert len(kept0) == 0
    assert len(kept1) == 1


def test_project_with_no_board_approval_date_is_rejected_not_kept():
    pad = _pad([("d", "P100", "2005-03-01", "u")])
    approval = _approval([("P999", "2005-04-15")])  # P100 absent
    kept, rejected = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert len(kept) == 0
    assert rejected["reject_reason"].tolist() == ["no_board_approval_date"]


def test_pad_with_no_docdt_is_rejected():
    pad = _pad([("d", "P100", None, "u")])
    approval = _approval([("P100", "2005-04-15")])
    kept, rejected = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert len(kept) == 0
    assert rejected["reject_reason"].tolist() == ["no_docdt"]


def test_every_input_row_is_either_kept_or_rejected_exactly_once():
    """No silent drops: the filter must account for every exploded row."""
    pad = _pad([
        ("a", "P1", "2000-01-01", "u"),
        ("b", "P1", "2005-01-01", "u"),
        ("c", "P2", "2001-01-01", "u"),
        ("d", "P3", None, "u"),
        ("e", "P4", "2001-01-01", "u"),      # no approval date
        ("f", "P1,P2", "2000-06-01", "u"),   # multi-project
    ])
    approval = _approval([
        ("P1", "2000-02-01"), ("P2", "2001-02-01"), ("P3", "2001-02-01"),
    ])
    ex = join.explode_projectids(pad)
    kept, rejected = join.qualifying_pad(ex, approval)
    assert len(kept) + len(rejected) == len(ex)
    pairs_in = set(zip(ex["id"], ex["projectid"]))
    pairs_out = set(zip(kept["id"], kept["projectid"])) | set(
        zip(rejected["id"], rejected["projectid"]))
    assert pairs_in == pairs_out


def test_multi_project_document_can_be_the_qualifying_pad_for_one_project_only():
    """Doc 'f' is late for P1 but on time for P2."""
    pad = _pad([
        ("a", "P1", "2000-01-01", "u"),
        ("f", "P1,P2", "2001-01-15", "u"),
    ])
    approval = _approval([("P1", "2000-02-01"), ("P2", "2001-02-01")])
    kept, rejected = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert dict(zip(kept["projectid"], kept["id"])) == {"P1": "a", "P2": "f"}
    assert rejected["reject_reason"].tolist() == ["docdt_after_approval_plus_grace"]


def test_kept_is_one_row_per_project():
    pad = _pad([
        ("a", "P1", "2000-01-01", "u"), ("b", "P1", "2000-01-02", "u"),
        ("c", "P1", "2000-01-03", "u"),
    ])
    approval = _approval([("P1", "2000-02-01")])
    kept, _ = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert kept["projectid"].is_unique and len(kept) == 1


def test_ties_on_docdt_are_broken_deterministically():
    pad_a = _pad([("z", "P1", "2000-01-01", "u"), ("a", "P1", "2000-01-01", "u")])
    pad_b = _pad([("a", "P1", "2000-01-01", "u"), ("z", "P1", "2000-01-01", "u")])
    approval = _approval([("P1", "2000-02-01")])
    k1, _ = join.qualifying_pad(join.explode_projectids(pad_a), approval)
    k2, _ = join.qualifying_pad(join.explode_projectids(pad_b), approval)
    assert k1["id"].tolist() == k2["id"].tolist() == ["a"]


# ------------------------------------------------------------------ funnel

def test_funnel_counts_are_set_sizes_and_monotone_where_nested():
    ieg = pd.DataFrame({"projectid": ["P1", "P2", "P3", "P4"]})
    pad = _pad([
        ("a", "P1", "2000-01-01", "u"),
        ("b", "P2", "2000-01-01", None),
        ("c", "P5", "2000-01-01", "u"),
    ])
    approval = _approval([("P1", "2000-02-01"), ("P2", "2000-02-01"),
                          ("P5", "2000-02-01")])
    ex = join.explode_projectids(pad)
    kept, _ = join.qualifying_pad(ex, approval)
    f = join.funnel(ieg, ex, approval, kept).set_index("stage")["n"].to_dict()
    assert f["distinct projects with an IEG rating"] == 4
    assert f["distinct projects with any PAD in WDS"] == 3
    assert f["rated projects with any PAD"] == 2
    assert f["rated projects with a QUALIFYING PAD (leakage filter passed)"] == 2
    assert f["rated projects with a qualifying PAD and a txturl"] == 1
    assert (f["rated projects with a qualifying PAD and a txturl"]
            <= f["rated projects with a QUALIFYING PAD (leakage filter passed)"]
            <= f["rated projects with any PAD"]
            <= f["distinct projects with an IEG rating"])


# ---------------------------------------------------------- schedule slip

def test_schedule_slip_days_signs_and_nulls():
    actual = pd.Series(["2010-01-11", "2010-01-01", None, "2010-01-01"])
    planned = pd.Series(["2010-01-01", "2010-01-11", "2010-01-01", None])
    out = join.schedule_slip_days(actual, planned)
    assert out.tolist()[0] == 10       # closed late -> positive slip
    assert out.tolist()[1] == -10      # closed early -> negative
    assert pd.isna(out.tolist()[2]) and pd.isna(out.tolist()[3])


# ------------------------------------------------- language preference
# WDS carries translations of the appraisal document under the same P-number,
# and a translation is often dated EARLIER than the English original, so an
# "earliest only" rule selected it. Measured on the real data before this was
# added: 40 projects were represented by a non-English document and an English
# one qualified for 39 of them.

def test_english_is_preferred_over_an_earlier_translation():
    pad = _pad_lang([
        ("fr", "P100", "2005-03-01", "u_fr", "French"),
        ("en", "P100", "2005-03-20", "u_en", "English"),
    ])
    approval = _approval([("P100", "2005-04-15")])
    kept, rejected = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert kept["id"].tolist() == ["en"]
    assert rejected["id"].tolist() == ["fr"]


def test_language_preference_never_overrides_the_leakage_test():
    """An English PAD dated after the grace window must still be excluded."""
    pad = _pad_lang([
        ("fr", "P100", "2005-03-01", "u_fr", "French"),
        ("en_late", "P100", "2005-09-01", "u_en", "English"),
    ])
    approval = _approval([("P100", "2005-04-15")])
    kept, rejected = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert kept["id"].tolist() == ["fr"]
    assert rejected.set_index("id").loc["en_late", "reject_reason"] == (
        "docdt_after_approval_plus_grace")


def test_earliest_english_wins_among_several_english():
    pad = _pad_lang([
        ("en_late", "P100", "2005-03-20", "u1", "English"),
        ("en_early", "P100", "2005-01-10", "u2", "English"),
        ("es", "P100", "2005-01-01", "u3", "Spanish"),
    ])
    approval = _approval([("P100", "2005-04-15")])
    kept, _ = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert kept["id"].tolist() == ["en_early"]


def test_translation_is_kept_when_no_english_version_qualifies():
    pad = _pad_lang([("fr", "P100", "2005-03-01", "u_fr", "French")])
    approval = _approval([("P100", "2005-04-15")])
    kept, _ = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert kept["id"].tolist() == ["fr"]


def test_missing_lang_column_falls_back_to_earliest():
    """A frame without `lang` must behave exactly as it did before."""
    pad = _pad([
        ("later", "P100", "2005-03-20", "u2"),
        ("earlier", "P100", "2005-01-10", "u1"),
    ])
    approval = _approval([("P100", "2005-04-15")])
    kept, _ = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert kept["id"].tolist() == ["earlier"]


# ------------------------------------------------- reject reason split

def test_same_day_duplicate_and_later_version_are_distinguished():
    """Most of what the filter drops is a same-day duplicate, not a post-hoc doc."""
    pad = _pad_lang([
        ("en", "P100", "2005-01-10", "u1", "English"),
        ("dup", "P100", "2005-01-10", "u2", "Spanish"),
        ("later", "P100", "2005-03-20", "u3", "English"),
    ])
    approval = _approval([("P100", "2005-04-15")])
    kept, rejected = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert kept["id"].tolist() == ["en"]
    reasons = rejected.set_index("id")["reject_reason"].to_dict()
    assert reasons["dup"] == "same_date_duplicate_or_translation"
    assert reasons["later"] == "later_version_within_grace_window"


# ------------------------------------------------- date normalisation
# WDS renders `docdt` as an instant at midnight US Eastern (04:00Z or 05:00Z),
# while boardapprovaldate is a bare date at 00:00. Differencing them without
# normalising lost a day to truncation on 100% of real rows.

def test_parse_dt_normalises_a_midnight_eastern_instant_to_its_date():
    s = pd.Series(["2003-05-15T04:00:00Z", "2003-01-15T05:00:00Z"])
    out = join.parse_dt(s)
    assert out.tolist() == [pd.Timestamp("2003-05-15"),
                            pd.Timestamp("2003-01-15")]
    assert (out.dt.hour == 0).all()


def test_parse_dt_leaves_a_bare_date_alone():
    out = join.parse_dt(pd.Series(["2003-05-15"]))
    assert out.tolist() == [pd.Timestamp("2003-05-15")]


def test_lead_days_is_a_whole_calendar_day_count():
    """The bug this prevents: .dt.days truncating 27 days 20 hours to 27."""
    board = pd.Series([pd.Timestamp("2003-06-12")])
    docdt = join.parse_dt(pd.Series(["2003-05-15T04:00:00Z"]))
    assert (board - docdt).dt.days.tolist() == [28]


def test_parse_dt_returns_nat_for_unparseable_values():
    out = join.parse_dt(pd.Series(["", None, "not a date"]))
    assert out.isna().all()


def test_id_tie_break_compares_integers_not_strings():
    """WDS stores `id` as a string of digits, so a plain sort is arbitrary."""
    pad = _pad_lang([
        ("18082379", "P100", "2005-01-10", "u1", "English"),
        ("440661", "P100", "2005-01-10", "u2", "English"),
    ])
    approval = _approval([("P100", "2005-04-15")])
    kept, _ = join.qualifying_pad(join.explode_projectids(pad), approval)
    # a lexicographic sort would pick "18082379"; the integer sort picks 440661
    assert kept["id"].tolist() == ["440661"]


def test_tie_break_still_total_when_an_id_is_not_numeric():
    pad = _pad_lang([
        ("zz-alpha", "P100", "2005-01-10", "u1", "English"),
        ("440661", "P100", "2005-01-10", "u2", "English"),
    ])
    approval = _approval([("P100", "2005-04-15")])
    kept, rejected = join.qualifying_pad(join.explode_projectids(pad), approval)
    assert len(kept) == 1
    assert len(rejected) == 1
