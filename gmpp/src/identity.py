"""Link project-years into projects across snapshots.

Two regimes exist in the published data, observed on 2026-09-15:

* Nearly every row from the September 2019 snapshot onward carries a GMPP ID
  Number such as "MOD_0001_1112-Q1", and so do 55 rows in the September 2016
  snapshot (the 2017 publications of CO, DfE, DH, DWP, HMRC and MoJ). The
  suffix is the financial-year quarter in which the project joined the
  portfolio. The full id is the identity key: the numeric core alone is reused.
  "BEIS_0004" is "Future Shared Services Programme" with the 1920-Q2 suffix and
  "Industrial Decarbonisation & Hydrogen Revenue Support" with the 2122-Q2
  suffix, so matching on the core would merge two unrelated projects.
* Every other snapshot before September 2019 publishes no id at all, so those
  rows must be linked by name. Coverage is not quite complete at the end either:
  the March 2026 file leaves the id blank on two rows.

The linking is deliberately conservative and fully auditable: every merge that
is not an exact normalised-name match is written to
`results/identity_fuzzy_merges.csv` with its similarity score.
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict

import pandas as pd

from .calendar_map import ordered_snapshots

# Words that carry no distinguishing information in a GMPP project name. Removed
# only for the similarity comparison, never from the published name.
STOPWORDS = {
    "programme", "program", "project", "projects", "the", "of", "and", "a",
    "phase", "scheme", "system", "systems",
}

_BRACKET_RE = re.compile(r"\((?:[^()]*)\)")

# Words after which a small number names an instalment rather than a quantity.
_SERIES_WORDS = {
    "phase", "tranche", "part", "stage", "wave", "tier", "block", "increment",
    "generation", "gen", "programme", "program", "project", "release", "step",
    "lot", "batch", "wave",
}
_WORD_ORDINALS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6,
}


def instalment_numbers(value: object) -> frozenset[int]:
    """Small numbers that name an instalment of a series.

    A number counts only when it follows a series word ("Tranche 3", "Phase
    Two", "Priority School Building Programme 2") or ends the name, and only
    when it is at most 20. This keeps "Type 26 Global Combat Ship" and
    "16/17 New Property Model Programme" out of the guard while catching the
    instalment pairs that must never be merged.
    """
    # Split a digit that is glued to the end of a word, so that "NHSmail2" and
    # "NHSmail 2" are read as the same instalment rather than as one name with
    # an instalment and one without.
    spaced = re.sub(r"(?<=[a-z])(?=\d)", " ", normalise_name(value))
    tokens = spaced.split()
    out: set[int] = set()
    for i, tok in enumerate(tokens):
        number: int | None = None
        if tok.isdigit():
            number = int(tok)
        elif tok in _WORD_ORDINALS:
            number = _WORD_ORDINALS[tok]
        if number is None or not 1 <= number <= 20:
            continue
        follows_series = i > 0 and tokens[i - 1] in _SERIES_WORDS
        is_final = i == len(tokens) - 1
        if follows_series or is_final:
            out.add(number)
    return frozenset(out)


# Pairs the mechanical guards allow but that inspection of the published rows
# shows are different projects. Each is recorded with the reason.
BLOCKED_MERGES: set[frozenset[str]] = {
    # DECC published "New Nuclear Programme" (whole-life cost GBP 40.8m) only in
    # the September 2012 and September 2013 snapshots; "New Nuclear Project
    # (Sizewell C)" first appears in March 2025 under id BEIS_0019_2122-Q1. A
    # twelve-year gap with no intervening rows is not one project.
    frozenset({"new nuclear programme", "new nuclear project"}),
}


# Departments that must be linked together even though they are reported apart.
#
# DECC was abolished in July 2016 and its projects moved to BEIS, which became
# DESNZ and DBT in February 2023. The panel reports DECC/DESNZ and BEIS/DBT
# separately, which is right for a departmental breakdown, but the name linker
# only ever compares inside one group, so a project that crossed the 2016 move
# could not link. The evidence is in the ids: the BEIS prefix appears on 38
# rows labelled BEIS/DBT and 50 labelled DECC/DESNZ, and cores such as
# 0009_2021-Q3 (SIXEP Continuity Plant) and 0014_2021-Q4 (Social Housing
# Decarbonisation Fund) appear under both labels for the same project.
LINKING_GROUPS: dict[str, str] = {
    "BEIS/DBT": "BEIS lineage",
    "DECC/DESNZ": "BEIS lineage",
}


def linking_group(department_norm: object) -> str:
    key = str(department_norm)
    return LINKING_GROUPS.get(key, key)


def normalise_name(value: object) -> str:
    text = str(value) if value is not None else ""
    text = text.replace(" ", " ").replace("&", " and ")
    text = _BRACKET_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def normalise_name_keeping_qualifiers(value: object) -> str:
    """As `normalise_name` but keeps the bracketed qualifier.

    Used only to break a tie between two components whose names normalise to the
    same string, which is exactly the case the bracket stripping creates: the
    September 2014 DH file publishes "BT LSP (London)" and "BT LSP (South)" as
    two projects, and both normalise to "bt lsp". Deriving the project key from
    `normalise_name` alone would hand them the same key and so undo the
    within-snapshot guard that kept them apart.
    """
    text = str(value) if value is not None else ""
    text = text.replace("\u00a0", " ").replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def name_tokens(value: object) -> frozenset[str]:
    return frozenset(t for t in normalise_name(value).split() if t not in STOPWORDS)


def similarity(a: str, b: str) -> float:
    """Max of a sequence ratio and a token Jaccard, both on normalised names.

    The sequence ratio catches small edits and rewordings ("Smart Metering
    Implementation Programme" vs "Smart Meters Implementation Programme",
    0.947); the Jaccard catches reordering and added or dropped qualifiers
    ("Crossrail Programme" vs "Crossrail", 1.00). Neither catches a rename to an
    acronym: "Puma Helicopter Life Extension Programme" against "PUMA" scores
    0.25 and is left unlinked, which is the intended direction of the error and
    is reported in results/report.md.
    """
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return 0.0
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = name_tokens(a), name_tokens(b)
    jac = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return max(seq, jac)


class _Union:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def assign_project_keys(
    panel: pd.DataFrame, fuzzy_threshold: float = 0.90
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Add `project_key` and `project_key_source` to the panel.

    Returns (panel, fuzzy_merge_log, name_collision_log, rename_merge_log).
    """
    work = panel.copy()
    work["gmpp_id_norm"] = (
        work["gmpp_id"].astype(str).str.upper().str.strip().replace({"NAN": None})
    )
    work.loc[work["gmpp_id_norm"].isin(["NONE", "NAN", ""]), "gmpp_id_norm"] = None
    work["name_norm"] = work["project_name"].map(normalise_name)
    work["link_group"] = work["department_norm"].map(linking_group)
    # Position in the snapshot series, so "the next snapshot" means the next
    # published position rather than the next calendar year. The one step from
    # September 2019 to March 2021 is 18 months, every other is 12.
    _order = {pd.Timestamp(d): i for i, d in enumerate(ordered_snapshots())}
    work["snapshot_index"] = pd.to_datetime(work["snapshot_date"]).map(_order)

    # Row-level node id, so union-find can work over rows.
    work["node_id"] = [f"r{i}" for i in range(len(work))]

    uf = _Union()

    # 1. Rows sharing a GMPP id are the same project, full stop.
    for _id, idx in work[work["gmpp_id_norm"].notna()].groupby("gmpp_id_norm").groups.items():
        nodes = work.loc[idx, "node_id"].tolist()
        for n in nodes[1:]:
            uf.union(nodes[0], n)

    # 1b. The prefix of a GMPP id is the department of the day, not part of the
    #     project's identity: the same health project is published as
    #     DH_0031_1314-Q1 and DOH_0031_1314-Q1. The numeric core and the joining
    #     quarter together are the identity. That pair is NOT unique across
    #     government (0001_1112-Q1 is A400M at MOD, Crossrail at DfT and St
    #     Helena Airport at DFID), so it links only inside one linking group,
    #     where it was checked against all 23 cores that carry more than one
    #     prefix and never merges two different projects.
    core_of = work["gmpp_id_norm"].str.extract(r"^[A-Z]+_(\d+_\d{4}-Q\d)$")[0]
    work["gmpp_id_core"] = core_of
    id_core_merges: list[dict] = []
    for (group, core), idx in work[core_of.notna()].groupby(
        ["link_group", "gmpp_id_core"]
    ).groups.items():
        block = work.loc[idx]
        roots = {uf.find(n) for n in block["node_id"]}
        if len(roots) < 2:
            continue
        # Two rows of the same project never share a snapshot.
        if block.groupby("snapshot_date").size().gt(1).any():
            continue
        nodes = block["node_id"].tolist()
        for n in nodes[1:]:
            uf.union(nodes[0], n)
        id_core_merges.append(
            {
                "link_group": group,
                "gmpp_id_core": core,
                "ids": " | ".join(sorted(set(block["gmpp_id_norm"].dropna()))),
                "names": " | ".join(sorted(set(block["project_name"].astype(str)))),
                "snapshots": " ".join(
                    sorted({str(d)[:10] for d in block["snapshot_date"]})
                ),
            }
        )

    # 2. Rows sharing an exact normalised name inside a department group are the
    #    same project. This is what links the pre-2019 snapshots, and it also
    #    pulls the id-free years onto the id-bearing components.
    #
    #    With one guard. Normalising strips bracketed qualifiers, so two
    #    genuinely different projects published in the same snapshot can collide:
    #    the September 2014 Department of Health file publishes both "BT LSP
    #    (London)" (whole-life cost 1,108.97) and "BT LSP (South)" (634.06), and
    #    merging them would delete a project and invent a 57 per cent cost rise
    #    on the survivor. If a name group holds two distinct components inside one
    #    snapshot, the group is not merged at all.
    #
    #    The test is on the names themselves. Two rows in one snapshot whose
    #    RAW names are identical are the same project published twice, not two
    #    projects: Defra has two gov.uk pages both carrying the September 2014
    #    position, so every Defra project of that year appears twice. Those are
    #    merged here and the copy is dropped downstream. The guard fires only
    #    when the raw names differ inside a snapshot, which is the case
    #    bracket-stripping creates and the only case it needs to cover.
    name_collisions: list[dict] = []
    collided: set[tuple[str, str]] = set()
    for key, idx in work[work["name_norm"] != ""].groupby(
        ["link_group", "name_norm"]
    ).groups.items():
        block = work.loc[idx]
        distinct_names_per_snapshot = block.groupby("snapshot_date")[
            "project_name"
        ].apply(lambda names: names.astype(str).nunique())
        if (distinct_names_per_snapshot > 1).any():
            collided.add((key[0], key[1]))
            name_collisions.append(
                {
                    "link_group": key[0],
                    "name_norm": key[1],
                    "names": " | ".join(sorted(set(block["project_name"].astype(str)))),
                    "snapshots": " ".join(
                        sorted({str(d)[:10] for d in block["snapshot_date"]})
                    ),
                    "n_rows": len(block),
                }
            )
            continue
        nodes = block["node_id"].tolist()
        for n in nodes[1:]:
            uf.union(nodes[0], n)

    # 3. Conservative fuzzy pass. Only between two components inside the same
    #    department group, only above the threshold, and only when merging does
    #    not put two rows of the same project in the same snapshot (which would
    #    mean they are different projects that happen to be similarly named).
    work["root_id"] = work["node_id"].map(uf.find)
    merges: list[dict] = []
    for dept, block in work.groupby("link_group"):
        comps = defaultdict(list)
        for row in block.itertuples():
            comps[row.root_id].append(row)
        roots = list(comps)
        reps = {
            r: max(comps[r], key=lambda x: len(str(x.project_name))) for r in roots
        }
        snaps = {r: {x.snapshot_date for x in comps[r]} for r in roots}
        for i, ra in enumerate(roots):
            for rb in roots[i + 1 :]:
                ra_now, rb_now = uf.find(ra), uf.find(rb)
                if ra_now == rb_now:
                    continue
                if snaps[ra] & snaps[rb]:
                    continue
                name_a, name_b = reps[ra].project_name, reps[rb].project_name
                if instalment_numbers(name_a) != instalment_numbers(name_b):
                    continue
                pair = frozenset({normalise_name(name_a), normalise_name(name_b)})
                if pair in BLOCKED_MERGES:
                    continue
                # Never let the fuzzy pass undo the guard above. The September
                # 2015 DH file publishes one "BT LSP" row whose whole-life cost
                # (1743.03) is the sum of the two September 2014 rows (1108.97
                # and 634.06), so it is the consolidation of both and merging it
                # into either one alone would invent a 57 per cent cost rise.
                if (
                    (dept, normalise_name(name_a)) in collided
                    and (dept, normalise_name(name_b)) in collided
                ):
                    continue
                score = similarity(name_a, name_b)
                if score >= fuzzy_threshold:
                    uf.union(ra_now, rb_now)
                    snaps[ra] = snaps[ra] | snaps[rb]
                    snaps[rb] = snaps[ra]
                    merges.append(
                        {
                            "link_group": dept,
                            "name_a": name_a,
                            "name_b": name_b,
                            "similarity": round(score, 4),
                        }
                    )

    work["root_id"] = work["node_id"].map(uf.find)

    # 3b. Renames the name matcher cannot see.
    #
    #     A project that is renamed outright, rather than edited, scores below
    #     any safe similarity threshold: "Puma Helicopter Life Extension
    #     Programme" against "PUMA" scores 0.25. Left unlinked it invents a
    #     permanent exit for the old name and a new project for the new one, and
    #     exit is one of the scored outcomes, so the error is not cosmetic.
    #
    #     The published fields identify these without reference to the name. A
    #     component that ends at snapshot s and another that begins at s+1, in
    #     the same linking group, with the SAME published latest-approved start
    #     date and a baseline whole-life cost within 2 per cent across the step,
    #     is one project under two names. A project's approved start date is
    #     fixed history, so two projects agreeing on it to the day and on their
    #     whole-life cost to within 2 per cent, in the same department, in
    #     adjacent snapshots, is not a coincidence the panel produces otherwise.
    #     Every merge is written to results/identity_rename_merges.csv.
    rename_merges: list[dict] = []
    has_rename_evidence = {"start_date", "wlc_baseline_gbp_m"} <= set(work.columns)
    work["root_id"] = work["node_id"].map(uf.find)
    comp = work.groupby("root_id")
    spans = comp.agg(
        first_index=("snapshot_index", "min"),
        last_index=("snapshot_index", "max"),
        group=("link_group", "first"),
    )
    last_row = (
        work.sort_values("snapshot_index").groupby("root_id").last()
    )
    first_row = (
        work.sort_values("snapshot_index").groupby("root_id").first()
    )
    by_start_index: dict[tuple, list] = defaultdict(list)
    for root, row in spans.iterrows():
        by_start_index[(row["group"], row["first_index"])].append(root)

    for root, row in spans.iterrows() if has_rename_evidence else []:
        # Only components that end before the final snapshot can be renames.
        successors = by_start_index.get((row["group"], row["last_index"] + 1), [])
        if not successors:
            continue
        end = last_row.loc[root]
        if pd.isna(end["start_date"]) or pd.isna(end["wlc_baseline_gbp_m"]):
            continue
        for other in successors:
            if uf.find(root) == uf.find(other):
                continue
            begin = first_row.loc[other]
            if pd.isna(begin["start_date"]) or pd.isna(begin["wlc_baseline_gbp_m"]):
                continue
            if str(end["start_date"])[:10] != str(begin["start_date"])[:10]:
                continue
            a = float(end["wlc_baseline_gbp_m"])
            b = float(begin["wlc_baseline_gbp_m"])
            if a <= 0 or b <= 0 or abs(b / a - 1.0) > 0.02:
                continue
            uf.union(uf.find(root), uf.find(other))
            rename_merges.append(
                {
                    "link_group": row["group"],
                    "name_before": end["project_name"],
                    "name_after": begin["project_name"],
                    "last_snapshot_before": str(end["snapshot_date"])[:10],
                    "first_snapshot_after": str(begin["snapshot_date"])[:10],
                    "start_date": str(end["start_date"])[:10],
                    "wlc_before": a,
                    "wlc_after": b,
                    "name_similarity": round(
                        similarity(end["project_name"], begin["project_name"]), 4
                    ),
                }
            )
            break

    work["root_id"] = work["node_id"].map(uf.find)

    # 4. Stable, readable project keys: the GMPP id where the component has one,
    #    otherwise DEPT::normalised-name of the component's longest name.
    #
    #    The name form can collide. Normalising strips bracketed qualifiers, so
    #    the two components the guard in step 2 deliberately kept apart ("BT LSP
    #    (London)" and "BT LSP (South)") would otherwise be handed the same key,
    #    silently undoing that guard. A collided key is therefore rebuilt from
    #    the qualifier-preserving name, and if that still ties, from the sorted
    #    set of the component's published names. Both are functions of the names
    #    alone, so the keys do not depend on row order.
    key_for: dict[str, str] = {}
    source_for: dict[str, str] = {}
    name_components: dict[str, list[str]] = defaultdict(list)
    for root, block in work.groupby("root_id"):
        ids = sorted(set(block["gmpp_id_norm"].dropna()))
        if ids:
            key_for[root] = ids[0]
            source_for[root] = "gmpp_id" if len(ids) == 1 else "gmpp_id (multiple)"
        else:
            longest = max(sorted(block["project_name"].astype(str)), key=len)
            key = f"{block['link_group'].iloc[0]}::{normalise_name(longest)}"
            key_for[root] = key
            source_for[root] = "name"
            name_components[key].append(root)

    for key, roots in name_components.items():
        if len(roots) < 2:
            continue
        for root in roots:
            block = work[work["root_id"] == root]
            longest = max(sorted(block["project_name"].astype(str)), key=len)
            dept = block["link_group"].iloc[0]
            candidate = f"{dept}::{normalise_name_keeping_qualifiers(longest)}"
            if candidate == key or candidate in key_for.values():
                names = "+".join(sorted(set(block["project_name"].astype(str))))
                candidate = f"{dept}::{normalise_name_keeping_qualifiers(names)}"
            key_for[root] = candidate
            source_for[root] = (
                "name (disambiguated: another project in this department "
                "normalises to the same name)"
            )

    work["project_key"] = work["root_id"].map(key_for)
    work["project_key_source"] = work["root_id"].map(source_for)
    out = work.drop(columns=["node_id", "root_id", "snapshot_index"])
    fuzzy = pd.DataFrame(merges)
    if id_core_merges:
        fuzzy = pd.concat(
            [fuzzy, pd.DataFrame(id_core_merges).assign(similarity=None,
                                                        via="gmpp id core")],
            ignore_index=True,
        )
    return out, fuzzy, pd.DataFrame(name_collisions), pd.DataFrame(rename_merges)
