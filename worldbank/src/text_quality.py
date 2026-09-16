"""Measure OCR noise in the PAD corpus, by approval year and by fold.

WHY THIS EXISTS. An earlier version of the report carried this caveat:

    "Older documents are scanned and OCR'd; the text layer is noisier before
     roughly 2005, which is exactly the training fold."

Nothing in the repository measured it. It was a mechanism claim about how the
corpus was produced, asserted as fact, and this project's rule is that such a
claim must be observed or labelled. Worse, when measured it turns out to be
BACKWARDS in both of its parts, and the true picture points at a live
methodological hazard rather than a decorative caveat.

THE PROXIES. Two signatures of a bad text layer, both cheap and both specific:

  broken_of_per_1k
      Occurrences of "Ia", "ofthe", "tbe", "arid", "aud", "conunitment" and
      similar per 1,000 tokens. A scanned page run through OCR splits or merges
      short function words in characteristic ways; born-digital text extracted
      from a PDF's text layer does not. This is the sharper of the two.

  single_char_token_rate
      Share of alphabetic tokens that are a single character other than "a" or
      "i". Character-level OCR fragmentation inflates it.

Neither is a ground-truth measurement of whether a document was scanned; no
World Bank source states that. They are noise proxies, and the module reports
them as such.

Run:  .venv/bin/python -m worldbank.src.text_quality
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import model
from .paths import RESULTS

# Tokens that are characteristic OCR corruptions of very common words. "Ia" is
# the classic: a capital I followed by a lowercase a, which is how OCR reads
# "la" and, in World Bank French and Spanish documents, extremely often.
OCR_MARKERS = [
    r"\bIa\b", r"\bofthe\b", r"\bthe\b(?=[a-z])", r"\btbe\b", r"\btbat\b",
    r"\barid\b", r"\baud\b", r"\bconunitment\b", r"\bdevelopmnent\b",
    r"\bprojeet\b", r"\bfmancial\b", r"\bfmancing\b", r"\bJ3ank\b",
    r"\bWorId\b", r"\bBaak\b",
]
MARKER_RE = re.compile("|".join(OCR_MARKERS))
TOKEN_RE = re.compile(r"[A-Za-z]+")
SAMPLE_CHARS = 120_000   # enough to characterise a document, cheap to scan


def score_text(text: str) -> dict:
    """Noise proxies for one document. Empty text returns NaN, not zero."""
    t = text[:SAMPLE_CHARS]
    toks = TOKEN_RE.findall(t)
    n = len(toks)
    if n < 500:
        return {"n_tokens": n, "broken_of_per_1k": np.nan,
                "single_char_token_rate": np.nan}
    singles = sum(1 for w in toks if len(w) == 1 and w.lower() not in ("a", "i"))
    return {
        "n_tokens": n,
        "broken_of_per_1k": 1000.0 * len(MARKER_RE.findall(t)) / n,
        "single_char_token_rate": singles / n,
    }


def run() -> dict:
    df = pd.read_parquet(RESULTS / "pad_ieg_join.parquet")
    df = df[df["y_satisfactory"].notna() & df["approval_year"].notna()].copy()
    df = model.attach_text(df)
    cuts = model.choose_splits(df)

    scored = pd.DataFrame([score_text(t) for t in df["pad_text"]])
    d = pd.concat([df[["projectid", "approval_year"]].reset_index(drop=True),
                   scored], axis=1)
    d["approval_year"] = d["approval_year"].astype(int)
    d["fold"] = np.where(d["approval_year"] <= cuts["train_end"], "train",
                         np.where(d["approval_year"] <= cuts["valid_end"],
                                  "validate", "test"))

    by_year = d.groupby("approval_year").agg(
        n=("projectid", "size"),
        broken_of_per_1k=("broken_of_per_1k", "median"),
        single_char_token_rate=("single_char_token_rate", "median"),
    ).reset_index()
    by_fold = d.groupby("fold").agg(
        n=("projectid", "size"),
        broken_of_per_1k=("broken_of_per_1k", "median"),
        mean_broken_of_per_1k=("broken_of_per_1k", "mean"),
        single_char_token_rate=("single_char_token_rate", "median"),
    ).reset_index()
    # order the folds chronologically, not alphabetically
    by_fold["fold"] = pd.Categorical(by_fold["fold"],
                                     ["train", "validate", "test"],
                                     ordered=True)
    by_fold = by_fold.sort_values("fold")

    by_year.to_csv(RESULTS / "text_quality_by_year.csv", index=False)
    by_fold.to_csv(RESULTS / "text_quality_by_fold.csv", index=False)
    print(by_fold.to_string(index=False))
    print()
    print(by_year.to_string(index=False))
    return {"by_year": by_year, "by_fold": by_fold, "cuts": cuts}


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
