"""The forward-chained model ladder.

Four rungs, each scored against the same held-out test window:

1. base rate - the constant training-window rate;
2. reference class - shrunken CPV division by region cell mean from training;
3. GBM on the lot alone, with no identity of any kind in it;
4. the same plus the buyer's as-of record;
5. the same plus the winner's price position on that lot;
6. the same plus the winner's as-of record.

Rungs 3 to 6 are nested, so each step is one question: what the lot says, what
the buyer's identity adds, what the winning price adds, and what the winner's
identity adds on top of all of it.

Training never sees a row whose tender started on or after the test window's
first day, and every history feature is as-of the tender's own start, so the
split is forward-chained in both senses.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from src.features import BIDDER_HISTORY, BUYER_HISTORY
from src.scoring import summarise

# The booster's own early-stopping split is a random 15 percent of the
# training window, not a temporal one. The test window is strictly later than
# the whole training window either way, so no test information enters the fit;
# this is noted in the report rather than hidden.
# A label with almost no positives on one side of the split produces AUC and
# skill numbers that are noise dressed as results, so the ladder refuses it and
# the report says which labels were refused and why.
MIN_POSITIVES = 20


class DegenerateLabel(ValueError):
    """Raised when a label has too few positives on one side of the split."""


GBM_KWARGS = dict(
    max_iter=400,
    learning_rate=0.06,
    max_leaf_nodes=31,
    min_samples_leaf=40,
    l2_regularization=1.0,
    early_stopping=True,
    validation_fraction=0.15,
    random_state=20260916,
)


def align_categories(train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Give train and test identical category sets so the GBM can encode both."""
    tr, te = train.copy(), test.copy()
    for col in tr.columns:
        if str(tr[col].dtype) == "category":
            cats = sorted(set(tr[col].astype(str)) | set(te[col].astype(str)))
            tr[col] = pd.Categorical(tr[col].astype(str), categories=cats)
            te[col] = pd.Categorical(te[col].astype(str), categories=cats)
    return tr, te


def reference_class(
    train: pd.DataFrame, test: pd.DataFrame, label: str, keys: list[str], k: float = 20.0
) -> np.ndarray:
    """Shrunken cell mean; unseen cells fall back to the training base rate."""
    base = float(train[label].mean())
    g = train.groupby(keys, observed=True)[label].agg(["sum", "count"])
    rate = ((g["sum"] + k * base) / (g["count"] + k)).rename("p")
    idx = pd.MultiIndex.from_frame(test[keys].astype(str)) if len(keys) > 1 else pd.Index(
        test[keys[0]].astype(str)
    )
    rate.index = (
        pd.MultiIndex.from_tuples([tuple(str(x) for x in t) for t in rate.index])
        if len(keys) > 1
        else pd.Index([str(x) for x in rate.index])
    )
    return rate.reindex(idx).fillna(base).to_numpy()


def fit_gbm(X_tr: pd.DataFrame, y_tr: np.ndarray, X_te: pd.DataFrame) -> tuple[np.ndarray, object]:
    """Fit on train, predict test, and remember the fitted category sets.

    The category sets are stored on the model so that later scoring passes
    (the counterfactual frames in experiment 2) encode unseen categories the
    same way the fit did, rather than silently shifting the encoding.
    """
    X_tr, X_te = align_categories(X_tr, X_te)
    cat_mask = [str(X_tr[c].dtype) == "category" for c in X_tr.columns]
    model = HistGradientBoostingClassifier(categorical_features=cat_mask, **GBM_KWARGS)
    model.fit(X_tr, y_tr)
    model._fit_categories = {
        c: list(X_tr[c].cat.categories) for c in X_tr.columns if str(X_tr[c].dtype) == "category"
    }
    model._fit_columns = list(X_tr.columns)
    return model.predict_proba(X_te)[:, 1], model


def run_ladder(
    frame: pd.DataFrame,
    lotX: pd.DataFrame,
    bidX: pd.DataFrame,
    label: str,
    train_mask: np.ndarray,
    test_mask: np.ndarray,
) -> tuple[pd.DataFrame, dict[str, np.ndarray], object]:
    """Score every rung on the same test rows; return the table and forecasts."""
    ok = frame[label].notna().to_numpy()
    tr = train_mask & ok
    te = test_mask & ok
    y_tr = frame.loc[tr, label].to_numpy(dtype=float)
    y_te = frame.loc[te, label].to_numpy(dtype=float)
    if y_tr.sum() < MIN_POSITIVES or y_te.sum() < MIN_POSITIVES:
        raise DegenerateLabel(
            f"{label}: {int(y_tr.sum())} positives in train, {int(y_te.sum())} in test"
        )
    base = float(y_tr.mean())

    preds: dict[str, np.ndarray] = {"base rate": np.full(len(y_te), base)}
    preds["reference class"] = reference_class(
        frame.loc[tr, ["cpv_division", "region", label]].assign(**{label: y_tr}),
        frame.loc[te, ["cpv_division", "region"]],
        label,
        ["cpv_division", "region"],
    )
    bare = lotX.drop(columns=[c for c in BUYER_HISTORY if c in lotX.columns])
    preds["GBM lot, no buyer history"], _ = fit_gbm(bare.loc[tr], y_tr, bare.loc[te])
    preds["GBM lot, plus buyer history"], _ = fit_gbm(lotX.loc[tr], y_tr, lotX.loc[te])
    price_cols = [c for c in bidX.columns if c not in BIDDER_HISTORY]
    priced = pd.concat([lotX, bidX[price_cols]], axis=1)
    preds["GBM plus the bidder's price"], _ = fit_gbm(priced.loc[tr], y_tr, priced.loc[te])
    full = pd.concat([lotX, bidX], axis=1)
    preds["GBM plus the bidder's price and history"], model = fit_gbm(
        full.loc[tr], y_tr, full.loc[te]
    )

    rows = []
    for name, p in preds.items():
        rows.append({"model": name, **summarise(y_te, p, base)})
    table = pd.DataFrame(rows)
    table.insert(0, "label", label)
    table["train_base_rate"] = base
    return table, {"y": y_te, **preds}, model
