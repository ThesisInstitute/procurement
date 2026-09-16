"""Reference-class forecaster: shrunk cell means over a fixed hierarchy.

Cells are (awarding agency, NAICS 2-digit, contract pricing code, log-value
quintile). A cell with fewer than MIN_CELL_N observations is shrunk towards its
parent, recursively, up to the unconditional training mean. Quintile edges and
every cell mean come from the training period only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_CELL_N = 30
SHRINK_K = float(MIN_CELL_N)

LEVELS = [
    ["awarding_agency_code", "naics2", "type_of_contract_pricing_code", "value_quintile"],
    ["awarding_agency_code", "naics2", "type_of_contract_pricing_code"],
    ["awarding_agency_code", "naics2"],
    ["awarding_agency_code"],
]


def value_quintiles(train_values: pd.Series) -> np.ndarray:
    """Interior quintile edges from the training distribution of log ceiling."""
    v = pd.to_numeric(train_values, errors="coerce").dropna()
    return np.unique(np.quantile(v, [0.2, 0.4, 0.6, 0.8]))


def assign_quintile(values: pd.Series, edges: np.ndarray) -> pd.Series:
    v = pd.to_numeric(values, errors="coerce")
    q = np.digitize(v.to_numpy(dtype=float), edges, right=False).astype(float)
    q[np.isnan(v.to_numpy(dtype=float))] = np.nan
    return pd.Series(q, index=values.index).astype("Int64").astype("string").fillna("NA")


def _key(df: pd.DataFrame, cols: list) -> pd.Series:
    s = df[cols[0]].astype("string").fillna("NA")
    for c in cols[1:]:
        s = s + "||" + df[c].astype("string").fillna("NA")
    return s


class ReferenceClassModel:
    """Fit shrunk cell means on train, predict for any frame."""

    def __init__(self, min_cell_n: int = MIN_CELL_N, shrink_k: float = SHRINK_K):
        self.min_cell_n = min_cell_n
        self.shrink_k = shrink_k
        self.edges_: np.ndarray | None = None
        self.global_mean_: float = float("nan")
        self.tables_: list[pd.DataFrame] = []

    def fit(self, train: pd.DataFrame, y: pd.Series) -> "ReferenceClassModel":
        df = train.copy()
        self.edges_ = value_quintiles(df["log_base_ceiling"])
        df["value_quintile"] = assign_quintile(df["log_base_ceiling"], self.edges_)
        yy = pd.to_numeric(y, errors="coerce")
        ok = yy.notna()
        df = df[ok]
        yy = yy[ok]
        self.global_mean_ = float(yy.mean()) if len(yy) else float("nan")

        parent_pred = pd.Series(self.global_mean_, index=df.index, dtype=float)
        self.tables_ = []
        for cols in reversed(LEVELS):  # coarsest first, so each level has a parent
            k = _key(df, cols)
            grp = pd.DataFrame({"k": k, "y": yy.to_numpy(),
                                "parent": parent_pred.to_numpy()})
            agg = grp.groupby("k", sort=False).agg(
                n=("y", "size"), mean=("y", "mean"), parent=("parent", "mean"))
            agg["shrunk"] = ((agg["n"] * agg["mean"] + self.shrink_k * agg["parent"])
                             / (agg["n"] + self.shrink_k))
            agg["cols"] = "||".join(cols)
            self.tables_.append(agg)
            parent_pred = grp["k"].map(agg["shrunk"]).astype(float)
            parent_pred.index = df.index
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        d = df.copy()
        d["value_quintile"] = assign_quintile(d["log_base_ceiling"], self.edges_)
        pred = np.full(len(d), self.global_mean_, dtype=float)
        for cols, tab in zip(reversed(LEVELS), self.tables_):
            k = _key(d, cols)
            hit = k.map(tab["shrunk"])
            pred = np.where(hit.notna().to_numpy(), hit.to_numpy(dtype=float), pred)
        return pred

    def cell_table(self) -> pd.DataFrame:
        """The finest level's cells, with n, raw mean and shrunk mean."""
        finest = self.tables_[-1].copy()
        cols = LEVELS[0]
        parts = finest.index.to_series().str.split(r"\|\|", expand=True, regex=True)
        parts.columns = cols
        out = pd.concat([parts.reset_index(drop=True),
                         finest.reset_index(drop=True)[["n", "mean", "parent",
                                                        "shrunk"]]], axis=1)
        return out.sort_values("n", ascending=False)
