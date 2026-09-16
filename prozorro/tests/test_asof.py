"""As-of history must not see anything dated at or after the cutoff."""

import numpy as np
import pandas as pd
import pytest

from src.features import AsOfHistory, SumHistory, bidder_block, build_history, lot_block, shrink


def _sec(iso: str) -> float:
    return pd.Timestamp(iso).timestamp()


def test_asof_count_is_strictly_before_the_cutoff():
    h = AsOfHistory()
    h.add("a", _sec("2020-01-01T00:00:00+00:00"))
    h.add("a", _sec("2020-06-01T00:00:00+00:00"))
    h.add("b", _sec("2020-03-01T00:00:00+00:00"))
    h.finalise()
    assert h.count("a", _sec("2019-12-31T00:00:00+00:00")) == 0
    # An event exactly at the cutoff is not yet knowable.
    assert h.count("a", _sec("2020-01-01T00:00:00+00:00")) == 0
    assert h.count("a", _sec("2020-01-02T00:00:00+00:00")) == 1
    assert h.count("a", _sec("2021-01-01T00:00:00+00:00")) == 2
    assert h.count("unknown", _sec("2021-01-01T00:00:00+00:00")) == 0
    assert h.count(None, _sec("2021-01-01T00:00:00+00:00")) == 0
    assert h.count("a", float("nan")) == 0
    assert h.total(_sec("2020-04-01T00:00:00+00:00")) == 2


def test_sum_history_mean_uses_only_prior_values():
    h = SumHistory()
    h.add_value("a", _sec("2020-01-01T00:00:00+00:00"), 0.10)
    h.add_value("a", _sec("2020-06-01T00:00:00+00:00"), 0.30)
    h.finalise()
    assert np.isnan(h.mean("a", _sec("2019-01-01T00:00:00+00:00")))
    assert h.mean("a", _sec("2020-02-01T00:00:00+00:00")) == pytest.approx(0.10)
    assert h.mean("a", _sec("2021-01-01T00:00:00+00:00")) == pytest.approx(0.20)


def test_sum_history_sorts_out_of_order_inserts():
    h = SumHistory()
    h.add_value("a", _sec("2020-06-01T00:00:00+00:00"), 0.30)
    h.add_value("a", _sec("2020-01-01T00:00:00+00:00"), 0.10)
    h.finalise()
    assert h.mean("a", _sec("2020-02-01T00:00:00+00:00")) == pytest.approx(0.10)


def test_shrink_pulls_small_samples_toward_the_prior():
    out = shrink(np.array([1.0]), np.array([1.0]), np.array([0.2]), k=5.0)
    assert out[0] == pytest.approx((1 + 5 * 0.2) / (1 + 5))
    big = shrink(np.array([100.0]), np.array([100.0]), np.array([0.2]), k=5.0)
    assert big[0] > out[0]
    # A missing prior is treated as zero, never as NaN.
    assert np.isfinite(shrink(np.array([1.0]), np.array([1.0]), np.array([np.nan]))[0])


def _lots_frame() -> pd.DataFrame:
    """Alpha wins in 2019 and is extended in 2020-03; Beta has no record."""
    return pd.DataFrame(
        [
            {
                "tender_id": "T1", "lot_id": "", "buyer_id": "BUY",
                "tender_start": "2019-05-01T00:00:00+03:00",
                "award_end": "2019-05-20T00:00:00+03:00",
                "tc_dateSigned": "2019-06-01T00:00:00+03:00",
                "first_duration_change_date": "2020-03-01T00:00:00+02:00",
                "winner_id": "ALPHA", "winner_discount": 0.20, "winner_rank": 1.0,
                "winner_is_lowest": True, "n_bids_lot": 2, "lot_expected_value": 100000.0,
                "n_lots": 1, "bid_cv": 0.1, "bid_spread": 0.2, "method": "aboveThreshold",
                "cpv_division": "45", "region": "Київська область",
                "main_category": "works", "buyer_kind": "general",
            },
            {
                "tender_id": "T2", "lot_id": "", "buyer_id": "BUY",
                "tender_start": "2020-02-01T00:00:00+02:00",
                "award_end": "2020-02-20T00:00:00+02:00",
                "tc_dateSigned": "2020-03-05T00:00:00+02:00",
                "first_duration_change_date": None,
                "winner_id": "ALPHA", "winner_discount": 0.10, "winner_rank": 1.0,
                "winner_is_lowest": True, "n_bids_lot": 3, "lot_expected_value": 200000.0,
                "n_lots": 1, "bid_cv": 0.2, "bid_spread": 0.3, "method": "aboveThreshold",
                "cpv_division": "45", "region": "Київська область",
                "main_category": "works", "buyer_kind": "general",
            },
            {
                "tender_id": "T3", "lot_id": "", "buyer_id": "BUY",
                "tender_start": "2021-01-01T00:00:00+02:00",
                "award_end": "2021-01-20T00:00:00+02:00",
                "tc_dateSigned": "2021-02-01T00:00:00+02:00",
                "first_duration_change_date": None,
                "winner_id": "BETA", "winner_discount": 0.05, "winner_rank": 2.0,
                "winner_is_lowest": False, "n_bids_lot": 3, "lot_expected_value": 50000.0,
                "n_lots": 1, "bid_cv": 0.05, "bid_spread": 0.1, "method": "aboveThresholdUA",
                "cpv_division": "33", "region": "Львівська область",
                "main_category": "goods", "buyer_kind": "general",
            },
        ]
    )


def _bids_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"tender_id": "T1", "bidder_id": "ALPHA", "discount": 0.20},
            {"tender_id": "T1", "bidder_id": "BETA", "discount": 0.05},
            {"tender_id": "T2", "bidder_id": "ALPHA", "discount": 0.10},
            {"tender_id": "T2", "bidder_id": "BETA", "discount": 0.02},
            {"tender_id": "T2", "bidder_id": "GAMMA", "discount": 0.30},
            {"tender_id": "T3", "bidder_id": "BETA", "discount": 0.05},
            {"tender_id": "T3", "bidder_id": "GAMMA", "discount": 0.15},
            {"tender_id": "T3", "bidder_id": "DELTA", "discount": 0.01},
        ]
    )


def test_bidder_history_excludes_an_extension_dated_after_the_cutoff():
    lots, bids = _lots_frame(), _bids_frame()
    hist = build_history(lots, bids)
    ww, we = hist["winner_wins"], hist["winner_ext"]
    # At T2's start (2020-02-01) Alpha has one prior win and the extension of
    # that contract is not yet recorded (it is dated 2020-03-01).
    cut_t2 = pd.Timestamp("2020-02-01T00:00:00+02:00").timestamp()
    assert ww.count("ALPHA", cut_t2) == 1
    assert we.count("ALPHA", cut_t2) == 0
    # By 2021 it is visible.
    cut_t3 = pd.Timestamp("2021-01-01T00:00:00+02:00").timestamp()
    assert ww.count("ALPHA", cut_t3) == 2
    assert we.count("ALPHA", cut_t3) == 1


def test_bidder_block_columns_and_first_row_has_no_history():
    lots, bids = _lots_frame(), _bids_frame()
    hist = build_history(lots, bids)
    blk = bidder_block(
        lots["winner_id"],
        lots["tender_start"],
        lots["winner_discount"],
        lots["winner_is_lowest"],
        pd.Series([0.0, 0.0, 0.5]),
        hist,
    )
    assert blk.loc[0, "bidder_prior_wins_log"] == 0.0
    assert blk.loc[0, "bidder_prior_bids_log"] == 0.0
    assert np.isnan(blk.loc[0, "bidder_prior_mean_discount"])
    assert blk.loc[1, "bidder_prior_wins_log"] == pytest.approx(np.log1p(1.0))
    assert blk.loc[1, "bidder_prior_mean_discount"] == pytest.approx(0.20)
    assert blk.loc[1, "bidder_discount"] == pytest.approx(0.10)
    assert blk.loc[2, "bidder_prior_bids_log"] == pytest.approx(np.log1p(2.0))


def test_lot_block_buyer_history_is_also_as_of():
    lots, bids = _lots_frame(), _bids_frame()
    hist = build_history(lots, bids)
    blk = lot_block(lots, hist)
    assert blk.loc[0, "buyer_prior_lots_log"] == 0.0
    assert blk.loc[1, "buyer_prior_lots_log"] == pytest.approx(np.log1p(1.0))
    assert blk.loc[2, "buyer_prior_lots_log"] == pytest.approx(np.log1p(2.0))
    assert str(blk["method"].dtype) == "category"
    assert blk.loc[0, "log_value"] == pytest.approx(np.log1p(100000.0))
