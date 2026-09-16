"""Score the published Delivery Confidence Assessments as forecasts.

Produces every table in `results/report.md` plus the CSVs behind them.

Run: .venv/bin/python -m gmpp.src.score
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from .paths import RESULTS_DIR
from .ratings import FIVE_POINT, IMPLIED_P_OK, THREE_POINT, implied_p_adverse
from .scoring import (
    auc,
    bootstrap_ci,
    brier_decomposition,
    cluster_bootstrap_ci,
    isotonic_fit,
    spearman,
)

OUTCOMES_PATH = RESULTS_DIR / "panel_outcomes.csv"

RATINGS = set(FIVE_POINT) | set(THREE_POINT)
SCALE_ORDER = {"five_point": FIVE_POINT, "three_point": THREE_POINT}

# Adverse outcomes. Each is 1 when the bad thing happened by the next snapshot.
BINARY_OUTCOMES = {
    "wlc_growth_1y_gt_10": "Baseline whole-life cost up more than 10 per cent",
    "wlc_growth_1y_gt_25": "Baseline whole-life cost up more than 25 per cent",
    "slip_1y_gt_6m": "End date slipped more than 6 months",
    "slip_1y_gt_12m": "End date slipped more than 12 months",
    "red_next": "Rated Red at the next snapshot",
    "worsened_next": "Rating worse at the next snapshot",
    "worsened_next_excl_worst":
        "Rating worse at the next snapshot, excluding projects already on the "
        "worst rating",
    "permanent_exit_next": "Left the portfolio and did not return",
}
CONTINUOUS_OUTCOMES = {
    "wlc_growth_1y": "Baseline whole-life cost growth",
    "slip_1y_months": "End-date slip in months",
}

# A single published units error: HMT reports the Equitable Life Payment Scheme
# whole-life cost as 59,173,700 in a column headed GBP million while its own
# narrative in the same row says "total outturn of GBP 58m". The largest
# genuine figure in the portfolio is around GBP 60bn, so anything above GBP
# 200bn is a units error, not a project.
WLC_IMPLAUSIBLE_ABOVE_GBP_M = 200_000


def load() -> pd.DataFrame:
    frame = pd.read_csv(OUTCOMES_PATH, low_memory=False)
    frame["snapshot_date"] = pd.to_datetime(frame["snapshot_date"])
    frame["snapshot"] = frame["snapshot_date"].dt.date.astype(str)
    frame["is_rating"] = frame["dca_published"].isin(RATINGS)
    frame["p_adverse_implied"] = [
        implied_p_adverse(r, s) if r in RATINGS else np.nan
        for r, s in zip(frame["dca_published"], frame["scale"])
    ]
    implausible = frame["wlc_baseline_gbp_m"] > WLC_IMPLAUSIBLE_ABOVE_GBP_M
    frame["wlc_units_implausible"] = implausible
    for col in ("wlc_growth_1y", "wlc_growth_2y", "wlc_growth_1y_gt_10",
                "wlc_growth_1y_gt_25", "wlc_growth_2y_gt_10", "wlc_growth_2y_gt_25"):
        frame.loc[implausible, col] = np.nan
    # The March 2026 file is in 2024/25 real prices and every earlier file is
    # nominal, so the step into it mixes price bases and is excluded from the
    # cost outcomes by default. `--include-price-break` keeps it.
    # One flag per horizon: a one-year step into the real-prices file, a
    # two-year step into it, and the real-prices row itself for growth against
    # the project's first observed baseline. A single one-step flag left the
    # two-year outcome comparing a nominal March 2024 baseline with a real-price
    # March 2026 one on 101 rated project-years, unflagged.
    def _flag(col: str) -> pd.Series:
        if col not in frame.columns:
            return pd.Series(False, index=frame.index)
        return frame[col].astype(str).str.lower() == "true"

    frame["wlc_price_break"] = _flag("wlc_growth_price_base_break")
    frame["wlc_price_break_2y"] = _flag("wlc_growth_2y_price_base_break")
    frame["wlc_price_break_vs_first"] = _flag(
        "wlc_growth_vs_first_price_base_break"
    )
    return frame


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.replace({"True": 1, "False": 0, True: 1, False: 0}), errors="coerce"
    )


def analysis_frame(
    frame: pd.DataFrame,
    outcome: str,
    *,
    exclude_price_break: bool = True,
    exclude_rebaselined: bool = False,
    only_12_month_steps: bool = False,
    drop_last_snapshots: int = 0,
) -> pd.DataFrame:
    work = frame[frame["is_rating"]].copy()
    work["y"] = _numeric(work[outcome])
    work = work[work["y"].notna()]
    # Dropped AFTER the outcome is resolved. The terminal snapshot contributes
    # no rows to any outcome, so dropping it off the raw snapshot list removed
    # nothing and left the right-censoring variant one step shallower than it
    # claimed to be.
    if drop_last_snapshots:
        snaps = sorted(work["snapshot"].unique())
        keep = snaps[: max(0, len(snaps) - drop_last_snapshots)]
        work = work[work["snapshot"].isin(keep)]
    if exclude_price_break and outcome.startswith("wlc"):
        if "_2y" in outcome:
            work = work[~work["wlc_price_break_2y"]]
        elif "vs_first" in outcome:
            work = work[~work["wlc_price_break_vs_first"]]
        else:
            work = work[~work["wlc_price_break"]]
    if exclude_rebaselined:
        work = work[~work["rebaseline_mentioned_t"].astype(bool)]
    if only_12_month_steps:
        work = work[_numeric(work["interval_months_1"]) == 12]
    return work


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------

def coverage_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for snap, block in frame.groupby("snapshot"):
        rows.append(
            {
                "snapshot": snap,
                "projects": len(block),
                "departments": block["department_norm"].nunique(),
                "with_published_dca": int(block["is_rating"].sum()),
                "exempt": int((block["dca_published"] == "EXEMPT").sum()),
                "not_rated_or_missing": int(
                    block["dca_published"].isin(["NOT_RATED", "MISSING", "RESET"]).sum()
                ),
                "with_wlc": int(block["wlc_baseline_gbp_m"].notna().sum()),
                "with_end_date": int(block["end_date"].notna().sum()),
                "assessor_ipa": int((block["dca_assessor"] == "IPA").sum()),
                "assessor_sro": int((block["dca_assessor"] == "SRO").sum()),
                "scale": block["scale"].iloc[0],
            }
        )
    return pd.DataFrame(rows)


def linkage_table(frame: pd.DataFrame) -> pd.DataFrame:
    """How many project-years link to an adjacent snapshot of the same project."""
    rows = []
    for snap, block in frame.groupby("snapshot"):
        has_next = ~block["absent_next"].astype(str).str.lower().eq("true")
        last = block["absent_next"].isna().all()
        rows.append(
            {
                "snapshot": snap,
                "project_years": len(block),
                "linked_to_next_snapshot": (
                    None if last else int(has_next.sum())
                ),
                "link_rate": (
                    None if last else round(float(has_next.mean()), 4)
                ),
                "key_from_gmpp_id": int(
                    block["project_key_source"].astype(str).str.startswith("gmpp_id").sum()
                ),
                "key_from_name": int((block["project_key_source"] == "name").sum()),
            }
        )
    return pd.DataFrame(rows)


def rating_distribution(frame: pd.DataFrame) -> pd.DataFrame:
    table = pd.crosstab(frame["snapshot"], frame["dca_published"])
    order = [
        c
        for c in ["Green", "Amber/Green", "Amber", "Amber/Red", "Red",
                  "EXEMPT", "RESET", "NOT_RATED", "MISSING"]
        if c in table.columns
    ]
    return table[order].reset_index()


def calibration_table(frame: pd.DataFrame, **kw) -> pd.DataFrame:
    rows = []
    for outcome, label in BINARY_OUTCOMES.items():
        work = analysis_frame(frame, outcome, **kw)
        for scale, block in work.groupby("scale"):
            for rating in SCALE_ORDER[scale]:
                sub = block[block["dca_published"] == rating]
                if sub.empty:
                    rows.append(
                        {
                            "outcome": outcome,
                            "outcome_label": label,
                            "scale": scale,
                            "rating": rating,
                            "n": 0,
                            "observed_rate": None,
                            "implied_p_adverse": round(
                                1 - IMPLIED_P_OK[scale][rating], 4
                            ),
                            "gap": None,
                        }
                    )
                    continue
                observed = float(sub["y"].mean())
                implied = 1 - IMPLIED_P_OK[scale][rating]
                rows.append(
                    {
                        "outcome": outcome,
                        "outcome_label": label,
                        "scale": scale,
                        "rating": rating,
                        "n": len(sub),
                        "observed_rate": round(observed, 4),
                        "implied_p_adverse": round(implied, 4),
                        "gap": round(observed - implied, 4),
                    }
                )
    return pd.DataFrame(rows)


# Outcomes whose definition depends on the rating being scored, so that a
# skill-free forecast does not score 0.5. "Worse next year" cannot happen to a
# project already on the worst rating, and a project one step off the worst can
# only worsen by one step while a Green can worsen by four. Ranking by the
# rating therefore runs backwards even with no information in the rating at all.
RATING_DEPENDENT_OUTCOMES = {
    "worsened_next",
    "worsened_next_excl_worst",
    "red_next",
    "red_or_amberred_next",
}


def structural_null_auc(
    block: pd.DataFrame, outcome: str, draws: int = 400, seed: int = 20260916
) -> tuple[float, float, float]:
    """The AUC a forecast with no information would score on this outcome.

    The next rating is redrawn, independently of the current one, from the
    marginal distribution of next ratings actually observed on these rows, the
    outcome is rebuilt from that draw, and the AUC of the CURRENT rating against
    it is taken. Repeated `draws` times. This holds the arithmetic of the
    outcome fixed and removes only the information, so it is the reference the
    observed AUC has to beat. Returns (mean, 2.5th, 97.5th percentile).

    Returns NaN when the rows do not carry the next rating.
    """
    if "dca_next_rank" not in block.columns or "dca_published_rank" not in block:
        return float("nan"), float("nan"), float("nan")
    now = pd.to_numeric(block["dca_published_rank"], errors="coerce").to_numpy(float)
    nxt = pd.to_numeric(block["dca_next_rank"], errors="coerce").to_numpy(float)
    keep = np.isfinite(now) & np.isfinite(nxt)
    now, nxt = now[keep], nxt[keep]
    if len(now) < 20 or len(np.unique(nxt)) < 2:
        return float("nan"), float("nan"), float("nan")
    scale = str(block["scale"].iloc[0])
    worst = 4.0 if scale == "five_point" else 2.0
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(draws):
        drawn = rng.choice(nxt, size=len(nxt), replace=True)
        if outcome == "worsened_next":
            y = (drawn > now).astype(float)
            scores = now
        elif outcome == "worsened_next_excl_worst":
            mask = now < worst
            y = (drawn[mask] > now[mask]).astype(float)
            scores = now[mask]
        elif outcome == "red_next":
            y = (drawn == worst).astype(float)
            scores = now
        elif outcome == "red_or_amberred_next":
            y = (drawn >= worst - 1).astype(float)
            scores = now
        else:
            return float("nan"), float("nan"), float("nan")
        if len(np.unique(y)) < 2:
            continue
        values.append(auc(scores, y))
    if not values:
        return float("nan"), float("nan"), float("nan")
    arr = np.asarray(values, dtype=float)
    return float(arr.mean()), float(np.percentile(arr, 2.5)), float(
        np.percentile(arr, 97.5)
    )


def discrimination_table(frame: pd.DataFrame, **kw) -> pd.DataFrame:
    rows = []
    for outcome, label in BINARY_OUTCOMES.items():
        work = analysis_frame(frame, outcome, **kw)
        for scale, block in work.groupby("scale"):
            scores = block["dca_published_rank"].to_numpy(dtype=float)
            y = block["y"].to_numpy(dtype=float)
            value = auc(scores, y)
            lo, hi = bootstrap_ci(auc, scores, y)
            # Project-years of the same project are correlated, so the
            # row-level interval is too narrow. The clustered interval
            # resamples whole projects and is the one to read.
            clo, chi = cluster_bootstrap_ci(
                auc, scores, y, clusters=block["project_key"].to_numpy()
            )
            rows.append(
                {
                    "outcome": outcome,
                    "outcome_label": label,
                    "scale": scale,
                    "n": len(block),
                    "n_projects": int(block["project_key"].nunique()),
                    "base_rate": round(float(y.mean()), 4),
                    "auc": round(value, 4) if np.isfinite(value) else None,
                    "auc_lo_rows": round(lo, 4) if np.isfinite(lo) else None,
                    "auc_hi_rows": round(hi, 4) if np.isfinite(hi) else None,
                    "auc_lo": round(clo, 4) if np.isfinite(clo) else None,
                    "auc_hi": round(chi, 4) if np.isfinite(chi) else None,
                    **_null_columns(block, outcome),
                }
            )
    return pd.DataFrame(rows)


def _null_columns(block: pd.DataFrame, outcome: str) -> dict:
    """The no-information reference for this outcome, 0.5 unless the outcome is
    defined in terms of the rating being scored."""
    if outcome not in RATING_DEPENDENT_OUTCOMES:
        return {"null_auc": 0.5, "null_auc_lo": None, "null_auc_hi": None,
                "auc_above_null": None}
    mean, lo, hi = structural_null_auc(block, outcome)
    if not np.isfinite(mean):
        return {"null_auc": None, "null_auc_lo": None, "null_auc_hi": None,
                "auc_above_null": None}
    observed = auc(
        block["dca_published_rank"].to_numpy(dtype=float),
        block["y"].to_numpy(dtype=float),
    )
    return {
        "null_auc": round(mean, 4),
        "null_auc_lo": round(lo, 4),
        "null_auc_hi": round(hi, 4),
        "auc_above_null": round(observed - mean, 4)
        if np.isfinite(observed)
        else None,
    }


def discrimination_by_snapshot(frame: pd.DataFrame, **kw) -> pd.DataFrame:
    rows = []
    for outcome in BINARY_OUTCOMES:
        work = analysis_frame(frame, outcome, **kw)
        for snap, block in work.groupby("snapshot"):
            scores = block["dca_published_rank"].to_numpy(dtype=float)
            y = block["y"].to_numpy(dtype=float)
            value = auc(scores, y)
            rows.append(
                {
                    "outcome": outcome,
                    "snapshot": snap,
                    "n": len(block),
                    "base_rate": round(float(y.mean()), 4) if len(block) else None,
                    "auc": round(value, 4) if np.isfinite(value) else None,
                }
            )
    return pd.DataFrame(rows)


def spearman_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for outcome, label in CONTINUOUS_OUTCOMES.items():
        work = frame[frame["is_rating"]].copy()
        work["v"] = _numeric(work[outcome])
        if outcome.startswith("wlc"):
            work = work[~work["wlc_price_break"] & ~work["wlc_units_implausible"]]
        work = work[work["v"].notna()]
        for scale, block in work.groupby("scale"):
            x = block["dca_published_rank"].to_numpy(dtype=float)
            v = block["v"].to_numpy(dtype=float)
            rho = spearman(x, v)
            lo, hi = bootstrap_ci(spearman, x, v)
            clo, chi = cluster_bootstrap_ci(
                spearman, x, v, clusters=block["project_key"].to_numpy()
            )
            rows.append(
                {
                    "outcome": outcome,
                    "outcome_label": label,
                    "scale": scale,
                    "n": len(block),
                    "n_projects": int(block["project_key"].nunique()),
                    "median": round(float(np.median(v)), 4),
                    "spearman_rho": round(rho, 4) if np.isfinite(rho) else None,
                    "rho_lo_rows": round(lo, 4) if np.isfinite(lo) else None,
                    "rho_hi_rows": round(hi, 4) if np.isfinite(hi) else None,
                    "rho_lo": round(clo, 4) if np.isfinite(clo) else None,
                    "rho_hi": round(chi, 4) if np.isfinite(chi) else None,
                }
            )
    return pd.DataFrame(rows)


def brier_table(frame: pd.DataFrame, **kw) -> pd.DataFrame:
    """Brier and its decomposition for the DCA, the base rate and persistence."""
    rows = []
    for outcome, label in BINARY_OUTCOMES.items():
        work = analysis_frame(frame, outcome, **kw)
        for scale, block in work.groupby("scale"):
            y = block["y"].to_numpy(dtype=float)
            if y.size == 0 or len(np.unique(y)) < 2:
                continue

            # Forecast 1: the published DCA through the stated implied mapping.
            f_dca = block["p_adverse_implied"].to_numpy(dtype=float)
            d = brier_decomposition(f_dca, y, bins=block["dca_published"].to_numpy())
            rows.append({"forecast": "published DCA", "outcome": outcome,
                         "outcome_label": label, "scale": scale, **d.as_dict()})

            # Forecast 2: the in-sample base rate. This is the reference the
            # Brier skill score is defined against, but it uses the answer, so
            # it is not a forecast anyone could have made.
            base = np.full_like(y, float(y.mean()))
            db = brier_decomposition(base, y, bins=np.zeros_like(y))
            rows.append({"forecast": "base rate (in sample)", "outcome": outcome,
                         "outcome_label": label, "scale": scale, **db.as_dict()})

            # Forecast 3: climatology that could actually have been issued. For
            # each snapshot, the outcome rate over the SAME scale era's earlier
            # snapshots only. Snapshots with no prior history are dropped, and
            # the DCA is rescored on the same rows for a like-for-like reading.
            clim, clim_mask = _climatology(block)
            if clim_mask.sum() >= 40 and len(np.unique(y[clim_mask])) == 2:
                dc = brier_decomposition(
                    clim[clim_mask], y[clim_mask],
                    bins=block["snapshot"].to_numpy()[clim_mask],
                )
                rows.append({"forecast": "climatology (prior snapshots only)",
                             "outcome": outcome, "outcome_label": label,
                             "scale": scale, **dc.as_dict()})
                dcd = brier_decomposition(
                    f_dca[clim_mask], y[clim_mask],
                    bins=block["dca_published"].to_numpy()[clim_mask],
                )
                rows.append({"forecast": "published DCA (climatology rows)",
                             "outcome": outcome, "outcome_label": label,
                             "scale": scale, **dcd.as_dict()})

            # Forecast 4: persistence, the rating one snapshot earlier used in
            # place of the current one. Restricted to rows that have one, and
            # the DCA is rescored on the same restricted rows so the comparison
            # is like for like.
            prior = block["dca_prev"]
            has_prior = prior.isin(RATINGS).to_numpy()
            if has_prior.sum() >= 20 and len(np.unique(y[has_prior])) == 2:
                f_prev = block["p_adverse_implied_prev"].to_numpy(dtype=float)[has_prior]
                dp = brier_decomposition(
                    f_prev, y[has_prior], bins=prior.to_numpy()[has_prior]
                )
                rows.append({"forecast": "persistence (previous DCA)",
                             "outcome": outcome, "outcome_label": label,
                             "scale": scale, **dp.as_dict()})
                dd = brier_decomposition(
                    f_dca[has_prior],
                    y[has_prior],
                    bins=block["dca_published"].to_numpy()[has_prior],
                )
                rows.append({"forecast": "published DCA (persistence rows)",
                             "outcome": outcome, "outcome_label": label,
                             "scale": scale, **dd.as_dict()})
    return pd.DataFrame(rows)


def exit_diagnosis_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Why projects left the portfolio, as far as the published data can say.

    The published files do not record whether a project left because it
    finished or because it was cancelled, and the collection carries no
    departure list. What the files do carry is the project's latest approved end
    date at the snapshot before it left. A project whose end date had already
    passed, or was within a year, most likely left by finishing; one that left
    with years still to run did not. This is an INFERENCE from the end-date
    distribution, not a published classification, and it is labelled as such
    wherever it is used.
    """
    work = frame.copy()
    work["snapshot_date"] = pd.to_datetime(work["snapshot_date"])
    work["end_date"] = pd.to_datetime(work["end_date"], errors="coerce")
    work["months_to_end"] = (
        work["end_date"] - work["snapshot_date"]
    ).dt.days / 30.4375
    exits = work[_numeric(work["permanent_exit_next"]) == 1]
    stays = work[_numeric(work["permanent_exit_next"]) == 0]

    buckets = pd.cut(
        exits["months_to_end"],
        bins=[-np.inf, 0, 12, 24, np.inf],
        labels=["end date already passed", "within 12 months",
                "12 to 24 months", "more than 24 months away"],
    )
    rows = []
    for (scale, rating), block in exits.groupby(["scale", "dca_published"]):
        if not block["dca_published"].isin(RATINGS).any():
            continue
        b = buckets.loc[block.index]
        n = int(b.notna().sum())
        if n < 10:
            continue
        counts = b.value_counts()
        rows.append(
            {
                "rating": rating,
                "scale": scale,
                "exits_with_an_end_date": n,
                "projects": int(block.loc[b.notna(), "project_key"].nunique()),
                "end_date_passed_or_within_12m": round(
                    float(
                        (counts.get("end date already passed", 0)
                         + counts.get("within 12 months", 0)) / n
                    ),
                    4,
                ),
                "more_than_24m_still_to_run": round(
                    float(counts.get("more than 24 months away", 0) / n), 4
                ),
                "median_months_to_end_date": round(
                    float(block["months_to_end"].median()), 1
                ),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    # The comparison group is the projects that stayed, within the same era.
    stay_median = (
        stays.groupby("scale")["months_to_end"].median().round(1).to_dict()
    )
    out["median_months_to_end_date_for_projects_that_stayed"] = out["scale"].map(
        stay_median
    )
    order = {"five_point": 0, "three_point": 1}
    rank_in = {s: {r: i for i, r in enumerate(SCALE_ORDER[s])} for s in SCALE_ORDER}
    out = out.sort_values(
        by=["scale", "rating"],
        key=lambda col: col.map(order)
        if col.name == "scale"
        else pd.Series(
            [rank_in[s].get(r, 99) for s, r in zip(out["scale"], out["rating"])],
            index=out.index,
        ),
    ).reset_index(drop=True)
    return out


def _climatology(block: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Per-row forecast equal to the outcome rate at that era's earlier snapshots.

    Strictly backward looking: a row in the third snapshot of an era sees only
    the first two. Rows in the first snapshot of an era have no history and are
    masked out.
    """
    snaps = sorted(block["snapshot"].unique())
    forecast = np.full(len(block), np.nan)
    mask = np.zeros(len(block), dtype=bool)
    snapshot_col = block["snapshot"].to_numpy()
    y = block["y"].to_numpy(dtype=float)
    for i, snap in enumerate(snaps):
        if i == 0:
            continue
        prior = np.isin(snapshot_col, snaps[:i])
        if prior.sum() < 20:
            continue
        rate = float(y[prior].mean())
        here = snapshot_col == snap
        forecast[here] = rate
        mask |= here
    return forecast, mask


def assessor_table(frame: pd.DataFrame, **kw) -> pd.DataFrame:
    """IPA-made versus SRO-made ratings.

    No project-year carries both, so this is a comparison between two disjoint
    groups of projects, not a head-to-head on the same projects.
    """
    rows = []
    for outcome, label in BINARY_OUTCOMES.items():
        work = analysis_frame(frame, outcome, **kw)
        work = work[work["scale"] == "three_point"]
        for assessor, block in work.groupby("dca_assessor"):
            if len(block) < 30:
                continue
            y = block["y"].to_numpy(dtype=float)
            if len(np.unique(y)) < 2:
                continue
            f = block["p_adverse_implied"].to_numpy(dtype=float)
            d = brier_decomposition(f, y, bins=block["dca_published"].to_numpy())
            rows.append(
                {
                    "outcome": outcome,
                    "outcome_label": label,
                    "assessor": assessor,
                    "n": len(block),
                    "base_rate": round(float(y.mean()), 4),
                    "auc": round(
                        auc(block["dca_published_rank"].to_numpy(dtype=float), y), 4
                    ),
                    "brier": round(d.brier, 4),
                    "skill_vs_base_rate": round(d.skill_vs_base_rate, 4),
                }
            )
    return pd.DataFrame(rows)


def breakdown_table(frame: pd.DataFrame, by: str, min_n: int = 40, **kw) -> pd.DataFrame:
    """Discrimination and Brier within a department or a category.

    Split by scale era as well as by the key. A rank of 2 is Amber on the
    five-point scale and Red on the three-point one, so pooling the eras ranks
    a middling project above a failing one and the resulting AUC means nothing.
    Every department and every category in this panel spans both eras, so
    pooling affected every row of both breakdowns rather than a few.
    """
    rows = []
    for outcome, label in BINARY_OUTCOMES.items():
        work = analysis_frame(frame, outcome, **kw)
        for (key, scale), block in work.groupby([by, "scale"]):
            if len(block) < min_n:
                continue
            y = block["y"].to_numpy(dtype=float)
            if len(np.unique(y)) < 2:
                continue
            f = block["p_adverse_implied"].to_numpy(dtype=float)
            d = brier_decomposition(f, y, bins=block["dca_published"].to_numpy())
            rows.append(
                {
                    "outcome": outcome,
                    "outcome_label": label,
                    by: key,
                    "scale": scale,
                    "n": len(block),
                    "n_projects": int(block["project_key"].nunique()),
                    "base_rate": round(float(y.mean()), 4),
                    "auc": round(
                        auc(block["dca_published_rank"].to_numpy(dtype=float), y), 4
                    ),
                    "brier": round(d.brier, 4),
                    "skill_vs_base_rate": round(d.skill_vs_base_rate, 4),
                }
            )
    return pd.DataFrame(rows)


def isotonic_table(frame: pd.DataFrame, splits: dict, **kw) -> pd.DataFrame:
    """Forward-chained isotonic recalibration of the rating.

    The mapping from rating to probability is fitted on the earlier snapshots of
    a scale era and applied to the later ones. It is never fitted and evaluated
    on the same rows, and never fitted across the scale change, because a rank
    on the five-point scale does not mean the same thing on the three-point one.
    """
    rows = []
    for outcome, label in BINARY_OUTCOMES.items():
        work = analysis_frame(frame, outcome, **kw)
        for scale, (train_snaps, test_snaps) in splits.items():
            block = work[work["scale"] == scale]
            train = block[block["snapshot"].isin(train_snaps)]
            test = block[block["snapshot"].isin(test_snaps)]
            if len(train) < 40 or len(test) < 40:
                continue
            y_test = test["y"].to_numpy(dtype=float)
            if len(np.unique(y_test)) < 2:
                continue

            model = isotonic_fit(
                train["dca_published_rank"].to_numpy(dtype=float),
                train["y"].to_numpy(dtype=float),
            )
            f_iso = model.predict(test["dca_published_rank"].to_numpy(dtype=float))
            f_stated = test["p_adverse_implied"].to_numpy(dtype=float)
            f_base = np.full_like(y_test, float(train["y"].mean()))

            bins = test["dca_published"].to_numpy()
            d_iso = brier_decomposition(f_iso, y_test, bins=bins)
            d_stated = brier_decomposition(f_stated, y_test, bins=bins)
            d_base = brier_decomposition(f_base, y_test, bins=np.zeros_like(y_test))
            mapping = {
                r: round(
                    float(
                        model.predict(
                            np.array([float(SCALE_ORDER[scale].index(r))])
                        )[0]
                    ),
                    4,
                )
                for r in SCALE_ORDER[scale]
            }
            rows.append(
                {
                    "outcome": outcome,
                    "outcome_label": label,
                    "scale": scale,
                    "n_train": len(train),
                    "n_test": len(test),
                    "test_base_rate": round(float(y_test.mean()), 4),
                    "brier_stated_mapping": round(d_stated.brier, 4),
                    "brier_perfectly_recalibrated": round(
                        d_stated.uncertainty - d_stated.resolution, 4
                    ),
                    "brier_isotonic": round(d_iso.brier, 4),
                    "brier_train_base_rate": round(d_base.brier, 4),
                    # Two reference forecasts, and they are not the same.
                    # `skill_*` is against the TEST period's own base rate,
                    # which nobody could have issued because it uses the answer.
                    # `skill_*_vs_train_base` is against the TRAINING period's
                    # base rate, which is the forecast a person standing at the
                    # split with the same information would actually have made,
                    # and is therefore the implementable comparison.
                    "skill_stated": round(d_stated.skill_vs_base_rate, 4),
                    "skill_isotonic": round(d_iso.skill_vs_base_rate, 4),
                    "skill_stated_vs_train_base": round(
                        1.0 - d_stated.brier / d_base.brier, 4
                    )
                    if d_base.brier > 0
                    else None,
                    "skill_isotonic_vs_train_base": round(
                        1.0 - d_iso.brier / d_base.brier, 4
                    )
                    if d_base.brier > 0
                    else None,
                    "fitted_mapping": str(mapping),
                }
            )
    return pd.DataFrame(rows)


def sensitivity_table(frame: pd.DataFrame) -> pd.DataFrame:
    variants = {
        "headline": {},
        "excluding project-years whose narrative mentions rebaselining":
            {"exclude_rebaselined": True},
        "12-month steps only (drops September 2019 to March 2021)":
            {"only_12_month_steps": True},
        "including the March 2025 to March 2026 price-base break":
            {"exclude_price_break": False},
        # "Left for good" is right censored: a project last seen at the
        # second-to-last snapshot has only one later snapshot of evidence that
        # it did not come back. Dropping the final two snapshots gives every
        # remaining row at least three.
        "excluding the final two snapshots (right censoring)":
            {"drop_last_snapshots": 2},
    }
    rows = []
    for name, kw in variants.items():
        for outcome in BINARY_OUTCOMES:
            work = analysis_frame(frame, outcome, **kw)
            for scale, block in work.groupby("scale"):
                y = block["y"].to_numpy(dtype=float)
                if y.size < 40 or len(np.unique(y)) < 2:
                    continue
                f = block["p_adverse_implied"].to_numpy(dtype=float)
                d = brier_decomposition(f, y, bins=block["dca_published"].to_numpy())
                rows.append(
                    {
                        "variant": name,
                        "outcome": outcome,
                        "scale": scale,
                        "n": len(block),
                        "base_rate": round(float(y.mean()), 4),
                        "auc": round(
                            auc(block["dca_published_rank"].to_numpy(dtype=float), y), 4
                        ),
                        "brier": round(d.brier, 4),
                        "skill_vs_base_rate": round(d.skill_vs_base_rate, 4),
                    }
                )
    return pd.DataFrame(rows)


def add_previous_rating(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach the same project's rating at the previous snapshot."""
    work = frame.sort_values(["project_key", "snapshot_date"]).copy()
    keyed = work.set_index(["project_key", "snapshot_index"])
    keyed = keyed[~keyed.index.duplicated(keep="first")]
    idx = pd.MultiIndex.from_arrays(
        [work["project_key"], work["snapshot_index"] - 1]
    )
    work["dca_prev"] = keyed["dca_published"].reindex(idx).to_numpy()
    work["scale_prev"] = keyed["scale"].reindex(idx).to_numpy()
    work["dca_prev_rank"] = keyed["dca_published_rank"].reindex(idx).to_numpy()
    # A previous rating on the other scale is not a usable forecast on this one.
    same_scale = work["scale_prev"] == work["scale"]
    work.loc[~same_scale, ["dca_prev", "dca_prev_rank"]] = np.nan
    work["p_adverse_implied_prev"] = [
        implied_p_adverse(r, s) if isinstance(r, str) and r in RATINGS else np.nan
        for r, s in zip(work["dca_prev"], work["scale"])
    ]
    return work.loc[frame.index]


def main() -> int:
    frame = add_previous_rating(load())

    snaps = sorted(frame["snapshot"].unique())
    five = [s for s in snaps if s < "2022-01-01"]
    three = [s for s in snaps if s >= "2022-01-01"]
    # Forward-chained: train on the earlier half of each era, test on the later.
    splits = {
        "five_point": (five[: len(five) - 3], five[len(five) - 3 :]),
        "three_point": (three[:2], three[2:]),
    }

    tables = {
        "coverage": coverage_table(frame),
        "linkage": linkage_table(frame),
        "rating_distribution": rating_distribution(frame),
        "calibration": calibration_table(frame),
        "discrimination": discrimination_table(frame),
        "discrimination_by_snapshot": discrimination_by_snapshot(frame),
        "spearman": spearman_table(frame),
        "brier": brier_table(frame),
        "assessor": assessor_table(frame),
        "by_department": breakdown_table(frame, "department_norm"),
        "by_category": breakdown_table(frame, "annual_report_category", min_n=30),
        "isotonic": isotonic_table(frame, splits),
        "sensitivity": sensitivity_table(frame),
        "exit_diagnosis": exit_diagnosis_table(frame),
    }
    for name, table in tables.items():
        path = RESULTS_DIR / f"table_{name}.csv"
        table.to_csv(path, index=False)
        print(f"{name}: {len(table)} rows -> {path.name}")

    print("\n=== calibration, pooled, headline outcomes ===")
    cal = tables["calibration"]
    print(
        cal[cal["outcome"].isin(["wlc_growth_1y_gt_10", "slip_1y_gt_6m"])]
        .to_string(index=False)
    )
    print("\n=== discrimination ===")
    print(tables["discrimination"].to_string(index=False))
    print("\n=== Brier ===")
    brier = tables["brier"].copy()
    # The Brier a forecast would score if its bins were relabelled with their own
    # observed rates: reliability goes to zero and the resolution it already has
    # is kept. This separates "the ranking is uninformative" from "the colours
    # are read as the wrong numbers".
    brier["brier_perfectly_recalibrated"] = (
        brier["uncertainty"] - brier["resolution"]
    )
    brier.to_csv(RESULTS_DIR / "table_brier.csv", index=False)
    cols = ["forecast", "outcome", "scale", "n", "brier",
            "brier_perfectly_recalibrated", "reliability", "resolution",
            "uncertainty", "skill_vs_base_rate"]
    print(brier[cols].round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
