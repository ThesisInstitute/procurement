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
from timing import record as record_timing  # noqa: E402

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


SOLICITATION_MIN_LEN = 8


def looks_like_a_solicitation_number(s: pd.Series) -> pd.Series:
    """Shape test for a SAM.gov style solicitation number.

    This is an INFERENCE, not an official rule, and it is labelled as such
    wherever it is reported: a real solicitation number carries both letters and
    digits and is at least SOLICITATION_MIN_LEN characters long. Placeholders
    such as "NONE", "N/A" or a bare sequence number fail it. The test says
    nothing about whether the value resolves to a retrievable notice.
    """
    v = s.astype("string").str.strip()
    has_alpha = v.str.contains(r"[A-Za-z]", regex=True, na=False)
    has_digit = v.str.contains(r"[0-9]", regex=True, na=False)
    long_enough = (v.str.len() >= SOLICITATION_MIN_LEN).fillna(False)
    return (has_alpha & has_digit & long_enough).fillna(False)


def _restatement_block(frame: pd.DataFrame, field: str, final_col: str,
                       base_col: str) -> dict | None:
    """How often a field on a non-final action already equals its final value.

    A field that is genuinely carried per action should rarely equal the value
    the award ends up with, on awards where that value changed. A field that is
    restated across the award's whole history will equal it almost always.
    """
    if frame.empty:
        return None
    return {
        "n_actions": int(len(frame)),
        "share_equal_to_the_awards_final_value": float(
            close(frame[field], frame[final_col]).mean()),
        "share_equal_to_the_base_action_value": float(
            close(frame[field], frame[base_col]).mean()),
    }


def _date_restatement_block(frame: pd.DataFrame, field: str, final_col: str,
                            base_col: str) -> dict | None:
    """The same test for a date field, compared exactly rather than within a tolerance."""
    if frame.empty:
        return None
    f = pd.to_datetime(frame[field], errors="coerce")
    return {
        "n_actions": int(len(frame)),
        "share_equal_to_the_awards_final_value": float(
            (f == pd.to_datetime(frame[final_col], errors="coerce")).mean()),
        "share_equal_to_the_base_action_value": float(
            (f == pd.to_datetime(frame[base_col], errors="coerce")).mean()),
    }


def fill_rate_tables(base: pd.DataFrame, log) -> dict:
    """The two fill-rate tables a public scoreboard needs, on base actions."""
    b = base.copy()
    b["fy"] = fiscal_year(b["action_date"])
    b = b[b["fy"].notna()]
    out: dict = {}

    sol = b["solicitation_identifier"]
    shaped = looks_like_a_solicitation_number(sol)
    rows = {}
    for fy, blk in b.groupby("fy"):
        m = blk.index
        rows[str(int(fy))] = {
            "base_actions": int(len(blk)),
            "share_non_null": float(sol.loc[m].notna().mean()),
            "share_matching_solicitation_number_shape": float(shaped.loc[m].mean()),
        }
    out["solicitation_identifier_by_base_fy"] = rows
    out["solicitation_identifier_overall"] = {
        "base_actions": int(len(b)),
        "share_non_null": float(sol.notna().mean()),
        "share_matching_solicitation_number_shape": float(shaped.mean()),
        "shape_rule": (f"contains at least one letter and one digit and is at "
                       f"least {SOLICITATION_MIN_LEN} characters after stripping "
                       f"whitespace; an inference, not an official rule"),
    }
    present = sol[sol.notna()].astype("string").str.strip()
    out["solicitation_identifier_most_common_values_failing_the_shape_rule"] = {
        str(k): int(v) for k, v in
        present[~looks_like_a_solicitation_number(present)].value_counts().head(15).items()}

    offers = pd.to_numeric(b["number_of_offers_received"], errors="coerce")
    rows = {}
    for fy, blk in b.groupby("fy"):
        o = offers.loc[blk.index]
        rows[str(int(fy))] = {
            "base_actions": int(len(blk)),
            "share_non_null": float(o.notna().mean()),
            "median_where_present": (float(o.median()) if o.notna().any() else None),
            "share_equal_to_one_where_present": (
                float((o.dropna() == 1).mean()) if o.notna().any() else None),
        }
    out["number_of_offers_received_by_base_fy"] = rows

    ec = b["extent_competed_code"].astype("string").fillna("(null)")
    rows = {}
    for code, blk in b.groupby(ec):
        o = offers.loc[blk.index]
        rows[str(code)] = {
            "base_actions": int(len(blk)),
            "share_of_all_base_actions": float(len(blk) / len(b)),
            "share_non_null": float(o.notna().mean()),
            "median_where_present": (float(o.median()) if o.notna().any() else None),
            "share_equal_to_one_where_present": (
                float((o.dropna() == 1).mean()) if o.notna().any() else None),
        }
    out["number_of_offers_received_by_extent_competed_code"] = rows
    log(f"fill-rate tables: solicitation non-null "
        f"{out['solicitation_identifier_overall']['share_non_null']:.3f}, "
        f"shaped {out['solicitation_identifier_overall']['share_matching_solicitation_number_shape']:.3f}")
    return out


def restatement_evidence(tx: pd.DataFrame, base: pd.DataFrame, sizes: pd.Series,
                         cutoff_fy: int | None, log) -> dict:
    """Per-action behaviour of the ceiling field and of the current end date.

    Restricted to awards with at least three actions so "non-final action" means
    something, and, for the ceiling field, to base fiscal years at or after the
    first year in which the field is populated on every action, so the test is
    not selecting on availability.
    """
    out: dict = {}
    base_fy_all = fiscal_year(base["action_date"])
    keep = ((sizes.reindex(base.index) >= 3)
            & (base_fy_all >= (cutoff_fy if cutoff_fy else 0)).fillna(False))
    keys = base.index[keep.to_numpy(dtype=bool)]
    sub = tx[tx["contract_award_unique_key"].isin(set(keys))].copy()
    if sub.empty:
        return out
    sg = sub.groupby("contract_award_unique_key", sort=False)
    sub["rank_from_end"] = sg.cumcount(ascending=False)
    sub["delta"] = np.where(sub["is_base_row"], 0.0,
                            pd.to_numeric(sub["base_and_all_options_value"],
                                          errors="coerce").fillna(0.0))
    sub["ceiling_base"] = sub["contract_award_unique_key"].map(
        base["base_and_all_options_value"])
    sub["ceiling_final"] = sg["potential_total_value_of_award"].transform("last")
    sub["end_base"] = sub["contract_award_unique_key"].map(
        base["period_of_performance_current_end_date"])
    sub["end_final"] = sg["period_of_performance_current_end_date"].transform("last")

    changed_ceiling = set(sg["delta"].sum().abs().pipe(lambda x: x[x > 1]).index)
    end_changed = sg["period_of_performance_current_end_date"].nunique(dropna=True)
    changed_end = set(end_changed[end_changed > 1].index)

    nonfinal = sub[sub["rank_from_end"] > 0]
    out["ceiling_field_restatement"] = {
        "awards_tested": int(len(keys)),
        "awards_whose_ceiling_changed": int(len(changed_ceiling)),
        "all_non_final_actions": _restatement_block(
            nonfinal, "potential_total_value_of_award", "ceiling_final", "ceiling_base"),
        "non_final_actions_on_awards_whose_ceiling_changed": _restatement_block(
            nonfinal[nonfinal["contract_award_unique_key"].isin(changed_ceiling)],
            "potential_total_value_of_award", "ceiling_final", "ceiling_base"),
        "reading": ("on an award whose ceiling changed, a non-final action that "
                    "already carries the award's final ceiling is a restated "
                    "record: reading it at a horizon imports the future"),
    }
    out["current_end_date_restatement"] = {
        "awards_tested": int(len(keys)),
        "awards_whose_current_end_date_changed": int(len(changed_end)),
        "all_non_final_actions": _date_restatement_block(
            nonfinal, "period_of_performance_current_end_date", "end_final", "end_base"),
        "non_final_actions_on_awards_whose_end_date_changed": _date_restatement_block(
            nonfinal[nonfinal["contract_award_unique_key"].isin(changed_end)],
            "period_of_performance_current_end_date", "end_final", "end_base"),
        "reading": ("the same test applied to the schedule field. A low share "
                    "equal to the final value on awards whose end date moved "
                    "means the field is carried per action and can be read at a "
                    "horizon"),
    }

    # Restatement rate by the fiscal year of the action, for the ceiling field.
    nf_changed = nonfinal[nonfinal["contract_award_unique_key"].isin(changed_ceiling)]
    if not nf_changed.empty:
        by_fy = {}
        for fy, blk in nf_changed.groupby(fiscal_year(nf_changed["action_date"])):
            if pd.isna(fy):
                continue
            blk = blk[blk["potential_total_value_of_award"].notna()]
            if blk.empty:
                continue
            by_fy[str(int(fy))] = {
                "non_final_actions": int(len(blk)),
                "share_already_equal_to_the_awards_final_value": float(
                    close(blk["potential_total_value_of_award"],
                          blk["ceiling_final"]).mean()),
            }
        out["ceiling_field_restatement_rate_by_action_fy"] = by_fy
    log(f"restatement: ceiling non-final-on-changed "
        f"{out['ceiling_field_restatement']['non_final_actions_on_awards_whose_ceiling_changed']}, "
        f"end-date non-final-on-changed "
        f"{out['current_end_date_restatement']['non_final_actions_on_awards_whose_end_date_changed']}")
    return out


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

    ev["fill_rates_for_the_scoreboard"] = fill_rate_tables(base, log)
    ev["per_action_restatement"] = restatement_evidence(
        tx, base, sizes, (min(full_years) + 1) if full_years else None, log)

    # Twenty heavily modified awards, printed action by action. The selection is
    # deliberate: an award whose ceiling never moved shows the reconstruction
    # converging but shows nothing about restatement, because every action
    # trivially carries the same value. The sample therefore prefers awards that
    # are based in a year where potential_total_value_of_award is populated on
    # every action AND whose ceiling actually changed, which is the only case
    # where the two readings of the field can be told apart by eye.
    counts_per_award = nact.sort_values(ascending=False)
    big = base.index.intersection(counts_per_award.index)
    ranked = counts_per_award.loc[big]
    ranked = ranked[ranked >= 8]
    sample_keys = list(ranked.index[:4000])

    pool = tx[tx["contract_award_unique_key"].isin(set(sample_keys))]
    has_event = set(pool[pool["action_type_code"].isin(
        ["A", "D", "E", "F", "X", "G"])]["contract_award_unique_key"].unique())
    net_delta = (pool[~pool["is_base_row"]]
                 .groupby("contract_award_unique_key", sort=False)
                 ["base_and_all_options_value"].sum().abs())
    ceiling_moved = set(net_delta[net_delta > 1].index)
    base_fy_sample = fiscal_year(base["action_date"])
    fully_populated = set(base.index[
        base_fy_sample.isin(full_years).fillna(False).to_numpy()]) if full_years else set()

    def pick(pred, n):
        return [k for k in sample_keys if pred(k)][:n]

    # Best evidence first, then progressively weaker fallbacks, so the sample is
    # always twenty awards even on a small extract.
    chosen = pick(lambda k: k in ceiling_moved and k in fully_populated
                  and k in has_event, 12)
    for extra in (pick(lambda k: k in ceiling_moved and k in has_event, 20),
                  pick(lambda k: k in has_event, 20),
                  sample_keys[:20]):
        for k in extra:
            if len(chosen) >= 20:
                break
            if k not in chosen:
                chosen.append(k)
        if len(chosen) >= 20:
            break
    ev["sample_selection"] = {
        "awards_with_at_least_eight_actions_considered": len(sample_keys),
        "of_those_whose_ceiling_moved": len(ceiling_moved & set(sample_keys)),
        "of_those_also_based_in_a_fully_populated_year": len(
            ceiling_moved & fully_populated & set(sample_keys)),
        "chosen_whose_ceiling_moved": sum(1 for k in chosen if k in ceiling_moved),
    }

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
        recon_final = float(recon.iloc[-1]) if len(recon) else float(bl)
        moved = "yes" if abs(recon_final - float(bl)) > 1 else "no"
        lines.append(f"base ceiling {bl}; base plus summed mod deltas "
                     f"{recon_final}; potential_total_value_of_award on last "
                     f"action {last_pot}; ceiling moved: {moved}")
        if moved == "yes":
            pot = pd.to_numeric(blk["potential_total_value_of_award"],
                                errors="coerce")
            fin = pot.iloc[-1]
            early = pot.iloc[:-1]
            n_eq = int(close(early, pd.Series([fin] * len(early),
                                              index=early.index)).sum())
            lines.append(
                f"of the {len(early)} actions before the last, {n_eq} already "
                f"carry the award's final potential_total_value_of_award, which "
                f"is what a reader should look at: those are the restated ones")
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
    record_timing(a.out, "field_evidence", ev["seconds"],
                  {"transactions": int(len(tx))})
    log(f"wrote {a.out/'field_evidence.json'} in {ev['seconds']}s")
    handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
