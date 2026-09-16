"""The header map must describe headers the published files really carry."""
from __future__ import annotations

import pandas as pd
import pytest

from gmpp.src.paths import RAW_DIR
from gmpp.src.profile_headers import norm_header
from gmpp.src.schema import HEADER_MAP, KNOWN_NON_DATA_HEADERS, map_header

HEADER_SUMMARY = RAW_DIR / "header_summary.csv"
# Every header in every sheet of every file: the universe the map must describe.
ALL_SHEETS = RAW_DIR / "header_all_sheets.csv"
# Headers in the files the panel actually reads: the universe that must be
# fully accounted for, because a header here that is neither mapped nor
# declared non-data is a column silently dropped from the published panel.
PANEL_HEADERS = RAW_DIR / "header_panel_files.csv"

requires_corpus = pytest.mark.skipif(
    not (HEADER_SUMMARY.exists() and ALL_SHEETS.exists() and PANEL_HEADERS.exists()),
    reason="needs the downloaded corpus (gmpp.src.profile_headers)",
)


def observed(path=None) -> set[str]:
    return set(pd.read_csv(path or HEADER_SUMMARY)["norm_header"].astype(str))


def test_every_map_key_is_already_normalised():
    """A key written from the raw spelling rather than the normalised one can
    never match. This catches it without needing the corpus.
    """
    wrong = {k: norm_header(k) for k in HEADER_MAP if norm_header(k) != k}
    assert wrong == {}


@requires_corpus
def test_every_map_key_names_a_header_some_file_carries():
    """Four keys once named headers no file produces, because `norm_header`
    strips a bracketed qualifier before it rewrites a pound sign: "FY Budget
    (GBPm) inc Non Gov" normalises to "fy budget inc non gov", never to "fy
    budget gbpm inc non gov". Those keys silently did nothing.
    """
    seen = observed(ALL_SHEETS)
    dead = sorted(k for k in HEADER_MAP if k not in seen)
    assert dead == []


@requires_corpus
def test_every_declared_non_data_header_is_one_some_file_carries():
    seen = observed(ALL_SHEETS)
    dead = sorted(k for k in KNOWN_NON_DATA_HEADERS if k not in seen)
    assert dead == []


@requires_corpus
def test_every_observed_header_is_either_mapped_or_declared_non_data():
    """No header carrying project data may be silently ignored. Anything not
    mapped has to be listed as a known non-data header, so a new spelling in a
    future publication fails the suite rather than dropping a column.
    """
    unaccounted = sorted(
        h
        for h in observed(PANEL_HEADERS)
        if map_header(h) is None
        and h not in KNOWN_NON_DATA_HEADERS
        and not h.startswith("_unnamed")
    )
    assert unaccounted == []


def test_the_dca_and_whole_life_cost_headers_map_where_it_matters():
    """The two fields the whole study turns on, across their published
    spellings.
    """
    for header in (
        "IPA Delivery Confidence Assessment",
        "MPA RAG rating",
        "MPA RAG (Departmental RAG used if MPA RAG missing)",
    ):
        assert map_header(norm_header(header)) == "dca_ipa", header
    for header in (
        "TOTAL Baseline Whole Life Costs (£m) (including Non-Government Costs)",
        "Whole Life Cost TOTAL Baseline £m (including Non-Government costs)",
        "TOTAL BUDGETED WHOLE LIFE COSTS including Non-Government Costs",
    ):
        assert map_header(norm_header(header)) == "wlc_baseline_gbp_m", header


def test_the_sro_rating_is_never_read_as_the_ipa_rating():
    assert map_header(norm_header("SRO Delivery Confidence Assessment")) == "dca_sro"
    assert map_header(norm_header("IPA Delivery Confidence Assessment")) == "dca_ipa"


def test_an_in_year_figure_is_never_read_as_a_whole_life_cost():
    assert map_header(norm_header("Financial Year Baseline (£m)")) == "fy_baseline_gbp_m"
    assert (
        map_header(norm_header("2018/19 TOTAL Baseline £m"))
        == "fy_baseline_gbp_m"
    )
    assert (
        map_header(norm_header("Whole Life Cost TOTAL Baseline £m"))
        == "wlc_baseline_gbp_m"
    )
