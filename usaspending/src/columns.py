"""Column subset kept from the USAspending contract archive CSVs.

Names are the USAspending download column names. They are sent verbatim as the
`columns` list in the bulk-download request, so the server does the projection.

Verified two ways on 2026-09-15: against the header of
FY2010_All_Contracts_Full_20260906.zip from the independent monthly archive, and
against the parquet schema of all 17 delivered fiscal years. All 44 are present
in every year. The check is `usaspending/src/schema_check.py`, it is the `schema`
target of the Makefile, and it writes
usaspending/results/column_mapping.json.
"""

KEEP = [
    "contract_award_unique_key",
    "award_id_piid",
    "parent_award_id_piid",
    "modification_number",
    "transaction_number",
    "action_date",
    "action_type_code",
    "action_type",
    "award_type_code",
    "award_type",
    "federal_action_obligation",
    "total_dollars_obligated",
    "base_and_exercised_options_value",
    "current_total_value_of_award",
    "base_and_all_options_value",
    "potential_total_value_of_award",
    "period_of_performance_start_date",
    "period_of_performance_current_end_date",
    "period_of_performance_potential_end_date",
    "awarding_agency_code",
    "awarding_agency_name",
    "awarding_sub_agency_code",
    "awarding_office_code",
    "funding_agency_code",
    "recipient_uei",
    "recipient_duns",
    "recipient_name",
    "recipient_parent_uei",
    "contracting_officers_determination_of_business_size_code",
    "type_of_contract_pricing_code",
    "naics_code",
    "product_or_service_code",
    "extent_competed_code",
    "solicitation_procedures_code",
    "number_of_offers_received",
    "type_of_set_aside_code",
    "solicitation_identifier",
    "fed_biz_opps_code",
    "performance_based_service_acquisition_code",
    "multi_year_contract_code",
    "cost_or_pricing_data_code",
    "primary_place_of_performance_state_code",
    "prime_award_transaction_place_of_performance_state_fips_code",
    "last_modified_date",
]

NUMERIC = [
    "federal_action_obligation",
    "total_dollars_obligated",
    "base_and_exercised_options_value",
    "current_total_value_of_award",
    "base_and_all_options_value",
    "potential_total_value_of_award",
    "number_of_offers_received",
]

DATES = [
    "action_date",
    "period_of_performance_start_date",
    "period_of_performance_current_end_date",
    "period_of_performance_potential_end_date",
    "last_modified_date",
]
