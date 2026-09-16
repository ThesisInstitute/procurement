"""Leakage-controlled join of Project Appraisal Documents to IEG outcome ratings.

THE LEAKAGE THIS REMOVES. Additional-financing appraisal documents and
restructuring papers are filed under the SAME P-number as the original project
and are dated AFTER board approval. A document written years into
implementation can describe what has already happened, so admitting it as an
ex-ante input would leak the outcome.

THE RULE (tested in tests/test_join.py). Among the PADs of a project, keep the
one that
  1. has docdt <= board approval date + 30 days   <- the leakage test
  2. is in English, if any qualifying version is
  3. is the earliest of what remains
  4. has the lowest document id AS AN INTEGER, purely for determinism (WDS
     stores it as a string of digits, so a plain sort would compare
     lexicographically and "18082379" would precede "440661")
Only step 1 is about leakage. Steps 2 to 4 choose among documents that have all
already passed it. The 30-day grace window exists because the document date and
the board date are recorded independently and the PAD is sometimes stamped just
after the Board.

WHAT THE DUPLICATION ACTUALLY IS (observed 2026-09-15, reproduce with
`make dataset`; these counts are POST-explode, which is what the filter sees).
Of 6,991 PAD records, 12 carry no projectid and 138 carry a comma-separated
multi-project projectid, giving 7,142 document-project rows over 6,575 distinct
P-numbers:

    PADs per P-number:  1 -> 6,065   2 -> 484   3 -> 22   4 -> 2   5 -> 1
                       30 -> 1

The single P-number with 30 rows is P173789, and it is not 30 versions of a
project's history: it is one 2020 operation whose appraisal document was
disclosed in English, Spanish and Arabic across several same-week dates.

That case generalises. Of the rows this filter drops as "not selected" and that
belong to a project that IS in the release table, 84.9% carry the SAME docdt as
the document that was kept (291 rows). So the majority of what the filter
removes is a same-day duplicate or a translation, NOT a post-hoc document. The
additional-financing and restructuring case is real, and it is what step 1
exists for, but it is the minority of the drops, and describing the whole drop
set as post-hoc leakage would overstate what the filter is doing. The reject
reasons below distinguish the two so the report can show the split.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

GRACE_DAYS = 30


def explode_projectids(pad: pd.DataFrame) -> pd.DataFrame:
    """One row per (document, P-number).

    Observed: 138 of 6,991 PAD records carry a comma-separated multi-project
    `projectid` (e.g. "P512332,P512820"). Those documents appraise more than one
    project and are legitimately the appraisal document for each.
    """
    out = pad.copy()
    out["projectid"] = out["projectid"].astype("string")
    out = out[out["projectid"].notna()].copy()
    out["projectid"] = out["projectid"].str.split(r"[;,]")
    out = out.explode("projectid")
    out["projectid"] = out["projectid"].str.strip().str.upper()
    out = out[out["projectid"].str.fullmatch(r"P\d+", na=False)]
    return out.reset_index(drop=True)


def parse_dt(s: pd.Series) -> pd.Series:
    """Parse a WDS date field to a CALENDAR DATE at midnight.

    `docdt` is a date, but WDS renders it as an instant at midnight US Eastern:
    across all 6,991 PAD records the time-of-day is only ever 04:00:00Z (4,535
    records, EDT) or 05:00:00Z (2,456, EST). `boardapprovaldate_exact` is a bare
    date and parses to 00:00:00.

    Differencing the two without normalising loses a partial day to truncation.
    Measured before this fix: `(board - docdt).dt.days` was one day short on
    7,109 of 7,109 PAD-project rows, i.e. every single one, and the documented
    "approval date plus 30 days" grace window was really 29 days plus 20 hours,
    because a document stamped 04:00Z on day 30 sorts after a cutoff at 00:00.
    (No PAD actually sits between 27 and 32 days after approval, so that second
    effect changed no row's inclusion; it was still wrong.)

    `.dt.normalize()` floors to midnight AFTER the conversion to UTC, which
    recovers the intended calendar date in both offsets: 04:00Z is midnight EDT
    on the same date, and 05:00Z is midnight EST on the same date.
    """
    return (pd.to_datetime(s, errors="coerce", utc=True)
            .dt.tz_localize(None).dt.normalize())


def qualifying_pad(
    pad_exploded: pd.DataFrame,
    approval: pd.DataFrame,
    grace_days: int = GRACE_DAYS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (kept, rejected).

    `approval` must have columns projectid and boardapprovaldate (datetime).
    kept    : earliest PAD per project with docdt <= approval + grace_days
    rejected: every PAD row excluded, with a `reject_reason`
    """
    df = pad_exploded.merge(approval, on="projectid", how="left")
    df["docdt_dt"] = parse_dt(df["docdt"])

    reasons = pd.Series(pd.NA, index=df.index, dtype="string")
    reasons[df["docdt_dt"].isna()] = "no_docdt"
    reasons[reasons.isna() & df["boardapprovaldate"].isna()] = "no_board_approval_date"

    cutoff = df["boardapprovaldate"] + pd.Timedelta(days=grace_days)
    late = reasons.isna() & (df["docdt_dt"] > cutoff)
    reasons[late] = "docdt_after_approval_plus_grace"

    eligible = df[reasons.isna()].copy()
    # Selection among the documents that PASS the leakage test, in order:
    #   1. English, if an English version qualifies
    #   2. earliest docdt
    #   3. document id, purely so the result is deterministic
    #
    # Step 1 is not cosmetic. WDS carries translations of the appraisal document
    # under the same P-number, and a translation is frequently dated EARLIER
    # than the English original, so an "earliest only" rule selected it.
    # Measured before this fix: 40 projects were represented by a French,
    # Spanish, Arabic, Russian or Portuguese document, and for 39 of them an
    # English PAD existed in WDS and qualified. Those 40 documents then entered
    # an English-stopword TF-IDF model as their own vocabulary, contributing
    # noise rather than signal.
    #
    # This does NOT relax the leakage rule. Every candidate here has already
    # passed `docdt <= approval + grace`; the preference only chooses among
    # documents that are all equally admissible.
    # `lang` is WDS metadata and may be absent from a caller's frame (the unit
    # fixtures do not carry it). Missing means "no language preference
    # expressible", and the selection then falls through to earliest-then-id,
    # which is the pre-existing behaviour. It is NOT treated as non-English,
    # because that would silently reorder every candidate.
    if "lang" in eligible.columns:
        eligible["_not_english"] = (~eligible["lang"].eq("English")).astype(int)
    else:
        eligible["_not_english"] = 0
    # WDS stores `id` as a STRING of digits, so sorting on it compares
    # lexicographically: "18082379" sorts before "440661". As a tie-break that
    # is not wrong so much as arbitrary, and arbitrary is the one thing a
    # tie-break must not be. Sorting the integer instead makes "lowest document
    # id" mean what it says. Measured: after the language preference, 27
    # projects still reach this tie-break and 6 of them change hands.
    eligible["_id_sort"] = pd.to_numeric(eligible["id"], errors="coerce")
    if eligible["_id_sort"].isna().any():
        # a non-numeric id would sort as NaN and land last; fall back to the
        # string so the ordering stays total and deterministic
        eligible["_id_sort"] = eligible["id"].astype(str)
    eligible = eligible.sort_values(
        ["projectid", "_not_english", "docdt_dt", "_id_sort"])
    kept = eligible.groupby("projectid", as_index=False).first()
    kept = kept.drop(columns=["_not_english", "_id_sort"])
    eligible = eligible.drop(columns=["_not_english", "_id_sort"])

    kept_keys = set(zip(kept["projectid"], kept["id"]))
    not_kept = eligible[
        ~pd.Series(list(zip(eligible["projectid"], eligible["id"])),
                   index=eligible.index).isin(kept_keys)
    ].copy()
    # Distinguish a same-day duplicate or translation from a genuinely later
    # document. Both passed the leakage test; only the second is the case the
    # filter's headline description is about, and the two were previously
    # collapsed into one label that implied all of them were post-hoc.
    if len(not_kept):
        kept_date = pd.to_datetime(
            not_kept["projectid"].map(
                kept.set_index("projectid")["docdt_dt"].to_dict()),
            errors="coerce")
        same_day = (pd.to_datetime(not_kept["docdt_dt"], errors="coerce")
                    == kept_date).to_numpy()
        not_kept["reject_reason"] = np.where(
            same_day, "same_date_duplicate_or_translation",
            "later_version_within_grace_window")
    else:
        not_kept["reject_reason"] = pd.Series(dtype="object")

    hard = df[reasons.notna()].copy()
    hard["reject_reason"] = reasons[reasons.notna()].values

    rejected = pd.concat([hard, not_kept], ignore_index=True)
    return kept.reset_index(drop=True), rejected.reset_index(drop=True)


def funnel(
    ieg: pd.DataFrame,
    pad_exploded: pd.DataFrame,
    approval: pd.DataFrame,
    kept: pd.DataFrame,
    n_ieg_rows_raw: int | None = None,
) -> pd.DataFrame:
    """The reported funnel. Every number here is a set size, not an estimate."""
    rated = set(ieg["projectid"])
    with_pad = set(pad_exploded["projectid"])
    with_approval = set(approval.loc[approval["boardapprovaldate"].notna(), "projectid"])
    qualifying = set(kept["projectid"])
    downloadable = set(kept.loc[kept["txturl"].notna(), "projectid"])

    rows = [
        # `ieg` reaches this function already deduplicated to one row per
        # project, so reporting len(ieg) as "rows in the bulk CSV" understated
        # the file by the one duplicate P-number it contains. The raw count is
        # passed in explicitly instead of inferred.
        ("IEG rating rows in the bulk CSV (as published)",
         int(n_ieg_rows_raw) if n_ieg_rows_raw is not None else len(ieg)),
        ("rows dropped as duplicate P-numbers",
         (int(n_ieg_rows_raw) - len(ieg)) if n_ieg_rows_raw is not None else 0),
        ("distinct projects with an IEG rating", len(rated)),
        ("distinct projects with any PAD in WDS", len(with_pad)),
        ("rated projects with any PAD", len(rated & with_pad)),
        ("rated projects with a board approval date", len(rated & with_approval)),
        ("rated projects with a PAD and a board approval date",
         len(rated & with_pad & with_approval)),
        ("rated projects with a QUALIFYING PAD (leakage filter passed)",
         len(rated & qualifying)),
        ("rated projects with a qualifying PAD and a txturl",
         len(rated & downloadable)),
    ]
    return pd.DataFrame(rows, columns=["stage", "n"])


def schedule_slip_days(actual_close: pd.Series, planned_close: pd.Series) -> pd.Series:
    """Actual closing minus planned closing, in days. NaN where either is missing."""
    a = pd.to_datetime(actual_close, errors="coerce")
    p = pd.to_datetime(planned_close, errors="coerce")
    return (a - p).dt.days.astype("Float64")
