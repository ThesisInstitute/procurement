"""Tests for the OCR-noise proxies, on synthetic text.

These exist because the proxies replaced an asserted mechanism claim ("older
documents are scanned and OCR'd; the text layer is noisier before roughly
2005"), and a measurement that replaces a claim has to be shown to measure
something. Each test constructs text whose noisiness is known by construction.
"""
import numpy as np
import pytest

from worldbank.src import text_quality as tq

CLEAN = ("the project will finance the construction of rural roads and the "
         "rehabilitation of existing infrastructure in the northern region " * 40)
NOISY = ("tbe projeet will fmance tbe construction of Ia roads arid tbe "
         "rehabilitation ofthe existing infrastructure in Ia northern region " * 40)


def test_clean_text_scores_near_zero_on_the_ocr_marker_rate():
    r = tq.score_text(CLEAN)
    assert r["n_tokens"] > 500
    assert r["broken_of_per_1k"] == pytest.approx(0.0, abs=0.5)


def test_noisy_text_scores_much_higher_than_clean_text():
    assert (tq.score_text(NOISY)["broken_of_per_1k"]
            > 10 * max(tq.score_text(CLEAN)["broken_of_per_1k"], 0.1))


def test_single_character_fragmentation_is_detected():
    frag = "t h e p r o j e c t w i l l f i n a n c e r o a d s " * 80
    assert (tq.score_text(frag)["single_char_token_rate"]
            > tq.score_text(CLEAN)["single_char_token_rate"])


def test_a_and_i_are_not_counted_as_fragmentation():
    """They are real single-letter English words, so they must not inflate it."""
    t = "a i " * 600 + CLEAN
    r = tq.score_text(t)
    assert r["single_char_token_rate"] == pytest.approx(0.0, abs=1e-9)


def test_short_documents_return_nan_rather_than_a_misleading_zero():
    r = tq.score_text("the project will finance roads")
    assert r["n_tokens"] < 500
    assert np.isnan(r["broken_of_per_1k"])
    assert np.isnan(r["single_char_token_rate"])


def test_empty_text_returns_nan_not_zero():
    r = tq.score_text("")
    assert r["n_tokens"] == 0
    assert np.isnan(r["broken_of_per_1k"])


def test_the_rate_is_per_thousand_tokens_not_per_document():
    """Doubling the document must not change the rate."""
    one = tq.score_text(NOISY)["broken_of_per_1k"]
    two = tq.score_text(NOISY + NOISY)["broken_of_per_1k"]
    assert two == pytest.approx(one, rel=0.05)


def test_only_the_sampled_prefix_is_scanned():
    """Scoring is bounded, so a 3 MB document cannot dominate the run time."""
    t = CLEAN + "Ia " * 200_000
    assert len(t) > tq.SAMPLE_CHARS
    r = tq.score_text(t)
    assert r["n_tokens"] <= tq.SAMPLE_CHARS


def test_markers_are_word_bounded_and_do_not_fire_inside_longer_words():
    """"Ia" must not match inside "Iamb"; "arid" must not match "aridity"."""
    t = "Iamb aridity tbench " * 300
    assert tq.score_text(t)["broken_of_per_1k"] == pytest.approx(0.0, abs=1e-9)
