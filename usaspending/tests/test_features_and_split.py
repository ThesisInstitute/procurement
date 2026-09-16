"""Category lumping and the forward-chained split."""
import numpy as np
import pandas as pd
import pytest

import features as F
import models as M


def test_category_maps_are_fitted_on_train_only():
    train = pd.DataFrame({c: ["a"] * 10 for c in F.CATEGORICAL})
    maps = F.fit_category_maps(train)
    assert maps["naics2"] == ["a"]
    test = pd.DataFrame({c: ["a", "b"] for c in F.CATEGORICAL})
    out = F.apply_category_maps(test[F.CATEGORICAL], maps)
    assert list(out["naics2"].astype(str)) == ["a", F.OTHER]


def test_category_maps_cap_cardinality_at_the_binning_limit():
    many = [f"v{i}" for i in range(1000)]
    train = pd.DataFrame({c: many for c in F.CATEGORICAL})
    maps = F.fit_category_maps(train)
    assert len(maps["awarding_office_code"]) == F.MAX_CATEGORIES
    out = F.apply_category_maps(train[F.CATEGORICAL], maps)
    assert len(out["awarding_office_code"].cat.categories) == F.MAX_CATEGORIES + 1


def test_missing_categories_get_an_explicit_level_not_dropped():
    train = pd.DataFrame({c: ["a", None, "a"] for c in F.CATEGORICAL})
    maps = F.fit_category_maps(train)
    assert F.MISSING in maps["naics2"]
    out = F.apply_category_maps(train[F.CATEGORICAL], maps)
    assert out["naics2"].isna().sum() == 0


def test_feature_columns_history_toggle():
    cat_a, num_a = F.feature_columns(True)
    cat_b, num_b = F.feature_columns(False)
    assert cat_a == cat_b
    assert set(num_a) - set(num_b) == set(F.HISTORY)


def test_split_masks_are_disjoint_and_forward_chained():
    df = pd.DataFrame({"base_fy": list(range(2010, 2023))})
    m = M.split_masks(df)
    assert not (m["train"] & m["val"]).any()
    assert not (m["val"] & m["test"]).any()
    assert not (m["train"] & m["test"]).any()
    fy = df["base_fy"].to_numpy()
    assert fy[m["train"]].max() < fy[m["val"]].min()
    assert fy[m["val"]].max() < fy[m["test"]].min()
    assert m["train"].sum() + m["val"].sum() + m["test"].sum() == len(df)


def test_split_masks_match_the_documented_year_ranges():
    df = pd.DataFrame({"base_fy": list(range(2010, 2023))})
    m = M.split_masks(df)
    fy = df["base_fy"].to_numpy()
    assert fy[m["train"]].tolist() == list(range(2010, 2018))
    assert fy[m["val"]].tolist() == [2018, 2019]
    assert fy[m["test"]].tolist() == [2020, 2021, 2022]


def test_binary_metrics_reports_zero_skill_for_the_base_rate_forecast():
    y = np.array([1.0] * 30 + [0.0] * 70)
    m = M.binary_metrics(y, np.full(100, 0.3), 0.3)
    assert m["bss_vs_train_base_rate"] == pytest.approx(0.0)
    assert m["n"] == 100
    assert m["observed_rate"] == pytest.approx(0.3)


def test_prepare_matrix_keeps_every_requested_column():
    n = 20
    df = pd.DataFrame({c: ["x"] * n for c in F.CATEGORICAL})
    for c in F.NUMERIC + F.HISTORY:
        df[c] = np.arange(n, dtype=float)
    maps = F.fit_category_maps(df)
    X = M.prepare_matrix(df, maps, use_history=True)
    cat, num = F.feature_columns(True)
    assert list(X.columns) == cat + num
    X2 = M.prepare_matrix(df, maps, use_history=False)
    assert not set(F.HISTORY) & set(X2.columns)


def test_prepare_matrix_tolerates_a_missing_numeric_column():
    n = 10
    df = pd.DataFrame({c: ["x"] * n for c in F.CATEGORICAL})
    for c in F.NUMERIC:
        df[c] = 1.0
    maps = F.fit_category_maps(df)
    X = M.prepare_matrix(df, maps, use_history=True)
    assert X["recipient_prior_award_count"].isna().all()


def test_permutation_importance_sign_convention():
    """The stored importance must be a positive Brier increase for a feature the
    model actually uses."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    import scoring as S

    rng = np.random.RandomState(0)
    n = 4000
    signal = rng.normal(size=n)
    noise = rng.normal(size=n)
    y = (rng.uniform(size=n) < 1 / (1 + np.exp(-3 * signal))).astype(int)
    X = pd.DataFrame({"signal": signal, "noise": noise})
    clf = HistGradientBoostingClassifier(max_iter=60, early_stopping=False,
                                         random_state=0).fit(X, y)

    def neg_brier(est, Xa, ya):
        return -S.brier_score(ya, est.predict_proba(Xa)[:, 1])

    pi = permutation_importance(clf, X, y, scoring=neg_brier, n_repeats=3,
                                random_state=0, n_jobs=1)
    imp = dict(zip(X.columns, pi.importances_mean))
    assert imp["signal"] > 0
    assert imp["signal"] > imp["noise"]
    # and the value really is a Brier increase
    base = S.brier_score(y, clf.predict_proba(X)[:, 1])
    Xp = X.copy()
    Xp["signal"] = rng.permutation(Xp["signal"].to_numpy())
    permuted = S.brier_score(y, clf.predict_proba(Xp)[:, 1])
    assert permuted > base


def test_fiscal_year_windows_tile_the_year_without_gaps_or_overlap():
    import pandas as _pd
    import bulk_fetch as B

    start, end = B.fy_window(2018)
    assert (start, end) == ("2017-10-01", "2018-09-30")
    for splits in (1, 2, 3, 4, 12):
        w = B.fy_windows(2018, splits)
        assert len(w) == splits
        assert w[0][0] == start
        assert w[-1][1] == end
        for a, b in w:
            assert _pd.Timestamp(a) <= _pd.Timestamp(b)
        for i in range(len(w) - 1):
            gap = _pd.Timestamp(w[i + 1][0]) - _pd.Timestamp(w[i][1])
            assert gap == _pd.Timedelta(days=1)


def test_fiscal_year_window_is_october_to_september():
    import bulk_fetch as B
    assert B.fy_window(2010) == ("2009-10-01", "2010-09-30")
    assert B.fy_window(2026) == ("2025-10-01", "2026-09-30")
