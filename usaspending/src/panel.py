"""Build the award-level panel: base rows, labels at 12/24/36 months, features.

Mechanics relied on here, each verified this session either against the
USAspending data dictionary (GET /api/v2/references/data_dictionary/, pulled
2026-09-15) or against the transaction data itself by field_evidence.py:

  action_type_code   FPDS Reason for Modification. Dictionary domain for
                     contracts: A additional work, B supplemental agreement
                     within scope, C funding only, D change order, E terminate
                     for default, F terminate for convenience, G exercise an
                     option, H definitize letter contract, J novation, K close
                     out, L definitize change order, M other administrative,
                     N legal contract cancellation, P/R/S/T/V/W re-representation
                     and administrative, X terminate for cause, Y add
                     subcontract plan.
  base_and_all_options_value
                     Dictionary: "For the Award it is the mutually agreed upon
                     total contract value including all options (if any). ...
                     For modifications enter the CHANGE, positive or negative."
                     So it is a level on the base row and a delta on mods.
  potential_total_value_of_award
                     Dictionary: "the total amount that could be obligated on a
                     contract, if the base and all options are exercised." The
                     dictionary does not say whether the value on an action is
                     the ceiling as of that action or the award's ceiling as
                     later restated. Measured below: it is often the latter, so
                     this field is never read to build a label.
  current_total_value_of_award
                     Dictionary: "the total amount obligated to date on a
                     contract, including the base and exercised options."
  period_of_performance_current_end_date
                     Dictionary: scheduled completion for the base contract and
                     exercised options, revised by modifications; it does not
                     change to reflect a closeout date.

Observed, and decisive for how the labels are built. Every figure in this
paragraph is measured by field_evidence.py over the full FY2010-FY2026 extract
(3,287,223 definitive-contract actions, run 2026-09-15) and is written to
usaspending/results/field_evidence.json; none of it is asserted from the
dictionary. potential_total_value_of_award cannot be used to build a label, for
two separately sufficient reasons.

First, its availability moves with the split. It is populated on 0.26, 0.24,
0.24, 0.22, 0.23, 0.25 and 0.28 of actions in FY2010 through FY2016, on 0.52 in
FY2017, and on 1.00 of actions in every year from FY2018 on; 0.61 of all actions
loaded. The training years are exactly where it is worst and the test years are
where it is complete, so a label built from it is not the same label on both
sides of the split. base_and_all_options_value is populated on 1.00 of actions in
every single year.

Second, where it is complete it carries restated values. Among awards based in
FY2019 or later with at least three actions (97,496 awards, of which 65,067 saw
their ceiling change), a non-final action of an award whose ceiling changed
already equals that award's EVENTUAL FINAL value 0.377 of the time, and equals
the contemporaneous reconstruction only 0.709 of the time. Reading the field at a
horizon therefore imports the award's future on a large minority of awards.

So the ceiling at a horizon is reconstructed from the per-action deltas:

    ceiling(H) = base_and_all_options_value(base action)
               + sum of base_and_all_options_value over later actions dated at or
                 before base action date + H months

which is what the dictionary prescribes ("For modifications enter the CHANGE,
positive or negative") and which the data confirms: on an award's FINAL action
the reconstruction equals potential_total_value_of_award 0.985 of the time, while
the base ceiling read alone equals it only 0.397 of the time. The convergence on
the final action is the check that the reconstruction arrives at the right
number.

period_of_performance_current_end_date was put through the same restatement test
and passes: on non-final actions of awards whose end date moved, it equals the
award's final end date only 0.170 of the time. It is genuinely carried per action
and the schedule-slip labels read it as it stands.

Everything else in this module is arithmetic on those fields.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from columns import DATES, NUMERIC  # noqa: E402
from timing import record as record_timing  # noqa: E402

HORIZONS = (12, 24, 36)
TERMINATION_CODES = ("E", "F", "X")
DEFAULT_TERMINATION_CODES = ("E",)
CHANGE_ORDER_CODES = ("A", "D")
SAT_THRESHOLD = 250_000.0
BASE_FY_MIN = 2010
BASE_FY_MAX = 2022
ROUND_DECIMALS = 10
HISTORY_GROWTH_FLOOR = -1.0
HISTORY_GROWTH_CAP = 10.0
MISSING_KEY = "__MISSING__"

_MOD_DIGITS = re.compile(r"(\d+)\s*$")


def fiscal_year(dates: pd.Series) -> pd.Series:
    """US federal fiscal year: FY N runs 1 Oct N-1 through 30 Sep N."""
    d = pd.to_datetime(dates)
    return (d.dt.year + (d.dt.month >= 10).astype("int64")).astype("Int64")


def is_base_mod(mod: pd.Series) -> pd.Series:
    """True where modification_number denotes the base award action.

    Rule: strip whitespace and surrounding quotes, uppercase, and treat the
    value as the base action when every character is either a digit or a
    leading alphabetic prefix and the digits are all zero. This admits "0",
    "00", "0000" and the agency style "P00000", and rejects "P00001".
    """
    s = mod.astype("string").fillna("").str.strip().str.strip('"').str.upper()
    digits = s.str.replace(r"^[A-Z]+", "", regex=True)
    all_digits = digits.str.fullmatch(r"\d+").fillna(False)
    zero = digits.str.fullmatch(r"0+").fillna(False)
    return (all_digits & zero).astype(bool)


def mod_sequence(mod: pd.Series) -> pd.Series:
    """Numeric suffix of modification_number, used only to break date ties."""
    s = mod.astype("string").fillna("").str.strip().str.strip('"')
    out = s.str.extract(_MOD_DIGITS, expand=False)
    return pd.to_numeric(out, errors="coerce").fillna(-1).astype("int64")


_FY_IN_NAME = re.compile(r"FY(\d{4})")


def fiscal_years_present(pdir: Path) -> list[int]:
    out = []
    for f in sorted(pdir.glob("contracts_D_FY*.parquet")):
        m = _FY_IN_NAME.search(f.name)
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


def check_year_coverage(pdir: Path) -> list[int]:
    """Fiscal years missing from an otherwise contiguous run of extract files."""
    years = fiscal_years_present(pdir)
    if not years:
        return []
    return [y for y in range(years[0], years[-1] + 1) if y not in years]


def load_transactions(pdir: Path, log, allow_year_gaps: bool = False) -> pd.DataFrame:
    files = sorted(pdir.glob("contracts_D_FY*.parquet"))
    if not files:
        raise FileNotFoundError(f"no parquet under {pdir}")
    missing = check_year_coverage(pdir)
    if missing:
        msg = (f"fiscal years {missing} are missing from {pdir}. Outcomes are read "
               f"from the modification record of LATER years, so a gap does not "
               f"just shrink the sample: it silently removes real modifications "
               f"and makes every label whose horizon crosses the gap wrong, with "
               f"no error anywhere. Fetch the missing years first.")
        if not allow_year_gaps:
            raise ValueError(msg)
        log("WARNING, proceeding with a gap because allow_year_gaps is set: " + msg)
    log(f"fiscal years loaded: {fiscal_years_present(pdir)}")
    frames = []
    for f in files:
        df = pd.read_parquet(f)
        log(f"loaded {f.name} rows={len(df)}")
        frames.append(df)
    tx = pd.concat(frames, ignore_index=True)
    for c in NUMERIC:
        if c in tx.columns:
            tx[c] = pd.to_numeric(tx[c], errors="coerce")
    for c in DATES:
        if c in tx.columns:
            tx[c] = pd.to_datetime(tx[c], errors="coerce")
    tx = tx[tx["award_type_code"] == "D"].copy()
    tx = tx[tx["action_date"].notna()].copy()
    tx["mod_seq"] = mod_sequence(tx["modification_number"])
    tx["txn_seq"] = pd.to_numeric(tx["transaction_number"],
                                  errors="coerce").fillna(0).astype("int64")
    tx["is_base_mod"] = is_base_mod(tx["modification_number"])
    # modification_number is part of the sort key, not only its numeric suffix.
    # Measured on the full extract: 2,595 rows (0.079 percent) tie on
    # (key, action_date, mod_seq, txn_seq), and adding the raw modification
    # number resolves every one of them, leaving zero ties. Without it, which
    # action counts as "the latest at horizon H" among tied rows would depend on
    # the order the parquet files happened to be concatenated in.
    tx["mod_str"] = tx["modification_number"].astype("string").fillna("")
    tx = tx.sort_values(
        ["contract_award_unique_key", "action_date", "mod_seq", "txn_seq",
         "mod_str"],
        kind="mergesort",
    ).reset_index(drop=True)
    log(f"transactions after type-D and action_date filters: {len(tx)}")
    return tx


def pick_base_rows(tx: pd.DataFrame, log) -> tuple[pd.DataFrame, dict]:
    """One base row per award, plus the funnel counts."""
    tx["__row__"] = np.arange(len(tx))
    g = tx.groupby("contract_award_unique_key", sort=False)
    first_idx = g.head(1).index
    first_rows = tx.loc[first_idx].set_index("contract_award_unique_key")

    base_candidates = tx[tx["is_base_mod"]]
    base_first_rows = base_candidates.groupby("contract_award_unique_key",
                                              sort=False).head(1)
    base_first = base_first_rows.set_index("contract_award_unique_key")

    # Mark the single action chosen as the base, so every other action can be
    # treated as carrying a delta.
    tx["is_base_row"] = False
    tx.loc[base_first_rows.index, "is_base_row"] = True

    n_base_rows_per_award = base_candidates.groupby(
        "contract_award_unique_key", sort=False).size()
    multi_base = set(n_base_rows_per_award[n_base_rows_per_award > 1].index)

    all_keys = first_rows.index
    has_mod0 = base_first.index
    n_awards = len(all_keys)
    n_no_mod0 = int(n_awards - len(has_mod0))

    # The specification allows falling back to the earliest action when no
    # modification-zero row exists. That fallback is not taken: an award whose
    # first action in the window is a mid-life modification already carries a
    # grown ceiling, so using it as the denominator of ceiling growth would
    # understate growth for exactly the oldest contracts. Those awards are
    # excluded instead, and the count is reported in the funnel. Keeping the
    # reindex here means the frame still has one row per award, with the
    # fallback awards carrying null dates that the funnel then drops.
    base = base_first.reindex(all_keys)

    base["first_action_date"] = first_rows["action_date"]
    base["has_explicit_mod0"] = base.index.isin(has_mod0)
    base["has_single_base_row"] = ~base.index.isin(multi_base)
    # Only meaningful for an award that HAS a modification-zero action. For an
    # award that has none the base row is null, and counting that as "the base
    # row is not the first action" would fold 72,424 left-truncated awards into a
    # diagnostic that is supposed to isolate the handful of awards whose
    # modification zero is genuinely dated after a later-numbered action.
    base["base_is_first_action"] = (
        (base["action_date"] <= base["first_action_date"])
        & base["has_explicit_mod0"])

    not_first = int((base["has_explicit_mod0"]
                     & ~(base["action_date"] <= base["first_action_date"])).sum())
    funnel = {
        "awards_type_D_total": int(n_awards),
        "awards_without_modification_number_zero": n_no_mod0,
        "awards_with_modification_zero_that_is_not_the_first_action": not_first,
        "awards_with_more_than_one_base_action": int(len(multi_base)),
    }
    log(f"base rows: {json.dumps(funnel)}")
    return base.reset_index(), funnel


def _stepper(steps: list, log):
    def note(name: str, df: pd.DataFrame) -> None:
        steps.append({"filter": name, "awards_remaining": int(len(df))})
        log(f"funnel {name}: {len(df)}")
    return note


def apply_identity_filters(base: pd.DataFrame, log) -> tuple[pd.DataFrame, list]:
    """Filters that decide whether an award is a well identified base award.

    These come first because the result is also the HISTORY SOURCE: the set of
    prior awards a contractor's or an office's track record is counted over. It
    deliberately excludes none of the small awards, so "this contractor's tenth
    federal contract" means what it says rather than "tenth contract above the
    simplified acquisition threshold that also happened to survive four later
    filters".
    """
    steps = []
    note = _stepper(steps, log)
    df = base.copy()
    note("start: one base row per type-D award", df)

    df = df[df["has_explicit_mod0"]].copy()
    note("award has an action with an explicit modification_number of zero", df)

    df = df[df["base_is_first_action"].fillna(False)].copy()
    note("that modification-zero action is the award's first action", df)

    df["base_fy"] = fiscal_year(df["action_date"])
    df = df[(df["base_fy"] >= BASE_FY_MIN) & (df["base_fy"] <= BASE_FY_MAX)].copy()
    note(f"base action_date in FY{BASE_FY_MIN}-FY{BASE_FY_MAX}", df)
    return df, steps


def apply_population_filters(base: pd.DataFrame, log) -> tuple[pd.DataFrame, list]:
    """Filters that decide whether an award is IN SCOPE for the forecast.

    Applied after labels, features and history, so that dropping an award here
    removes it from the modelling panel without also removing it from another
    award's contractor history. One of these filters, the single-base-row check,
    looks at actions dated after the base date; applying it before the history
    was computed would let a later action change an earlier award's prior-award
    count, which is a look-ahead even though it is not a label leak.
    """
    steps = []
    note = _stepper(steps, log)
    df = base.copy()

    df = df[df["has_single_base_row"]].copy()
    note("exactly one action carries a modification_number of zero", df)

    df = df[df["federal_action_obligation"].notna()].copy()
    df = df[df["federal_action_obligation"] >= SAT_THRESHOLD].copy()
    note(f"base federal_action_obligation >= {SAT_THRESHOLD:,.0f}", df)

    df = df[df["period_of_performance_current_end_date"].notna()].copy()
    note("base period_of_performance_current_end_date is not null", df)

    df = df[df["base_ceiling_valid"]].copy()
    note("base_and_all_options_value > 0 and not null", df)
    return df, steps


def state_at_horizon(tx: pd.DataFrame, base: pd.DataFrame, months: int,
                     log) -> pd.DataFrame:
    """Latest action state, and event counts, at base action_date + months."""
    keys = base.set_index("contract_award_unique_key")
    cutoff = (keys["action_date"] + pd.DateOffset(months=months)).rename("cutoff")

    sub = tx[tx["contract_award_unique_key"].isin(keys.index)].copy()
    sub = sub.join(cutoff, on="contract_award_unique_key")
    sub = sub[sub["action_date"] <= sub["cutoff"]].copy()

    # already sorted by (key, action_date, mod_seq, txn_seq) in load_transactions
    last = sub.groupby("contract_award_unique_key", sort=False).tail(1)
    last = last.set_index("contract_award_unique_key")

    out = pd.DataFrame(index=keys.index)
    out[f"current_end_at_{months}"] = last["period_of_performance_current_end_date"]
    out[f"n_actions_by_{months}"] = sub.groupby(
        "contract_award_unique_key", sort=False).size()
    out[f"last_action_date_by_{months}"] = last["action_date"]

    # Reconstructed running levels. The base action carries the level; every
    # later action carries the change. See the module docstring for why the
    # award-level potential_total_value_of_award cannot be read at a horizon.
    deltas = sub[~sub["is_base_row"]]
    dg = deltas.groupby("contract_award_unique_key", sort=False)
    out[f"ceiling_delta_by_{months}"] = dg["base_and_all_options_value"].sum(
        ).reindex(out.index).fillna(0.0)
    out[f"exercised_delta_by_{months}"] = dg["base_and_exercised_options_value"].sum(
        ).reindex(out.index).fillna(0.0)
    out[f"obligated_by_{months}"] = sub.groupby(
        "contract_award_unique_key", sort=False)["federal_action_obligation"].sum(
        ).reindex(out.index).fillna(0.0)
    out[f"ceiling_at_{months}"] = (
        keys["base_and_all_options_value"] + out[f"ceiling_delta_by_{months}"])
    out[f"exercised_at_{months}"] = (
        keys["base_and_exercised_options_value"]
        + out[f"exercised_delta_by_{months}"])

    at = sub["action_type_code"].astype("string")
    term = sub[at.isin(TERMINATION_CODES)]
    term_default = sub[at.isin(DEFAULT_TERMINATION_CODES)]
    co = sub[at.isin(CHANGE_ORDER_CODES)]

    out[f"terminated_{months}"] = out.index.isin(
        term["contract_award_unique_key"]).astype("int8")
    out[f"terminated_default_{months}"] = out.index.isin(
        term_default["contract_award_unique_key"]).astype("int8")
    out[f"change_order_count_{months}"] = co.groupby(
        "contract_award_unique_key", sort=False).size().reindex(out.index).fillna(0)
    out[f"change_order_value_{months}"] = co.groupby(
        "contract_award_unique_key", sort=False)["base_and_all_options_value"].sum(
        ).reindex(out.index).fillna(0.0)
    out[f"option_exercise_count_{months}"] = sub[at == "G"].groupby(
        "contract_award_unique_key", sort=False).size().reindex(out.index).fillna(0)

    log(f"state at H={months}: {len(out)} awards, "
        f"{int(out[f'terminated_{months}'].sum())} terminated")
    return out


def build_labels(base: pd.DataFrame, tx: pd.DataFrame, data_end: pd.Timestamp,
                 log) -> pd.DataFrame:
    df = base.set_index("contract_award_unique_key").copy()
    base_ceiling = df["base_and_all_options_value"]
    df["base_ceiling"] = base_ceiling
    df["base_ceiling_valid"] = (base_ceiling.notna() & (base_ceiling > 0))
    df["base_current_end"] = df["period_of_performance_current_end_date"]
    # Carried for validation only. This is the award-level end-state value the
    # feed pastes onto every action; it is never used to build a label.
    df["award_level_potential_total_value_diagnostic"] = df[
        "potential_total_value_of_award"]

    for h in HORIZONS:
        st = state_at_horizon(tx, base, h, log)
        df = df.join(st)

        cutoff = df["action_date"] + pd.DateOffset(months=h)
        df[f"qualifies_{h}"] = (cutoff <= data_end)

        growth = df[f"ceiling_at_{h}"] / df["base_ceiling"] - 1.0
        growth = growth.where(df["base_ceiling_valid"])
        df[f"ceiling_growth_{h}"] = growth
        # A ratio of exactly 1.10 evaluates to 0.10000000000000009 in binary
        # floating point, which would put an award with no growth beyond the
        # threshold on the wrong side of a strict inequality. Round to
        # ROUND_DECIMALS before comparing so the threshold means what it says.
        growth_r = growth.round(ROUND_DECIMALS)
        for thr, tag in ((0.10, "10"), (0.25, "25"), (0.50, "50")):
            df[f"ceiling_growth_gt{tag}_{h}"] = (growth_r > thr).astype("float64")
            df.loc[growth.isna(), f"ceiling_growth_gt{tag}_{h}"] = np.nan

        slip = (df[f"current_end_at_{h}"] - df["base_current_end"]).dt.days
        df[f"schedule_slip_days_{h}"] = slip
        df[f"schedule_slip_gt90_{h}"] = (slip > 90).astype("float64")
        df.loc[slip.isna(), f"schedule_slip_gt90_{h}"] = np.nan
        df[f"schedule_slip_gt365_{h}"] = (slip > 365).astype("float64")
        df.loc[slip.isna(), f"schedule_slip_gt365_{h}"] = np.nan

        # Diagnostic only, never a model target: the label that would result from
        # reading the award-level potential_total_value_of_award at this horizon.
        # Because that field is the award's end state it barely moves with the
        # horizon, which is the visible signature of the leak.
        leak_growth = (df["award_level_potential_total_value_diagnostic"]
                       / df["base_ceiling"] - 1.0).where(df["base_ceiling_valid"])
        df[f"ceiling_growth_awardlevel_diagnostic_{h}"] = leak_growth
        df[f"ceiling_growth_awardlevel_gt25_diagnostic_{h}"] = (
            leak_growth.round(ROUND_DECIMALS) > 0.25).astype("float64")
        df.loc[leak_growth.isna(),
               f"ceiling_growth_awardlevel_gt25_diagnostic_{h}"] = np.nan

        unplanned = df[f"change_order_value_{h}"] / df["base_ceiling"]
        df[f"unplanned_growth_{h}"] = unplanned.where(df["base_ceiling_valid"])
        df[f"any_change_order_{h}"] = (
            df[f"change_order_count_{h}"] > 0).astype("float64")

    return df.reset_index()


def add_base_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["naics2"] = d["naics_code"].astype("string").str.slice(0, 2)
    d["naics6"] = d["naics_code"].astype("string").str.slice(0, 6)
    d["psc1"] = d["product_or_service_code"].astype("string").str.slice(0, 1)
    d["psc_full"] = d["product_or_service_code"].astype("string")

    d["log_base_obligation"] = np.log10(
        d["federal_action_obligation"].clip(lower=1.0))
    ceiling = d["base_and_all_options_value"]
    d["log_base_ceiling"] = np.log10(ceiling.where(ceiling > 0)).astype("float64")

    exercised = d["base_and_exercised_options_value"]
    d["option_heaviness"] = np.where(
        (exercised.notna()) & (exercised > 0) & ceiling.notna(),
        ceiling / exercised.replace(0, np.nan), np.nan)

    d["planned_duration_days"] = (
        d["period_of_performance_current_end_date"]
        - d["period_of_performance_start_date"]).dt.days
    d["potential_extra_duration_days"] = (
        d["period_of_performance_potential_end_date"]
        - d["period_of_performance_current_end_date"]).dt.days

    d["n_offers"] = pd.to_numeric(d["number_of_offers_received"], errors="coerce")
    d["n_offers_missing"] = d["n_offers"].isna().astype("int8")

    d["base_month"] = d["action_date"].dt.month
    d["base_is_september"] = (d["base_month"] == 9).astype("int8")
    return d


# USAspending publishes some contract actions against placeholder recipients that
# stand for a bucket of firms rather than one firm. Measured on this panel, three
# of them account for 4,324 base awards: MISCELLANEOUS FOREIGN AWARDEES (2,731),
# FOREIGN AWARDEES (UNDISCLOSED) (922) and DOMESTIC AWARDEES (UNDISCLOSED) (671).
# The largest is by itself the single most frequent recipient UEI in the panel,
# ahead of Raytheon at 1,147. Counting them as one contractor would give a
# fictitious firm a track record of thousands of awards and would pool the
# outcomes of unrelated companies into one prior mean. The rule below is an
# INFERENCE from the recipient name, not an official flag; the word "aggregate"
# is deliberately not in it, because it matches real construction firms such as
# HIGH DESERT AGGREGATE & PAVING.
AGGREGATE_RECIPIENT_PATTERN = (
    r"UNDISCLOSED|MISCELLANEOUS FOREIGN AWARDEES|MULTIPLE RECIPIENTS|REDACTED")


def is_aggregate_recipient(name: pd.Series) -> pd.Series:
    """True where the recipient name denotes a bucket of firms, not one firm."""
    n = name.astype("string").str.upper().fillna("")
    return n.str.contains(AGGREGATE_RECIPIENT_PATTERN, regex=True, na=False)


def _asof_group_stats(event_group: pd.Series, event_date: pd.Series,
                      event_value: pd.Series, q_group: pd.Series,
                      q_date: pd.Series, strict: bool) -> tuple[np.ndarray, np.ndarray]:
    """Per-group count and sum of events whose date precedes each query date.

    strict=True uses event_date < q_date; strict=False uses event_date <= q_date.
    Implemented with a per-group sorted array and binary search, so the result
    depends only on information dated before the query.
    """
    ev = pd.DataFrame({"g": event_group.to_numpy(),
                       "d": pd.to_datetime(event_date).to_numpy(),
                       "v": pd.to_numeric(event_value, errors="coerce").to_numpy()})
    ev = ev[pd.notna(ev["d"])].sort_values(["g", "d"], kind="mergesort")
    counts = np.zeros(len(q_group), dtype=float)
    sums = np.full(len(q_group), np.nan, dtype=float)
    ns = np.zeros(len(q_group), dtype=float)

    by_group: dict[object, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for g, blk in ev.groupby("g", sort=False):
        d = blk["d"].to_numpy()
        v = blk["v"].to_numpy(dtype=float)
        valid = ~np.isnan(v)
        cum_v = np.concatenate([[0.0], np.nancumsum(np.where(valid, v, 0.0))])
        cum_n = np.concatenate([[0.0], np.cumsum(valid.astype(float))])
        by_group[g] = (d, cum_v, cum_n)

    qg = q_group.to_numpy()
    qd = pd.to_datetime(q_date).to_numpy()
    side = "left" if strict else "right"
    for i in range(len(qg)):
        entry = by_group.get(qg[i])
        if entry is None or pd.isna(qd[i]):
            continue
        d, cum_v, cum_n = entry
        j = int(np.searchsorted(d, qd[i], side=side))
        counts[i] = j
        ns[i] = cum_n[j]
        sums[i] = cum_v[j]
    with np.errstate(invalid="ignore", divide="ignore"):
        means = np.where(ns > 0, sums / np.where(ns > 0, ns, 1.0), np.nan)
    return counts, means


def add_history_features(df: pd.DataFrame, resolution_months: int = 36) -> pd.DataFrame:
    """Prior-award history for recipient and office, strictly as of the base date.

    Counts use prior base awards dated strictly before this award's base date.
    Outcome means use only prior awards whose horizon had already closed by this
    base date, that is prior_base_date + resolution_months <= this base date.

    Two groups are held out of the pooling entirely, as both event and query, and
    receive a null history rather than a pooled one:

      - awards whose grouping key is missing, which would otherwise form one
        enormous pseudo-contractor or pseudo-office out of unrelated records;
      - awards booked to an aggregate placeholder recipient, for the reason set
        out at AGGREGATE_RECIPIENT_PATTERN above.

    A null here is the honest answer and the gradient booster handles it as a
    missing value natively, whereas a zero would assert that the contractor is
    new when the truth is that the record does not say who the contractor is.
    """
    d = df.copy()
    d = d.sort_values("action_date", kind="mergesort").reset_index(drop=True)
    d["recipient_is_aggregate"] = is_aggregate_recipient(
        d["recipient_name"] if "recipient_name" in d.columns
        else pd.Series([""] * len(d))).astype("int8")

    resolved_at = d["action_date"] + pd.DateOffset(months=resolution_months)
    # Ceiling growth has a very long right tail: an award with a small base
    # ceiling and a large later modification can show growth in the thousands,
    # and a single such award would dominate a contractor's prior mean. Cap the
    # input at fixed bounds chosen a priori, so the cap uses no data and cannot
    # leak. The label itself is left uncapped.
    growth = d[f"ceiling_growth_{resolution_months}"].clip(
        lower=HISTORY_GROWTH_FLOOR, upper=HISTORY_GROWTH_CAP)
    term = d[f"terminated_{resolution_months}"].astype("float64")
    slip = d[f"schedule_slip_gt90_{resolution_months}"].astype("float64")
    ones = pd.Series(np.ones(len(d)))

    for col, keyname in (("recipient_uei", "recipient"),
                         ("awarding_office_code", "office")):
        raw = d[col].astype("string")
        g = raw.fillna(MISSING_KEY)
        usable = raw.notna().to_numpy()
        if keyname == "recipient":
            usable = usable & ~d["recipient_is_aggregate"].astype(bool).to_numpy()

        ev_g = g[usable]
        ev_date = d.loc[usable, "action_date"]
        ev_resolved = resolved_at[usable]

        cnt, _ = _asof_group_stats(ev_g, ev_date, ones[usable], g,
                                   d["action_date"], strict=True)
        d[f"{keyname}_prior_award_count"] = cnt
        for src, suffix in ((growth, f"prior_mean_ceiling_growth_{resolution_months}"),
                            (term, f"prior_termination_rate_{resolution_months}"),
                            (slip, f"prior_slip_rate_{resolution_months}")):
            _, mean = _asof_group_stats(ev_g, ev_resolved, src[usable], g,
                                        d["action_date"], strict=False)
            d[f"{keyname}_{suffix}"] = mean

        # A row that is itself held out gets a null history, not a zero count.
        held_out = ~usable
        for c in [f"{keyname}_prior_award_count",
                  f"{keyname}_prior_mean_ceiling_growth_{resolution_months}",
                  f"{keyname}_prior_termination_rate_{resolution_months}",
                  f"{keyname}_prior_slip_rate_{resolution_months}"]:
            d.loc[held_out, c] = np.nan
    return d


def build_panel(tx: pd.DataFrame, data_end: pd.Timestamp,
                log) -> tuple[pd.DataFrame, pd.DataFrame, dict, list]:
    """The whole pipeline, in the one order that is correct.

    Returns (panel, history_source, base_row_diagnostics, funnel_steps).

    Labels, features and history are built on the widest well identified set of
    base awards, and the in-scope filters are applied only afterwards. That
    ordering is what makes "this contractor's prior awards" mean prior awards
    rather than prior awards that happened to clear a size threshold, and it
    keeps a filter that inspects later actions from reaching back and changing an
    earlier award's history. main() and the tests both go through here, so the
    tests exercise the production path rather than a reconstruction of it.
    """
    base_all, base_funnel = pick_base_rows(tx, log)
    hist_base, early_steps = apply_identity_filters(base_all, log)
    labels = build_labels(hist_base, tx, data_end, log)
    labels = add_base_features(labels)
    labels = add_history_features(labels)
    panel, late_steps = apply_population_filters(labels, log)
    return panel, labels, base_funnel, early_steps + late_steps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdir", type=Path, default=Path("data/raw/usaspending/parquet"))
    ap.add_argument("--out", type=Path, default=Path("data/raw/usaspending/panel.parquet"))
    ap.add_argument("--funnel", type=Path,
                    default=Path("usaspending/results/funnel.json"))
    ap.add_argument("--log", type=Path, default=Path("usaspending/logs/panel.log"))
    ap.add_argument("--history-source", type=Path, default=None,
                    help="also write the wider base-award frame the history "
                         "features are computed over")
    ap.add_argument("--allow-year-gaps", action="store_true",
                    help="proceed even though a fiscal year is missing from the "
                         "extract; this makes every label whose horizon crosses "
                         "the gap wrong and is only for debugging")
    a = ap.parse_args()

    a.log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(a.log, "a")

    def log(msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}"
        print(line, flush=True)
        handle.write(line + "\n")
        handle.flush()

    t0 = time.time()
    tx = load_transactions(a.pdir, log, allow_year_gaps=a.allow_year_gaps)
    data_end = tx["action_date"].max()
    log(f"data end (max action_date) = {data_end.date()}")

    panel, labels, base_funnel, steps = build_panel(tx, data_end, log)
    log(f"history source: {len(labels)} base awards, "
        f"{int(labels['recipient_is_aggregate'].sum())} of them booked to an "
        f"aggregate placeholder recipient and held out of the pooling")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(a.out, index=False, compression="zstd")
    if a.history_source:
        labels.to_parquet(a.history_source, index=False, compression="zstd")
        log(f"history source -> {a.history_source}")
    a.funnel.parent.mkdir(parents=True, exist_ok=True)
    a.funnel.write_text(json.dumps({
        "data_end": str(data_end.date()),
        "transactions_loaded": int(len(tx)),
        "fiscal_years_loaded": fiscal_years_present(a.pdir),
        "base_row_diagnostics": base_funnel,
        "history_source_awards": int(len(labels)),
        "history_source_aggregate_recipient_awards": int(
            labels["recipient_is_aggregate"].sum()),
        "funnel": steps,
        "seconds": round(time.time() - t0, 1),
    }, indent=1))
    record_timing(a.funnel.parent, "panel", time.time() - t0,
                  {"awards": int(len(panel)), "transactions": int(len(tx)),
                   "history_source_awards": int(len(labels))})
    log(f"panel -> {a.out} rows={len(panel)} in {time.time()-t0:.0f}s")
    handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
