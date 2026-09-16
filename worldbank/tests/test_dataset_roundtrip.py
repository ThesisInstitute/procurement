"""Tests for the release table's CSV round-trip guard.

The CSV is the published artefact, and pandas' READER defaults corrupt two
kinds of value in it silently:
  - 11 `pad_guid` values look numeric ("099751207242621222"), so a bare
    read_csv strips the leading zero;
  - Namibia's ISO country code is "NA", which is in pandas' default
    missing-value list, so it reads as null.
Neither is a defect of the file, and both disappear with the documented reader
arguments. `verify_csv_roundtrip` runs on every build so the artefact can never
quietly stop round-tripping.
"""
import pandas as pd
import pytest

from worldbank.src import dataset


def _frame():
    return pd.DataFrame({
        "projectid": ["P000123", "P000456"],
        "pad_guid": ["099751207242621222", "123456789012345678"],
        "countrycode": ["NA", "ZA"],
        "pad_doc_id": ["0900123", "0900456"],
        "ieg_outcome": ["Satisfactory", "Unsatisfactory"],
    })


def test_roundtrip_passes_with_the_documented_reader(tmp_path):
    df = _frame()
    f = tmp_path / "t.csv"
    df.to_csv(f, index=False)
    dataset.verify_csv_roundtrip(df, f)          # must not raise


def test_a_naive_read_really_does_lose_the_leading_zero(tmp_path):
    """The defect the reader recipe exists to avoid."""
    df = _frame()
    f = tmp_path / "t.csv"
    df.to_csv(f, index=False)
    naive = pd.read_csv(f)
    assert str(naive.loc[0, "pad_guid"]) != df.loc[0, "pad_guid"]
    assert pd.isna(naive.loc[0, "countrycode"])


def test_the_documented_reader_preserves_both(tmp_path):
    df = _frame()
    f = tmp_path / "t.csv"
    df.to_csv(f, index=False)
    back = dataset.read_release_table(f)
    assert back.loc[0, "pad_guid"] == "099751207242621222"
    assert back.loc[0, "countrycode"] == "NA"


def test_roundtrip_raises_when_a_value_is_lost(tmp_path):
    df = _frame()
    f = tmp_path / "t.csv"
    df.to_csv(f, index=False)
    corrupted = df.copy()
    corrupted.loc[0, "pad_guid"] = "different-value"
    with pytest.raises(RuntimeError, match="pad_guid"):
        dataset.verify_csv_roundtrip(corrupted, f)


def test_roundtrip_raises_on_a_row_count_change(tmp_path):
    df = _frame()
    f = tmp_path / "t.csv"
    df.head(1).to_csv(f, index=False)
    with pytest.raises(RuntimeError, match="row count"):
        dataset.verify_csv_roundtrip(df, f)


def test_roundtrip_raises_on_a_column_change(tmp_path):
    df = _frame()
    f = tmp_path / "t.csv"
    df.drop(columns="countrycode").to_csv(f, index=False)
    with pytest.raises(RuntimeError, match="columns"):
        dataset.verify_csv_roundtrip(df, f)
