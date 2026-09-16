"""Canonical GMPP schema and the header-variant map.

Every entry below was taken from `data/raw/gmpp/header_summary.csv`, which is
built by `gmpp.src.profile_headers` from the 542 downloaded files. Keys are
headers normalised by `profile_headers.norm_header`: lower-cased, bracketed
explanatory text removed, non-alphanumerics collapsed to single spaces. The
bracket strip matters because from 2014 the DCA header embeds the full scale
definition and that wording changes between years while the field does not.

Unmapped headers are never dropped silently: `gmpp.src.panel` writes every one
to `results/unmapped_headers.csv` with its file and year.

Four keys here once named headers no published file produces. `norm_header`
strips a bracketed qualifier BEFORE it rewrites a pound sign, so "FY Budget
(£m) inc Non Gov" becomes "fy budget inc non gov" and never "fy budget gbpm
inc non gov". A test asserts that every key is a header some file really
carries, so a key written from the raw spelling rather than the normalised one
fails immediately instead of sitting dead.
"""
from __future__ import annotations

CANONICAL_COLUMNS = [
    # Published only by the two NISTA consolidated files, and populated on every
    # row of both: 213 project-years in March 2025 and 189 in March 2026. It is
    # the first evaluation-commitment field the portfolio has ever published.
    "evaluation_plan",
    "gmpp_id",
    "project_name",
    "department",
    "report_year",
    "snapshot_date",
    "annual_report_category",
    "description",
    "dca_ipa",
    "dca_sro",
    "dca_commentary",
    "start_date",
    "end_date",
    "schedule_narrative",
    "fy_baseline_gbp_m",
    "fy_forecast_gbp_m",
    "fy_variance_pct",
    "fy_variance_gbp_m",
    "budget_narrative",
    "wlc_baseline_gbp_m",
    "wlc_narrative",
    "benefits_baseline_gbp_m",
    "benefits_narrative",
    "sro_name",
    "source_file",
]

# normalised header -> canonical column
HEADER_MAP: dict[str, str] = {
    # evaluation commitment, published by the two NISTA files only
    "does the project have an evaluation plan": "evaluation_plan",
    "evaluation plan and registry link": "evaluation_plan",

    # identity
    "gmpp id number": "gmpp_id",
    "gmpp id": "gmpp_id",
    "major projects id": "gmpp_id",
    "id numbers": "gmpp_id",
    "project name": "project_name",
    "department": "department",
    "annual report category": "annual_report_category",
    "project category": "annual_report_category",
    # description
    "description": "description",
    "description aims": "description",
    "detailed description aims": "description",
    "project description": "description",
    # the forecast being scored
    "ipa delivery confidence assessment": "dca_ipa",
    "mpa rag rating": "dca_ipa",
    "ipa rag rating": "dca_ipa",
    "mpa rag": "dca_ipa",
    "sro delivery confidence assessment": "dca_sro",
    "departmental commentary on actions planned or taken on the ipa rag rating":
        "dca_commentary",
    "departmental commentary on actions planned or taken on the mpa rag rating":
        "dca_commentary",
    "departmental narrative actions on delivery confidence assessment":
        "dca_commentary",
    "departmental commentary on delivery confidence assessment rating":
        "dca_commentary",
    # schedule
    "project start date": "start_date",
    "start date": "start_date",
    "project end date": "end_date",
    "end date": "end_date",
    "departmental narrative on schedule including any deviation from planned "
    "schedule": "schedule_narrative",
    "schedule narrative": "schedule_narrative",
    # in-year finance: baseline / budget
    "financial year baseline": "fy_baseline_gbp_m",
    "2012 13 budget": "fy_baseline_gbp_m",
    "2013 2014 budget": "fy_baseline_gbp_m",
    "2014 2015 budget": "fy_baseline_gbp_m",
    "2015 16 budget": "fy_baseline_gbp_m",
    "2016 17 total baseline gbpm": "fy_baseline_gbp_m",
    "2016 17 total baseline m": "fy_baseline_gbp_m",
    "2017 18 total baseline gbpm": "fy_baseline_gbp_m",
    "2017 18 total baseline m": "fy_baseline_gbp_m",
    "2018 19 total baseline gbpm": "fy_baseline_gbp_m",
    "fy budget inc non gov": "fy_baseline_gbp_m",
    # in-year finance: forecast
    "financial year forecast": "fy_forecast_gbp_m",
    "2012 13 forecast": "fy_forecast_gbp_m",
    "2013 2014 forecast": "fy_forecast_gbp_m",
    "2014 2015 forecast": "fy_forecast_gbp_m",
    "2015 16 forecast": "fy_forecast_gbp_m",
    "2016 17 total forecast gbpm": "fy_forecast_gbp_m",
    "2016 17 total forecast m": "fy_forecast_gbp_m",
    "2017 18 total forecast gbpm": "fy_forecast_gbp_m",
    "2017 18 total forecast m": "fy_forecast_gbp_m",
    "2018 19 total forecast gbpm": "fy_forecast_gbp_m",
    "fy forecast inc non gov": "fy_forecast_gbp_m",
    # in-year finance: variance. "%age" is the published spelling of "percentage";
    # 2014 and 2015 publish the variance twice, once in GBP million and once as a
    # percentage, so the two are kept apart.
    "financial year variance": "fy_variance_pct",
    "2013 2014 variance age": "fy_variance_pct",
    "2014 2015 variance age": "fy_variance_pct",
    "variance budget forecast age": "fy_variance_pct",
    "2016 2017 variance age": "fy_variance_pct",
    "2017 2018 variance age": "fy_variance_pct",
    "2018 2019 variance age": "fy_variance_pct",
    "budget variance": "fy_variance_pct",
    "2013 2014 variance": "fy_variance_gbp_m",
    "2014 2015 variance": "fy_variance_gbp_m",
    # whole-life cost, the headline money figure
    "total baseline whole life costs": "wlc_baseline_gbp_m",
    "total budgeted whole life costs": "wlc_baseline_gbp_m",
    "whole life cost total baseline gbpm": "wlc_baseline_gbp_m",
    "whole life cost total baseline m": "wlc_baseline_gbp_m",
    "whole life cost": "wlc_baseline_gbp_m",
    "total budgeted whole life costs including non government costs":
        "wlc_baseline_gbp_m",
    "departmental narrative on budgeted whole life costs": "wlc_narrative",
    "costs narrative": "wlc_narrative",
    # benefits
    "total baseline benefits": "benefits_baseline_gbp_m",
    "benefits": "benefits_baseline_gbp_m",
    "departmental narrative on budgeted benefits": "benefits_narrative",
    "benefits narrative": "benefits_narrative",
    # people
    "senior responsible owner name": "sro_name",
    "sro": "sro_name",
}

# The in-year budget narrative header carries the financial year in its text and
# therefore changes spelling every year. Matched by prefix rather than listed.
BUDGET_NARRATIVE_PREFIXES = (
    "departmental narrative on budget forecast variance for",
    "in year variance narrative",
)

# Headers observed in the files that carry no project-level data: spreadsheet
# working notes, exemption bookkeeping, and long methodological footnotes that
# the publisher placed in a header cell. Listed so they are excluded knowingly
# rather than appearing as unmapped noise.
KNOWN_NON_DATA_HEADERS = {
    "b",
    "cells to be exempted",
    "d10 d16",
    "e4 e6 e9 16",
    "e g b3",
    "unnamed 14",
    "ar year",
    "quarter",
    "unique id",
    "department grouped",
    "mpa rag grouped",
    "joiner",
    "project length",
    "gov wlc",
    "non gov wlc",
    "the ipa annual report publishes the whole life cycle costs on projects "
    "based on figures from their business cases whilst the national "
    "infrastructure and construction pipeline focuses primarily on the upfront "
    "capital investment on a project where both documents refer to the same "
    "projects this distinction will be the principal reason for any differences "
    "in the data sets published other government publications may use different "
    "methodologies to derive cost figures",
    "the whole life cost figures are based on q2 2014 15 projections and "
    "represent the department s best assessment of future expenditure at that "
    "time they are based on a combination of commercial intelligence and decc s "
    "modelling outputs drawing on decc s projections of generation mix "
    "electricity demand and fossil fuel and carbon prices published in autumn "
    "2014 uncertainties over the future evolution of key variables used by decc "
    "as modelling input assumptions for these projections must be taken into "
    "account when interpreting these figures",
}


def map_header(norm_header: str) -> str | None:
    """Canonical column for a normalised header, or None if unmapped."""
    if norm_header in HEADER_MAP:
        return HEADER_MAP[norm_header]
    for prefix in BUDGET_NARRATIVE_PREFIXES:
        if norm_header.startswith(prefix):
            return "budget_narrative"
    if norm_header.startswith("_unnamed") or norm_header == "":
        return None
    return None
