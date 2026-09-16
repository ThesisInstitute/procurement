"""Select the tender sample from the census of the Prozorro feed.

The census (`census.py`) is a complete walk of the feed from 2019-01-01 to the
run date, so every tender created on or after 2019-01-01 appears exactly once
(de-duplicated on `id`).  From that population we take completed
above-threshold tenders whose tenderID creation date falls in the sample window
and draw a proportional stratified sample by creation month, with a fixed seed.

Proportional (not equal) allocation is deliberate: it keeps the sampled label
base rates unbiased estimates of the population base rates for each year.
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.census import CENSUS_DIR, tender_id_date  # noqa: E402

MONTHS_DIR = CENSUS_DIR.parent / "census_months"

RESULTS = Path(__file__).resolve().parents[1] / "results"


def load_census(census_dir: Path = CENSUS_DIR) -> dict[str, dict]:
    """De-duplicate census rows on tender id, keeping the latest dateModified."""
    best: dict[str, dict] = {}
    for path in sorted(census_dir.glob("cand_*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                prev = best.get(row["id"])
                if prev is None or row["dateModified"] > prev["dateModified"]:
                    best[row["id"]] = row
    return best


def census_coverage(census_dir: Path = CENSUS_DIR) -> dict:
    """Total feed rows walked and the dateModified span actually covered."""
    metas = [json.loads(p.read_text()) for p in sorted(census_dir.glob("meta_*.json"))]
    per_year: Counter[str] = Counter()
    method_status: Counter[tuple[str, str]] = Counter()
    for m in metas:
        for c in m["daily_counts"]:
            per_year[c["day"][:4]] += c["n"]
            method_status[(c["method"], c["status"])] += c["n"]
    firsts = [m["first_dateModified"] for m in metas if m["first_dateModified"]]
    lasts = [m["last_dateModified"] for m in metas if m["last_dateModified"]]
    design_path = census_dir / "design.json"
    design = json.loads(design_path.read_text()) if design_path.exists() else {}
    return {
        "design": design,
        "windows": len(metas),
        "rows_walked": sum(m["rows_seen"] for m in metas),
        "pages": sum(m["pages"] for m in metas),
        "kept": sum(m["kept"] for m in metas),
        "first_dateModified": min(firsts) if firsts else None,
        "last_dateModified": max(lasts) if lasts else None,
        "rows_by_dateModified_year": dict(sorted(per_year.items())),
        "rows_by_method_status": {f"{m}|{s}": n for (m, s), n in method_status.most_common()},
    }


def select(
    population: dict[str, dict],
    start: str = "2019-01-01",
    end: str = "2022-12-31",
    n_target: int = 45000,
    seed: int = 20260916,
) -> tuple[list[dict], dict]:
    """Proportional stratified sample by tenderID creation month."""
    strata: dict[str, list[dict]] = defaultdict(list)
    for row in population.values():
        d = tender_id_date(row.get("tenderID") or "")
        if d is None or d < start or d > end:
            continue
        row = dict(row, created=d)
        strata[d[:7]].append(row)

    total = sum(len(v) for v in strata.values())
    rng = random.Random(seed)
    chosen: list[dict] = []
    # Largest-remainder allocation so the sample sums exactly to n_target.
    exact = {k: len(v) * n_target / total for k, v in strata.items()}
    alloc = {k: min(int(v), len(strata[k])) for k, v in exact.items()}
    short = n_target - sum(alloc.values())
    order = sorted(exact, key=lambda k: (-(exact[k] - int(exact[k])), k))
    i = 0
    while short > 0 and i < len(order) * 3:
        k = order[i % len(order)]
        if alloc[k] < len(strata[k]):
            alloc[k] += 1
            short -= 1
        i += 1
    for month in sorted(strata):
        pool = sorted(strata[month], key=lambda r: r["id"])
        rng.shuffle(pool)
        chosen.extend(pool[: alloc[month]])
    # Interleave months so that an interrupted fetch still spans the window.
    rng.shuffle(chosen)
    meta = {
        "population_in_window": total,
        "population_by_month": {k: len(v) for k, v in sorted(strata.items())},
        "sampled": len(chosen),
        "sampled_by_month": dict(Counter(r["created"][:7] for r in chosen)),
        "window": [start, end],
        "seed": seed,
    }
    return chosen, meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=45000)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2022-12-31")
    ap.add_argument("--seed", type=int, default=20260916)
    ap.add_argument("--out", default=str(CENSUS_DIR / "sample_ids.txt"))
    args = ap.parse_args()

    pop = load_census()
    print(f"census population (deduped complete above-threshold): {len(pop):,}")
    chosen, meta = select(pop, args.start, args.end, args.n, args.seed)
    meta["census"] = census_coverage()
    meta["months_census"] = census_coverage(MONTHS_DIR) if MONTHS_DIR.exists() else {}
    meta["population_deduped_all_years"] = len(pop)
    Path(args.out).write_text("\n".join(r["id"] for r in chosen))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "sample_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"population in {args.start}..{args.end}: {meta['population_in_window']:,}")
    print(f"sampled: {meta['sampled']:,} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
