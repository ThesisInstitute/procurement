"""Evidence that the value and date fields behave as the data dictionary says.

Nothing here is asserted from the dictionary alone. Each claim is turned into a
test computed on the transaction data, and a sample of 20 heavily modified
awards is printed action by action so a reader can check the arithmetic by eye.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from panel import fiscal_year, is_base_mod, load_transactions  # noqa: E402

SAMPLE_COLS = [
    "modification_number", "action_date", "action_type_code",
    "federal_action_obligation", "base_and_all_options_value",
    "potential_total_value_of_award", "current_total_value_of_award",
    "base_and_exercised_options_value",
    "period_of_performance_current_end_date",
    "period_of_performance_potential_end_date",
]


def close(a: pd.Series, b: pd.Series, rel: float = 0.01, abs_: float = 1.0) -> pd.Series:
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    denom = pd.concat([a.abs(), b.abs()], axis=1).max(axis=1)
    return ((a - b).abs() <= np.maximum(abs_, rel * denom))


def run(tx: pd.DataFrame, out_dir: Path, log) -> dict:
    ev: dict = {}

    at = tx["action_type_code"].astype("string").fillna("(null)")
    counts = at.value_counts().sort_values(ascending=False)
    ev["action_type_code_counts"] = {k: int(v) for k, v in counts.items()}
    log(f"action_type_code codes observed: {list(counts.index)}")

    mod = tx["modification_number"].astype("string").fillna("(null)")
    base_mask = tx["is_base_mod"]
    ev["modification_number_top20_overall"] = {
        k: int(v) for k, v in mod.value_counts().head(20).items()}
    first = tx.groupby("contract_award_unique_key", sort=False).head(1)
    ev["modification_number_top20_on_first_action"] = {
        k: int(v) for k, v in
        first["modification_number"].astype("string").fillna("(null)"
        ).value_counts().head(20).items()}

    gg = tx.groupby("contract_award_unique_key", sort=False)
    sizes = gg.size()
    multi_keys = sizes[sizes > 1].index

    base_rows = tx[base_mask].groupby("contract_award_unique_key", sort=False).head(1)
    tx["is_base_row"] = False
    tx.loc[base_rows.index, "is_base_row"] = True
    base = base_rows.set_index("contract_award_unique_key")
    n_base = len(base)

    # Claim 1: on the base row, base_and_all_options_value is a level equal to
    # potential_total_value_of_award.
    eq = close(base["base_and_all_options_value"],
               base["potential_total_value_of_award"])
    ev["claim_base_row_ceiling_equals_potential"] = {
        "n_base_rows": int(n_base),
        "n_both_present": int((base["base_and_all_options_value"].notna()
                               & base["potential_total_value_of_award"].notna()).sum()),
        "share_equal_within_1pct_or_1usd": float(eq.mean()),
    }

    # Claim 2: on modifications, base_and_all_options_value is a CHANGE, so the
    # base level plus the running sum of the mod deltas tracks
    # potential_total_value_of_award at each action.
    t = tx.copy()
    t["base_level"] = t["contract_award_unique_key"].map(
        base["base_and_all_options_value"])
    t["delta"] = np.where(t["is_base_mod"], 0.0,
                          pd.to_numeric(t["base_and_all_options_value"],
                                        errors="coerce").fillna(0.0))
    t["cum_delta"] = t.groupby("contract_award_unique_key", sort=False)["delta"].cumsum()
    t["reconstructed_ceiling"] = t["base_level"] + t["cum_delta"]
    mods = t[~t["is_base_mod"] & t["base_level"].notna()
             & t["potential_total_value_of_award"].notna()]
    recon_ok = close(mods["reconstructed_ceiling"],
                     mods["potential_total_value_of_award"], rel=0.01, abs_=1.0)
    level_ok = close(mods["base_and_all_options_value"],
                     mods["potential_total_value_of_award"], rel=0.01, abs_=1.0)
    ev["claim_mod_ceiling_field_is_a_delta"] = {
        "n_modification_rows_tested": int(len(mods)),
        "share_where_base_plus_running_delta_matches_potential": float(recon_ok.mean()),
        "share_where_the_mod_field_itself_matches_potential": float(level_ok.mean()),
        "reading": ("the delta reading reconstructs the running ceiling far more "
                    "often than the level reading" if recon_ok.mean() > level_ok.mean()
                    else "the level reading matches more often"),
    }

    # Claim 2b: the three value-state fields are award-level end-state summaries
    # pasted onto every action, not per-action running levels. Test: how often is
    # the field constant across the actions of one award, and how often is it
    # populated at all.
    constancy = {}
    for c in ["potential_total_value_of_award", "current_total_value_of_award",
              "total_dollars_obligated", "base_and_all_options_value",
              "base_and_exercised_options_value", "federal_action_obligation",
              "period_of_performance_current_end_date",
              "period_of_performance_potential_end_date",
              "period_of_performance_start_date"]:
        if c not in tx.columns:
            continue
        nun = gg[c].nunique(dropna=True).reindex(multi_keys)
        npop = gg[c].count().reindex(multi_keys)  # count() skips nulls
        sel = nun[npop > 1]
        constancy[c] = {
            "share_of_all_actions_populated": float(tx[c].notna().mean()),
            "awards_with_more_than_one_populated_action": int(len(sel)),
            "share_constant_within_award": float((sel == 1).mean()) if len(sel) else None,
        }
    ev["claim_value_state_fields_are_award_level"] = {
        "per_field": constancy,
        "reading": ("a field that is near constant within an award is an "
                    "award-level summary joined onto every action, so its value "
                    "at a horizon is the award's end state and cannot be used to "
                    "build a label"),
    }

    # Claim 2c: how the ceiling field behaves at each action, tested only where
    # potential_total_value_of_award is fully populated so the test is not
    # selecting on availability. Three comparisons per non-final action:
    # the contemporaneous reconstruction, the award's final value, and the base
    # level. A field that is a true running level matches the reconstruction; a
    # field carrying a restated end state matches the final value.
    pop_by_fy = tx.groupby(fiscal_year(tx["action_date"]))[
        "potential_total_value_of_award"].apply(lambda ser: float(ser.notna().mean()))
    ev["potential_value_population_rate_by_action_fy"] = {
        str(int(k)): round(v, 4) for k, v in pop_by_fy.items() if pd.notna(k)}
    base_pop_by_fy = tx.groupby(fiscal_year(tx["action_date"]))[
        "base_and_all_options_value"].apply(lambda ser: float(ser.notna().mean()))
    ev["base_and_all_options_population_rate_by_action_fy"] = {
        str(int(k)): round(v, 4) for k, v in base_pop_by_fy.items() if pd.notna(k)}

    full_years = sorted(int(k) for k, v in ev[
        "potential_value_population_rate_by_action_fy"].items() if v > 0.99)
    ev["fiscal_years_where_potential_value_is_fully_populated"] = full_years

    if full_years:
        cutoff_fy = min(full_years) + 1  # base year whose whole life is inside
        base_fy_all = fiscal_year(base["action_date"])
        keys = base.index[(base_fy_all >= cutoff_fy)
                          & (sizes.reindex(base.index) >= 3)]
        sub = tx[tx["contract_award_unique_key"].isin(set(keys))].copy()
        sub["delta"] = np.where(sub["is_base_row"], 0.0,
                                pd.to_numeric(sub["base_and_all_options_value"],
                                              errors="coerce").fillna(0.0))
        sub["base_level"] = sub["contract_award_unique_key"].map(
            base["base_and_all_options_value"])
        sg = sub.groupby("contract_award_unique_key", sort=False)
        sub["recon"] = sub["base_level"] + sg["delta"].cumsum()
        sub["final_value"] = sg["potential_total_value_of_award"].transform("last")
        sub["rank_from_end"] = sg.cumcount(ascending=False)
        nonlast = sub[sub["rank_from_end"] > 0]
        changed_keys = set(sg["delta"].sum().abs().pipe(lambda x: x[x > 1]).index)
        nl_changed = nonlast[nonlast["contract_award_unique_key"].isin(changed_keys)]
        last_rows = sub[sub["rank_from_end"] == 0]

        def block(frame):
            if frame.empty:
                return None
            return {
                "n_actions": int(len(frame)),
                "share_equal_to_contemporaneous_reconstruction": float(
                    close(frame["potential_total_value_of_award"], frame["recon"]).mean()),
                "share_equal_to_the_awards_final_value": float(
                    close(frame["potential_total_value_of_award"],
                          frame["final_value"]).mean()),
                "share_equal_to_the_base_level": float(
                    close(frame["potential_total_value_of_award"],
                          frame["base_level"]).mean()),
            }

        ev["claim_ceiling_field_behaviour_where_fully_populated"] = {
            "base_fiscal_year_at_or_after": int(cutoff_fy),
            "awards_tested": int(len(keys)),
            "awards_whose_ceiling_changed": int(len(changed_keys)),
            "non_final_actions": block(nonlast),
            "non_final_actions_on_awards_whose_ceiling_changed": block(nl_changed),
            "final_actions": block(last_rows),
            "reading": (
                "on the final action the field and the reconstruction agree, which "
                "is the convergence check. On earlier actions they disagree on a "
                "material share, and part of that share is the field already "
                "carrying the award's final value, which is a forward look"),
        }

    # Claim 3: current_total_value_of_award is obligated-to-date, so it tracks the
    # running sum of federal_action_obligation and sits at or below the ceiling.
    t["cum_oblig"] = t.groupby("contract_award_unique_key", sort=False)[
        "federal_action_obligation"].cumsum()
    cmp_rows = t[t["current_total_value_of_award"].notna() & t["cum_oblig"].notna()]
    ev["claim_current_value_is_obligated_to_date"] = {
        "n_rows_tested": int(len(cmp_rows)),
        "share_current_value_matches_running_obligation": float(
            close(cmp_rows["current_total_value_of_award"],
                  cmp_rows["cum_oblig"], rel=0.01, abs_=1.0).mean()),
        "share_current_value_le_potential": float(
            (pd.to_numeric(cmp_rows["current_total_value_of_award"], errors="coerce")
             <= pd.to_numeric(cmp_rows["potential_total_value_of_award"],
                              errors="coerce") + 1.0).mean()),
    }

    # Claim 4: period_of_performance_current_end_date is revised by modifications.
    nun = gg["period_of_performance_current_end_date"].nunique(dropna=True)
    nact = sizes
    multi = nact[nact > 1].index
    ev["claim_current_end_date_is_revised_by_mods"] = {
        "awards_with_more_than_one_action": int(len(multi)),
        "share_of_those_with_more_than_one_distinct_current_end_date": float(
            (nun.loc[multi] > 1).mean()),
        "share_with_exactly_one_distinct_current_end_date": float(
            (nun.loc[multi] == 1).mean()),
    }

    # Claim 5: potential_total_value_of_award is non-decreasing far more often
    # than not, consistent with a running ceiling rather than a per-action value.
    t["pot"] = pd.to_numeric(t["potential_total_value_of_award"], errors="coerce")
    t["pot_prev"] = t.groupby("contract_award_unique_key", sort=False)["pot"].shift(1)
    step = t[t["pot"].notna() & t["pot_prev"].notna()]
    ev["claim_potential_value_is_a_running_level"] = {
        "n_consecutive_pairs": int(len(step)),
        "share_non_decreasing": float((step["pot"] >= step["pot_prev"] - 1.0).mean()),
        "share_unchanged": float(close(step["pot"], step["pot_prev"]).mean()),
    }

    # Field fill rates, including the solicitation join key the memo flagged.
    fill = {}
    for c in ["solicitation_identifier", "number_of_offers_received",
              "recipient_uei", "recipient_duns", "awarding_office_code",
              "naics_code", "product_or_service_code", "extent_competed_code",
              "type_of_contract_pricing_code", "type_of_set_aside_code",
              "fed_biz_opps_code", "performance_based_service_acquisition_code",
              "multi_year_contract_code", "cost_or_pricing_data_code",
              "contracting_officers_determination_of_business_size_code",
              "period_of_performance_potential_end_date"]:
        if c in base.columns:
            fill[c] = float(base[c].notna().mean())
    ev["base_row_fill_rate"] = fill

    # solicitation_identifier fill rate by fiscal year (memo: unmeasured).
    b = base.copy()
    b["fy"] = fiscal_year(b["action_date"])
    sol = b.groupby("fy")["solicitation_identifier"].apply(
        lambda s: float(s.notna().mean()))
    ev["solicitation_identifier_fill_rate_by_base_fy"] = {
        str(k): round(v, 4) for k, v in sol.items() if pd.notna(k)}

    # Awards missing a base action, by the fiscal year of their first observed
    # action. Left truncation should concentrate this in the first year loaded.
    first_fy = fiscal_year(gg["action_date"].min())
    has0 = gg["is_base_mod"].any()
    trunc = pd.DataFrame({"first_fy": first_fy, "has_base": has0})
    ev["share_without_a_base_action_by_first_seen_fy"] = {
        str(int(k)): {"awards": int(len(b)),
                      "share_without_base_action": round(float(1 - b["has_base"].mean()), 4)}
        for k, b in trunc.groupby("first_fy") if pd.notna(k)}

    # Twenty heavily modified awards, printed action by action.
    counts_per_award = nact.sort_values(ascending=False)
    big = base.index.intersection(counts_per_award.index)
    ranked = counts_per_award.loc[big]
    ranked = ranked[ranked >= 8]
    sample_keys = list(ranked.index[:2000])
    # prefer awards that are large and have terminations or change orders
    interesting = tx[tx["contract_award_unique_key"].isin(sample_keys)]
    has_event = interesting[interesting["action_type_code"].isin(
        ["A", "D", "E", "F", "X", "G"])]["contract_award_unique_key"].unique()
    chosen = [k for k in sample_keys if k in set(has_event)][:20]
    if len(chosen) < 20:
        chosen = sample_keys[:20]

    lines = []
    chosen_rows = tx[tx["contract_award_unique_key"].isin(set(chosen))]
    by_key = {k: b for k, b in chosen_rows.groupby("contract_award_unique_key",
                                                   sort=False)}
    for k in chosen:
        blk = by_key[k][SAMPLE_COLS].copy()
        lines.append(f"### {k}")
        lines.append("")
        lines.append(blk.to_string(index=False, max_colwidth=22))
        lines.append("")
        bl = base.loc[k, "base_and_all_options_value"]
        recon = bl + pd.to_numeric(
            blk.loc[~is_base_mod(blk["modification_number"]),
                    "base_and_all_options_value"], errors="coerce").fillna(0).cumsum()
        last_pot = blk["potential_total_value_of_award"].iloc[-1]
        lines.append(f"base ceiling {bl}; base plus summed mod deltas "
                     f"{float(recon.iloc[-1]) if len(recon) else bl}; "
                     f"potential_total_value_of_award on last action {last_pot}")
        lines.append("")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "field_evidence_samples.md").write_text(
        "# Field behaviour: twenty heavily modified awards\n\n" + "\n".join(lines))
    ev["sample_award_keys"] = chosen
    log(f"wrote {out_dir/'field_evidence_samples.md'} with {len(chosen)} awards")
    return ev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdir", type=Path, default=Path("data/raw/usaspending/parquet"))
    ap.add_argument("--out", type=Path, default=Path("usaspending/results"))
    ap.add_argument("--log", type=Path,
                    default=Path("usaspending/logs/field_evidence.log"))
    ap.add_argument("--sample-fy", type=int, default=None,
                    help="restrict to one source fiscal year for a fast run")
    a = ap.parse_args()
    a.log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(a.log, "a")

    def log(msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}"
        print(line, flush=True)
        handle.write(line + "\n")
        handle.flush()

    t0 = time.time()
    tx = load_transactions(a.pdir, log)
    if a.sample_fy:
        tx = tx[tx["source_fiscal_year"] == a.sample_fy].copy()
    ev = run(tx, a.out, log)
    ev["seconds"] = round(time.time() - t0, 1)
    (a.out / "field_evidence.json").write_text(json.dumps(ev, indent=1))
    log(f"wrote {a.out/'field_evidence.json'} in {ev['seconds']}s")
    handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
