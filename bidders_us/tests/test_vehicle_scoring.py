"""Within-vehicle scoring against brute force on small fixtures."""
import itertools

import numpy as np
import pandas as pd
import pytest

from bidders_us.src import vehicle_scoring as V


def _brute_cross_holder_auc(df):
    num = den = 0.0
    for _, blk in df.groupby("vehicle"):
        rows = blk.to_dict("records")
        for a, b in itertools.product(rows, rows):
            if a["y"] == 1 and b["y"] == 0 and a["holder"] != b["holder"]:
                den += 1
                num += 1.0 if a["p"] > b["p"] else (0.5 if a["p"] == b["p"] else 0.0)
    return num / den


def test_within_vehicle_cross_holder_auc_matches_brute_force():
    rng = np.random.default_rng(0)
    n = 300
    df = pd.DataFrame({
        "vehicle": rng.choice(["V1", "V2", "V3"], n),
        "holder": rng.choice(list("ABCD"), n),
        "y": rng.integers(0, 2, n).astype(float),
        "p": np.round(rng.random(n), 1),   # coarse so ties occur
    })
    out = V.within_vehicle_cross_holder_auc(df, "y", "p")
    assert out["auc"] == pytest.approx(_brute_cross_holder_auc(df))


def test_within_vehicle_auc_ignores_same_holder_pairs():
    # only one holder per vehicle: no cross-holder pairs at all
    df = pd.DataFrame({"vehicle": ["V"] * 4, "holder": ["A"] * 4,
                       "y": [1, 0, 1, 0], "p": [0.9, 0.1, 0.8, 0.2]})
    out = V.within_vehicle_cross_holder_auc(df, "y", "p")
    assert np.isnan(out["auc"]) and out["n_pairs"] == 0


def test_rank_numerator_hand_computed():
    num, den = V.rank_numerator(np.array([1, 0, 0, 1]), np.array([0.9, 0.5, 0.9, 0.1]))
    # pairs: (0.9 vs 0.5)=1, (0.9 vs 0.9)=0.5, (0.1 vs 0.5)=0, (0.1 vs 0.9)=0 -> 1.5 of 4
    assert num == pytest.approx(1.5) and den == 4


def _table():
    rows = []
    for v in ("V1", "V2"):
        for h, tr_rate, te_rate in (("A", 0.2, 0.3), ("B", 0.5, 0.5), ("C", 0.8, 0.9)):
            for split, rate in (("train", tr_rate), ("test", te_rate)):
                for i in range(10):
                    rows.append({"vehicle": v, "holder": h, "split": split,
                                 "y": 1.0 if i < round(rate * 10) else 0.0, "resid": 0.0})
    return pd.DataFrame(rows)


def test_holder_rate_table_and_thresholds():
    t = V.holder_rate_table(_table(), "y", min_train=3, min_test=3, resid_col="resid")
    assert len(t) == 6
    assert t.loc[("V1", "A"), "rate_train"] == pytest.approx(0.2)
    assert t.loc[("V1", "A"), "rate_test"] == pytest.approx(0.3)
    assert t.loc[("V1", "C"), "n_test"] == 10
    assert "resid_train" in t.columns
    assert V.holder_rate_table(_table(), "y", min_train=11).empty


def test_within_vehicle_spearman_perfect_order():
    t = V.holder_rate_table(_table(), "y")
    out = V.within_vehicle_spearman(t, "rate_train", "rate_test")
    assert out["n_vehicles"] == 2
    assert out["weighted_mean"] == pytest.approx(1.0)
    assert out["pooled_within_vehicle_weighted_pearson"] > 0.9


def test_within_vehicle_spearman_skips_small_vehicles():
    t = V.holder_rate_table(_table(), "y")
    t = t.drop(index=("V2", "C"))
    out = V.within_vehicle_spearman(t, "rate_train", "rate_test", min_holders=3)
    assert out["n_vehicles"] == 1


def test_holder_gaps_hand_computed():
    t = V.holder_rate_table(_table(), "y")
    g = V.holder_gaps(t).set_index("vehicle")
    assert g.loc["V1", "oracle_gap"] == pytest.approx(0.6)
    assert g.loc["V1", "recovered_gap"] == pytest.approx(0.6)   # train order matches test order
    assert g.loc["V1", "train_gap"] == pytest.approx(0.6)
    # reverse the test ordering for V2: recovered becomes negative, oracle stays positive
    t2 = t.copy()
    t2.loc[("V2", "A"), "rate_test"], t2.loc[("V2", "C"), "rate_test"] = 0.9, 0.3
    g2 = V.holder_gaps(t2).set_index("vehicle")
    assert g2.loc["V2", "recovered_gap"] == pytest.approx(-0.6)
    assert g2.loc["V2", "oracle_gap"] == pytest.approx(0.6)


def test_permute_holders_within_vehicle_keeps_multiset_and_mask():
    df = pd.DataFrame({"vehicle": ["V1"] * 4 + ["V2"] * 3, "holder": list("ABCDEFG")})
    mask = np.array([True, True, True, True, True, True, False])
    rng = np.random.default_rng(0)
    out = V.permute_holders_within_vehicle(df, "holder", "vehicle", mask, rng)
    assert sorted(out[:4]) == list("ABCD")
    assert sorted(out[4:6]) == list("EF")
    assert out.iloc[6] == "G"


def test_holder_gaps_tie_break_prefers_larger_record_at_both_ends():
    idx = pd.MultiIndex.from_tuples([("V", "A"), ("V", "B"), ("V", "C"), ("V", "D")],
                                    names=["vehicle", "holder"])
    t = pd.DataFrame({"n_train": [3, 9, 3, 9], "rate_train": [0.2, 0.2, 0.8, 0.8],
                      "n_test": [3, 3, 3, 3], "rate_test": [0.1, 0.5, 0.3, 0.9]}, index=idx)
    g = V.holder_gaps(t).iloc[0]
    # low end: tie at 0.2 -> B (n_train 9); high end: tie at 0.8 -> D (n_train 9)
    assert g["recovered_gap"] == pytest.approx(0.9 - 0.5)


def test_pooled_within_vehicle_pearson_is_a_correlation():
    t = V.holder_rate_table(_table(), "y")
    t2 = t.copy()
    t2["rate_test"] = 0.5 * t2["rate_train"] + 0.1
    out = V.within_vehicle_spearman(t2, "rate_train", "rate_test")
    assert out["pooled_within_vehicle_weighted_pearson"] == pytest.approx(1.0)
    t3 = t2.copy()
    t3.loc["V2", "rate_test"] = t3.loc["V2", "rate_test"].to_numpy() + 0.3
    out3 = V.within_vehicle_spearman(t3, "rate_train", "rate_test")
    assert out3["pooled_within_vehicle_weighted_pearson"] == pytest.approx(1.0)
