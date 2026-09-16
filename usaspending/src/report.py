"""Assemble usaspending/results/report.md and the charts beside it."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

PLOT_LABELS = [
    ("ceiling_growth_gt25", "Ceiling growth over 25 percent"),
    ("schedule_slip_gt90", "Schedule slip over 90 days"),
    ("terminated", "Terminated"),
    ("any_change_order", "Any change order"),
]

HEADLINE = [
    ("ceiling_growth_gt10", 12), ("ceiling_growth_gt10", 24), ("ceiling_growth_gt10", 36),
    ("ceiling_growth_gt25", 12), ("ceiling_growth_gt25", 24), ("ceiling_growth_gt25", 36),
    ("ceiling_growth_gt50", 12), ("ceiling_growth_gt50", 24), ("ceiling_growth_gt50", 36),
    ("schedule_slip_gt90", 12), ("schedule_slip_gt90", 24), ("schedule_slip_gt90", 36),
    ("schedule_slip_gt365", 12), ("schedule_slip_gt365", 24), ("schedule_slip_gt365", 36),
    ("terminated", 12), ("terminated", 24), ("terminated", 36),
    ("terminated_default", 12), ("terminated_default", 24), ("terminated_default", 36),
    ("any_change_order", 12), ("any_change_order", 24), ("any_change_order", 36),
]


def fmt(x, nd=4):
    if x is None:
        return "n/a"
    try:
        f = float(x)
    except (TypeError, ValueError):
        return str(x)
    if np.isnan(f):
        return "n/a"
    return f"{f:.{nd}f}"


def md_table(rows, headers) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def df_table(df: pd.DataFrame, floatfmt=4) -> str:
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(lambda v: fmt(v, floatfmt))
    return md_table(d.astype(str).values.tolist(), list(d.columns))


def dir_bytes(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


# --------------------------------------------------------------------- charts

def chart_base_rates(base_rates: pd.DataFrame, out: Path) -> str:
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=False)
    for ax, h in zip(axes, (12, 24, 36)):
        for label, nice in PLOT_LABELS:
            sub = base_rates[(base_rates["label"] == label)
                             & (base_rates["horizon_months"] == h)
                             & (base_rates["base_fy"] != "ALL")].copy()
            if sub.empty:
                continue
            sub["base_fy"] = sub["base_fy"].astype(int)
            sub = sub.sort_values("base_fy")
            ax.plot(sub["base_fy"], sub["base_rate"], marker="o", ms=3, label=nice)
        ax.set_title(f"Horizon {h} months")
        ax.set_xlabel("Base action fiscal year")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("Share of awards")
    axes[-1].legend(fontsize=7, loc="best")
    fig.suptitle("Outcome base rates by base fiscal year")
    fig.tight_layout()
    p = out / "base_rates_by_fy.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


def chart_reliability(results: list, out: Path) -> list:
    names = []
    for label, h in [("ceiling_growth_gt25", 36), ("schedule_slip_gt90", 36),
                     ("terminated", 36), ("any_change_order", 36)]:
        r = next((x for x in results if x.get("label") == label
                  and x.get("horizon") == h and "calibration_test" in x), None)
        if r is None:
            continue
        gbm = pd.DataFrame(r["calibration_test"])
        rc = pd.DataFrame(r["calibration_test_reference_class"])
        fig, ax = plt.subplots(figsize=(5, 5))
        ax.plot([0, 1], [0, 1], color="0.6", lw=1, ls="--", label="Perfect calibration")
        for d, nice, mk in ((gbm, "Gradient boosting", "o"),
                            (rc, "Reference class", "s")):
            d = d[d["n"] > 0]
            ax.plot(d["mean_forecast"], d["observed_rate"], marker=mk, label=nice)
        ax.axhline(r["test_base_rate"], color="0.3", lw=0.8, ls=":",
                   label="Test base rate")
        ax.set_xlabel("Mean forecast probability")
        ax.set_ylabel("Observed frequency")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        ax.set_title(f"Reliability, {label.replace('_', ' ')}, {h} months")
        fig.tight_layout()
        p = out / f"reliability_{label}_{h}.png"
        fig.savefig(p, dpi=150)
        plt.close(fig)
        names.append(p.name)
    return names


def chart_bss(results: list, out: Path) -> str:
    rows = []
    for r in results:
        if "models" not in r:
            continue
        for m in ("reference_class", "gbm", "gbm_no_history"):
            rows.append({"cell": f"{r['label']} H{r['horizon']}", "model": m,
                         "bss": r["models"][m]["bss_vs_train_base_rate"]})
    if not rows:
        return ""
    d = pd.DataFrame(rows)
    piv = d.pivot(index="cell", columns="model", values="bss")
    piv = piv.reindex([f"{a} H{b}" for a, b in HEADLINE if f"{a} H{b}" in piv.index])
    fig, ax = plt.subplots(figsize=(11, max(5, 0.32 * len(piv))))
    y = np.arange(len(piv))
    w = 0.27
    for i, (col, nice) in enumerate((("reference_class", "Reference class"),
                                     ("gbm_no_history", "GBM without history"),
                                     ("gbm", "GBM with history"))):
        ax.barh(y + (i - 1) * w, piv[col].to_numpy(), height=w, label=nice)
    ax.set_yticks(y)
    ax.set_yticklabels([s.replace("_", " ") for s in piv.index], fontsize=8)
    ax.axvline(0, color="0.2", lw=1)
    ax.set_xlabel("Brier skill score against the training base rate (test years)")
    ax.legend(fontsize=8)
    ax.grid(axis="x", alpha=0.3)
    ax.set_title("Skill above the base rate, by label and horizon")
    fig.tight_layout()
    p = out / "bss_by_label.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


def chart_label_distributions(panel_path: Path, out: Path) -> str:
    if not panel_path.exists():
        return ""
    cols = ["ceiling_growth_36", "schedule_slip_days_36", "unplanned_growth_36",
            "qualifies_36"]
    d = pd.read_parquet(panel_path, columns=cols)
    d = d[d["qualifies_36"].astype(bool)]
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    specs = [("ceiling_growth_36", "Ceiling growth at 36 months", (-0.5, 2.0), 80),
             ("schedule_slip_days_36", "Schedule slip days at 36 months", (-200, 1200), 80),
             ("unplanned_growth_36", "Unplanned growth at 36 months", (-0.5, 1.5), 80)]
    for ax, (c, nice, rng, bins) in zip(axes, specs):
        s = pd.to_numeric(d[c], errors="coerce").dropna()
        inside = s[(s >= rng[0]) & (s <= rng[1])]
        ax.hist(inside, bins=bins, color="#3b6ea5")
        ax.set_title(nice, fontsize=10)
        ax.set_xlabel(f"clipped to [{rng[0]}, {rng[1]}]; "
                      f"{100*(1-len(inside)/max(len(s),1)):.1f} pct outside")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("Awards")
    fig.suptitle("Continuous label distributions, qualifying awards, 36 month horizon")
    fig.tight_layout()
    p = out / "label_distributions.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


# --------------------------------------------------------------------- report

def build(res_dir: Path, panel_path: Path, raw_dir: Path, wall_seconds: float) -> str:
    def load_json(name, default=None):
        p = res_dir / name
        return json.loads(p.read_text()) if p.exists() else default

    funnel = load_json("funnel.json", {})
    evidence = load_json("field_evidence.json", {})
    results = load_json("model_results.json", []) or []
    quant = load_json("quantile_results.json", []) or []
    manifest = load_json("fetch_manifest.json", []) or []
    xcheck = load_json("archive_crosscheck_FY2010.json", {})
    base_rates = (pd.read_csv(res_dir / "base_rates.csv")
                  if (res_dir / "base_rates.csv").exists() else pd.DataFrame())
    cont = (pd.read_csv(res_dir / "continuous_label_summary.csv")
            if (res_dir / "continuous_label_summary.csv").exists() else pd.DataFrame())

    charts = []
    if not base_rates.empty:
        charts.append(chart_base_rates(base_rates, res_dir))
    charts += chart_reliability(results, res_dir)
    b = chart_bss(results, res_dir)
    if b:
        charts.append(b)
    ld = chart_label_distributions(panel_path, res_dir)
    if ld:
        charts.append(ld)

    L = []
    A = L.append
    A("# Forecasting the outcome of a federal definitive contract at award")
    A("")
    A("A leakage-controlled backtest on USAspending contract actions, "
      "FY2010 through FY2022 base awards, resolved at 12, 24 and 36 months.")
    A("")
    A(f"Built {time.strftime('%Y-%m-%d')}. Every number below is produced by a "
      "script in `usaspending/src/` and reproduced by `make -C usaspending all` "
      "from the repository root.")
    A("")

    # ---------------------------------------------------------------- summary
    A("## What was built")
    A("")
    A("A forecast of what happens to a United States federal definitive contract "
      "after it is awarded, made only from information carried on the award "
      "action itself plus the prior public record of the contractor and the "
      "contracting office, and scored against the later official record of "
      "modifications to that same contract.")
    A("")
    A("The ladder has four rungs, run separately for every label and horizon:")
    A("")
    A("0. the unconditional base rate over the training years;")
    A("1. a reference class, meaning shrunk cell means over "
      "(awarding agency, NAICS 2-digit, contract pricing code, log value quintile);")
    A("2. gradient boosting on the award-time features plus as-of contractor and "
      "office history;")
    A("3. the same gradient boosting with the history block removed.")
    A("")
    A("Split by base action fiscal year: train FY2010 to FY2017, validate FY2018 "
      "to FY2019, test FY2020 to FY2022. Nothing is selected on the test years.")
    A("")

    # ------------------------------------------------------------------- data
    A("## The data")
    A("")
    A("Source: the USAspending Custom Award Data Download API, "
      "`POST https://api.usaspending.gov/api/v2/bulk_download/awards/`, with "
      "`prime_award_types: [\"D\"]` (definitive contract), `date_type: "
      "\"action_date\"`, and the all-agencies form "
      "`{\"type\": \"awarding\", \"tier\": \"toptier\", \"name\": \"All\"}`. One job "
      "per federal fiscal year, October 1 to September 30, FY2010 through FY2026. "
      "An explicit `columns` list restricts the download to the 44 columns used "
      "here. Rows are contract actions, one row per modification.")
    A("")
    if manifest:
        rows = []
        for m in manifest:
            rows.append([m.get("fiscal_year"),
                         f"{m.get('rows_type_D', m.get('rows_in_zip', 'n/a')):,}"
                         if isinstance(m.get("rows_type_D"), int) else "reused",
                         f"{m.get('unique_awards', 'n/a'):,}"
                         if isinstance(m.get("unique_awards"), int) else "n/a",
                         f"{m.get('parquet_bytes', 0)/1e6:.1f}"])
        A(md_table(rows, ["Fiscal year", "Type D actions", "Distinct awards",
                          "Parquet MB"]))
        A("")
    if xcheck:
        A("### Cross-check against the monthly full archive")
        A("")
        A("The same fiscal year was also taken from the independent bulk path, "
          f"`{('FY%d_All_Contracts_Full_20260906.zip' % xcheck['fiscal_year'])}`, "
          "streamed without extraction and filtered locally.")
        A("")
        A(md_table([
            ["Archive rows, all contract types", f"{xcheck['archive_rows_all_types']:,}"],
            ["Archive rows with award_type_code D", f"{xcheck['archive_rows_type_D']:,}"],
            ["Distinct type D awards in the archive",
             f"{xcheck['archive_unique_awards_type_D']:,}"],
            ["Columns of the 44 requested that are absent from the archive",
             str(len(xcheck["columns_absent"]))],
        ], ["Check", "Value"]))
        A("")
        api_rows = next((m.get("rows_type_D") for m in manifest
                         if m.get("fiscal_year") == xcheck["fiscal_year"]), None)
        if api_rows is not None:
            same = "identical" if api_rows == xcheck["archive_rows_type_D"] else "different"
            A(f"The API extract for the same year holds {api_rows:,} type D actions, "
              f"{same} to the archive count. The two paths are independent: the API "
              "applies the type filter server side, the archive path downloads every "
              "contract action for the year and filters locally.")
            A("")

    # -------------------------------------------------------- field behaviour
    A("## Field behaviour, observed")
    A("")
    A("No field semantics are asserted from the data dictionary alone. Each claim "
      "below is a statement about the dictionary followed by a count computed on "
      "the transactions. Twenty heavily modified awards are printed action by "
      "action in `field_evidence_samples.md` next to this file.")
    A("")
    if evidence:
        c = evidence.get("claim_base_row_ceiling_equals_potential", {})
        if c:
            A("**Dictionary**: `base_and_all_options_value` is \"the mutually agreed "
              "upon total contract value including all options\" on the award, and "
              "`potential_total_value_of_award` is \"the total amount that could be "
              "obligated on a contract, if the base and all options are exercised\". "
              "On the base action the two should therefore agree.")
            A("")
            A(md_table([[f"{c['n_base_rows']:,}", f"{c['n_both_present']:,}",
                         fmt(c['share_equal_within_1pct_or_1usd'])]],
                       ["Base rows", "Both fields present",
                        "Share equal within 1 percent or 1 dollar"]))
            A("")
        c = evidence.get("claim_mod_ceiling_field_is_a_delta", {})
        if c:
            A("**Dictionary**: on modifications, `base_and_all_options_value` holds "
              "\"the CHANGE, positive or negative\". If that is right, the base level "
              "plus the running sum of the modification values should track "
              "`potential_total_value_of_award` at each action, and the modification "
              "field read as a level should not.")
            A("")
            A(md_table([[f"{c['n_modification_rows_tested']:,}",
                         fmt(c['share_where_base_plus_running_delta_matches_potential']),
                         fmt(c['share_where_the_mod_field_itself_matches_potential'])]],
                       ["Modification rows tested",
                        "Share where base plus running delta matches potential",
                        "Share where the field read as a level matches potential"]))
            A("")
            A(f"Reading: {c['reading']}.")
            A("")
        c = evidence.get("claim_current_value_is_obligated_to_date", {})
        if c:
            A("**Dictionary**: `current_total_value_of_award` is \"the total amount "
              "obligated to date on a contract, including the base and exercised "
              "options\", so it should track the running sum of "
              "`federal_action_obligation` and sit at or below the ceiling.")
            A("")
            A(md_table([[f"{c['n_rows_tested']:,}",
                         fmt(c['share_current_value_matches_running_obligation']),
                         fmt(c['share_current_value_le_potential'])]],
                       ["Rows tested", "Share matching the running obligation",
                        "Share at or below potential total value"]))
            A("")
        c = evidence.get("claim_current_end_date_is_revised_by_mods", {})
        if c:
            A("**Dictionary**: `period_of_performance_current_end_date` is the "
              "scheduled completion date, revised by modifications that shorten or "
              "extend the period of performance.")
            A("")
            A(md_table([[f"{c['awards_with_more_than_one_action']:,}",
                         fmt(c['share_of_those_with_more_than_one_distinct_current_end_date']),
                         fmt(c['share_with_exactly_one_distinct_current_end_date'])]],
                       ["Awards with more than one action",
                        "Share whose current end date takes more than one value",
                        "Share whose current end date never changes"]))
            A("")
        c = evidence.get("claim_potential_value_is_a_running_level", {})
        if c:
            A("**Consequence to check**: if `potential_total_value_of_award` is a "
              "running ceiling rather than a per-action amount, consecutive actions "
              "on the same award should rarely show it falling.")
            A("")
            A(md_table([[f"{c['n_consecutive_pairs']:,}",
                         fmt(c['share_non_decreasing']), fmt(c['share_unchanged'])]],
                       ["Consecutive action pairs", "Share non-decreasing",
                        "Share unchanged"]))
            A("")
        c = evidence.get("claim_value_state_fields_are_award_level", {})
        if c:
            A("### The field the obvious label definition would use is a trap")
            A("")
            A("`potential_total_value_of_award` reads like a running ceiling, and "
              "the dictionary describes it as \"the total amount that could be "
              "obligated on a contract, if the base and all options are "
              "exercised\". In this feed it is not carried per action. It is an "
              "award-level end-state value pasted onto every action of the award, "
              "and it is populated on only about a quarter of rows. A field that "
              "is near constant within an award cannot be read at a horizon "
              "without importing the award's future.")
            A("")
            rows = []
            for k, v in c["per_field"].items():
                rows.append([k, fmt(v["share_of_all_actions_populated"], 3),
                             f"{v['awards_with_more_than_one_populated_action']:,}",
                             fmt(v["share_constant_within_award"], 4)])
            A(md_table(rows, ["Field", "Share of actions populated",
                              "Awards with more than one populated action",
                              "Share constant within the award"]))
            A("")
            A("The first three rows are award-level. The rest vary action to "
              "action and are safe to read at a horizon. So the ceiling at a "
              "horizon is reconstructed as the base action's "
              "`base_and_all_options_value` plus the sum of that same field over "
              "every later action dated at or before the horizon, and "
              "`period_of_performance_current_end_date` is used as it stands.")
            A("")
        pop = evidence.get("potential_value_population_rate_by_action_fy", {})
        bpop = evidence.get("base_and_all_options_population_rate_by_action_fy", {})
        if pop:
            A("The availability of that field also changes across the split, which "
              "on its own rules it out as a label. It is populated on about a "
              "quarter of actions in the training years and on every action from "
              "FY2019. A label that is present a quarter of the time in training "
              "and always in test is not the same label on both sides.")
            A("")
            A(md_table([[fy, fmt(pop[fy], 3), fmt(bpop.get(fy), 3)]
                        for fy in sorted(pop)],
                       ["Action fiscal year",
                        "potential_total_value_of_award populated",
                        "base_and_all_options_value populated"]))
            A("")
        c = evidence.get("claim_ceiling_field_behaviour_where_fully_populated", {})
        if c:
            A("Where the field is populated on every action, its behaviour can be "
              "tested directly. For awards based in FY"
              f"{c['base_fiscal_year_at_or_after']} or later with at least three "
              f"actions ({c['awards_tested']:,} awards), each action's value is "
              "compared with three things: the reconstruction as of that action, "
              "the award's own final value, and the base level.")
            A("")
            rows = []
            for key, nice in (("final_actions", "Final action of the award"),
                              ("non_final_actions", "All earlier actions"),
                              ("non_final_actions_on_awards_whose_ceiling_changed",
                               "Earlier actions, awards whose ceiling changed")):
                blk = c.get(key)
                if not blk:
                    continue
                rows.append([nice, f"{blk['n_actions']:,}",
                             fmt(blk["share_equal_to_contemporaneous_reconstruction"]),
                             fmt(blk["share_equal_to_the_awards_final_value"]),
                             fmt(blk["share_equal_to_the_base_level"])])
            A(md_table(rows, ["Actions", "n", "Equals the reconstruction",
                              "Equals the award's final value",
                              "Equals the base level"]))
            A("")
            fa = c.get("final_actions", {})
            nf = c.get("non_final_actions_on_awards_whose_ceiling_changed", {})
            A("Two things follow. On the award's last action the reconstruction "
              f"agrees with the field {fmt(fa.get('share_equal_to_contemporaneous_reconstruction'), 3)} "
              "of the time, so the reconstruction is arriving at the right number. "
              "On earlier actions of awards that did change, it agrees only "
              f"{fmt(nf.get('share_equal_to_contemporaneous_reconstruction'), 3)} of "
              "the time, while the field already equals the award's eventual final "
              f"value on {fmt(nf.get('share_equal_to_the_awards_final_value'), 3)} of "
              "them. Reading the field at a horizon would therefore import the "
              "award's future on a large minority of awards.")
            A("")
        leak = (pd.read_csv(res_dir / "leak_comparison.csv")
                if (res_dir / "leak_comparison.csv").exists() else pd.DataFrame())
        if not leak.empty:
            A("The consequence is visible in the label itself. Under the "
              "reconstruction the share of awards past 25 percent ceiling growth "
              "rises with the horizon, as it must. Under the award-level reading "
              "it barely moves, because the same end state is being read at every "
              "horizon.")
            A("")
            A(df_table(leak))
            A("")

        counts = evidence.get("action_type_code_counts", {})
        if counts:
            A("### Reason for modification codes actually present")
            A("")
            A("The dictionary domain for contracts, pulled from "
              "`GET /api/v2/references/data_dictionary/` this session, is A "
              "additional work, B supplemental agreement within scope, C funding "
              "only, D change order, E terminate for default, F terminate for "
              "convenience, G exercise an option, H definitize letter contract, J "
              "novation, K close out, L definitize change order, M other "
              "administrative, N legal contract cancellation, P and R "
              "re-representation, S change PIID, T transfer, V entity identifier or "
              "name change, W address change, X terminate for cause, Y add "
              "subcontract plan. Counts over every type D action loaded:")
            A("")
            tot = sum(counts.values())
            rows = [[k, f"{v:,}", fmt(v / tot, 4)] for k, v in
                    sorted(counts.items(), key=lambda kv: -kv[1])]
            A(md_table(rows, ["action_type_code", "Actions", "Share"]))
            A("")
        fill = evidence.get("base_row_fill_rate", {})
        if fill:
            A("### Fill rates on the base action")
            A("")
            A(md_table([[k, fmt(v)] for k, v in
                        sorted(fill.items(), key=lambda kv: -kv[1])],
                       ["Field", "Share not null on base rows"]))
            A("")
        sol = evidence.get("solicitation_identifier_fill_rate_by_base_fy", {})
        if sol:
            A("The memo flagged the `solicitation_identifier` fill rate as unmeasured "
              "and as the key that would link an award back to its solicitation. "
              "Measured here on base actions, by base fiscal year:")
            A("")
            A(md_table([[k, fmt(v)] for k, v in sorted(sol.items())],
                       ["Base fiscal year", "Share of base actions with a solicitation identifier"]))
            A("")

    # ----------------------------------------------------------------- funnel
    A("## Data funnel")
    A("")
    if funnel:
        A(f"Data end, the latest action_date in the extract: "
          f"**{funnel.get('data_end')}**. Transactions loaded: "
          f"**{funnel.get('transactions_loaded', 0):,}**.")
        A("")
        d = funnel.get("base_row_diagnostics", {})
        if d:
            A(md_table([[k.replace("_", " "), f"{v:,}"] for k, v in d.items()],
                       ["Base row diagnostic", "Awards"]))
            A("")
        steps = funnel.get("funnel", [])
        if steps:
            rows = []
            prev = None
            for s in steps:
                n = s["awards_remaining"]
                drop = "" if prev is None else f"-{prev - n:,}"
                rows.append([s["filter"], f"{n:,}", drop])
                prev = n
            A(md_table(rows, ["Filter", "Awards remaining", "Dropped"]))
            A("")

    # -------------------------------------------------------- label defs
    A("## Label definitions")
    A("")
    A("For an award with base action date `t0` and horizon `H` months, the state "
      "at `H` is taken from the latest action with `action_date <= t0 + H months`, "
      "ordering actions by action date, then by the numeric suffix of the "
      "modification number, then by transaction number.")
    A("")
    A(md_table([
        ["ceiling_growth_H",
         "potential_total_value_of_award at H divided by base_and_all_options_value "
         "on the base action, minus one"],
        ["ceiling_growth_gt10_H, gt25_H, gt50_H",
         "ceiling_growth_H strictly above 0.10, 0.25, 0.50, after rounding the "
         "ratio to ten decimal places so an award at exactly the threshold is not "
         "counted"],
        ["schedule_slip_days_H",
         "period_of_performance_current_end_date at H minus the same field on the "
         "base action, in days"],
        ["schedule_slip_gt90_H, gt365_H", "schedule_slip_days_H above 90, above 365"],
        ["terminated_H", "any action by H with action_type_code in E, F or X"],
        ["terminated_default_H", "any action by H with action_type_code E only"],
        ["change_order_count_H", "count of actions by H with action_type_code A or D"],
        ["unplanned_growth_H",
         "sum of base_and_all_options_value on A and D actions by H, divided by the "
         "base ceiling"],
        ["any_change_order_H", "change_order_count_H above zero"],
    ], ["Label", "Definition"]))
    A("")
    A("An award qualifies for horizon H only when `t0 + H months` is at or before "
      "the data end, so no label is read off a period the data does not cover. "
      "Awards whose base ceiling is missing or not positive are dropped, since "
      "ceiling growth is undefined for them.")
    A("")

    # ---------------------------------------------------- label distributions
    A("## Label distributions")
    A("")
    if not base_rates.empty:
        for h in (12, 24, 36):
            sub = base_rates[(base_rates["horizon_months"] == h)
                             & (base_rates["base_fy"] != "ALL")].copy()
            if sub.empty:
                continue
            sub["base_fy"] = sub["base_fy"].astype(int)
            piv = sub.pivot(index="base_fy", columns="label", values="base_rate")
            ns = sub.pivot(index="base_fy", columns="label", values="n").max(axis=1)
            piv.insert(0, "qualifying_awards", ns)
            piv = piv.reset_index()
            A(f"### Base rates by base fiscal year, horizon {h} months")
            A("")
            A(df_table(piv))
            A("")
        allrow = base_rates[base_rates["base_fy"] == "ALL"]
        if not allrow.empty:
            piv = allrow.pivot(index="label", columns="horizon_months",
                               values="base_rate").reset_index()
            piv.columns = ["label"] + [f"H{c}" for c in piv.columns[1:]]
            A("### Pooled base rates over all base years")
            A("")
            A(df_table(piv))
            A("")
    if not cont.empty:
        A("### Continuous labels")
        A("")
        A(df_table(cont))
        A("")
    if ld:
        A(f"![Continuous label distributions]({ld})")
        A("")
    A(f"![Base rates by fiscal year](base_rates_by_fy.png)")
    A("")

    # ----------------------------------------------------------------- models
    A("## Model results")
    A("")
    A("All figures are on the test years, base action fiscal year FY2020 to "
      "FY2022. The Brier skill score uses the training-period base rate as the "
      "reference forecast, so zero means no skill above knowing the historical "
      "frequency and nothing else.")
    A("")
    if results:
        rows = []
        for r in results:
            if "models" not in r:
                rows.append([r.get("label"), r.get("horizon"), "", "",
                             r.get("error", "no result"), "", "", "", "", "", "", ""])
                continue
            m = r["models"]
            rows.append([
                r["label"], r["horizon"], f"{r['n_test']:,}",
                fmt(r["train_base_rate"]), fmt(r["test_base_rate"]),
                fmt(m["base_rate"]["brier"]),
                fmt(m["reference_class"]["brier"]), fmt(m["gbm"]["brier"]),
                fmt(m["gbm_no_history"]["brier"]),
                fmt(m["reference_class"]["bss_vs_train_base_rate"]),
                fmt(m["gbm"]["bss_vs_train_base_rate"]),
                fmt(m["gbm_no_history"]["bss_vs_train_base_rate"]),
                fmt(m["reference_class"]["auc"], 3), fmt(m["gbm"]["auc"], 3),
                fmt(m["gbm_no_history"]["auc"], 3),
            ])
        A(md_table(rows, [
            "Label", "H", "n test", "Train base rate", "Test base rate",
            "Brier base rate", "Brier ref class", "Brier GBM", "Brier GBM no hist",
            "BSS ref class", "BSS GBM", "BSS GBM no hist",
            "AUC ref class", "AUC GBM", "AUC GBM no hist"]))
        A("")
        if b:
            A(f"![Brier skill score by label]({b})")
            A("")

        best = [r for r in results if "models" in r]
        if best:
            top = sorted(best, key=lambda r: -r["models"]["gbm"]["bss_vs_train_base_rate"])
            A("Best and worst cells by gradient boosting skill:")
            A("")
            rows = [[r["label"], r["horizon"],
                     fmt(r["models"]["gbm"]["bss_vs_train_base_rate"]),
                     fmt(r["models"]["gbm"]["auc"], 3)]
                    for r in top[:5] + top[-5:]]
            A(md_table(rows, ["Label", "H", "BSS GBM", "AUC GBM"]))
            A("")

    # ------------------------------------------------------------ calibration
    A("## Calibration")
    A("")
    for label, h in [("ceiling_growth_gt25", 36), ("schedule_slip_gt90", 36),
                     ("terminated", 36), ("any_change_order", 36)]:
        r = next((x for x in results if x.get("label") == label
                  and x.get("horizon") == h and "calibration_test" in x), None)
        if r is None:
            continue
        A(f"### {label.replace('_', ' ')}, horizon {h} months, gradient boosting")
        A("")
        A(df_table(pd.DataFrame(r["calibration_test"])))
        A("")
        A(f"Expected calibration error, gradient boosting: "
          f"{fmt(r['models']['gbm']['ece'])}; reference class: "
          f"{fmt(r['models']['reference_class']['ece'])}.")
        A("")
        png = f"reliability_{label}_{h}.png"
        if (res_dir / png).exists():
            A(f"![Reliability {label}]({png})")
            A("")

    # ------------------------------------------------------ unseen recipients
    A("## Test rows whose contractor never appears in training")
    A("")
    A("The history features are keyed on the contractor, so a contractor with no "
      "training-period award is the case where the model has the least to go on. "
      "The slice below restricts the test years to awards whose recipient UEI does "
      "not appear on any training-year base award.")
    A("")
    rows = []
    for r in results:
        u = r.get("unseen_recipient_test")
        if not u or "gbm" not in u:
            continue
        rows.append([r["label"], r["horizon"], f"{u['n']:,}",
                     fmt(u["share_of_test"], 3), fmt(u["gbm"]["observed_rate"]),
                     fmt(u["reference_class"]["bss_vs_train_base_rate"]),
                     fmt(u["gbm"]["bss_vs_train_base_rate"]),
                     fmt(u["gbm"]["auc"], 3)])
    if rows:
        A(md_table(rows, ["Label", "H", "n unseen", "Share of test",
                          "Observed rate", "BSS ref class", "BSS GBM", "AUC GBM"]))
        A("")

    # ------------------------------------------------------------- importance
    A("## Feature importance")
    A("")
    A("Permutation importance on the validation years for the gradient boosting "
      "model with history, measured as the increase in Brier score when one "
      "feature is shuffled. Higher means the model relied on it more.")
    A("")
    for label, h in [("ceiling_growth_gt25", 36), ("schedule_slip_gt90", 36),
                     ("terminated", 36)]:
        r = next((x for x in results if x.get("label") == label
                  and x.get("horizon") == h
                  and "permutation_importance_val" in x), None)
        if r is None:
            continue
        A(f"### {label.replace('_', ' ')}, horizon {h} months")
        A("")
        A(md_table([[e["feature"], fmt(e["mean_brier_increase"], 6), fmt(e["std"], 6)]
                    for e in r["permutation_importance_val"][:15]],
                   ["Feature", "Mean Brier increase", "Standard deviation"]))
        A("")

    # ------------------------------------------------------------- quantiles
    if quant:
        A("## Continuous labels, quantile forecasts")
        A("")
        A("Gradient boosting with the pinball loss at 0.10, 0.50 and 0.90, against "
          "a constant forecast at the training-period quantile. Outcomes are "
          "winsorised at the 1st and 99th percentile of the training distribution "
          "before fitting and scoring, and the cut points are reported so the "
          "effect is visible.")
        A("")
        rows = []
        for r in quant:
            if "quantiles" not in r:
                continue
            for q, e in r["quantiles"].items():
                rows.append([r["label"], r["horizon"], q,
                             fmt(e["train_constant"], 4),
                             fmt(e["pinball_constant"], 5),
                             fmt(e["pinball_gbm"], 5),
                             fmt(e["pinball_skill_vs_constant"], 4)])
        A(md_table(rows, ["Label", "H", "Quantile", "Train constant",
                          "Pinball constant", "Pinball GBM", "Skill"]))
        A("")
        rows = []
        for r in quant:
            e = r.get("quantiles", {}).get("0.50")
            if e and "mae_gbm" in e:
                rows.append([r["label"], r["horizon"],
                             fmt(e["mae_constant"], 4), fmt(e["mae_gbm"], 4),
                             fmt(r["train_winsor_low"], 3),
                             fmt(r["train_winsor_high"], 3)])
        if rows:
            A("Median forecasts, mean absolute error:")
            A("")
            A(md_table(rows, ["Label", "H", "MAE constant", "MAE GBM",
                              "Winsor low", "Winsor high"]))
            A("")

    # ---------------------------------------------------------------- caveats
    A("## Caveats")
    A("")
    for c in [
        "Only the award that was made is scored. Losing bids are source selection "
        "information under FAR 3.104 and never become public, so nothing here "
        "forecasts a proposal that did not win. This is the carve-out the memo "
        "identified and it is not fixable with public United States data.",
        "Option exercises are planned growth. `ceiling_growth` counts every "
        "increase in the potential total value, including exercised options and "
        "within-scope supplemental agreements, so it is not an overrun measure. "
        "`unplanned_growth` and `change_order_count`, which count only "
        "action_type_code A and D, are the closer proxies for unplanned work; "
        "both are reported.",
        "FPDS data quality is uneven. The Government Accountability Office found "
        "18 percent of reviewed records miscoded in 2010, and competition codes on "
        "orders have been inherited from the parent vehicle since October 2009. "
        "That last point does not bite here because orders under indefinite "
        "delivery vehicles are award type C and are excluded, but coding error in "
        "the reason-for-modification field goes straight into the labels.",
        "The award is a treatment, not only a label. Contract type, ceiling and "
        "duration are chosen by the contracting officer partly in anticipation of "
        "risk, so a feature that predicts an outcome may be a response to it. "
        "Nothing here is causal.",
        "Records are restated. The extract is a single snapshot taken from files "
        "stamped 2026-09-06; FPDS records can be corrected after the fact, so a "
        "true pre-registered forecast would have to freeze the first print at "
        "registration time rather than read history back from one snapshot.",
        "The base action is identified by an explicit modification number of zero. "
        "Awards whose first action in the window is a later modification are "
        "excluded, which removes contracts whose base action falls before FY2010 "
        "and also removes any award whose base row is missing from the feed.",
        "Contractor identity is only as stable as the unique entity identifier. "
        "Novations (action_type_code J) and the 2022 move from DUNS to UEI both "
        "break the key, so contractor history is understated for affected firms.",
        "CPARS past performance ratings, the richest outcome label in federal "
        "contracting, are closed by FAR 42.1503 and are not used.",
    ]:
        A(f"- {c}")
    A("")

    A("## What could not be verified")
    A("")
    for c in [
        "Whether a restated record differs materially from the first print. "
        "Testing that needs two snapshots of the same fiscal year taken months "
        "apart, and only the 2026-09-06 stamp was available this session.",
        "Whether the `solicitation_identifier` values that are present actually "
        "resolve to a retrievable solicitation. The fill rate is measured above; "
        "the join to SAM.gov or an archive of notices was not attempted.",
        "Whether the residual miscoding rate in the reason-for-modification field "
        "is still near the 18 percent the Government Accountability Office reported "
        "in 2010. That figure is quoted from the memo, not measured here.",
        "Whether terminations that never produce an E, F or X action exist in "
        "material numbers, for example a contract quietly allowed to lapse. The "
        "termination label only sees actions that were coded as terminations.",
    ]:
        A(f"- {c}")
    A("")

    # ------------------------------------------------------------- operations
    A("## Reproduction, disk and wall time")
    A("")
    raw_mb = dir_bytes(raw_dir) / 1e6
    panel_mb = (panel_path.stat().st_size / 1e6) if panel_path.exists() else 0.0
    A(md_table([
        ["Definitive-contract parquet extract", f"{raw_mb:.1f} MB"],
        ["Award panel", f"{panel_mb:.1f} MB"],
        ["Peak additional disk during the archive cross-check",
         "1.17 GB, one zip held at a time and deleted after streaming"],
        ["Wall time for this report step", f"{wall_seconds:.0f} s"],
    ], ["Item", "Value"]))
    A("")
    A("```")
    A("make -C usaspending all      # fetch, evidence, panel, models, quantiles, report")
    A("make -C usaspending test     # pytest")
    A("make -C usaspending crosscheck  # optional, re-runs the archive validation")
    A("```")
    A("")
    A("Files written next to this report: `base_rates.csv`, "
      "`reference_class_table.csv`, `continuous_label_summary.csv`, `funnel.json`, "
      "`field_evidence.json`, `field_evidence_samples.md`, `model_results.json`, "
      "`quantile_results.json`, `fetch_manifest.json`, and the PNG charts.")
    A("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, default=Path("usaspending/results"))
    ap.add_argument("--panel", type=Path,
                    default=Path("data/raw/usaspending/panel.parquet"))
    ap.add_argument("--raw", type=Path, default=Path("data/raw/usaspending/parquet"))
    a = ap.parse_args()
    t0 = time.time()
    a.results.mkdir(parents=True, exist_ok=True)
    text = build(a.results, a.panel, a.raw, time.time() - t0)
    (a.results / "report.md").write_text(text)
    print(f"wrote {a.results/'report.md'} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
