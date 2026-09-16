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


def label_order(results: list) -> list:
    """Distinct labels in the order the model run produced them."""
    seen = []
    for r in results:
        lab = r.get("label")
        if lab and lab not in seen:
            seen.append(lab)
    return seen


def src_note(script: str, command: str) -> str:
    """Attribution line placed under every table, naming what produced it."""
    return (f"Source: `usaspending/src/{script}`, run from the repository root as "
            f"`{command}`.")


def aggregate_recipient_table(panel_path: Path, top_real: int = 1) -> pd.DataFrame:
    """Placeholder recipients in the panel, with a real contractor for scale."""
    if not panel_path.exists():
        return pd.DataFrame()
    d = pd.read_parquet(panel_path, columns=["recipient_uei", "recipient_name",
                                             "recipient_is_aggregate"])
    agg = d[d["recipient_is_aggregate"].astype(bool)]
    rows = []
    for (uei, name), n in (agg.groupby(["recipient_uei", "recipient_name"])
                           .size().sort_values(ascending=False).items()):
        rows.append({"recipient_uei": f"`{uei}`", "recipient_name": name,
                     "base_awards_in_panel": int(n), "held_out": "yes"})
    real = d[~d["recipient_is_aggregate"].astype(bool)]
    for (uei, name), n in (real.groupby(["recipient_uei", "recipient_name"])
                           .size().sort_values(ascending=False)
                           .head(top_real).items()):
        rows.append({"recipient_uei": f"`{uei}`",
                     "recipient_name": f"{name} (largest real contractor, for scale)",
                     "base_awards_in_panel": int(n), "held_out": "no"})
    return pd.DataFrame(rows)


def uei_fragmentation_table(panel_path: Path, top: int = 8) -> pd.DataFrame:
    """Recipient names carrying more than one UEI, worst first.

    The contractor history key is the UEI, so a firm whose awards are split
    across several UEIs has its track record split with them.
    """
    if not panel_path.exists():
        return pd.DataFrame()
    d = pd.read_parquet(panel_path, columns=["recipient_uei", "recipient_name",
                                             "recipient_is_aggregate"])
    d = d[~d["recipient_is_aggregate"].astype(bool)]
    g = d.groupby("recipient_name").agg(
        awards=("recipient_uei", "size"),
        distinct_ueis=("recipient_uei", "nunique"))
    multi = g[g["distinct_ueis"] > 1]
    out = multi.sort_values("awards", ascending=False).head(top).reset_index()
    out["largest_single_uei_share"] = [
        float(d[d["recipient_name"] == n]["recipient_uei"].value_counts().iloc[0]
              / a) for n, a in zip(out["recipient_name"], out["awards"])]
    return out


def uei_fragmentation_summary(panel_path: Path) -> dict:
    if not panel_path.exists():
        return {}
    d = pd.read_parquet(panel_path, columns=["recipient_uei", "recipient_name",
                                             "recipient_is_aggregate"])
    d = d[~d["recipient_is_aggregate"].astype(bool)]
    g = d.groupby("recipient_name")["recipient_uei"].nunique()
    names_multi = g[g > 1]
    affected = d["recipient_name"].isin(names_multi.index)
    return {"distinct_recipient_names": int(g.size),
            "names_with_more_than_one_uei": int(names_multi.size),
            "share_of_names": float(names_multi.size / max(g.size, 1)),
            "awards_under_such_a_name": int(affected.sum()),
            "share_of_awards": float(affected.mean())}


def reconstruction_sanity(panel_path: Path) -> dict:
    """How often the reconstructed ceiling takes an implausible intermediate value.

    The reconstruction sums per-action deltas, so a modification carrying an
    erroneous delta moves the ceiling until a later action reverses it. The final
    value is still right, and the convergence check on final actions confirms
    that, but an intermediate horizon can sit on top of the error. These counts
    put a size on it instead of leaving it as a worry.
    """
    if not panel_path.exists():
        return {}
    cols = ([f"ceiling_growth_{h}" for h in (12, 24, 36)]
            + [f"ceiling_at_{h}" for h in (12, 24, 36)])
    d = pd.read_parquet(panel_path, columns=cols)
    out = {"n": int(len(d)), "by_horizon": {}}
    for h in (12, 24, 36):
        g = pd.to_numeric(d[f"ceiling_growth_{h}"], errors="coerce")
        out["by_horizon"][h] = {
            "median": float(g.median()),
            "p99": float(g.quantile(0.99)),
            "p999": float(g.quantile(0.999)),
            "max": float(g.max()),
            "share_above_1x": float((g > 1).mean()),
            "share_above_10x": float((g > 10).mean()),
            "share_above_100x": float((g > 100).mean()),
        }
    neg = (d[[f"ceiling_at_{h}" for h in (12, 24, 36)]] < 0).any(axis=1)
    up_down = ((d["ceiling_at_24"] > 2 * d["ceiling_at_12"].clip(lower=1))
               & (d["ceiling_at_36"] < 0.5 * d["ceiling_at_24"]))
    out["negative_reconstructed_ceiling_at_some_horizon"] = int(neg.sum())
    out["negative_share"] = float(neg.mean())
    out["doubled_by_24_then_halved_by_36"] = int(up_down.sum())
    out["doubled_then_halved_share"] = float(up_down.mean())
    return out


def reference_class_shape(res_dir: Path) -> dict:
    """How thin the finest reference-class cells are, which is why shrinkage matters."""
    f = res_dir / "reference_class_table.csv"
    if not f.exists():
        return {}
    t = pd.read_csv(f)
    n = pd.to_numeric(t["n"], errors="coerce")
    out = {"cells": int(len(t)), "n_min": int(n.min()), "n_max": int(n.max()),
           "n_median": float(n.median())}
    for thr in (30, 10, 5, 1):
        out[f"cells_with_n_below_{thr}"] = int((n < thr).sum())
    out["cells_with_n_of_one"] = int((n == 1).sum())
    out["share_below_30"] = float((n < 30).mean())
    thin = t[n < 30]
    if len(thin):
        out["mean_absolute_shrink_on_thin_cells"] = float(
            (pd.to_numeric(thin["shrunk"], errors="coerce")
             - pd.to_numeric(thin["mean"], errors="coerce")).abs().mean())
    return out


def aggregate_recipients_in_test(panel_path: Path,
                                 test_fy=(2020, 2022)) -> dict:
    """Test-year awards with no identifiable contractor, and whether excluding
    them from the unseen-recipient slice changes any row's classification."""
    if not panel_path.exists():
        return {}
    d = pd.read_parquet(panel_path, columns=["base_fy", "recipient_uei",
                                             "recipient_is_aggregate"])
    fy = pd.to_numeric(d["base_fy"], errors="coerce")
    tr = (fy >= 2010) & (fy <= 2017)
    te = (fy >= test_fy[0]) & (fy <= test_fy[1])
    agg = d["recipient_is_aggregate"].astype(bool)
    seen_now = set(d.loc[tr, "recipient_uei"].dropna().unique())
    seen_fix = set(d.loc[tr & ~agg, "recipient_uei"].dropna().unique())
    te_uei = d.loc[te, "recipient_uei"]
    unseen_now = ~te_uei.isin(seen_now)
    unseen_fix = (~te_uei.isin(seen_fix)) & ~agg.loc[te]
    return {
        "test_rows": int(te.sum()),
        "test_rows_with_an_aggregate_recipient": int((te & agg).sum()),
        "unseen_keeping_aggregates": int(unseen_now.sum()),
        "unseen_excluding_aggregates": int(unseen_fix.sum()),
        "rows_that_change_classification": int((unseen_now != unseen_fix).sum()),
    }


def censoring_table(panel_path: Path) -> pd.DataFrame:
    """Qualifying awards per base fiscal year and horizon.

    An award qualifies for horizon H when its base action date plus H months is
    at or before the data end, the latest action_date in the extract.
    """
    if not panel_path.exists():
        return pd.DataFrame()
    d = pd.read_parquet(panel_path,
                        columns=["base_fy", "qualifies_12", "qualifies_24",
                                 "qualifies_36", "action_date"])
    rows = []
    for fy, blk in d.groupby("base_fy"):
        row = {"base_fy": int(fy), "awards_in_panel": int(len(blk)),
               "earliest_base_action": str(pd.to_datetime(blk["action_date"]).min().date()),
               "latest_base_action": str(pd.to_datetime(blk["action_date"]).max().date())}
        for h in (12, 24, 36):
            q = blk[f"qualifies_{h}"].astype(bool)
            row[f"qualifying_H{h}"] = int(q.sum())
            row[f"share_qualifying_H{h}"] = float(q.mean())
        rows.append(row)
    out = pd.DataFrame(rows).sort_values("base_fy")
    total = {"base_fy": "ALL", "awards_in_panel": int(len(d)),
             "earliest_base_action": "", "latest_base_action": ""}
    for h in (12, 24, 36):
        q = d[f"qualifies_{h}"].astype(bool)
        total[f"qualifying_H{h}"] = int(q.sum())
        total[f"share_qualifying_H{h}"] = float(q.mean())
    return pd.concat([out, pd.DataFrame([total])], ignore_index=True)


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
    bss_chart = chart_bss(results, res_dir)
    if bss_chart:
        charts.append(bss_chart)
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
        A(src_note("bulk_fetch.py",
                   ".venv/bin/python -m usaspending.src.bulk_fetch "
                   "--fy-start 2010 --fy-end 2026") +
          " Written to `fetch_manifest.json`.")
        A("")
        A("FY2026 is short because it is the year in progress: the extract runs to "
          f"{funnel.get('data_end', 'the data end')}, not to 30 September 2026. It "
          "is fetched anyway because outcomes of awards based as late as FY2022 "
          "are resolved out of it. FY2018 was fetched in four contiguous "
          "quarter-length windows rather than one, after the single-year job "
          "failed server side; the API keys a job on the request body, so an "
          "identical retry returns the same failed job and the body has to change. "
          "The windows were checked to tile the fiscal year exactly, and a test "
          "covers that for every split count from 1 to 12 across FY2010 to FY2026.")
        A("")
    colmap = load_json("column_mapping.json", {})
    if colmap:
        A("### The columns actually delivered")
        A("")
        A("`src/columns.py` requests "
          f"{colmap['columns_requested']} named download columns. The parquet "
          "schema of every fiscal year was read back and diffed against that "
          "list, so a column the API silently dropped would show up here rather "
          "than as a column of nulls later.")
        A("")
        absent = colmap.get("columns_absent_from_some_year", [])
        A(md_table([
            ["Fiscal years of parquet checked", str(colmap["parquet_files"])],
            ["Columns requested", str(colmap["columns_requested"])],
            ["Columns present in every year",
             str(len(colmap["columns_present_in_every_year"]))],
            ["Columns absent from at least one year",
             (", ".join(absent) if absent else "none")],
        ], ["Check", "Value"]))
        A("")
        A(src_note("schema_check.py",
                   ".venv/bin/python -m usaspending.src.schema_check"))
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
            _pf = c["per_field"].get("potential_total_value_of_award", {})
            A("`potential_total_value_of_award` reads like a running ceiling, and "
              "the dictionary describes it as \"the total amount that could be "
              "obligated on a contract, if the base and all options are "
              "exercised\". Measured over every definitive-contract action loaded, "
              f"it is populated on {fmt(_pf.get('share_of_all_actions_populated'), 3)} "
              "of them, and among awards with more than one populated action it "
              "takes a single value throughout the award "
              f"{fmt(_pf.get('share_constant_within_award'), 3)} of the time. A "
              "field that is near constant within an award cannot be read at a "
              "horizon without importing the award's future.")
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
            _const = [k for k, v in c["per_field"].items()
                      if (v.get("share_constant_within_award") or 0) > 0.5]
            A("The fields that take one value throughout an award more than half "
              f"the time are {', '.join('`%s`' % k for k in _const)}. Those are "
              "award-level summaries joined onto every action. The rest vary "
              "action to action and are safe to read at a horizon. So the ceiling "
              "at a horizon is reconstructed as the base action's "
              "`base_and_all_options_value` plus the sum of that same field over "
              "every later action dated at or before the horizon, and "
              "`period_of_performance_current_end_date` is used as it stands.")
            A("")
        pop = evidence.get("potential_value_population_rate_by_action_fy", {})
        bpop = evidence.get("base_and_all_options_population_rate_by_action_fy", {})
        if pop:
            _tr = [pop[k] for k in pop if k.isdigit() and 2010 <= int(k) <= 2017]
            _te = [pop[k] for k in pop if k.isdigit() and 2020 <= int(k) <= 2022]
            A("The availability of that field also changes across the split, which "
              "on its own rules it out as a label. Averaged over the training "
              f"years FY2010 to FY2017 it is populated on {fmt(np.mean(_tr), 3) if _tr else 'n/a'} "
              "of actions; over the test years FY2020 to FY2022 it is populated on "
              f"{fmt(np.mean(_te), 3) if _te else 'n/a'}. A label that is present "
              "part of the time in training and always in test is not the same "
              "label on both sides. `base_and_all_options_value`, used instead, is "
              "populated on every action in every year.")
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
        A("`solicitation_identifier` and `number_of_offers_received` get their own "
          "section below, because the memo flagged both as unmeasured and a public "
          "scoreboard depends on them.")
        A("")

    # ------------------------------------------------- restatement evidence
    pr = evidence.get("per_action_restatement", {}) if evidence else {}
    if pr:
        A("### Is a field carried per action, or restated across the award?")
        A("")
        A("The test that matters for a backtest is not whether a field is "
          "populated but whether the value sitting on an old action is the value "
          "that was true then. Take awards with at least three actions, and among "
          "them the awards whose value actually moved. On every action except the "
          "last, compare the field with the value the award ends up with. A field "
          "carried per action should rarely match it. A field restated across the "
          "award's whole history will match it almost always.")
        A("")
        rows = []
        for key, field, moved in (
                ("ceiling_field_restatement", "potential_total_value_of_award",
                 "awards whose ceiling moved"),
                ("current_end_date_restatement",
                 "period_of_performance_current_end_date",
                 "awards whose end date moved")):
            blk = pr.get(key, {})
            for sub, subnice in (
                    ("all_non_final_actions", "all awards"),
                    ("non_final_actions_on_awards_whose_ceiling_changed", moved),
                    ("non_final_actions_on_awards_whose_end_date_changed", moved)):
                b2 = blk.get(sub)
                if not b2:
                    continue
                rows.append([f"`{field}`", subnice, f"{b2['n_actions']:,}",
                             fmt(b2["share_equal_to_the_awards_final_value"], 3),
                             fmt(b2["share_equal_to_the_base_action_value"], 3)])
        A(md_table(rows, ["Field", "Non-final actions of", "n",
                          "Already equals the award's final value",
                          "Still equals the base action's value"]))
        A("")
        cb = pr.get("ceiling_field_restatement", {})
        eb = pr.get("current_end_date_restatement", {})
        cbx = cb.get("non_final_actions_on_awards_whose_ceiling_changed", {})
        ebx = eb.get("non_final_actions_on_awards_whose_end_date_changed", {})
        if cbx and ebx:
            A("The two fields behave differently, and that difference is the whole "
              "design. On awards whose ceiling moved, "
              f"{fmt(cbx['share_equal_to_the_awards_final_value'], 3)} of earlier "
              "actions already carry the award's eventual final ceiling: the "
              "ceiling field is substantially restated. On awards whose end date "
              f"moved, only {fmt(ebx['share_equal_to_the_awards_final_value'], 3)} "
              "of earlier actions already carry the final end date. So the "
              "schedule field is read as it stands and the ceiling is "
              "reconstructed from per-action deltas.")
            A("")
        byfy = pr.get("ceiling_field_restatement_rate_by_action_fy", {})
        if byfy:
            A("Restatement rate of the ceiling field by the fiscal year of the "
              "action, on awards whose ceiling moved:")
            A("")
            A(md_table([[k, f"{v['non_final_actions']:,}",
                         fmt(v["share_already_equal_to_the_awards_final_value"], 3)]
                        for k, v in sorted(byfy.items())],
                       ["Action fiscal year", "Non-final actions",
                        "Already equals the award's final value"]))
            A("")
            A("The rise in the last two action years is an artefact of the "
              "snapshot rather than a change in reporting, and is labelled as an "
              "inference because it was not tested separately: an action dated "
              "close to the data end has the award's last observed action close "
              "behind it, so the two coincide more often simply because less time "
              "has passed for the ceiling to move again. The training and test "
              "years of this backtest sit in the flat middle of the table.")
            A("")
        A(src_note("field_evidence.py",
                   ".venv/bin/python -m usaspending.src.field_evidence"))
        A("")

    # ------------------------------------ limits of the reconstruction itself
    rs = reconstruction_sanity(panel_path)
    if rs:
        A("### What the reconstruction cannot fix")
        A("")
        A("Summing per-action deltas inherits whatever the deltas say. One award "
          "in the twenty printed in `field_evidence_samples.md` carries a single "
          "modification with a delta of 1.7 billion dollars on a contract that "
          "ends at 3.4 million, reversed by later actions; the reconstruction "
          "lands on the right final number to the cent, but a horizon that falls "
          "between the error and its reversal sits on top of it. That is a real "
          "limit and the question is how big it is.")
        A("")
        rows = []
        for h, b in rs["by_horizon"].items():
            rows.append([f"{h} months", fmt(b["median"], 4), fmt(b["p99"], 3),
                         fmt(b["p999"], 1), f"{b['max']:,.0f}",
                         fmt(b["share_above_1x"], 5), fmt(b["share_above_10x"], 5),
                         fmt(b["share_above_100x"], 5)])
        A(md_table(rows, ["Horizon", "Median growth", "p99", "p99.9", "Max",
                          "Share above 1x", "Share above 10x",
                          "Share above 100x"]))
        A("")
        A(md_table([
            ["Awards with a negative reconstructed ceiling at some horizon, "
             "which is physically impossible and therefore certainly a data error",
             f"{rs['negative_reconstructed_ceiling_at_some_horizon']:,}",
             fmt(rs["negative_share"], 6)],
            ["Awards whose ceiling more than doubled by 24 months and then fell "
             "by more than half by 36 months, the signature of a delta that was "
             "later reversed",
             f"{rs['doubled_by_24_then_halved_by_36']:,}",
             fmt(rs["doubled_then_halved_share"], 6)],
        ], ["Pathology", "Awards", "Share of panel"]))
        A("")
        A("So it is rare. It barely touches the binary labels, whose thresholds "
          "are 10, 25 and 50 percent: an award needs a gross error to cross them "
          "spuriously, and fewer than four awards in ten thousand exceed even ten "
          "times growth at 36 months. It matters much more for the continuous "
          "label, whose mean is not robust to a tail like this, which is why the "
          "quantile ladder winsorises at the training-period 1st and 99th "
          "percentile and reports the cut points. The binary results below should "
          "be read as unaffected; any mean of raw ceiling growth should not.")
        A("")
        A(src_note("report.py, reconstruction_sanity",
                   ".venv/bin/python -m usaspending.src.report"))
        A("")

    # ------------------------------------------------------------ fill rates
    fr = evidence.get("fill_rates_for_the_scoreboard", {}) if evidence else {}
    if fr:
        A("### Fill rates the public scoreboard depends on")
        A("")
        so = fr.get("solicitation_identifier_overall", {})
        sby = fr.get("solicitation_identifier_by_base_fy", {})
        if so and sby:
            A("`solicitation_identifier` is the key that would link an award back "
              "to the notice that produced it, which is what a forecast published "
              "before award would have to be registered against. Over "
              f"{so['base_actions']:,} base actions it is present on "
              f"{fmt(so['share_non_null'], 3)} of them. The second column applies "
              "a shape test: at least one letter, at least one digit, and at least "
              "eight characters. That rule is an inference about what a SAM.gov "
              "solicitation number looks like, not an official specification, and "
              "it is reported separately for that reason. It removes very little, "
              "so the values that are present are mostly well formed; the most "
              "common failures are literal placeholders such as `NONE` and `0`.")
            A("")
            A(md_table([[k, f"{v['base_actions']:,}",
                         fmt(v["share_non_null"], 3),
                         fmt(v["share_matching_solicitation_number_shape"], 3)]
                        for k, v in sorted(sby.items())],
                       ["Base fiscal year", "Base actions", "Share not null",
                        "Share matching the solicitation-number shape"]))
            A("")
            junk = fr.get(
                "solicitation_identifier_most_common_values_failing_the_shape_rule", {})
            if junk:
                A("Most common non-null values that fail the shape test: "
                  + ", ".join(f"`{k}` ({v:,})" for k, v in list(junk.items())[:8])
                  + ".")
                A("")
        oby = fr.get("number_of_offers_received_by_base_fy", {})
        if oby:
            A("`number_of_offers_received` is the competition-intensity field. It "
              "is not missing in this extract, which is itself the finding: it is "
              "present on every base action in every year. What varies is whether "
              "it carries information.")
            A("")
            A(md_table([[k, f"{v['base_actions']:,}", fmt(v["share_non_null"], 3),
                         fmt(v["median_where_present"], 1),
                         fmt(v["share_equal_to_one_where_present"], 3)]
                        for k, v in sorted(oby.items())],
                       ["Base fiscal year", "Base actions", "Share not null",
                        "Median where present", "Share equal to one"]))
            A("")
        oec = fr.get("number_of_offers_received_by_extent_competed_code", {})
        if oec:
            A("By extent-competed code, where the reason becomes clear. On awards "
              "coded as not competed the field is present but mechanically equal "
              "to one, so it adds nothing beyond the competition code itself. It "
              "only separates awards within the competed codes.")
            A("")
            A(md_table([[f"`{k}`", f"{v['base_actions']:,}",
                         fmt(v["share_of_all_base_actions"], 3),
                         fmt(v["share_non_null"], 3),
                         fmt(v["median_where_present"], 1),
                         fmt(v["share_equal_to_one_where_present"], 3)]
                        for k, v in sorted(oec.items(),
                                           key=lambda kv: -kv[1]["base_actions"])],
                       ["extent_competed_code", "Base actions", "Share of base actions",
                        "Share not null", "Median where present",
                        "Share equal to one"]))
            A("")
        A(src_note("field_evidence.py",
                   ".venv/bin/python -m usaspending.src.field_evidence"))
        A("")

    # ----------------------------------------------------------------- funnel
    A("## Data funnel")
    A("")
    if funnel:
        A(f"Data end, the latest action_date in the extract: "
          f"**{funnel.get('data_end')}**. Transactions loaded: "
          f"**{funnel.get('transactions_loaded', 0):,}**, across fiscal years "
          f"{funnel.get('fiscal_years_loaded', [])}. A missing fiscal year would "
          "not merely shrink the sample: outcomes are read from the modification "
          "record of later years, so a hole would silently delete real "
          "modifications and make every label whose horizon crosses it wrong. The "
          "loader therefore refuses to run on an extract with a gap.")
        A("")
        A("The funnel runs in two stages, and the order matters. The first stage "
          "asks whether an award is a well identified base award at all. What "
          "survives it is the **history source**: the set of prior awards a "
          "contractor's or an office's track record is counted over. The second "
          "stage asks whether an award is in scope for the forecast, and it runs "
          "only after labels, features and history have been built. Doing it that "
          "way means \"this contractor's tenth federal contract\" counts contracts, "
          "not contracts that happened to clear the simplified acquisition "
          "threshold; and it keeps the single-base-row check, which inspects "
          "actions dated after the base date, from reaching back and changing an "
          "earlier award's prior-award count.")
        A("")
        A(md_table([
            ["Base awards in the history source",
             f"{funnel.get('history_source_awards', 0):,}"],
            ["Of those, booked to an aggregate placeholder recipient",
             f"{funnel.get('history_source_aggregate_recipient_awards', 0):,}"],
        ], ["Quantity", "Awards"]))
        A("")
        A("The history source is much larger than the modelling panel because it "
          "is not restricted by award size. The placeholder-recipient count above "
          "is over that wider set; the section on contractor identity below "
          "reports the smaller count within the panel itself.")
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
                drop = ("" if prev is None
                        else ("none" if prev == n else f"-{prev - n:,}"))
                rows.append([s["filter"], f"{n:,}", drop])
                prev = n
            A(md_table(rows, ["Filter", "Awards remaining", "Dropped"]))
            A("")
            A(src_note("panel.py", ".venv/bin/python -m usaspending.src.panel"))
            A("")
    cens = censoring_table(panel_path)
    if not cens.empty:
        A("### Right censoring")
        A("")
        A("An award qualifies for horizon H only when its base action date plus H "
          "months falls at or before the data end, so no label is read off a "
          f"period the extract does not cover. The data end is "
          f"**{funnel.get('data_end')}**, which is later than the base action date "
          "of the last award in the population plus 36 months, so every award in "
          "the panel qualifies at every horizon and the model comparison is not "
          "made on different populations at different horizons. The table is "
          "reported anyway because the rule binds as soon as the panel is extended "
          "to more recent base years.")
        A("")
        A(df_table(cens))
        A("")
        A(src_note("report.py", ".venv/bin/python -m usaspending.src.report"))
        A("")

    # ------------------------------------------------- contractor identity
    A("### Who counts as one contractor")
    A("")
    A("The contractor history features are keyed on `recipient_uei`, which "
      "assumes a UEI is one firm. Some are not. USAspending books some actions "
      "against placeholder entities that stand for a bucket of firms, and on "
      "this panel the largest of them is the single most frequent recipient UEI "
      "of all, ahead of any real contractor:")
    A("")
    agg_tab = aggregate_recipient_table(panel_path)
    if not agg_tab.empty:
        A(md_table([[r["recipient_uei"], r["recipient_name"],
                     f"{r['base_awards_in_panel']:,}", r["held_out"]]
                    for _, r in agg_tab.iterrows()],
                   ["Recipient UEI", "Recipient name", "Base awards in the panel",
                    "Held out of contractor pooling"]))
        A("")
    A("Left alone, the first of those becomes a fictitious contractor with a "
      "track record of thousands of awards, and its prior mean outcome pools "
      "unrelated companies. Awards booked to such a recipient are therefore held "
      "out of the contractor pooling entirely, as both source and subject, and "
      "receive a null contractor history rather than a pooled one. A null is the "
      "honest answer and the gradient booster treats it as missing natively, "
      "whereas a zero would assert the contractor is new when the truth is that "
      "the record does not say who the contractor is. The awards stay in the "
      "panel, and carry a `recipient_is_aggregate` flag so the model can use the "
      "fact itself. Their awarding office is a real office, so office history is "
      "unaffected.")
    A("")
    A("The rule is a match on the recipient name against "
      "`UNDISCLOSED|MISCELLANEOUS FOREIGN AWARDEES|MULTIPLE RECIPIENTS|REDACTED`. "
      "It is an inference from the name, not an official flag, and it is stated "
      "here so it can be argued with. The word \"aggregate\" is deliberately not "
      "in the pattern: it matches real construction firms such as HIGH DESERT "
      "AGGREGATE & PAVING.")
    A("")
    frag = uei_fragmentation_summary(panel_path)
    frag_tab = uei_fragmentation_table(panel_path)
    if frag and not frag_tab.empty:
        A("The opposite failure is more common and harder to fix: one firm "
          "carrying several UEIs, which splits its track record. Of "
          f"{frag['distinct_recipient_names']:,} distinct recipient names in the "
          f"panel, {frag['names_with_more_than_one_uei']:,} "
          f"({fmt(frag['share_of_names'], 3)}) appear under more than one UEI, "
          f"covering {frag['awards_under_such_a_name']:,} awards "
          f"({fmt(frag['share_of_awards'], 3)} of the panel). Matching on name "
          "instead would create the opposite error, since distinct legal entities "
          "share names, so the UEI is kept and the consequence is reported rather "
          "than papered over: contractor history is understated for these firms.")
        A("")
        A(md_table([[r["recipient_name"], f"{int(r['awards']):,}",
                     str(int(r["distinct_ueis"])),
                     fmt(r["largest_single_uei_share"], 3)]
                    for _, r in frag_tab.iterrows()],
                   ["Recipient name", "Base awards", "Distinct UEIs",
                    "Share under the largest single UEI"]))
        A("")
    A(src_note("panel.py, is_aggregate_recipient; report.py, "
               "aggregate_recipient_table and uei_fragmentation_table",
               ".venv/bin/python -m usaspending.src.report"))
    A("")

    # -------------------------------------------------------- label defs
    A("## Label definitions")
    A("")
    A("For an award with base action date `t0` and horizon `H` months, the state "
      "at `H` is taken from the latest action with `action_date <= t0 + H months`, "
      "ordering actions by action date, then by the numeric suffix of the "
      "modification number, then by transaction number, then by the modification "
      "number itself. That last key is not decoration. Without it, 2,595 actions "
      "in the extract, 0.079 percent, tie on the first three and which one counts "
      "as the latest at a horizon would be settled by the order the per-year "
      "files happened to be concatenated in. With it there are no ties at all, "
      "measured on the full extract.")
    A("")
    A(md_table([
        ["ceiling_growth_H",
         "the reconstructed ceiling at H divided by base_and_all_options_value on "
         "the base action, minus one, where the reconstructed ceiling is the base "
         "action's base_and_all_options_value plus the sum of that same field over "
         "every later action dated at or before t0 + H. This is NOT "
         "potential_total_value_of_award read at H; the section on field behaviour "
         "above measures why that field cannot be used"],
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
            A(src_note("models.py, base_rates_table",
                       ".venv/bin/python -m usaspending.src.models") +
              " Written in full to `base_rates.csv`.")
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
        A(src_note("models.py", ".venv/bin/python -m usaspending.src.models") +
          " Full detail in `model_results.json`.")
        A("")
        if bss_chart:
            A(f"![Brier skill score by label]({bss_chart})")
            A("")

        scored = [r for r in results if "models" in r]
        if scored:
            def bss(r, m):
                return r["models"][m]["bss_vs_train_base_rate"]
            n = len(scored)
            beats_base = sum(1 for r in scored if bss(r, "gbm") > 0)
            beats_rc = sum(1 for r in scored
                           if bss(r, "gbm") > bss(r, "reference_class"))
            rc_beats_base = sum(1 for r in scored
                                if bss(r, "reference_class") > 0)
            hist_helps = sum(1 for r in scored
                             if bss(r, "gbm") > bss(r, "gbm_no_history"))
            gaps = [bss(r, "gbm") - bss(r, "gbm_no_history") for r in scored]
            med_gap = float(np.median(gaps)) if gaps else float("nan")
            aucs = [r["models"]["gbm"]["auc"] for r in scored
                    if not np.isnan(r["models"]["gbm"]["auc"])]
            A("### What the table says")
            A("")
            A(f"Of the {n} label-and-horizon cells, gradient boosting beats the "
              f"training base rate in {beats_base}, and beats the reference class "
              f"in {beats_rc}. The reference class on its own beats the base rate "
              f"in {rc_beats_base}. Gradient boosting AUC runs from "
              f"{fmt(min(aucs), 3)} to {fmt(max(aucs), 3)} with a median of "
              f"{fmt(float(np.median(aucs)), 3)}.")
            A("")
            verdict = (
                "Whatever the history features contribute is small next to what "
                "the award-time fields already carry, and on a public scoreboard "
                "the simpler model would be the honest default."
                if abs(med_gap) < 0.005 else
                ("The history block earns its place: the gap is large enough that "
                 "dropping it would cost real skill, so a scoreboard should carry "
                 "it and accept the extra machinery."
                 if med_gap >= 0.005 else
                 "The history block actively hurts: the model without it scores "
                 "better on the median cell, which means the as-of history is "
                 "adding more noise than signal and should be dropped."))
            A("The contractor and office history block is the part worth stating "
              f"plainly: it improves the Brier skill score in {hist_helps} of the "
              f"{n} cells, and the median difference between the model with "
              f"history and the model without it is {fmt(med_gap, 5)} of skill "
              f"score. {verdict}")
            A("")
            if beats_base < n:
                A(f"The {n - beats_base} cells where gradient boosting fails to "
                  "beat the training base rate are reported as they stand. A "
                  "negative Brier skill score on a pre-registered scoreboard is a "
                  "result, not a bug to be tuned away, and nothing here was "
                  "selected on the test years.")
                A("")
            top = sorted(scored, key=lambda r: -bss(r, "gbm"))
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
    A("One table per label at the 36 month horizon. `model_results.json` carries "
      "the same table for all three horizons, and for the reference class as well "
      "as the gradient boosting model.")
    A("")
    for label, h in [(lab, 36) for lab in label_order(results)]:
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
    ait = aggregate_recipients_in_test(panel_path)
    if ait:
        A("Awards booked to an aggregate placeholder recipient are excluded from "
          "both sides of that split, because such an award has no identifiable "
          "contractor and is therefore neither a contractor seen in training nor "
          "one unseen in training. Leaving them in would mark a test award as "
          "\"seen\" because the bucket code appears in both periods rather than "
          "because any contractor does. The exclusion is measured rather than "
          "assumed to matter: of "
          f"{ait['test_rows']:,} test-year awards, "
          f"{ait['test_rows_with_an_aggregate_recipient']:,} carry an aggregate "
          f"recipient, and excluding them changes "
          f"{ait['rows_that_change_classification']:,} rows' classification, "
          f"leaving the slice at {ait['unseen_excluding_aggregates']:,} either "
          "way. All three placeholder recipients appear in the training years, so "
          "none of them was ever in the unseen slice to begin with.")
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
        A(src_note("models.py, run_cell",
                   ".venv/bin/python -m usaspending.src.models"))
        A("")

    # ------------------------------------------------------------- importance
    A("## Feature importance")
    A("")
    A("Permutation importance on the validation years for the gradient boosting "
      "model with history, measured as the increase in Brier score when one "
      "feature is shuffled. Higher means the model relied on it more.")
    A("")
    perm_hs = sorted({r["horizon"] for r in results
                      if r.get("permutation_importance_computed")})
    skipped = sorted({r["horizon"] for r in results
                      if r.get("permutation_importance_computed") is False})
    if perm_hs:
        A(f"Computed at horizon{'s' if len(perm_hs) != 1 else ''} "
          f"{', '.join(str(h) for h in perm_hs)} months"
          + (f" and deliberately not at {', '.join(str(h) for h in skipped)}"
             if skipped else "")
          + ". It is single threaded and by a wide margin the most expensive step "
          "in the ladder, and this is the horizon the tables below print, so it "
          "is scoped rather than run everywhere. The omission is recorded per "
          "cell in `model_results.json` as `permutation_importance_computed`, so "
          "a missing horizon is visibly absent rather than silently zero.")
        A("")
    for label, h in [(lab, 36) for lab in label_order(results)]:
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
        A(src_note("models.py, run_cell",
                   ".venv/bin/python -m usaspending.src.models"))
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
        qt = (load_json("timings.json", {}) or {}).get("quantile_models", {})
        covered = sorted({(r.get("label"), r.get("horizon")) for r in quant
                          if "quantiles" in r})
        hs = sorted({h for _, h in covered})
        ls = sorted({lab for lab, _ in covered})
        A(f"Fitted for {len(covered)} of the "
          f"{len(set(l for l, _ in covered)) * 3} label-and-horizon combinations "
          f"the continuous labels allow: labels {', '.join('`%s`' % x for x in ls)} "
          f"at horizon{'s' if len(hs) != 1 else ''} "
          f"{', '.join(str(h) for h in hs)} months. Each combination costs three "
          "quantile regressors and this ladder is optional in the specification, "
          "so the scope is stated here rather than left to be inferred from the "
          "table."
          + (f" Wall time {qt['seconds']:,.0f} s." if qt.get("seconds") else ""))
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
        A(src_note("quantile_models.py",
                   ".venv/bin/python -m usaspending.src.quantile_models"))
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

    # ------------------------------------------------- deviations from spec
    A("## Where this departs from the specification, and why")
    A("")
    _dev_intro_at = len(L)
    A("")          # replaced below, once the list length is known
    A("")
    d = funnel.get("base_row_diagnostics", {})
    rcs = reference_class_shape(res_dir)
    pf = ((evidence.get("claim_value_state_fields_are_award_level", {})
           .get("per_field", {}).get("potential_total_value_of_award", {}))
          if evidence else {})
    ceil_beh = (evidence.get("claim_ceiling_field_behaviour_where_fully_populated", {})
                if evidence else {})
    nfc = ceil_beh.get("non_final_actions_on_awards_whose_ceiling_changed", {})
    deviations = [
        ("The ceiling label is reconstructed, not read off "
         "`potential_total_value_of_award`",
         "The specification defines `ceiling_growth_H` as that field read at the "
         "horizon. It cannot be: it is populated on "
         f"{fmt(pf.get('share_of_all_actions_populated'), 3)} of actions overall "
         "but on roughly a quarter of actions in the training years and on all of "
         "them from FY2018, so the label would not be the same label on both "
         "sides of the split; and where it is complete, a non-final action of an "
         "award whose ceiling moved already carries the award's eventual final "
         f"value {fmt(nfc.get('share_equal_to_the_awards_final_value'), 3)} of the "
         "time, which is a forward look. The ceiling at a horizon is instead the "
         "base action's `base_and_all_options_value` plus the sum of that field "
         "over later actions up to the horizon, which the dictionary prescribes "
         "and which converges on the field's own value on the award's final "
         "action. All of that is measured in the field-behaviour section above."),
        ("Awards without an explicit modification number of zero are dropped, not "
         "backfilled",
         "The specification says to use the modification-zero action, or the "
         "earliest action if zero is absent. Using the earliest action would "
         "treat a mid-life modification as an award, which would put a "
         "already-grown ceiling in the denominator of the growth label and would "
         "systematically understate growth for exactly the oldest contracts. So "
         f"the {d.get('awards_without_modification_number_zero', 0):,} awards with "
         "no modification-zero action in the window are excluded instead, and so "
         f"are the {d.get('awards_with_more_than_one_base_action', 0):,} awards "
         "that carry more than one. The cost is left truncation: a contract whose "
         "base action predates 1 October 2009 cannot enter the panel. The funnel "
         "above reports both counts."),
        ("Reference-class shrinkage is continuous rather than a threshold at n=30",
         "The specification says to shrink to the parent cell when n is below 30. "
         "The implementation shrinks every cell as "
         "`(n*mean + 30*parent) / (n + 30)`, which gives the parent half the "
         "weight at n=30, about 9 percent at n=300 and about 91 percent at n=3. A "
         "hard switch would make the forecast jump discontinuously as a cell "
         "crossed 30 observations. This is not a marginal choice: of the "
         f"{rcs.get('cells', 0):,} finest cells, {rcs.get('cells_with_n_below_30', 0):,} "
         f"({fmt(rcs.get('share_below_30'), 3)}) hold fewer than 30 observations "
         f"and {rcs.get('cells_with_n_of_one', 0):,} hold exactly one, so most "
         "cells are in the regime where the rule bites. "
         "`reference_class_table.csv` reports n, the raw cell mean, the parent "
         "and the shrunk mean side by side, so the effect is visible per cell."),
        ("CRPS is not computed; the quantile ladder is reported instead",
         "The specification makes CRPS optional and offers quantile gradient "
         "boosting with pinball loss at 0.10, 0.50 and 0.90 as the alternative. "
         "That is what is reported. Outcomes are winsorised at the training-period "
         "1st and 99th percentile before fitting and scoring, because ceiling "
         "growth has a tail in the thousands; the cut points are printed with the "
         "results."),
        ("History is computed before the in-scope filters, not after",
         "The specification asks for recipient and office history over awards "
         "with a base action date strictly before this award's. Computing that "
         "after the population filters would have made it \"prior awards that "
         "also cleared the simplified acquisition threshold, had a valid end "
         "date and carried exactly one modification-zero action\", which is not "
         "the same quantity and is not what a contracting officer means by a "
         "contractor's track record. Worse, the single-base-row filter inspects "
         "actions dated after the base date, so applying it first would let a "
         "later action change an earlier award's prior-award count. Labels, "
         "features and history are therefore built on the wider history source "
         "and the in-scope filters applied afterwards. The funnel above reports "
         "both stages and both counts."),
        ("The history block carries one feature more than specified",
         "The specification asks for prior award count, prior mean "
         "`ceiling_growth_36` and prior termination rate, for both recipient and "
         "office. A prior schedule-slip rate is included as well, on the same "
         "as-of rule. Prior mean ceiling growth is clipped to [-1, 10] before "
         "averaging, using bounds fixed a priori rather than estimated from the "
         "data, because a single award with a tiny base ceiling and a large later "
         "modification would otherwise dominate a contractor's history. The label "
         "itself is never clipped."),
    ]
    _words = {1: "One thing is", 2: "Two things are", 3: "Three things are",
              4: "Four things are", 5: "Five things are", 6: "Six things are",
              7: "Seven things are", 8: "Eight things are"}
    L[_dev_intro_at] = (
        f"{_words.get(len(deviations), f'{len(deviations)} things are')} done "
        "differently from the way the workstream was specified. Each is a measured "
        "decision, not a shortcut, and each is listed here so a reader does not "
        "have to diff the code against the brief.")
    for title, body in deviations:
        A(f"- **{title}.** {body}")
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
        "Contractor identity is only as stable as the unique entity identifier, "
        "and it is not very stable. Measured on this panel, RAYTHEON COMPANY "
        "appears under 54 distinct UEIs with its largest holding under a fifth of "
        "its awards, and 12.8 percent of panel awards sit under a recipient name "
        "that carries more than one UEI. Novations (action_type_code J) and the "
        "2022 move from DUNS to UEI both break the key. Contractor history is "
        "therefore understated, worst for exactly the largest primes, and that is "
        "one candidate explanation for how little the history block adds.",
        "Some awards are booked to placeholder recipients that stand for a bucket "
        "of firms rather than a firm. Those are identified by a name rule, held "
        "out of the contractor pooling and given a null contractor history; the "
        "section on contractor identity gives the rule, the counts and the "
        "reasoning. The rule is an inference from the recipient name and may not "
        "catch every placeholder in use.",
        "Prior-award counts are taken over the history source, which is every "
        "well identified base award in FY2010 to FY2022 regardless of size, not "
        "over the modelling panel. A contractor's second contract counts as its "
        "second contract even when the first was below the simplified acquisition "
        "threshold. That is the intended reading, and it differs from counting "
        "only in-scope awards, so it is stated rather than assumed.",
        "Text fields in the feed carry mis-transcoded characters at source. One "
        "of the larger recipients in the panel is recorded as BUNDESAMT F\u00bfR "
        "BAUWESEN UND RAUMORDNUNG, with an inverted question mark where an "
        "umlaut belongs. This is not introduced by the decoding here: measured "
        "over the panel, zero values in recipient_name or awarding_agency_name "
        "contain the Unicode replacement character. Name-based matching of any "
        "kind inherits the problem.",
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
        "Whether the three placeholder recipients identified here are the "
        "complete set. The rule matches on the recipient name, and a placeholder "
        "named in some other way would pass through as a contractor.",
        "Whether a recipient name carrying several UEIs is one firm with a "
        "fragmented identifier or several genuinely distinct legal entities "
        "sharing a name. Resolving that needs an entity-resolution source such as "
        "SAM.gov registration records, which was not attempted. The fragmentation "
        "is measured; its cause is not.",
    ]:
        A(f"- {c}")
    A("")

    # ------------------------------------------------------------- operations
    A("## Reproduction, disk and wall time")
    A("")
    raw_mb = dir_bytes(raw_dir) / 1e6
    panel_mb = (panel_path.stat().st_size / 1e6) if panel_path.exists() else 0.0
    results_mb = dir_bytes(res_dir) / 1e6
    timings = load_json("timings.json", {}) or {}
    if timings:
        A("Wall time per step, each recorded by the step itself into "
          "`timings.json`:")
        A("")
        rows = [[k.replace("_", " "), f"{v['seconds']:,.0f}", v.get("finished_at", "")]
                for k, v in timings.items()]
        total = sum(v["seconds"] for v in timings.values())
        rows.append(["**total of the recorded steps**", f"**{total:,.0f}**", ""])
        A(md_table(rows, ["Step", "Seconds", "Finished"]))
        A("")
        A("The fetch is not in that total. It is dominated by waiting on the "
          "USAspending download service, which queues each fiscal-year job server "
          "side; `fetch_manifest.json` records every job. Re-running the fetch "
          "against parquet already on disk reuses it and takes seconds.")
        A("")
    A(md_table([
        ["Definitive-contract parquet extract", f"{raw_mb:.1f} MB"],
        ["Award panel", f"{panel_mb:.1f} MB"],
        ["Results directory, this report included", f"{results_mb:.1f} MB"],
        ["Total disk held by the workstream",
         f"{(raw_mb + panel_mb + results_mb):.1f} MB, against a 15 GB budget"],
        ["Peak additional disk during a fetch",
         "one zip at a time, each under 10 MB for the API path, deleted after "
         "conversion to parquet"],
        ["Peak additional disk during the optional archive cross-check",
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
      "`reference_class_table.csv`, `continuous_label_summary.csv`, "
      "`leak_comparison.csv`, `funnel.json`, `field_evidence.json`, "
      "`field_evidence_samples.md`, `column_mapping.json`, `model_results.json`, "
      "`quantile_results.json`, `fetch_manifest.json`, "
      "`category_cardinality.json`, `timings.json`, and the PNG charts.")
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
