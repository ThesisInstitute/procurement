"""End to end: parse -> labels -> features -> ladder -> transfer, on a world
whose bidder effect is known by construction."""

import pandas as pd
import pytest

from src.experiments import LABELS, analysis_set, run_all
from src.parse import attach_registry, parse_tender, registry_row
from tests.synth import build_world


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tenders, registries = build_world(n_tenders=3200, seed=11, bidder_effect=0.7)
    trows, brows, crows = [], [], []
    for t in tenders:
        tr, br, cr = parse_tender(t)
        trows.append(tr)
        brows.extend(br)
        crows.extend(cr)
    data = tmp_path_factory.mktemp("data")
    pd.DataFrame(trows).to_parquet(data / "tenders.parquet", index=False)
    pd.DataFrame(brows).to_parquet(data / "bids.parquet", index=False)
    attach_registry(pd.DataFrame(crows), [registry_row(r) for r in registries]).to_parquet(
        data / "contracts.parquet", index=False
    )
    from src.labels import add_labels, build_lots

    lots = add_labels(
        build_lots(
            pd.read_parquet(data / "tenders.parquet"),
            pd.read_parquet(data / "bids.parquet"),
            pd.read_parquet(data / "contracts.parquet"),
        )
    )
    lots.to_parquet(data / "lots.parquet", index=False)
    results = tmp_path_factory.mktemp("results")
    summary = run_all(data, results, n_perm=500)
    return {"data": data, "results": results, "summary": summary, "lots": lots}


def test_every_lot_has_one_row_and_a_winner(world):
    lots = world["lots"]
    assert lots.duplicated(["tender_id", "lot_id"]).sum() == 0
    assert lots["winner_id"].notna().all()
    assert lots["duration_extension"].notna().all()


def test_analysis_set_and_artifacts_exist(world):
    res = world["results"]
    for name in [
        "fill_rates.csv",
        "base_rates_by_year.csv",
        "model_ladder.csv",
        "calibration.csv",
        "lowest_disqualified_contrast.csv",
        "discount_deciles.csv",
        "bid_dispersion.csv",
        "summary.json",
        "extension_by_discount_decile.png",
        "transfer_scatter_duration_extension.png",
    ]:
        assert (res / name).exists(), name
    assert world["summary"]["lots_in_analysis_set"] == len(analysis_set(world["lots"]))


def test_ladder_covers_every_label_and_rung_on_the_primary_split(world):
    ladder = pd.read_csv(world["results"] / "model_ladder.csv")
    primary = ladder[ladder["split"] == "test 2021-2022"]
    assert set(primary["model"]) == {
        "base rate",
        "reference class",
        "GBM lot, no buyer history",
        "GBM lot, plus buyer history",
        "GBM plus the bidder's price",
        "GBM plus the bidder's price and history",
    }
    assert "duration_extension" in set(primary["label"])
    # The base-rate rung has zero skill against itself by construction.
    base = primary[primary["model"] == "base rate"]
    assert base["bss"].abs().max() < 1e-9
    # Every rung is scored on the same number of test rows.
    for lab, g in primary.groupby("label"):
        assert g["n"].nunique() == 1
    assert set(primary["label"]) <= set(LABELS)


def test_planted_bidder_effect_is_recovered_and_the_placebo_is_not(world):
    t = world["summary"]["transfer"]["duration_extension"]
    full = t["full model (price and identity)"]
    placebo = t["lot only (placebo)"]
    assert full["n_cells"] > 20
    assert full["observed"] > 0.15, full
    # The headline rows freeze bidder history at the start of the test window,
    # which removes real signal along with the circularity; the leaky variant
    # is the stronger test of whether the machinery works at all.
    assert full["p_greater"] < 0.10, full
    leaky = t["full model, history as of each tender (overlaps the resolution window)"]
    assert leaky["p_greater"] < 0.05, leaky
    # The lot block knows nothing about the bidder, so it must not transfer.
    assert abs(placebo["observed"]) < abs(full["observed"])
    assert full["excess_over_null"] > placebo["excess_over_null"]


def test_the_within_division_null_carries_the_composition_effect(world):
    """The null shuffles inside a division, so it keeps the between-division
    association: its mean is the correlation composition alone produces, not
    zero.  The placebo's observed value should sit on top of that mean, while
    the full model's should sit above it."""
    t = world["summary"]["transfer"]["duration_extension"]
    placebo = t["lot only (placebo)"]
    full = t["full model (price and identity)"]
    assert placebo["excess_over_null"] < 2 * placebo["null_sd"]
    assert full["excess_over_null"] > placebo["excess_over_null"]
    assert full["p_greater"] < placebo["p_greater"]


def test_report_renders_from_the_artifacts_alone(world):
    from src.report import build

    text = build(world["results"])
    assert text.startswith("# Forecasting contract slip per competing bidder")
    for heading in [
        "## What was built",
        "## Field evidence",
        "## Fill rates",
        "## Labels",
        "## Experiment 1",
        "## Experiment 2",
        "## Experiment 3",
        "## Experiment 4",
        "## Caveats",
        "## What could not be verified",
        "## Reproduction",
    ]:
        assert heading in text, heading
    # House style: no em dash, no en dash, no emoji or other pictographs.
    for name, code in [("em dash", 0x2014), ("en dash", 0x2013),
                       ("horizontal bar", 0x2015), ("minus sign", 0x2212)]:
        assert chr(code) not in text, name
    stray = {
        c for c in text
        if ord(c) > 0x2000 and not (0x0400 <= ord(c) <= 0x04FF) and c not in "‘’“”"
    }
    assert not stray, f"stray symbols: {sorted(hex(ord(c)) for c in stray)}"
    assert text.count("Spearman") >= 2


def test_identity_persistence_recovers_the_planted_bidder_effect(world):
    p = world["summary"]["identity_persistence"]
    key = "duration_extension|min_wins=3"
    assert key in p
    res = p[key]
    if res.get("n_bidders", 0) >= 10:
        assert res["observed"] > res["null_mean"]


def test_within_lot_test_runs_and_its_degenerate_control_is_uninformative(world):
    wl = pd.read_csv(world["results"] / "within_lot_test.csv")
    assert len(wl) >= 4
    de = wl[(wl["label"] == "duration_extension") & (wl["sample"] == "all test lots")]
    assert set(de["forecast"]) == {
        "raw price rank on the lot, no model",
        "full model (price and identity)",
        "price only",
        "prior extension rate only",
        "lot only (degenerate control)",
    }
    # The lot-only forecast is constant within a lot, so every percentile is
    # 0.5 and the statistic must be exactly uninformative.
    ctrl = de[de["forecast"] == "lot only (degenerate control)"].iloc[0]
    assert ctrl["auc"] == pytest.approx(0.5, abs=1e-9)
    # The null is centred on chance by construction.
    for _, r in de.iterrows():
        assert abs(r["null_mean"] - 0.5) < 0.05
    assert de["n_lots"].max() > 100


def test_within_lot_test_recovers_the_planted_bidder_effect(world):
    wl = pd.read_csv(world["results"] / "within_lot_test.csv")
    de = wl[(wl["label"] == "duration_extension") & (wl["sample"] == "all test lots")]
    prior = de[de["forecast"] == "prior extension rate only"].iloc[0]
    # The synthetic world gives each bidder a latent propensity, so a bidder's
    # own record must rank its outcome even with the lot held fixed.
    assert prior["auc"] > 0.52, prior.to_dict()
    assert prior["p_two_sided"] < 0.05, prior.to_dict()


def test_head_to_head_scores_every_predictor_on_the_same_rows(world):
    h2h = pd.read_csv(world["results"] / "identity_head_to_head.csv")
    primary = h2h[
        (h2h["split"] == "test 2021-2022")
        & (h2h["label"] == "duration_extension")
        & (h2h["subset"] == "all test lots")
    ]
    assert len(primary) >= 4
    assert set(h2h["subset"]) >= {"all test lots"}
    # Like for like: every predictor is scored on the same test rows.
    assert primary["n"].nunique() == 1
    assert primary["auc"].between(0.0, 1.0).all()
    # The synthetic world plants a bidder effect and no buyer effect, so the
    # winner's own record must out-rank the buyer's.
    by = dict(zip(primary["predictor"], primary["auc"]))
    assert by["winner's as-of extension rate"] > by["buyer's as-of extension rate"]
