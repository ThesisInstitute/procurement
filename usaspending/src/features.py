"""Feature blocks for the model ladder, and train-only categorical lumping."""
from __future__ import annotations

import pandas as pd

CATEGORICAL = [
    "type_of_contract_pricing_code",
    "extent_competed_code",
    "solicitation_procedures_code",
    "type_of_set_aside_code",
    "naics2",
    "naics6",
    "psc1",
    "psc_full",
    "awarding_agency_code",
    "awarding_sub_agency_code",
    "awarding_office_code",
    "contracting_officers_determination_of_business_size_code",
    "performance_based_service_acquisition_code",
    "multi_year_contract_code",
    "cost_or_pricing_data_code",
    "fed_biz_opps_code",
    "primary_place_of_performance_state_code",
]

NUMERIC = [
    "log_base_obligation",
    "log_base_ceiling",
    "option_heaviness",
    "planned_duration_days",
    "potential_extra_duration_days",
    "n_offers",
    "n_offers_missing",
    "base_fy",
    "base_month",
]

HISTORY = [
    "recipient_prior_award_count",
    "recipient_prior_mean_ceiling_growth_36",
    "recipient_prior_termination_rate_36",
    "recipient_prior_slip_rate_36",
    "office_prior_award_count",
    "office_prior_mean_ceiling_growth_36",
    "office_prior_termination_rate_36",
    "office_prior_slip_rate_36",
]

MAX_CATEGORIES = 254
OTHER = "__OTHER__"
MISSING = "__MISSING__"


def fit_category_maps(train: pd.DataFrame, cols=None) -> dict:
    """Keep the most frequent categories per column, counted on train only.

    HistGradientBoosting bins each feature into at most 255 bins, so a
    high-cardinality code such as awarding_office_code cannot be passed whole.
    Everything outside the train-period top MAX_CATEGORIES becomes __OTHER__.
    """
    cols = cols or CATEGORICAL
    maps = {}
    for c in cols:
        if c not in train.columns:
            continue
        vc = train[c].astype("string").fillna(MISSING).value_counts()
        maps[c] = list(vc.index[:MAX_CATEGORIES])
    return maps


def apply_category_maps(df: pd.DataFrame, maps: dict) -> pd.DataFrame:
    out = df.copy()
    for c, keep in maps.items():
        s = out[c].astype("string").fillna(MISSING)
        s = s.where(s.isin(keep), OTHER)
        out[c] = pd.Categorical(s, categories=list(keep) + [OTHER])
    return out


def feature_columns(use_history: bool) -> tuple[list, list]:
    num = list(NUMERIC) + (list(HISTORY) if use_history else [])
    return list(CATEGORICAL), num
