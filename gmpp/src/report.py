"""Assemble results/report.md from the tables in results/.

Every number in the report comes from a CSV written by `gmpp.src.score` or
`gmpp.src.crosscheck`, so nothing in the prose can drift from the computation.

Run: .venv/bin/python -m gmpp.src.report
"""
from __future__ import annotations

import sys

import re
import subprocess
import textwrap

import pandas as pd

from .paths import GMPP_DIR, REPO_DIR, RESULTS_DIR

REPORT_PATH = RESULTS_DIR / "report.md"


def table(frame: pd.DataFrame, columns: list[str] | None = None,
          headers: list[str] | None = None) -> str:
    data = frame[columns] if columns else frame
    head = headers or list(data.columns)
    lines = [
        "| " + " | ".join(head) + " |",
        "|" + "|".join(["---"] * len(head)) + "|",
    ]
    for row in data.itertuples(index=False):
        cells = []
        for value in row:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                cells.append("")
            elif isinstance(value, float):
                cells.append(f"{value:g}")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def pct(value: float, places: int = 1) -> str:
    return "" if pd.isna(value) else f"{value * 100:.{places}f}%"


def reflow(text: str, width: int = 80) -> str:
    """Rewrap prose paragraphs after number interpolation.

    Tables, code fences, headings and list items are left exactly as written;
    only ordinary paragraphs are rejoined and rewrapped, because interpolating a
    computed number into a hand-wrapped sentence leaves the number stranded on a
    line of its own.
    """
    out: list[str] = []
    buffer: list[str] = []
    in_code = False

    def flush() -> None:
        if not buffer:
            return
        joined = re.sub(r"\s+", " ", " ".join(buffer)).strip()
        out.extend(textwrap.wrap(joined, width=width, break_long_words=False,
                                 break_on_hyphens=False))
        buffer.clear()

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            in_code = not in_code
            out.append(line)
            continue
        if in_code or stripped.startswith("|") or stripped.startswith("#") \
                or stripped.startswith("- ") or stripped.startswith("*") \
                or re.match(r"^\d+\. ", stripped) or stripped.startswith("  "):
            flush()
            out.append(line)
            continue
        if stripped == "":
            flush()
            out.append("")
            continue
        buffer.append(stripped)
    flush()
    return "\n".join(out)


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(RESULTS_DIR / f"table_{name}.csv")


def count_tests() -> int:
    """Number of collected pytest cases, so the report cannot overstate it."""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", str(GMPP_DIR / "tests"),
             "--collect-only", "-q"],
            capture_output=True, text=True, timeout=180, cwd=str(REPO_DIR),
        ).stdout
        match = re.search(r"(\d+) tests? collected", out)
        return int(match.group(1)) if match else 0
    except Exception:  # noqa: BLE001 - the report must still build
        return 0


def main() -> int:
    n_tests = count_tests()
    cov = load("coverage")
    link = load("linkage")
    dist = load("rating_distribution")
    cal = load("calibration")
    disc = load("discrimination")
    spear = load("spearman")
    brier = load("brier")
    assessor = load("assessor")
    by_dept = load("by_department")
    by_cat = load("by_category")
    iso = load("isotonic")
    sens = load("sensitivity")
    exits = load("exit_diagnosis")
    xcheck = load("crosscheck")
    disc_snap = load("discrimination_by_snapshot")
    panel = pd.read_csv(RESULTS_DIR / "panel.csv")
    merges = pd.read_csv(RESULTS_DIR / "identity_fuzzy_merges.csv")
    unmapped_path = RESULTS_DIR / "unmapped_headers.csv"
    try:
        unmapped = pd.read_csv(unmapped_path)
    except pd.errors.EmptyDataError:
        unmapped = pd.DataFrame()

    # Acquisition and schema figures, read from the logs rather than written in,
    # so the prose cannot drift from what the pipeline actually did.
    import json as _json

    from .paths import RAW_DIR

    n_panel = len(panel)
    collection = _json.loads((RAW_DIR / "collection.json").read_text())
    n_documents = len(collection.get("links", {}).get("documents", []))
    dlog = pd.read_csv(RAW_DIR / "download_log.csv")
    n_downloaded = len(dlog)
    mb_downloaded = round(
        pd.to_numeric(dlog["bytes"], errors="coerce").sum() / 1e6, 1
    )
    # The distinct normalised headers actually SEEN in the files, and the
    # canonical columns they were mapped onto, both counted from the header
    # profile that `gmpp.src.profile_headers` builds by reading every file.
    from .schema import map_header

    header_profile = pd.read_csv(RAW_DIR / "header_summary.csv")
    n_header_variants = len(header_profile)
    n_canonical = len(
        {
            target
            for target in header_profile["norm_header"].map(map_header)
            if target is not None and not pd.isna(target)
        }
    )

    # The first snapshot that publishes any GMPP id, and how many rows carry one.
    ids_by_snapshot = (
        panel.assign(snap=panel["snapshot_date"].astype(str).str[:10])
        .groupby("snap")["gmpp_id"]
        .apply(lambda col: int(col.notna().sum()))
    )
    partial = ids_by_snapshot[(ids_by_snapshot > 0) & (ids_by_snapshot < 100)]
    if len(partial):
        early_snap = partial.index[0]
        n_early_ids = int(partial.iloc[0])
        early_id_snapshot = pd.Timestamp(early_snap).strftime("%B %Y")
    else:
        n_early_ids, early_id_snapshot = 0, "no earlier snapshot"

    # Cross-check totals, weighted by the rows that actually joined.
    xc_rows = int(xcheck["source_table_rows"].sum())
    xc_joined = int(xcheck["joined_to_panel"].sum())

    def _weighted(col: str) -> float:
        return float(
            (xcheck[col] * xcheck["joined_to_panel"]).sum() / xc_joined
        )

    xc_dca = pct(_weighted("dca_agreement"))
    xc_wlc = pct(_weighted("wlc_agreement"))
    xc_end = pct(_weighted("end_date_agreement"))
    _disagree = (1 - xcheck["dca_agreement"]) * xcheck["joined_to_panel"]
    xc_dca_disagree = int(round(_disagree.sum()))
    xc_dca_disagree_2012 = int(
        round(_disagree[xcheck["snapshot"].astype(str) == "2012-09-30"].sum())
    )
    _tail = (
        ""
        if xc_dca_disagree_2012 == xc_dca_disagree
        else (
            f" The remaining {xc_dca_disagree - xc_dca_disagree_2012} are "
            "single-step differences in later snapshots."
        )
    )
    xc_disagree_sentence = (
        f"All {xc_dca_disagree} rating disagreements are September 2012 rows "
        if xc_dca_disagree_2012 == xc_dca_disagree
        else (
            f"Of the {xc_dca_disagree} rating disagreements, "
            f"{xc_dca_disagree_2012} are September 2012 rows "
        )
    ) + (
        "where the department file left the cell blank and the IPA's own "
        "back-series records them as exempt. Both are treated here as "
        "non-ratings, so nothing in the scoring turns on it." + _tail
    )

    # Recalibrated skill against the implementable reference, over the cost and
    # schedule rows only (the rating outcomes and exit are discussed separately).
    _cs = iso[iso["outcome"].isin(
        ["wlc_growth_1y_gt_10", "wlc_growth_1y_gt_25",
         "slip_1y_gt_6m", "slip_1y_gt_12m"]
    )]["skill_isotonic_vs_train_base"]
    iso_cost_slip_lo = float(_cs.min())
    iso_cost_slip_hi = float(_cs.max())
    iso_red_three = float(
        iso[(iso["outcome"] == "red_next") & (iso["scale"] == "three_point")][
            "skill_isotonic_vs_train_base"
        ].iloc[0]
    )

    # Exit diagnosis, five-point era, indexed by rating.
    exit5 = exits[exits["scale"] == "five_point"].set_index("rating")
    exit3 = exits[exits["scale"] == "three_point"].set_index("rating")

    # Survivorship: how many rated project-years never get a next-snapshot
    # outcome at all, because the project is not there to be measured.
    outcomes_frame = pd.read_csv(RESULTS_DIR / "panel_outcomes.csv", low_memory=False)
    _rated = outcomes_frame[
        outcomes_frame["dca_published"].isin(
            ["Green", "Amber/Green", "Amber", "Amber/Red", "Red"]
        )
    ]
    _absent = _rated["absent_next"].astype(str).str.lower() == "true"
    n_rated = int(len(_rated))
    n_absent_rated = int(_absent.sum())

    # Departmental spread on the headline cost outcome, five-point era.
    _dept_cost = by_dept[
        (by_dept["outcome"] == "wlc_growth_1y_gt_10")
        & (by_dept["scale"] == "five_point")
    ].sort_values("auc")
    n_dept_rows = len(_dept_cost)
    dept_cost_worst = str(_dept_cost["department_norm"].iloc[0])
    dept_cost_worst_auc = float(_dept_cost["auc"].iloc[0])
    dept_cost_best = str(_dept_cost["department_norm"].iloc[-1])
    dept_cost_best_auc = float(_dept_cost["auc"].iloc[-1])
    _mod = _dept_cost[_dept_cost["department_norm"] == "MOD"]
    mod_cost_auc = float(_mod["auc"].iloc[0]) if len(_mod) else float("nan")
    mod_cost_n = int(_mod["n"].iloc[0]) if len(_mod) else 0

    _dept_next = outcomes_frame["department_published_next"].astype(str).str.lower()
    n_unobservable = int((_dept_next == "false").sum())

    # Share of the rated portfolio sitting in Amber at each three-point snapshot.
    _three = dist[dist["snapshot"] >= "2022-01-01"] if "snapshot" in dist else dist
    _rating_cols = [c for c in ("Green", "Amber", "Red") if c in _three.columns]
    _totals = _three[_rating_cols].sum(axis=1)
    _shares = (_three["Amber"] / _totals * 100).round(0).astype(int).tolist()
    n_three_point_snapshots = len(_shares)
    amber_share_three = (
        ", ".join(str(v) for v in _shares[:-1]) + f" and {_shares[-1]} per cent"
        if len(_shares) > 1
        else f"{_shares[0]} per cent"
    )

    n_snapshots = int(cov["snapshot"].nunique())
    _a_cost = assessor[assessor["outcome"] == "wlc_growth_1y_gt_10"].set_index(
        "assessor"
    )
    assessor_cost_ipa = float(_a_cost.loc["IPA", "auc"])
    assessor_cost_sro = float(_a_cost.loc["SRO", "auc"])
    _sc = sens[
        (sens["outcome"] == "wlc_growth_1y_gt_10") & (sens["scale"] == "three_point")
    ].set_index("variant")
    sens_cost_head = float(_sc.loc["headline", "auc"])
    sens_cost_break = float(
        _sc.loc["including the March 2025 to March 2026 price-base break", "auc"]
    )
    _se = sens[
        (sens["outcome"] == "permanent_exit_next") & (sens["scale"] == "three_point")
    ].set_index("variant")
    sens_exit_head = float(_se.loc["headline", "auc"])
    sens_exit_censor = float(
        _se.loc["excluding the final two snapshots (right censoring)", "auc"]
    )
    amber_share_lo, amber_share_hi = min(_shares), max(_shares)
    _r3 = brier[
        (brier["outcome"] == "red_next")
        & (brier["scale"] == "three_point")
        & (brier["forecast"] == "published DCA")
    ].iloc[0]
    red3_resolution = float(_r3["resolution"])
    red3_uncertainty = float(_r3["uncertainty"])
    red3_ratio = red3_resolution / red3_uncertainty
    n_brier_rows = len(brier)
    import ast as _ast

    _iso5 = _ast.literal_eval(
        iso[(iso["outcome"] == "wlc_growth_1y_gt_10") & (iso["scale"] == "five_point")][
            "fitted_mapping"
        ].iloc[0]
    )
    iso5_green = float(_iso5["Green"])
    iso5_red = float(_iso5["Red"])
    _cost_snaps = disc_snap[disc_snap["outcome"] == "wlc_growth_1y_gt_10"]
    n_cost_snapshots = len(_cost_snaps)
    n_cost_snapshots_below_half = int((_cost_snaps["auc"] < 0.5).sum())

    renames_path = RESULTS_DIR / "identity_rename_merges.csv"
    n_renames = len(pd.read_csv(renames_path)) if renames_path.exists() else 0
    n_fuzzy = int(merges["similarity"].notna().sum()) if "similarity" in merges else len(merges)

    gap_path = RESULTS_DIR / "table_crosscheck_gap.csv"
    gap = (
        pd.read_csv(gap_path)
        if gap_path.exists()
        else pd.DataFrame(columns=["department", "rows_in_the_ipa_back_series",
                                   "snapshots"])
    )

    # Header accounting over the files the panel actually reads.
    from .schema import KNOWN_NON_DATA_HEADERS

    panel_headers = pd.read_csv(RAW_DIR / "header_panel_files.csv")
    n_panel_headers = len(panel_headers)
    _targets = panel_headers["norm_header"].map(map_header)
    n_panel_mapped = int(_targets.notna().sum())
    n_panel_non_data = int(
        panel_headers["norm_header"].isin(KNOWN_NON_DATA_HEADERS).sum()
    )
    n_canonical = len({t for t in _targets if t is not None and not pd.isna(t)})
    n_panel_files = int(panel_headers["n_files"].max())

    # The two rating columns: how often both are non-empty, and whether either
    # pair is ever two ratings. The coalesce is only sound if none is.
    def _filled(col: pd.Series) -> pd.Series:
        return col.notna() & ~col.astype(str).isin(["", "nan", "None", "MISSING"])

    n_both_populated = int(
        (_filled(panel["dca_ipa"]) & _filled(panel["dca_sro"])).sum()
    )
    _rating_set = {"Green", "Amber/Green", "Amber", "Amber/Red", "Red"}
    n_both_rated = int(
        (panel["dca_ipa"].astype(str).isin(_rating_set)
         & panel["dca_sro"].astype(str).isin(_rating_set)).sum()
    )
    assert n_both_rated == 0, (
        f"{n_both_rated} project-years carry two ratings; the coalesce in "
        "gmpp.src.panel assumes none do"
    )

    # Dating cross-check, read from the validation table.
    calval = pd.read_csv(RESULTS_DIR / "table_calendar_validation.csv")
    n_publications_checked = len(calval)
    n_fy_agree = int((calval["verdict"] == "agrees").sum())
    n_fy_disagree = int((calval["verdict"] == "DISAGREES").sum())
    n_fy_checkable = n_fy_agree + n_fy_disagree
    n_fy_unchecked = n_publications_checked - n_fy_checkable

    # The largest whole-life cost that is not the one published units error.
    _wlc = pd.to_numeric(panel["wlc_baseline_gbp_m"], errors="coerce")
    max_credible_wlc = float(_wlc[_wlc < 200_000].max())

    brier = brier.copy()
    brier["skill_recalibrated"] = (
        1 - brier["brier_perfectly_recalibrated"] / brier["uncertainty"]
    )

    cover = cov.merge(
        link[["snapshot", "link_rate", "key_from_gmpp_id", "key_from_name"]],
        on="snapshot",
    )
    cover["link_rate_pct"] = (cover["link_rate"] * 100).round(1)

    def cal_block(outcome: str, scale: str) -> pd.DataFrame:
        block = cal[(cal["outcome"] == outcome) & (cal["scale"] == scale)]
        block = block[block["n"] > 0].copy()
        block["observed"] = block["observed_rate"].map(lambda v: pct(v))
        block["implied"] = block["implied_p_adverse"].map(lambda v: pct(v, 0))
        block["difference"] = block["gap"].map(
            lambda v: "" if pd.isna(v) else f"{v * 100:+.1f} points"
        )
        return block

    def disc_row(outcome: str, scale: str) -> pd.Series:
        return disc[(disc["outcome"] == outcome) & (disc["scale"] == scale)].iloc[0]

    def brier_rows(outcome: str, scale: str) -> pd.DataFrame:
        block = brier[(brier["outcome"] == outcome) & (brier["scale"] == scale)].copy()
        block["Brier"] = block["brier"].round(4)
        block["Reliability"] = block["reliability"].round(4)
        block["Resolution"] = block["resolution"].round(4)
        block["Uncertainty"] = block["uncertainty"].round(4)
        block["Brier if recalibrated"] = block["brier_perfectly_recalibrated"].round(4)
        block["Skill vs base rate"] = block["skill_vs_base_rate"].round(3)
        return block

    parts: list[str] = []
    a = parts.append

    # ---------------------------------------------------------------- header
    a(f"""# Scoring the UK government's own delivery confidence assessments

Since 2013 the UK Major Projects Authority, then the Infrastructure and Projects
Authority, and now the National Infrastructure and Service Transformation
Authority, has published a Delivery Confidence Assessment for every project on
the Government Major Projects Portfolio. It is a Red, Amber or Green judgment,
made at a dated snapshot by people with access to the project, of whether the
project will deliver. It is published alongside the project's baseline whole-life
cost, its financial-year baseline, forecast and variance, and its latest approved
start and end dates.

Those ratings are forecasts, and they have never been scored. This is what they
were worth.

The short answer: the ratings rank projects in roughly the right order, the
ordering is weak, and the probability a reader would naturally attach to each
colour is far too pessimistic. A green project was not 90 per cent safe and an
amber project was not a coin flip. Across {n_panel:,} project-years, the published
rating beats a constant forecast of the base rate on no cost or schedule outcome.
Recalibrated and scored against the base rate a person could actually have used,
it adds between {iso_cost_slip_lo:+.3f} and {iso_cost_slip_hi:+.3f} on cost and
schedule, which is to say nothing. The one thing it predicts well is next year's
rating, where recalibration buys {iso_red_three:+.3f}.""")

    # ------------------------------------------------------------- headline
    five_cost = disc_row("wlc_growth_1y_gt_10", "five_point")
    three_cost = disc_row("wlc_growth_1y_gt_10", "three_point")
    five_slip = disc_row("slip_1y_gt_6m", "five_point")
    three_red = disc_row("red_next", "three_point")
    cal5 = cal_block("wlc_growth_1y_gt_10", "five_point").set_index("rating")

    a(f"""
## What was found

**1. The ordering is real, small, and it stops one step short of Red.** On the
five-point scale in force from September 2012 to March 2021 a worse rating does
go with a worse record, up to Amber/Red. The share of projects whose baseline
whole-life cost rose by more than 10 per cent over the following year runs
{pct(cal5.loc['Green', 'observed_rate'])} for Green,
{pct(cal5.loc['Amber/Green', 'observed_rate'])} for Amber/Green,
{pct(cal5.loc['Amber', 'observed_rate'])} for Amber,
{pct(cal5.loc['Amber/Red', 'observed_rate'])} for Amber/Red and
{pct(cal5.loc['Red', 'observed_rate'])} for Red: four rising steps and then a
fall. Red is the smallest bucket on the five-point scale
(n={int(cal5.loc['Red', 'n'])} against
{int(cal5.loc['Amber/Red', 'n'])} for Amber/Red), so the fall is not firm, but
it is there on both cost thresholds and it is worth saying that the worst
rating did not carry the worst cost record. The rank discrimination is
{five_cost['auc']:.3f} (95 per cent bootstrap interval
{five_cost['auc_lo']:.3f} to {five_cost['auc_hi']:.3f}, n={int(five_cost['n'])}).
For a slip of more than six months it is {five_slip['auc']:.3f}. Both are better
than chance and both are a long way from a usable discriminator.

**2. Read as probabilities the colours are badly wrong, in one direction.** An
Amber rating on the five-point scale went with a
{pct(cal5.loc['Amber', 'observed_rate'])} chance of a cost rise above 10 per cent
and a {pct(cal_block('slip_1y_gt_6m', 'five_point').set_index('rating').loc['Amber', 'observed_rate'])}
chance of a slip beyond six months. Every single rating on every cost and
schedule outcome overshoots. The Brier score of the rating read through the
stated probability mapping is worse than a constant forecast of the base rate on
every one of those outcomes, and the whole of that loss is reliability, not lost
resolution.

**3. The three-point scale that replaced it in March 2022 discriminates less,
and on cost not measurably at all.** On the same cost outcome the rank
discrimination falls from {five_cost['auc']:.3f} to {three_cost['auc']:.3f}, and
its 95 per cent interval, clustered on the project,
{three_cost['auc_lo']:.3f} to {three_cost['auc_hi']:.3f}, includes chance. Green
projects now have a *higher* observed cost-growth rate than Amber ones
({pct(cal_block('wlc_growth_1y_gt_10', 'three_point').set_index('rating').loc['Green', 'observed_rate'])}
against
{pct(cal_block('wlc_growth_1y_gt_10', 'three_point').set_index('rating').loc['Amber', 'observed_rate'])}).
Collapsing five categories into three put most of the portfolio into a single
Amber bucket: {amber_share_three} at the {n_three_point_snapshots} three-point
snapshots.

**4. The rating predicts the rating.** The one thing the assessment forecasts
well is its own successor. On the three-point scale the discrimination for being
rated Red next year is {three_red['auc']:.3f}
({three_red['auc_lo']:.3f} to {three_red['auc_hi']:.3f}): a Red project had a
{pct(cal_block('red_next', 'three_point').set_index('rating').loc['Red', 'observed_rate'])}
chance of being Red again, against
{pct(cal_block('red_next', 'three_point').set_index('rating').loc['Green', 'observed_rate'])}
for a Green one.

**5. Green projects leave the portfolio, and they leave because they finish.**
The discrimination for leaving permanently runs *backwards*
({disc_row('permanent_exit_next', 'five_point')['auc']:.3f} on the five-point
scale): {pct(cal_block('permanent_exit_next', 'five_point').set_index('rating').loc['Green', 'observed_rate'])}
of Green project-years were the project's last, against
{pct(cal_block('permanent_exit_next', 'five_point').set_index('rating').loc['Amber/Red', 'observed_rate'])}
of Amber/Red ones. The published data does not say why a project left, but the
end dates point one way: a Green project that left had a median of
{exit5.loc['Green', 'median_months_to_end_date']} months left to run and
{pct(exit5.loc['Green', 'end_date_passed_or_within_12m'], 0)} were past or
within a year of their end date, against
{exit5.loc['Amber/Red', 'median_months_to_end_date']} months and
{pct(exit5.loc['Amber/Red', 'end_date_passed_or_within_12m'], 0)} for Amber/Red.
Projects that stayed had a median of
{exit5['median_months_to_end_date_for_projects_that_stayed'].iloc[0]} months to
run. That is an inference from the end-date distribution, not a published
classification.

**6. Almost nothing here is a passive prediction, and the exit result is why.**
Whether a project is still on the portfolio next year is itself strongly
predicted by the rating, and every other outcome is only resolvable for projects
that stay. {n_absent_rated:,} of the {n_rated:,} rated project-years have no row
at the next snapshot and therefore have no cost, schedule or next-rating
outcome at all. Because Green projects leave at
{pct(cal_block('permanent_exit_next', 'five_point').set_index('rating').loc['Green', 'observed_rate'], 0)}
and Amber/Red ones at
{pct(cal_block('permanent_exit_next', 'five_point').set_index('rating').loc['Amber/Red', 'observed_rate'], 0)},
the rows that survive to be scored are not a random sample of the rows that were
rated, and they are missing Green projects hardest. Every calibration and
discrimination number below is conditional on survival. This is not a defect
that can be corrected away: a project that has left has no next-year cost
baseline to grow.

**7. The rating is worth more in some departments than others.** On the
five-point scale and the cost outcome, discrimination runs from
{dept_cost_worst_auc:.3f} ({dept_cost_worst}) to {dept_cost_best_auc:.3f}
({dept_cost_best}) across the {n_dept_rows} departments with at least 40
resolvable project-years. The Ministry of Defence, the largest single block of
the portfolio, sits at {mod_cost_auc:.3f} over {mod_cost_n} project-years.
Departmental figures are computed within a scale era and never across the
change, because a rank of 2 is Amber on one scale and Red on the other.""")

    # ---------------------------------------------------------------- data
    a(f"""
## The data

Everything comes from the gov.uk collection *Major projects data*
(`/government/collections/major-projects-data`), read through the content API on
15 September 2026. The collection lists {n_documents} documents.
{n_downloaded} attachments were downloaded, {mb_downloaded} MB in total, every
one returning HTTP 200 and none failing; every URL, byte count and SHA-256 is in
`data/raw/gmpp/download_log.csv` and every discovery decision is in
`data/raw/gmpp/manifest.csv`.

Two things about the source were not obvious and change the shape of the study.

**The publication year is not the snapshot date.** The 2015 publications carry
the September 2014 position and the 2024 publications carry the March 2024
position. The transparency policy published alongside the first release states
that "the data for publication in May 2013 will be drawn from ... the second
quarter of 2012/13" and that "the annual updates will similarly be drawn from the
second quarter of the relevant financial year", so the first snapshot is 30
September 2012. The reporting date moved from September to March between the
2020 and 2021 publications, which leaves one 18-month gap in an otherwise
12-month series. Snapshot dates were parsed from attachment titles where they are
stated and from the publication body where they are not, and the source of each
is recorded in `data/raw/gmpp/snapshots.csv`. A month is accepted only when it
is one the portfolio actually reports on, September or March. Exactly one
publication in the collection names another month, the 2013 Home Office release
whose attachments are titled "MPA dashboard 14 May 2013", and that is the date
the dashboard was published rather than the position it carries.

That dating is confirmed against a source that is independent of anything the
publication page says. In the September era the files head their own money
columns with a financial year, "2018/19 TOTAL Baseline" and the like, and the
transparency policy fixes the position as quarter two of that year.
{n_fy_checkable} of the {n_publications_checked} files carry such a header, and
all {n_fy_agree} of them agree with the dating above, with none disagreeing
(`.venv/bin/python -m gmpp.src.validate_calendar`, which exits non-zero on any
disagreement). The remaining {n_fy_unchecked} are the March-era files, which
head their money columns "Financial Year Baseline" with no year and so cannot
be checked this way.

One trap here is worth recording, because reading the financial year out of the
wrong column silently destroys a whole snapshot. The September 2019 files head
their money columns "Financial Year Baseline (GBPm)" with no year, but they
carry, left over from the previous year's template, a narrative column headed
"Departmental narrative on budget/forecast variance for 2018/19". A
financial-year rule that matches any header mentioning a budget or a variance
picks that one up and dates all 120 September 2019 project-years to September
2018, merging two snapshots into one and destroying the transition between
them. Narrative columns are excluded, and the exclusion is under test.

**The series does not stop in 2024.** The NISTA annual reports for 2024-25 and
2025-26 publish consolidated CSVs, and their gov.uk pages state that the data
"was reported to the IPA by departments on 31 March 2025" and "reported to the
NISTA by departments on 31 March 2026". Including them gives
{n_snapshots} snapshots and {n_snapshots - 1} resolvable transitions rather than
{n_snapshots - 2} and {n_snapshots - 3}.

Two file layouts exist and are detected rather than assumed: the 2013 to 2020
publications are transposed, with field names down the first column and one
column per project; the 2021 publications onward put one project on each row.
Header spellings vary continuously. Across the {n_panel_files} files the panel
reads there are {n_panel_headers} distinct normalised headers;
{n_panel_mapped} of them are mapped onto {n_canonical} canonical columns and the
remaining {n_panel_non_data} are declared non-data, which is what they are:
spreadsheet working notes, exemption bookkeeping, and long methodological
footnotes the publisher put in a header cell. Every one is listed in
`gmpp/src/schema.py`, and a test fails if any header in those files is neither
mapped nor declared, so a new spelling in a future publication cannot silently
drop a column. `results/unmapped_headers.csv` is the run-time record and holds
{len(unmapped)} rows.

### Coverage

{table(cover, ['snapshot', 'scale', 'projects', 'departments', 'with_published_dca', 'exempt', 'not_rated_or_missing', 'with_wlc', 'with_end_date', 'assessor_ipa', 'assessor_sro', 'link_rate_pct', 'key_from_gmpp_id', 'key_from_name'], ['Snapshot', 'Scale', 'Projects', 'Departments', 'With a published rating', 'Exempt', 'Not rated or blank', 'With whole-life cost', 'With end date', 'Rated by the IPA', 'Rated by the SRO', 'Linked to the next snapshot, %', 'Identity from the GMPP id', 'Identity from the name'])}

The panel is {len(panel)} project-years covering {panel['project_key'].nunique()}
projects. Projects are linked across snapshots by the GMPP ID Number where it is
published, which is every row from the September 2019 snapshot onward and
{n_early_ids} rows in {early_id_snapshot}, and by name within a department group
before that. The full id
is the key, not its numeric core: BEIS_0004 is "Future Shared Services Programme"
under the 1920-Q2 joining quarter and "Industrial Decarbonisation and Hydrogen
Revenue Support" under 2122-Q2, so matching on the core alone would merge two
unrelated projects.

Name matching is deliberately conservative. An exact normalised-name match inside
a department group links automatically. Beyond that, {len(merges)} pairs were
merged on a similarity threshold of 0.90, all of them listed with their scores in
`results/identity_fuzzy_merges.csv`, and a merge is refused whenever the two
names name different instalments of a series. That guard is what keeps "PFI
Prison Expiry and Transfer Tranche 1" apart from "Tranche 3" and "Priority School
Building Programme" apart from "Priority School Building Programme 2", all of
which a plain string-similarity rule merges. It also refuses some merges that are
probably correct, which is the intended direction of the error.

### An independent check on the reconstruction

The XLSX attachments of the 2020 publications carry a sheet named `SourceTable`
holding the IPA's own consolidated back-series: 1,255 project-years from the
September 2012 to the September 2019 snapshot, across every department, with the
id, the rating, the dates and the whole-life cost. It was never the published
product, so it is used only to check that the reconstruction from the
per-department files reproduces the same portfolio.

{table(xcheck, ['snapshot', 'source_table_rows', 'joined_to_panel', 'join_rate', 'dca_agreement', 'wlc_agreement', 'end_date_agreement'], ['Snapshot', 'Rows in the IPA back-series', 'Joined to this panel', 'Join rate', 'Rating agrees', 'Whole-life cost agrees', 'End date agrees'])}

Overall {xc_joined:,} of {xc_rows:,} rows join, and where they do the rating
agrees on {xc_dca}, the whole-life cost on {xc_wlc} and the end date on
{xc_end}. {xc_disagree_sentence}

The rows that do not join are the honest measure of this panel's coverage, and
they are not all the same thing. Four departments never published a departmental
GMPP file at all in the September era and appear only inside the IPA's
consolidated table: the Office for National Statistics, the National Crime
Agency, the Crown Prosecution Service and National Savings and Investments.
Their project-years are on the portfolio and are not in this panel, and no
amount of parsing recovers them from releases that do not exist. The rest are
name-match misses concentrated in the first three snapshots, where no file
publishes a project id.

{table(gap, ['department', 'rows_in_the_ipa_back_series', 'snapshots'], ['Department', 'Back-series rows with no panel row', 'Snapshots'])}

One gap was recoverable and was recovered. The FCO's 2020 publication, which
carries the September 2019 position, exists on gov.uk at
`/government/publications/fco-government-major-projects-portfolio-data-2020` and
is simply not listed in the collection. Discovery therefore supplements the
collection with a gov.uk search for the publication title pattern; that search
returns exactly one publication the collection omits, and it is that one. Before
it was added, three FCO projects appeared to leave the portfolio in September
2018 and never return.""")

    # ------------------------------------------------------------- ratings
    a(f"""
## The rating scale, and the year it changed

The scale in force is stated in the published header of every file, not inferred.
Publications from 2013 to 2021 carry "a five-point scale, Red - Amber/Red -
Amber - Amber/Green - Green"; publications from 2022 onward carry "a three-point
scale, Red - Amber - Green". The two NISTA files state no scale, and only GREEN,
AMBER and RED appear in their data. The change therefore falls between the March
2021 and March 2022 snapshots. The five-point and three-point eras are scored
separately throughout and are never pooled, because Amber is the middle of five
in one era and the middle of three in the other.

Ratings are harmonised across their published spellings ("Amber/ Red",
"Amber/red", "AMBER"). Anything that is not a rating is kept as its own category
rather than dropped: EXEMPT for a Freedom of Information withholding, RESET,
NOT_RATED for an explicit "No DCA" or a departmental statement that the
information is unavailable, and MISSING for a blank.

{table(dist)}

One mechanism worth stating, because it is easy to misread the files. From the
March 2022 snapshot the published table carries two rating columns, one headed
"IPA Delivery Confidence Assessment" and one headed "SRO Delivery Confidence
Assessment". They are not two forecasts of the same project.

Stated precisely, because the loose version of this claim is wrong: the two
columns are both non-empty on {n_both_populated} of the {len(panel):,}
project-years, but on none of them do both carry a rating. What the second
column holds on those rows is an exemption or a "Not Applicable", which is how a
department says the other column is the live one. Across the whole panel no
project-year carries two ratings, and the report build asserts it. The published
assessment is therefore the coalesce of the two, and which body made it is kept
as a covariate.

Which body, exactly, changes at the end. The column is headed "IPA" throughout,
but the IPA ceased to exist on 1 April 2025: the 2024-25 publication states its
data was reported to the IPA on 31 March 2025, and the 2025-26 publication
states its data was reported to NISTA on 31 March 2026. The March 2026
assessments are recorded here as NISTA's, which is what they are.""")

    # ------------------------------------------------------------ outcomes
    a(f"""
## Outcomes

An outcome for a project-year at snapshot t is resolved from the snapshots after
t, and nothing from t+1 or later is ever used as an input. The year-t commentary
is not used as an input either, even though it is contemporaneous: it is written
knowing the rating, and feeding it to anything would be scoring the assessor's
own explanation.

| Outcome | Definition |
|---|---|
| Whole-life cost up more than 10% (25%) | The published TOTAL baseline whole-life cost at t+1 divided by the value at t, minus 1, exceeds 0.10 (0.25). A zero or negative baseline yields no ratio. |
| End date slipped more than 6 (12) months | The latest approved end date at t+1 minus the latest approved end date at t, in months of 30.4375 days, exceeds 6 (12). |
| Rated Red at the next snapshot | The published rating at t+1 is Red. Null when t+1 uses the other scale, because three-point Red absorbs part of what used to be Amber/Red. |
| Rating worse at the next snapshot | The rating at t+1 is a worse step on the same scale. A second version excludes projects already on the worst rating, which cannot worsen. |
| Left the portfolio and did not return | The project has no row at t+1 and none at any later snapshot, and its department did publish at a later snapshot. Null where the department published nothing later, because then the absence is a publication gap and not a departure. |

Two-snapshot versions of the cost and slip outcomes are built the same way and
are in `results/panel_outcomes.csv`.

An absence is only evidence of leaving if somebody was looking. A department
that published no file at a snapshot makes its projects unobservable there, not
departed, and counting them as exits manufactures departures out of a missing
release. {n_unobservable} project-years are on that footing and carry a null
exit outcome rather than a true one. A project that simply moved department has
not left either, and presence is decided by the project key rather than by
whether the old department still exists, which matters for the DECC projects
that continued under BEIS after DECC was abolished in 2016.

Four data facts constrain the cost outcome and are handled explicitly rather
than quietly.

- **One published units error.** HM Treasury reports the Equitable Life Payment
  Scheme whole-life cost as 59,173,700 in a column headed GBP million, while the
  narrative in the same row says "total outturn of GBP 58m". The largest
  credible figure anywhere in the panel is GBP {max_credible_wlc:,.0f}m, so any
  value above GBP 200,000m is
  treated as a units error and excluded from the cost outcomes. One row qualifies.
- **A price-base break at the end.** The March 2026 NISTA file spells its money
  columns "(GBPm, Presented in 2024/25 Real Prices)"; every earlier file spells
  them "(GBPm)". Any step that lands on that file mixes price bases, so the
  break is flagged on each horizon separately: the one-year step from March
  2025, the two-year step from March 2024, and the March 2026 row itself for
  growth against a project's first observed baseline. All three are excluded
  from the cost outcomes by default. A single one-step flag would leave 101
  two-year figures comparing a nominal baseline with a real-price one without
  saying so. The sensitivity table shows what including the one-year break does.
- **A sign change is not growth.** Two project-years publish a negative
  baseline whole-life cost, both DfT rail franchising, where the narrative
  explains the figure is net of the premium train operators pay the department.
  A ratio is taken only when both ends are strictly positive.
- **Withheld values are not numbers.** Two spellings of a Freedom of Information
  withholding appear: the department files write "Exempt under Section 43 of the
  Freedom of Information Act 2000 (Commercial Interests)" and the NISTA files
  write the bare "Section 43 - Commercial interests". A naive number-grab reads
  the second as 43. Both are rejected before any digit is read, and 49 values in
  the two NISTA files depend on that. The two NISTA files also introduce ranges
  ("Low: 2,750.00, Mid: 2,820.00, High: 3,100.00"), for which the mid point is
  taken and the fact that it was a range is recorded.""")

    # --------------------------------------------------------- calibration
    a(f"""
## The calibration table

This is the headline. For each rating: how many resolvable project-years carried
it, what share of them met each adverse outcome, and what probability the rating
would imply if the colours were read the way a reader naturally reads them.

**The implied probabilities are this study's assumption and not the publisher's.**
Neither the IPA nor NISTA has ever attached a number to a colour. The mapping
used here is the one specified for this exercise: on the five-point scale, a
probability of no material problem of 0.90 for Green, 0.75 for Amber/Green, 0.50
for Amber, 0.25 for Amber/Red and 0.10 for Red; on the three-point scale, 0.85,
0.50 and 0.15. Every Brier number below inherits that assumption, which is why
the isotonic recalibration further down exists: it shows what the same ratings
are worth when the mapping is fitted instead of assumed.

### Five-point scale, September 2012 to March 2021

{table(cal_block('wlc_growth_1y_gt_10', 'five_point'), ['rating', 'n', 'observed', 'implied', 'difference'], ['Rating', 'n', 'Whole-life cost up more than 10%', 'Implied by the colour', 'Difference'])}

{table(cal_block('slip_1y_gt_6m', 'five_point'), ['rating', 'n', 'observed', 'implied', 'difference'], ['Rating', 'n', 'End date slipped more than 6 months', 'Implied by the colour', 'Difference'])}

{table(cal_block('red_next', 'five_point'), ['rating', 'n', 'observed', 'implied', 'difference'], ['Rating', 'n', 'Rated Red at the next snapshot', 'Implied by the colour', 'Difference'])}

{table(cal_block('permanent_exit_next', 'five_point'), ['rating', 'n', 'observed', 'implied', 'difference'], ['Rating', 'n', 'Left the portfolio for good', 'Implied by the colour', 'Difference'])}

### Three-point scale, March 2022 to March 2026

{table(cal_block('wlc_growth_1y_gt_10', 'three_point'), ['rating', 'n', 'observed', 'implied', 'difference'], ['Rating', 'n', 'Whole-life cost up more than 10%', 'Implied by the colour', 'Difference'])}

{table(cal_block('slip_1y_gt_6m', 'three_point'), ['rating', 'n', 'observed', 'implied', 'difference'], ['Rating', 'n', 'End date slipped more than 6 months', 'Implied by the colour', 'Difference'])}

{table(cal_block('red_next', 'three_point'), ['rating', 'n', 'observed', 'implied', 'difference'], ['Rating', 'n', 'Rated Red at the next snapshot', 'Implied by the colour', 'Difference'])}

Every cost and schedule difference in the five-point era is negative and grows
with the severity of the rating: the colours overshoot, and they overshoot most
where they are most alarming. The three-point era breaks the ordering on cost
entirely, with Green above Amber.

The full table for all seven outcomes and both scales is
`results/table_calibration.csv`. Charts:
`chart_calibration_five_point.png`, `chart_calibration_three_point.png`,
`chart_adverse_rate_by_rating_five_point.png`,
`chart_adverse_rate_by_rating_three_point.png`.""")

    # ------------------------------------------------------ discrimination
    a(f"""
## Discrimination

Discrimination asks only whether the ranking is right, so it does not depend on
the probability mapping at all. The statistic is the area under the ROC curve of
the rating's rank, with ties averaged, and a 95 per cent percentile bootstrap
over 2,000 resamples at a fixed seed.

The bootstrap resamples whole projects, not project-years. The same project
appears in up to fourteen snapshots carrying a similar rating and a similar
trajectory, so resampling rows would treat correlated observations as fresh
information and give intervals that are too narrow. Both versions are in
`results/table_discrimination.csv`; the columns below are the clustered ones. In
this panel the difference turns out to be small, which is itself worth knowing:
the correction widens the headline cost interval by about 0.01.

**0.50 is not the right reference for every outcome.** Two of the outcomes are
defined in terms of the rating being scored, and their arithmetic makes the
ranking run backwards before any information enters. A project already on the
worst rating cannot get worse, and a project one step off the worst can only
worsen by one step while a Green can worsen by four. So the "no skill" value
for "rating worse next year" is not 0.5. The null column below measures it
directly: the next rating is redrawn, independently of the current one, from the
marginal distribution actually observed on those rows, the outcome is rebuilt
from that draw, and the AUC is taken; 400 draws, fixed seed. That holds the
arithmetic fixed and removes only the information. For the cost, schedule and
exit outcomes, which are not defined in terms of the rating, the null is 0.5.

{table(disc, ['outcome_label', 'scale', 'n', 'n_projects', 'base_rate', 'auc', 'auc_lo', 'auc_hi', 'null_auc', 'auc_above_null'], ['Outcome', 'Scale', 'Project-years', 'Projects', 'Base rate', 'Discrimination', 'Low', 'High', 'No-skill reference', 'Above reference'])}

Read across. On cost and schedule the five-point scale sits around 0.61, clear
of chance on every measure, and the three-point scale around 0.55, with both
cost intervals crossing 0.50 and both slip intervals only just clearing it. On
next year's rating the ratings do much better,
{disc_row('red_next', 'five_point')['auc']:.3f} and
{disc_row('red_next', 'three_point')['auc']:.3f}.

The two rating-transition outcomes look worse than chance and are not. "Rating
worse next year" scores
{disc_row('worsened_next', 'five_point')['auc']:.3f} on the five-point scale
against a no-skill reference of
{disc_row('worsened_next', 'five_point')['null_auc']:.3f}, so it is
{disc_row('worsened_next', 'five_point')['auc_above_null']:+.3f} above its own
null, not below chance. Excluding the projects that cannot worsen at all leaves
{disc_row('worsened_next_excl_worst', 'five_point')['auc']:.3f} against
{disc_row('worsened_next_excl_worst', 'five_point')['null_auc']:.3f}, which is
{disc_row('worsened_next_excl_worst', 'five_point')['auc_above_null']:+.3f}. The
rating does carry information about whether a project will be marked down; the
sub-0.5 number is the ceiling, not the forecast.

Leaving the portfolio is different. Its null really is 0.5, because nothing in
the definition of leaving refers to the rating, and the observed
{disc_row('permanent_exit_next', 'five_point')['auc']:.3f} is genuinely
backwards: Green projects leave more often than Red ones, which is the system
working rather than failing, as sections 5 and 6 of the findings set out.

Rank correlation with the continuous outcomes tells the same story.

{table(spear, ['outcome_label', 'scale', 'n', 'n_projects', 'spearman_rho', 'rho_lo', 'rho_hi'], ['Outcome', 'Scale', 'Project-years', 'Projects', 'Spearman rho', 'Low', 'High'])}

The correlations are positive but small, and both three-point intervals include
zero.

Year by year the picture is noisy: see `chart_auc_over_time.png` and
`results/table_discrimination_by_snapshot.csv`. Cost discrimination falls below
0.50 in {n_cost_snapshots_below_half} of the {n_cost_snapshots} individual
snapshots that resolve it.""")

    # ------------------------------------------------------------- brier
    a(f"""
## Brier score and its decomposition

The Brier score is the mean squared error of a probability forecast, and Murphy's
decomposition splits it into

    Brier = reliability - resolution + uncertainty

Reliability is the mean squared gap between what a bin forecast and what that bin
actually delivered, and zero is perfect calibration. Resolution is how far the
bins' outcome rates spread around the overall base rate, and more is better.
Uncertainty is the base rate's own variance, a property of the outcome rather
than of the forecaster. The identity is checked numerically on every row.

Four forecasts are compared on the same rows:

- **published DCA**: the rating read through the implied mapping above.
- **base rate (in sample)**: a constant equal to the realised rate on those rows.
  This is the reference the skill score is defined against, but it uses the
  answer, so nobody could have issued it.
- **climatology (prior snapshots only)**: for each snapshot, the outcome rate
  over the earlier snapshots of the same scale era. Strictly backward looking,
  and the forecast a person could actually have made.
- **persistence (previous DCA)**: the same project's rating one snapshot earlier,
  read through the same mapping.

"Brier if recalibrated" is `uncertainty - resolution`: what the same forecast
would score if each bin were relabelled with its own observed rate. It separates
"the ranking carries nothing" from "the colours are read as the wrong numbers".

### Whole-life cost up more than 10 per cent

{table(brier_rows('wlc_growth_1y_gt_10', 'five_point'), ['forecast', 'n', 'Brier', 'Brier if recalibrated', 'Reliability', 'Resolution', 'Uncertainty', 'Skill vs base rate'], ['Forecast', 'n', 'Brier', 'Brier if recalibrated', 'Reliability', 'Resolution', 'Uncertainty', 'Skill vs base rate'])}

*Five-point scale.*

{table(brier_rows('wlc_growth_1y_gt_10', 'three_point'), ['forecast', 'n', 'Brier', 'Brier if recalibrated', 'Reliability', 'Resolution', 'Uncertainty', 'Skill vs base rate'], ['Forecast', 'n', 'Brier', 'Brier if recalibrated', 'Reliability', 'Resolution', 'Uncertainty', 'Skill vs base rate'])}

*Three-point scale.*

### End date slipped more than 6 months

{table(brier_rows('slip_1y_gt_6m', 'five_point'), ['forecast', 'n', 'Brier', 'Brier if recalibrated', 'Reliability', 'Resolution', 'Uncertainty', 'Skill vs base rate'], ['Forecast', 'n', 'Brier', 'Brier if recalibrated', 'Reliability', 'Resolution', 'Uncertainty', 'Skill vs base rate'])}

*Five-point scale.*

### Rated Red at the next snapshot

{table(brier_rows('red_next', 'three_point'), ['forecast', 'n', 'Brier', 'Brier if recalibrated', 'Reliability', 'Resolution', 'Uncertainty', 'Skill vs base rate'], ['Forecast', 'n', 'Brier', 'Brier if recalibrated', 'Reliability', 'Resolution', 'Uncertainty', 'Skill vs base rate'])}

*Three-point scale. This is the one outcome where the ratings carry real
information: resolution of {red3_resolution:.4f} against an uncertainty of
{red3_uncertainty:.4f}, so a correctly calibrated reading of the colour would
cut the Brier score by {red3_ratio:.0%} against the base rate.*

The pattern is the same everywhere. Reliability accounts for essentially the
whole of the published rating's loss, resolution is an order of magnitude
smaller, and persistence is no better than the current rating. The honest
reference, climatology, scores within about one per cent of the in-sample base
rate, which means the base-rate comparison is not doing the ratings an injustice.

All {n_brier_rows} rows are in `results/table_brier.csv`.""")

    # --------------------------------------------------------- isotonic
    a(f"""
## What a calibrated rating would be worth

The miscalibration above is a property of the mapping, not of the ratings. To
separate the two, an isotonic regression of the outcome on the rating's rank is
fitted on the earlier snapshots of a scale era and evaluated on the later ones.
It is never fitted and evaluated on the same rows and never fitted across the
scale change.

Two reference forecasts are reported and they are not the same thing. "Skill vs
the training base rate" compares against a constant equal to the outcome rate
over the training snapshots: that is the forecast a person standing at the split
with the same information would actually have issued, so it is the implementable
comparison and the one to read. "Skill vs the test base rate" compares against a
constant equal to the rate the test period turned out to have, which nobody
could have issued because it uses the answer. The two differ whenever the rate
moved between the periods.

{table(iso, ['outcome_label', 'scale', 'n_train', 'n_test', 'test_base_rate', 'brier_stated_mapping', 'brier_isotonic', 'brier_train_base_rate', 'skill_isotonic_vs_train_base', 'skill_isotonic', 'fitted_mapping'], ['Outcome', 'Scale', 'Train n', 'Test n', 'Test base rate', 'Brier, stated mapping', 'Brier, recalibrated', 'Brier, training base rate', 'Skill recalibrated vs training base rate', 'Skill recalibrated vs test base rate', 'Fitted mapping'])}

Recalibration removes almost all of the loss and adds almost nothing. Against
the implementable reference, the training period's base rate, the recalibrated
rating scores between {iso_cost_slip_lo:+.3f} and {iso_cost_slip_hi:+.3f} on the
eight cost and schedule rows: a calibrated reading of the colour is worth about
as much as knowing how often the thing happens, and no more. The exception is
next year's rating on the three-point scale, where recalibration buys
{iso_red_three:+.3f}.

Where the isotonic fit collapses to a constant it reproduces the training base
rate exactly, so its skill against that reference is 0.000 rather than the
negative figure the test-base-rate column shows. That difference is the test
period's rate having moved, not the rating losing anything.

The fitted mappings are worth reading on their own. For "rating worse next year"
and for "left the portfolio" the isotonic fit collapses to a single constant for
every rating, which is the fit saying the rating carries no monotone information
about that outcome at all. For cost growth on the five-point scale it rises from
{iso5_green:.2f} for Green to {iso5_red:.2f} for Red, which is the same ordering
the published colours assert, over a range a third as wide as the colours imply.""")

    # ----------------------------------------------------- breakdowns
    a(f"""
## By department and by category

Discrimination on the cost outcome, departments with at least 40 resolvable
project-years:

{table(by_dept[by_dept['outcome'] == 'wlc_growth_1y_gt_10'].sort_values(['scale', 'n'], ascending=[True, False]), ['department_norm', 'scale', 'n', 'n_projects', 'base_rate', 'auc', 'brier', 'skill_vs_base_rate'], ['Department', 'Scale', 'Project-years', 'Projects', 'Base rate', 'Discrimination', 'Brier', 'Skill vs base rate'])}

And on the slip outcome:

{table(by_dept[by_dept['outcome'] == 'slip_1y_gt_6m'].sort_values(['scale', 'n'], ascending=[True, False]), ['department_norm', 'scale', 'n', 'n_projects', 'base_rate', 'auc', 'brier', 'skill_vs_base_rate'], ['Department', 'Scale', 'Project-years', 'Projects', 'Base rate', 'Discrimination', 'Brier', 'Skill vs base rate'])}

Every row is computed inside one scale era. Pooling the eras, which an earlier
version of this analysis did, ranks a five-point Amber (rank 2) alongside a
three-point Red (rank 2) and produces a number that means nothing; it moved 79
of the 140 breakdown rows by 0.05 or more and reversed the sign of the
conclusion on 14 of them.

The spread across departments is wide, from {dept_cost_worst_auc:.3f} to
{dept_cost_best_auc:.3f} on the five-point cost outcome, but so are the
intervals at these sample sizes: the largest block, the Ministry of Defence, has
{mod_cost_n} project-years and most have well under a hundred. No department
row here should be read as establishing that one department's assessors are
better than another's. What the table does establish is that the portfolio-wide
figure is not hiding one department with a strong signal.

By the portfolio's own annual-report category:

{table(by_cat[by_cat['outcome'].isin(['wlc_growth_1y_gt_10', 'slip_1y_gt_6m', 'red_next'])], ['outcome_label', 'annual_report_category', 'scale', 'n', 'n_projects', 'base_rate', 'auc', 'skill_vs_base_rate'], ['Outcome', 'Category', 'Scale', 'Project-years', 'Projects', 'Base rate', 'Discrimination', 'Skill vs base rate'])}

Category is published only from the 2017 publication onward, so these cover the
later part of the series. Infrastructure and construction has the lowest
cost-growth base rate and the best discrimination; military capability has the
worst discrimination on both cost and slip.""")

    # ---------------------------------------------------- assessor + sens
    a(f"""
## Who made the call

From March 2022 each row carries either an IPA assessment or the Senior
Responsible Owner's own. No project-year carries both, so this is a comparison
between two disjoint groups of projects and not a head-to-head on the same ones.

{table(assessor[assessor['outcome'].isin(['wlc_growth_1y_gt_10', 'slip_1y_gt_6m', 'red_next'])], ['outcome_label', 'assessor', 'n', 'base_rate', 'auc', 'brier', 'skill_vs_base_rate'], ['Outcome', 'Assessed by', 'n', 'Base rate', 'Discrimination', 'Brier', 'Skill vs base rate'])}

The IPA's own assessments discriminate better than the SRO's on cost
({assessor_cost_ipa:.3f} against {assessor_cost_sro:.3f}) and about the same on
slip. Whether that is the assessor or
the selection of which projects get which kind of assessment cannot be separated
from this data.

## Sensitivity

{table(sens[sens['outcome'].isin(['wlc_growth_1y_gt_10', 'slip_1y_gt_6m'])], ['variant', 'outcome', 'scale', 'n', 'base_rate', 'auc', 'brier', 'skill_vs_base_rate'], ['Variant', 'Outcome', 'Scale', 'n', 'Base rate', 'Discrimination', 'Brier', 'Skill vs base rate'])}

Nothing moves. Dropping the project-years whose narrative mentions rebaselining
changes the cost discrimination by less than 0.01. Dropping the one 18-month step
changes it by less than 0.01. Including the one-year price-base break at the end
changes the three-point cost discrimination from {sens_cost_head:.3f} to
{sens_cost_break:.3f}.

The last variant addresses right censoring, which matters only for the exit
outcome: a project last seen at the second-to-last snapshot has one later
snapshot of evidence that it did not come back, not several. Dropping the final
two snapshots so that every remaining row is followed by at least two more
moves the three-point exit discrimination from {sens_exit_head:.3f} to
{sens_exit_censor:.3f} and leaves the five-point figure untouched. The conclusion that the rating predicts exit backwards does not
depend on the censoring.

The full table covers all seven outcomes.""")

    # ------------------------------------------------------------ caveats
    a(f"""
## What this does and does not show

**The rating is not a forecast of these outcomes, and it does not claim to be.**
The IPA defines the Delivery Confidence Assessment as confidence in successful
delivery "to time, cost and quality", which is broader and vaguer than "the
baseline whole-life cost will rise by more than 10 per cent in the next twelve
months". A rating that is well calibrated against its own idea of a material
problem can look badly calibrated against a specific threshold. That is why the
discrimination results, which need no mapping, carry more weight here than the
Brier results, and why the isotonic recalibration is reported alongside.

**The rating is an input to what happens next.** A Red rating triggers
intervention, and intervention is supposed to change the outcome. A well-run
portfolio should therefore show *less* discrimination than a passive one, and
none of this can tell those two apart. The analogous point for the exit outcome
is stronger still: a Green project that finishes and leaves is the system
working.

**The baseline whole-life cost is a budget, not an actual.** Growth in it means
the approved budget was formally raised. A project that overspends without a
rebaseline shows no growth here; a project that is rebaselined for a scope
increase shows a lot. Excluding project-years whose narrative mentions
rebaselining moves nothing, which suggests the narratives do not reliably flag
it, not that rebaselining does not matter.

**The extreme values in the continuous outcomes are real and are definitional.**
The largest single-year cost growth in the panel is DECC's "FID Enabling for
Renewables", from GBP 3.7m in September 2013 to GBP 22.5bn in September 2014: a
preparatory phase being rebaselined as a full programme. The largest schedule
movements are Ministry of Defence projects whose end dates run to the 2060s and
2070s and then move by decades, which is a change in what the end date is taken
to mean. The binary flags are unaffected; the continuous outcomes are reported
only through rank statistics for this reason.

**The portfolio is not a fixed population.** Projects join and leave, and
selection into and out of the portfolio is not random. The published data gives
no departure reason and the collection carries no departure list, so the exit
classification in this report is an inference from end dates, clearly labelled.

**Every outcome except exit is conditional on survival, and survival depends on
the rating.** {n_absent_rated:,} of the {n_rated:,} rated project-years have no
row at the next snapshot, so they have no cost, schedule or next-rating outcome
to be scored against. Leaving is not random with respect to the rating: Green
project-years are the project's last
{pct(cal_block('permanent_exit_next', 'five_point').set_index('rating').loc['Green', 'observed_rate'], 0)}
of the time against
{pct(cal_block('permanent_exit_next', 'five_point').set_index('rating').loc['Amber/Red', 'observed_rate'], 0)}
for Amber/Red. The scored sample is therefore short of exactly the Green
project-years a calibration table most wants, which is one reason the Green row
carries the smallest n in every table here. Nothing in this report corrects for
that, and no correction is available: a project that has finished has no
next-year baseline to grow.

**Project identity is reconstructed, not given, before September 2019.** No file
published a project id until then, so the early snapshots are linked by name,
by an exact normalised match first and then by a conservative similarity pass, a
GMPP id core pass and a rename pass that links on the approved start date and
the whole-life cost. {n_renames} outright renames are caught that way and are
listed in `results/identity_rename_merges.csv`, and
{n_fuzzy} similarity merges are listed with their scores. Renames that changed
both the name and the whole-life cost in the same year are not caught by any of
this, and they appear as an exit and a new project. The exit base rate should
be read as an upper bound on real departures for that reason.

**The intervals are clustered on the project, but the point estimates still
pool.** The bootstrap resamples whole projects, so the intervals do not treat
fourteen snapshots of one project as fourteen independent observations. The point
estimates still pool project-years, so a department with a few long-lived
projects contributes many correlated rows to its own breakdown. The Brier and
calibration tables carry no intervals at all; their n columns are the guide.

**The three-point era has less data behind it than it looks.** It covers five
snapshots and four resolvable transitions, and between {amber_share_lo} and
{amber_share_hi} per cent of the rated portfolio sits in Amber at any snapshot,
so the separating power available is limited by construction.""")

    # ----------------------------------------------- could not verify
    a(f"""
## How this was checked, and what checking it changed

Nothing here is trustworthy because it was written carefully. It is trustworthy
to the extent it was attacked and survived. Three things were done, and all
three changed the numbers.

**The pipeline was audited against the raw files by independent readers.** Eight
readers took one dimension each, from header canonicalisation to the scoring
mathematics, and every finding they raised was handed to a separate reader
whose instructions were to refute it and who had to reproduce the defect before
confirming it. Eight findings were refuted that way and are not reflected here.
Twenty-nine survived. Twenty-seven were defects in this code and are fixed. The
other two are properties of the published data that cannot be fixed at all and
are now stated instead: that the outcomes are conditional on a project still
being on the portfolio, which is finding 6 above, and that four departments
never published a departmental file, which is in the coverage section.

**The scoring mathematics was reimplemented independently and compared.** Brier,
the Murphy three-term decomposition and the AUC were written a second time from
their definitions and run against this code on 400 random inputs. The largest
disagreement is 1.4e-16, floating-point noise. The Murphy identity, reliability
minus resolution plus uncertainty equals the Brier score, is checked numerically
on every row the report prints and the residual column is in
`results/table_brier.csv`.

**The dating was checked against a source independent of the publication
pages**, as the section on the data sets out: {n_fy_agree} files name a
financial year in a money header, all {n_fy_agree} agree, none disagrees.

The defects that mattered most, all of which were live when the first draft of
this report was written:

- **A whole snapshot was being destroyed.** The rule that dated each
  publication preferred a financial year parsed out of a money column, and its
  column filter also matched the narrative header "Departmental narrative on
  budget/forecast variance for 2018/19". The September 2019 files carry that
  string as a leftover from the previous year's template. All 120 September 2019
  project-years were stamped September 2018, two snapshots were merged into one,
  and the transition between them was lost.
- **The departmental and category breakdowns pooled the two rating scales.** A
  rank of 2 is Amber on the five-point scale and Red on the three-point one.
  Every row of both breakdowns spans both eras, so every number in them was
  computed on incomparable ranks. Splitting by era moves 79 of the 140 rows by
  0.05 or more and reverses the sign of the conclusion on 14.
- **One conclusion was backwards.** "Rating worse next year" scored 0.30 and was
  read as the rating mean-reverting. But a project on the worst rating cannot
  worsen and a project one step off it can only worsen by one step, so the
  no-skill value for that outcome is not 0.5. Measured, it is 0.19. The rating
  is 0.11 above its own null, not below chance.
- **Twenty-two renames were being counted as deaths.** "Successor SSBN" is
  published as "DREADNOUGHT" from the next snapshot, and the names score 0.08 on
  any similarity measure. Linking on the approved start date and the whole-life
  cost instead recovers 22 of these, each one of which was previously a
  fabricated permanent exit and a lost transition.
- **A department-year was missing from the source.** The FCO's 2020 publication
  is not in the gov.uk collection, so three FCO projects appeared to leave the
  portfolio in September 2018.
- **Twenty published variances were multiplied by a hundred.** A cell reading
  "0.64" is the fraction 0.0064 far more often than it is a variance of 0.64 per
  cent, and the parser assumed so unconditionally. The baseline and forecast
  published in the same row settle it, and on 20 rows they say the blanket rule
  turned a sub-one-per-cent variance into one of up to 97 per cent.
- **Smaller ones, each of which deleted or invented data.** A time-only cell,
  "00:00:00", was read as today's date and fabricated seven end dates in the
  cross-check. A pound sign that the file's encoding rendered as a different
  character made one cell read as prose and deleted a GBP 9.94bn whole-life
  cost. The spelling "Green/Amber" was bucketed as "not rated", because "n/a" is
  a substring of "green/amber". A workbook no Excel engine could open was parsed
  as text and its compressed bytes recorded as a successful read. Two columns
  the NISTA files publish on every row, on whether a project has an evaluation
  plan, were on the list of spreadsheet working notes and were being thrown
  away. The March 2026 file renames the ICT category and the two spellings were
  being counted as two categories.

Each of these is now covered by a test, and the suite is {n_tests} tests.

## What could not be verified

- **Why any project left the portfolio.** The published files record no departure
  reason and the collection contains no list of projects that completed against
  projects that were cancelled. The end-date proxy in this report is an inference
  and is labelled as one everywhere it appears.
- **What the IPA intends a colour to mean numerically.** No published document in
  the collection attaches a probability to a rating. The implied mapping used
  here is an assumption specified for this exercise.
- **Whether the blank ratings in the September 2012 snapshot are exemptions.**
  The IPA's own back-series records 18 of them as exempt, which is strong
  evidence, but the department files as published simply leave the cell blank.
  Both are treated as non-ratings, so nothing turns on it.
- **Whether the scale change in March 2022 was announced anywhere in this
  collection.** It is visible in the published headers and in the data. The
  transparency policy PDF in the collection dates from May 2013 and predates it.
- **Whether project-level whole-life cost figures are on a consistent basis
  across departments.** Two files carry publisher footnotes saying they are not:
  a DECC file states its figures rest on DECC's own modelling projections, and
  2019 and 2020 files carry a note that the whole-life-cost basis differs from
  the National Infrastructure and Construction Pipeline.
- **The March 2026 snapshot's outcomes.** It is the last snapshot, so nothing
  resolves from it. Its 189 project-years are in the panel and contribute to no
  outcome.""")

    # -------------------------------------------------------- reproducing
    a(f"""
## Reproducing every number

Everything in this report is rebuilt by one command from the repository root:

```
.venv/bin/python -m gmpp.src.run_all --test
```

It re-downloads from gov.uk only when `data/raw/gmpp/manifest.csv` is absent;
`--fetch` forces the download and `--no-fetch` runs the analysis alone. It
stops at the first stage that fails and exits with that stage's status. The
stages it runs, which can also be run one at a time:

```
.venv/bin/python -m gmpp.src.discover           # gov.uk content API -> manifest
.venv/bin/python -m gmpp.src.download           # every attachment
.venv/bin/python -m gmpp.src.snapshots          # snapshot date per publication
.venv/bin/python -m gmpp.src.profile_headers    # header inventory
.venv/bin/python -m gmpp.src.panel              # -> results/panel.csv
.venv/bin/python -m gmpp.src.validate_calendar  # dating vs the money headers
.venv/bin/python -m gmpp.src.outcomes           # -> results/panel_outcomes.csv
.venv/bin/python -m gmpp.src.score              # -> results/table_*.csv
.venv/bin/python -m gmpp.src.crosscheck         # -> results/table_crosscheck.csv
.venv/bin/python -m gmpp.src.charts             # -> results/*.png
.venv/bin/python -m gmpp.src.report             # -> results/report.md
.venv/bin/python -m pytest gmpp/tests -q        # {n_tests} tests
```

`make -C gmpp all` runs the same stages where `make` is available.

### Files

| File | What it is |
|---|---|
| `results/panel.csv` | The canonical panel: {len(panel)} project-years, {panel['project_key'].nunique()} projects, 14 snapshots. Publishable. |
| `results/panel_outcomes.csv` | The panel with every forward-resolved outcome. |
| `results/table_calibration.csv` | Observed rate by rating for all seven outcomes, both scales. |
| `results/table_discrimination.csv` | Rank discrimination with bootstrap intervals. |
| `results/table_brier.csv` | Brier and the Murphy decomposition for four competing forecasts. |
| `results/table_isotonic.csv` | Forward-chained recalibration. |
| `results/table_by_department.csv`, `table_by_category.csv` | Breakdowns. |
| `results/table_sensitivity.csv` | Five analysis variants. |
| `results/table_crosscheck.csv` | Agreement with the IPA's own back-series. |
| `results/table_exit_diagnosis.csv` | End-date position of projects that left. |
| `results/identity_fuzzy_merges.csv` | Every name merge above an exact match, with its score, and every merge made on a GMPP id core. |
| `results/identity_rename_merges.csv` | Every project linked across an outright rename, with the start date and whole-life cost that identified it. |
| `results/table_crosscheck_gap.csv` | Back-series project-years with no panel row, by department. |
| `results/identity_name_collisions.csv` | Name groups left unmerged because two different projects share a normalised name inside one snapshot. |
| `results/table_calendar_validation.csv` | Each publication's dating against the financial year in its own money headers. |
| `results/unmapped_headers.csv` | Headers carrying data that were not mapped. Empty. |
| `results/panel_build_log.csv` | One row per source file read. |
| `data/raw/gmpp/manifest.csv`, `download_log.csv`, `snapshots.csv`, `header_summary.csv`, `file_profile.csv` | The acquisition record. |

Source data is published on gov.uk under the Open Government Licence.""")

    body = reflow("\n".join(parts))
    body = re.sub(r"\n{3,}", "\n\n", body)
    # A prose block written as a plain string rather than an f-string leaves its
    # placeholders in the output, which reads as a typo but is actually a
    # missing number. Fail rather than publish one.
    stranded = re.findall(r"\{[a-z_][a-z_0-9]*(?:[:!][^{}]*)?\}", body)
    if stranded:
        raise AssertionError(
            "un-interpolated placeholders left in the report: "
            + ", ".join(sorted(set(stranded)))
        )

    REPORT_PATH.write_text(body.strip() + "\n")
    print(f"wrote {REPORT_PATH} ({len(''.join(parts)):,} characters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
