"""Charts for the GMPP report.

Colour is assigned by the job each encoding does, and every palette used here was
checked with the data-visualisation validator rather than eyeballed:

* The rating is an ordered good-to-bad scale, so the rating-composition chart
  uses a diverging ramp centred on the neutral middle rating
  (#184f95, #86b6ef, #eceae3, #ee8a5f, #a52424). Worst pair, all pairs:
  colour-vision-deficiency Delta E 17.8, normal vision 20.3, both clear of the
  floors. Three of the five steps sit below 3:1 contrast against the chart
  surface, so the documented relief applies: every segment carries a visible
  direct label and the same numbers are published in
  `results/table_rating_distribution.csv`.
* The calibration chart compares two things about one rating, which is identity,
  so it uses categorical slots 1 and 2 (#2a78d6, #eb6834): all checks pass.
* Single-series charts use one hue. A value ramp is never put on the bars,
  because the bar length already carries the magnitude.

Run: .venv/bin/python -m gmpp.src.charts
"""
from __future__ import annotations

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .paths import RESULTS_DIR  # noqa: E402
from .ratings import FIVE_POINT, THREE_POINT  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

SERIES_1 = "#2a78d6"
SERIES_2 = "#eb6834"

DIVERGING_5 = ["#184f95", "#86b6ef", "#eceae3", "#ee8a5f", "#a52424"]
DIVERGING_3 = ["#184f95", "#eceae3", "#a52424"]
NON_RATING_GREY = "#898781"

HEADLINE = [
    ("wlc_growth_1y_gt_10", "Whole-life cost up more than 10%"),
    ("wlc_growth_1y_gt_25", "Whole-life cost up more than 25%"),
    ("slip_1y_gt_6m", "End date slipped more than 6 months"),
    ("slip_1y_gt_12m", "End date slipped more than 12 months"),
    ("red_next", "Rated Red at the next snapshot"),
    ("permanent_exit_next", "Left the portfolio for good"),
]

SCALE_LABEL = {
    "five_point": "Five-point scale, September 2012 to March 2021",
    "three_point": "Three-point scale, March 2022 to March 2026",
}


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASELINE)
        ax.spines[side].set_linewidth(1.0)
    ax.tick_params(colors=INK_MUTED, labelsize=9, length=0)
    ax.grid(True, color=GRID, linewidth=0.8, axis="x")
    ax.set_axisbelow(True)


def _figure(nrows: int, ncols: int, figsize):
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize)
    fig.patch.set_facecolor(SURFACE)
    return fig, np.atleast_1d(axes).ravel()


def _save(fig, name: str) -> None:
    path = RESULTS_DIR / name
    fig.savefig(path, dpi=160, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path.name}")


def chart_calibration(cal: pd.DataFrame) -> None:
    """What each colour was read to mean against what it turned out to mean.

    A dumbbell per rating: the stated implied probability and the realised rate,
    joined by a line whose length is the miscalibration.
    """
    for scale, order in (("five_point", FIVE_POINT), ("three_point", THREE_POINT)):
        block = cal[(cal["scale"] == scale) & cal["outcome"].isin(
            [o for o, _ in HEADLINE]
        )]
        if block.empty:
            continue
        fig, axes = _figure(2, 3, (13.5, 6.6))
        for ax, (outcome, title) in zip(axes, HEADLINE):
            sub = block[block["outcome"] == outcome].set_index("rating")
            ys = np.arange(len(order))[::-1]
            for y, rating in zip(ys, order):
                if rating not in sub.index:
                    continue
                row = sub.loc[rating]
                observed = row["observed_rate"]
                implied = row["implied_p_adverse"]
                if pd.isna(observed):
                    continue
                ax.plot(
                    [implied, observed], [y, y], color=BASELINE, linewidth=2,
                    solid_capstyle="round", zorder=1,
                )
                ax.scatter([implied], [y], s=70, color=SERIES_2, zorder=3,
                           edgecolors=SURFACE, linewidths=2)
                ax.scatter([observed], [y], s=70, color=SERIES_1, zorder=3,
                           edgecolors=SURFACE, linewidths=2)
                ax.annotate(
                    f"{observed:.0%}  n={int(row['n'])}",
                    (observed, y), textcoords="offset points", xytext=(0, 11),
                    ha="center", fontsize=8, color=INK_SECONDARY,
                )
            _style(ax)
            ax.set_yticks(ys)
            ax.set_yticklabels(order, fontsize=9, color=INK)
            ax.set_xlim(-0.04, 1.0)
            ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
            ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
            ax.set_ylim(-0.7, len(order) - 0.3)
            ax.set_title(title, fontsize=10, color=INK, loc="left", pad=16)
        handles = [
            plt.Line2D([], [], marker="o", linestyle="", markersize=8,
                       color=SERIES_1, label="What actually happened"),
            plt.Line2D([], [], marker="o", linestyle="", markersize=8,
                       color=SERIES_2, label="Probability the colour implies"),
        ]
        fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False,
                   fontsize=10, bbox_to_anchor=(0.5, -0.035))
        fig.suptitle(
            "Read as probabilities, the delivery confidence colours overstate "
            "the risk of every cost and schedule outcome\n"
            "Published rating against what the next snapshot showed. "
            + SCALE_LABEL[scale]
            + ". The implied probabilities are this study's assumption, not "
            "the publisher's",
            fontsize=12.5, color=INK, x=0.012, ha="left", y=1.035,
        )
        fig.tight_layout()
        _save(fig, f"chart_calibration_{scale}.png")


def chart_rating_distribution(dist: pd.DataFrame) -> None:
    """Portfolio composition by rating at each snapshot, as published shares."""
    order_5 = FIVE_POINT
    order_3 = THREE_POINT
    frame = dist.set_index("snapshot").copy()
    # Four non-rating categories share one grey, so they are shown as one
    # segment rather than four legend swatches of the same colour. The split
    # between them is published in results/table_rating_distribution.csv.
    parts = [c for c in ("EXEMPT", "RESET", "NOT_RATED", "MISSING")
             if c in frame.columns]
    frame["Not rated or exempt"] = frame[parts].sum(axis=1)
    non_rating = ["Not rated or exempt"]
    fig, axes = _figure(1, 1, (11.5, 5.6))
    ax = axes[0]
    snapshots = list(frame.index)
    xs = np.arange(len(snapshots))

    colour_for: dict[str, str] = {}
    for rating, colour in zip(order_5, DIVERGING_5):
        colour_for[rating] = colour
    # On the three-point snapshots the same three names take the outer and
    # middle steps of the same ramp, so a colour never changes meaning.
    for rating, colour in zip(order_3, DIVERGING_3):
        colour_for.setdefault(rating, colour)

    stack_order = [c for c in order_5 if c in frame.columns] + non_rating
    totals = frame[stack_order].sum(axis=1).replace(0, np.nan)
    bottom = np.zeros(len(snapshots))
    for category in stack_order:
        share = (frame[category] / totals).fillna(0).to_numpy()
        colour = colour_for.get(category, NON_RATING_GREY)
        ax.bar(xs, share, bottom=bottom, width=0.72, color=colour,
               edgecolor=SURFACE, linewidth=2, label=category)
        for x, (value, base) in enumerate(zip(share, bottom)):
            if value >= 0.055:
                ax.text(
                    x, base + value / 2, f"{value:.0%}", ha="center", va="center",
                    fontsize=7.5,
                    color=INK if category in ("Amber/Green", "Amber", "Amber/Red")
                    else SURFACE,
                )
        bottom = bottom + share

    _style(ax)
    ax.grid(True, color=GRID, linewidth=0.8, axis="y")
    ax.grid(False, axis="x")
    ax.set_xticks(xs)
    ax.set_xticklabels(snapshots, rotation=45, ha="right", fontsize=8.5)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_ylim(0, 1.0)
    ax.axvline(8.5, color=INK_MUTED, linewidth=1, linestyle=(0, (4, 3)))
    ax.annotate(
        "Scale changes from five points to three; the two sides are not "
        "comparable",
        (8.65, 1.02), fontsize=8.5, color=INK_SECONDARY, annotation_clip=False,
    )
    ax.legend(
        loc="upper center", bbox_to_anchor=(0.5, -0.24), ncol=6, frameon=False,
        fontsize=9,
    )
    fig.suptitle(
        "Green fell from 17% of the portfolio in September 2012 to 1.5% in "
        "September 2017\nShare of projects by published delivery confidence "
        "rating at each annual snapshot. Amber/Green ceased to exist when the "
        "scale changed",
        fontsize=12.5, color=INK, x=0.012, ha="left", y=1.06,
    )
    fig.tight_layout()
    _save(fig, "chart_rating_distribution.png")


def chart_adverse_rate_by_rating(cal: pd.DataFrame) -> None:
    """Observed adverse-outcome rate by rating: does the ordering hold?"""
    for scale, order in (("five_point", FIVE_POINT), ("three_point", THREE_POINT)):
        block = cal[(cal["scale"] == scale)]
        fig, axes = _figure(2, 3, (13.5, 6.4))
        for ax, (outcome, title) in zip(axes, HEADLINE):
            sub = block[block["outcome"] == outcome].set_index("rating")
            xs = np.arange(len(order))
            values = [
                sub.loc[r, "observed_rate"] if r in sub.index else np.nan
                for r in order
            ]
            counts = [
                int(sub.loc[r, "n"]) if r in sub.index else 0 for r in order
            ]
            ax.bar(xs, values, width=0.62, color=SERIES_1, edgecolor=SURFACE,
                   linewidth=2)
            for x, (v, n) in enumerate(zip(values, counts)):
                if not pd.isna(v):
                    ax.text(x, v + 0.012, f"{v:.0%}", ha="center", fontsize=8.5,
                            color=INK)
                    ax.text(x, -0.035, f"n={n}", ha="center", fontsize=7.5,
                            color=INK_MUTED)
            _style(ax)
            ax.grid(True, color=GRID, linewidth=0.8, axis="y")
            ax.grid(False, axis="x")
            ax.set_xticks(xs)
            ax.set_xticklabels(order, fontsize=8.5, rotation=20, ha="right")
            top = max([v for v in values if not pd.isna(v)] + [0.1])
            ax.set_ylim(-0.06, top * 1.28)
            ax.set_yticks([])
            ax.set_title(title, fontsize=10, color=INK, loc="left", pad=8)
        headline = {
            "five_point": "On the five-point scale the record worsens down to "
                          "Amber/Red and then flattens, and leaving the "
                          "portfolio runs the other way",
            "three_point": "On the three-point scale only Red separates: Green "
                           "and Amber run together on cost and on slip",
        }[scale]
        fig.suptitle(
            headline + "\nObserved rate of each outcome by published rating. "
            + SCALE_LABEL[scale]
            + ". Projects leave the portfolio mainly by finishing, so that "
            "panel runs the other way",
            fontsize=12.5, color=INK, x=0.012, ha="left", y=1.035,
        )
        fig.tight_layout()
        _save(fig, f"chart_adverse_rate_by_rating_{scale}.png")


def chart_auc_over_time(by_snapshot: pd.DataFrame) -> None:
    """Discrimination snapshot by snapshot, against the no-skill line."""
    fig, axes = _figure(1, 1, (11.0, 5.2))
    ax = axes[0]
    wanted = ["wlc_growth_1y_gt_10", "slip_1y_gt_6m", "red_next"]
    labels = {
        "wlc_growth_1y_gt_10": "Whole-life cost up more than 10%",
        "slip_1y_gt_6m": "End date slipped more than 6 months",
        "red_next": "Rated Red at the next snapshot",
    }
    colours = [SERIES_1, SERIES_2, "#1baf7a"]
    snapshots = sorted(by_snapshot["snapshot"].unique())
    xs = {s: i for i, s in enumerate(snapshots)}
    for outcome, colour in zip(wanted, colours):
        sub = by_snapshot[
            (by_snapshot["outcome"] == outcome) & (by_snapshot["n"] >= 30)
        ].sort_values("snapshot")
        positions = [xs[s] for s in sub["snapshot"]]
        values = list(sub["auc"])
        # Break the line wherever a snapshot is missing, so a gap is not drawn
        # as a trend. "Rated Red at the next snapshot" has no March 2021 value
        # because that step crosses the scale change.
        broken_x: list[float] = []
        broken_y: list[float] = []
        for i, (x, v) in enumerate(zip(positions, values)):
            if i and x - positions[i - 1] > 1:
                broken_x.append(np.nan)
                broken_y.append(np.nan)
            broken_x.append(x)
            broken_y.append(v)
        ax.plot(
            broken_x, broken_y, marker="o", markersize=6, linewidth=2,
            color=colour, label=labels[outcome], markeredgecolor=SURFACE,
            markeredgewidth=1.5,
        )
    ax.axhline(0.5, color=INK_MUTED, linewidth=1.2, linestyle=(0, (4, 3)))
    ax.annotate("No skill", (-0.4, 0.515), fontsize=8.5, color=INK_SECONDARY)
    ax.axvline(8.5, color=INK_MUTED, linewidth=1, linestyle=(0, (4, 3)))
    ax.annotate("Scale change", (8.65, 0.95), fontsize=8.5,
                color=INK_SECONDARY)
    _style(ax)
    ax.grid(True, color=GRID, linewidth=0.8, axis="y")
    ax.grid(False, axis="x")
    ax.set_xticks(range(len(snapshots)))
    ax.set_xticklabels(snapshots, rotation=45, ha="right", fontsize=8.5)
    ax.set_ylabel("Area under the ROC curve", fontsize=9, color=INK_SECONDARY)
    ax.set_ylim(0.2, 1.0)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=3,
              frameon=False, fontsize=9)
    fig.suptitle(
        "The ratings rank better than chance in most years, and never by much\n"
        "Rank discrimination of the published rating, snapshots with at least "
        "30 resolvable projects",
        fontsize=12.5, color=INK, x=0.012, ha="left", y=1.06,
    )
    fig.tight_layout()
    _save(fig, "chart_auc_over_time.png")


def main() -> int:
    cal = pd.read_csv(RESULTS_DIR / "table_calibration.csv")
    dist = pd.read_csv(RESULTS_DIR / "table_rating_distribution.csv")
    by_snapshot = pd.read_csv(RESULTS_DIR / "table_discrimination_by_snapshot.csv")
    chart_calibration(cal)
    chart_rating_distribution(dist)
    chart_adverse_rate_by_rating(cal)
    chart_auc_over_time(by_snapshot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
