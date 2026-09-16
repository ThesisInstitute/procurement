"""PNG charts for the report. Matplotlib only, no seaborn, no emoji."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .paths import RESULTS  # noqa: E402

INK = "#1c2a3a"
ACCENT = "#2f6f8f"
ACCENT2 = "#c2703d"
GRID = "#d8dee5"


def _style(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=11, color=INK, loc="left", pad=10)
    ax.set_xlabel(xlabel, fontsize=9, color=INK)
    ax.set_ylabel(ylabel, fontsize=9, color=INK)
    ax.tick_params(labelsize=8, colors=INK)
    ax.grid(True, axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)


def n_by_year(df: pd.DataFrame, path=None) -> str:
    path = path or RESULTS / "n_by_approval_year.png"
    d = df[df["y_satisfactory"].notna()]
    c = d["approval_year"].value_counts().sort_index()
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=160)
    ax.bar(c.index, c.values, color=ACCENT, width=0.75)
    _style(ax, "Joined projects by board approval year",
           "Board approval year", "Projects with a PAD and an IEG rating")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def outcome_rate_by_year(df: pd.DataFrame, path=None) -> str:
    path = path or RESULTS / "outcome_rate_by_approval_year.png"
    d = df[df["y_satisfactory"].notna()]
    g = d.groupby("approval_year")["y_satisfactory"].agg(["mean", "size"])
    g = g[g["size"] >= 10]
    se = (g["mean"] * (1 - g["mean"]) / g["size"]) ** 0.5
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=160)
    ax.errorbar(g.index, g["mean"], yerr=1.96 * se, fmt="o-", color=ACCENT,
                ecolor=GRID, elinewidth=1.2, markersize=4, capsize=2,
                linewidth=1.4)
    ax.axhline(float(d["y_satisfactory"].mean()), color=ACCENT2, linewidth=1.2,
               linestyle="--",
               label=f"pooled base rate {d['y_satisfactory'].mean():.3f}")
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8, frameon=False)
    _style(ax, "Share rated at least Moderately Satisfactory, by approval year",
           "Board approval year", "Share satisfactory")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def calibration(cal: pd.DataFrame, path=None) -> str:
    path = path or RESULTS / "calibration.png"
    fig, ax = plt.subplots(figsize=(5.4, 5.0), dpi=160)
    ax.plot([0, 1], [0, 1], color=GRID, linewidth=1.2, linestyle="--",
            label="perfect calibration")
    colours = {"(b2) cell means, shrunk": ACCENT2,
               "(c) PAD text + structured fields": ACCENT,
               "(d) PAD text only (TF-IDF)": INK}
    for name, sub in cal.groupby("model"):
        s = sub[sub["n"] > 0]
        ax.plot(s["mean_forecast"], s["observed_rate"], "o-",
                color=colours.get(name, INK), markersize=5, linewidth=1.4,
                label=f"{name} (n={int(sub['n'].sum())})")
        for _, r in s.iterrows():
            ax.annotate(f"{int(r['n'])}", (r["mean_forecast"], r["observed_rate"]),
                        textcoords="offset points", xytext=(4, -9), fontsize=6,
                        color=INK)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(fontsize=7.5, frameon=False, loc="upper left")
    _style(ax, "Calibration on the test fold (bin counts annotated)",
           "Mean forecast probability", "Observed share satisfactory")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def disagreement(dis: pd.DataFrame, path=None) -> str:
    path = path or RESULTS / "bank_vs_ieg_disagreement.png"
    d = dis[dis["n"] >= 10]
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=160)
    ax.plot(d["year"], d["bank_higher"], "o-", color=ACCENT2, markersize=4,
            linewidth=1.4, label="Bank rates itself higher than IEG")
    ax.plot(d["year"], d["agree"], "o-", color=ACCENT, markersize=4,
            linewidth=1.4, label="Bank and IEG agree exactly")
    ax.plot(d["year"], d["bank_lower"], "o-", color=INK, markersize=4,
            linewidth=1.4, label="Bank rates itself lower than IEG")
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8, frameon=False)
    _style(ax, "Bank ICR self-rating versus IEG rating of outcome",
           "Board approval year", "Share of rated projects")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def country_ablation(abl: pd.DataFrame, path=None) -> str:
    """Pooled against within-country AUC, side by side.

    The point of the chart: the country-identity-only model has real pooled AUC
    and exactly 0.5 within-country AUC, because it is constant inside a country.
    Any model whose two bars look like that one's is reporting a country effect.
    """
    path = path or RESULTS / "country_ablation.png"
    d = abl.copy()
    y = range(len(d))
    fig, ax = plt.subplots(figsize=(8, 3.4), dpi=160)
    h = 0.38
    ax.barh([i + h / 2 for i in y], d["pooled_auc"], height=h, color=ACCENT2,
            label="pooled AUC")
    ax.barh([i - h / 2 for i in y], d["within_country_auc"], height=h,
            color=ACCENT, label="within-country AUC")
    ax.axvline(0.5, color=INK, linewidth=1.2, linestyle="--",
               label="no discrimination")
    ax.set_yticks(list(y))
    ax.set_yticklabels(d["model"], fontsize=8)
    ax.set_xlim(0.4, 0.7)
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    _style(ax, "What the country identity is worth", "AUC on the test fold", "")
    ax.grid(True, axis="x", color=GRID, linewidth=0.7)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def placebo_null(draws, observed: float, p_value: float, path=None) -> str:
    """The within-country permutation null with the observed statistic marked."""
    path = path or RESULTS / "placebo_null.png"
    fig, ax = plt.subplots(figsize=(7, 3.4), dpi=160)
    ax.hist(draws, bins=40, color=GRID, edgecolor=ACCENT, linewidth=0.5,
            label=f"null, labels permuted within country (n={len(draws)})")
    ax.axvline(0.5, color=INK, linewidth=1.0, linestyle=":",
               label="0.5")
    ax.axvline(observed, color=ACCENT2, linewidth=1.8,
               label=f"observed {observed:.3f} (p = {p_value:.3f})")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    _style(ax, "PAD text model against the within-country permutation null",
           "Within-country AUC", "Permutations")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def evaluation_coverage(cov: pd.DataFrame, min_share: float, path=None) -> str:
    """Share of each approval cohort that has been evaluated by the snapshot.

    This is the right-censoring picture: a project cannot carry an IEG rating
    until it closes and is evaluated, so recent cohorts are represented only by
    their fastest members.
    """
    path = path or RESULTS / "evaluation_coverage.png"
    d = cov[cov["n_with_qualifying_pad"] >= 20].copy()
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=160)
    ax.bar(d["approval_year"].astype(int), d["evaluated_share"], color=ACCENT,
           width=0.75, label="share of cohort with an IEG rating")
    ax.axhline(min_share, color=ACCENT2, linewidth=1.2, linestyle="--",
               label=f"restriction threshold {min_share:.0%}")
    ax2 = ax.twinx()
    ax2.plot(d["approval_year"].astype(int), d["median_implementation_years"],
             "o-", color=INK, markersize=3.5, linewidth=1.3,
             label="median years approval to closing (rated projects)")
    ax2.set_ylabel("Median implementation years", fontsize=9, color=INK)
    ax2.tick_params(labelsize=8, colors=INK)
    ax2.spines["top"].set_visible(False)
    ax.set_ylim(0, 1)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=7.5, frameon=False, loc="lower left")
    _style(ax, "Evaluation coverage and implementation length by approval year",
           "Board approval year", "Share of cohort evaluated")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def skill_by_year(by_year: pd.DataFrame, path=None) -> str:
    """One AUC per test approval year, with the per-year n annotated."""
    path = path or RESULTS / "skill_by_test_year.png"
    d = by_year[by_year["auc_within_year"].notna()].copy()
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=160)
    ax.plot(d["approval_year"], d["auc_within_year"], "o-", color=ACCENT,
            markersize=4, linewidth=1.4, label="AUC within approval year")
    ax.axhline(0.5, color=ACCENT2, linewidth=1.2, linestyle="--",
               label="no discrimination")
    for _, r in d.iterrows():
        ax.annotate(f"n={int(r['n'])}", (r["approval_year"],
                                         r["auc_within_year"]),
                    textcoords="offset points", xytext=(0, 7), fontsize=6,
                    ha="center", color=INK)
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8, frameon=False)
    _style(ax, "PAD text model skill, one test approval year at a time",
           "Board approval year", "AUC")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def text_quality(by_year: pd.DataFrame, cuts: dict, path=None) -> str:
    """OCR-noise proxies by approval year, with the fold boundaries marked.

    The point of the chart: the noisy block is 2004 to 2009, which straddles the
    train/validate boundary and leaves the test fold clean. A caveat that said
    "noisier before roughly 2005, which is exactly the training fold" was wrong
    in both halves.
    """
    path = path or RESULTS / "text_quality.png"
    d = by_year[by_year["n"] >= 5]
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=160)
    ax.bar(d["approval_year"], d["single_char_token_rate"], color=ACCENT,
           width=0.75, label="single-character token rate (median)")
    for x, lbl in ((cuts["train_end"] + 0.5, "train | validate"),
                   (cuts["valid_end"] + 0.5, "validate | test")):
        ax.axvline(x, color=ACCENT2, linewidth=1.3, linestyle="--")
        ax.annotate(lbl, (x, ax.get_ylim()[1]), rotation=90, fontsize=7,
                    color=ACCENT2, ha="right", va="top")
    ax.legend(fontsize=8, frameon=False)
    _style(ax, "OCR noise in the PAD corpus by approval year",
           "Board approval year", "Single-character token rate")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)
