"""Small synthetic Prozorro documents, shaped like the real ones.

The shapes here were copied from documents fetched on 2026-09-16 (tender
6fffbf33eb8d4c908ce7578be33e15a6 and the 80-tender probe): a single-lot tender
that still prices through `lotValues[]`, a single-lot tender that uses a bare
`bid.value`, and a two-lot tender where one bidder bids on both lots.
"""

from __future__ import annotations


def org(edrpou: str, name: str, region: str = "Київська область") -> dict:
    return {
        "name": name,
        "identifier": {"scheme": "UA-EDR", "id": edrpou, "legalName": name},
        "address": {"region": region, "countryName": "Україна"},
    }


def single_lot_tender() -> dict:
    """One lot, three bids priced through lotValues, lowest bid wins."""
    lot = "L1"
    return {
        "id": "T1",
        "tenderID": "UA-2021-03-04-000001-a",
        "procurementMethodType": "aboveThreshold",
        "status": "complete",
        "mainProcurementCategory": "services",
        "procuringEntity": dict(org("40081221", "Buyer One"), kind="general"),
        "value": {"amount": 100000.0, "currency": "UAH", "valueAddedTaxIncluded": False},
        "tenderPeriod": {"startDate": "2021-03-04T09:00:00+02:00"},
        "awardPeriod": {"endDate": "2021-03-20T12:00:00+02:00"},
        "lots": [
            {
                "id": lot,
                "status": "complete",
                "value": {"amount": 100000.0, "currency": "UAH", "valueAddedTaxIncluded": False},
            }
        ],
        "items": [{"relatedLot": lot, "classification": {"scheme": "ДК021", "id": "45233000-9"}}],
        "bids": [
            {
                "id": "B1",
                "status": "active",
                "date": "2021-03-08T10:00:00+02:00",
                "tenderers": [org("111", "Alpha")],
                "lotValues": [
                    {
                        "relatedLot": lot,
                        "status": "active",
                        "value": {"amount": 80000.0, "valueAddedTaxIncluded": False},
                    }
                ],
            },
            {
                "id": "B2",
                "status": "active",
                "date": "2021-03-08T11:00:00+02:00",
                "tenderers": [org("222", "Beta")],
                "lotValues": [
                    {
                        "relatedLot": lot,
                        "status": "active",
                        "value": {"amount": 90000.0, "valueAddedTaxIncluded": False},
                    }
                ],
            },
            {
                "id": "B3",
                "status": "deleted",
                "date": "2021-03-08T12:00:00+02:00",
                "tenderers": [org("333", "Gamma")],
                "lotValues": [
                    {
                        "relatedLot": lot,
                        "status": "deleted",
                        "value": {"amount": 70000.0, "valueAddedTaxIncluded": False},
                    }
                ],
            },
        ],
        "awards": [
            {
                "id": "A1",
                "status": "active",
                "lotID": lot,
                "bid_id": "B1",
                "date": "2021-03-20T12:00:00+02:00",
                "value": {"amount": 80000.0},
                "suppliers": [org("111", "Alpha")],
            }
        ],
        "contracts": [
            {
                "id": "C1",
                "awardID": "A1",
                "contractID": "UA-2021-03-04-000001-a-b1",
                "status": "active",
                "dateSigned": "2021-03-25T00:00:00+02:00",
                "period": {"startDate": "2021-03-25T00:00:00+02:00",
                           "endDate": "2021-12-31T00:00:00+02:00"},
                "value": {"amount": 80000.0, "currency": "UAH", "valueAddedTaxIncluded": False},
                "suppliers": [org("111", "Alpha")],
            }
        ],
    }


def bare_value_tender() -> dict:
    """No `lots` key at all; bids price through `bid.value`; second bid wins."""
    return {
        "id": "T2",
        "tenderID": "UA-2019-07-01-000002-b",
        "procurementMethodType": "aboveThresholdUA",
        "status": "complete",
        "mainProcurementCategory": "goods",
        "procuringEntity": dict(org("40081221", "Buyer One"), kind="general"),
        "value": {"amount": 50000.0, "currency": "UAH", "valueAddedTaxIncluded": True},
        "tenderPeriod": {"startDate": "2019-07-01T09:00:00+03:00"},
        "awardPeriod": {"endDate": "2019-07-15T12:00:00+03:00"},
        "items": [{"classification": {"scheme": "ДК021", "id": "09123000-7"}}],
        "bids": [
            {
                "id": "B10",
                "status": "active",
                "date": "2019-07-05T10:00:00+03:00",
                "tenderers": [org("111", "Alpha")],
                "value": {"amount": 40000.0, "valueAddedTaxIncluded": True},
            },
            {
                "id": "B11",
                "status": "active",
                "date": "2019-07-05T11:00:00+03:00",
                "tenderers": [org("222", "Beta")],
                "value": {"amount": 45000.0, "valueAddedTaxIncluded": True},
            },
        ],
        "awards": [
            {
                "id": "A10",
                "status": "unsuccessful",
                "bid_id": "B10",
                "date": "2019-07-12T12:00:00+03:00",
                "suppliers": [org("111", "Alpha")],
            },
            {
                "id": "A11",
                "status": "active",
                "bid_id": "B11",
                "date": "2019-07-15T12:00:00+03:00",
                "value": {"amount": 45000.0},
                "suppliers": [org("222", "Beta")],
            },
        ],
        "contracts": [
            {
                "id": "C10",
                "awardID": "A11",
                "status": "active",
                "dateSigned": "2019-07-20T00:00:00+03:00",
                "period": {"startDate": "2019-07-20T00:00:00+03:00",
                           "endDate": "2019-12-31T00:00:00+02:00"},
                "value": {"amount": 45000.0, "currency": "UAH", "valueAddedTaxIncluded": True},
                "suppliers": [org("222", "Beta")],
            }
        ],
    }


def multi_lot_tender() -> dict:
    """Two lots; Alpha bids on both and wins one; Beta wins the other."""
    return {
        "id": "T3",
        "tenderID": "UA-2022-05-10-000003-c",
        "procurementMethodType": "aboveThresholdEU",
        "status": "complete",
        "mainProcurementCategory": "works",
        "procuringEntity": dict(org("99999", "Buyer Two", "Львівська область"), kind="special"),
        "value": {"amount": 300000.0, "currency": "UAH", "valueAddedTaxIncluded": False},
        "tenderPeriod": {"startDate": "2022-05-10T09:00:00+03:00"},
        "awardPeriod": {"endDate": "2022-06-01T12:00:00+03:00"},
        "lots": [
            {"id": "LA", "status": "complete",
             "value": {"amount": 200000.0, "valueAddedTaxIncluded": False}},
            {"id": "LB", "status": "complete",
             "value": {"amount": 100000.0, "valueAddedTaxIncluded": False}},
        ],
        "items": [
            {"relatedLot": "LA", "classification": {"scheme": "ДК021", "id": "45000000-7"}},
            {"relatedLot": "LB", "classification": {"scheme": "ДК021", "id": "33600000-6"}},
        ],
        "bids": [
            {
                "id": "B20",
                "status": "active",
                "date": "2022-05-15T10:00:00+03:00",
                "tenderers": [org("111", "Alpha")],
                "lotValues": [
                    {"relatedLot": "LA", "status": "active",
                     "value": {"amount": 150000.0, "valueAddedTaxIncluded": False}},
                    {"relatedLot": "LB", "status": "active",
                     "value": {"amount": 95000.0, "valueAddedTaxIncluded": False}},
                ],
            },
            {
                "id": "B21",
                "status": "active",
                "date": "2022-05-15T11:00:00+03:00",
                "tenderers": [org("222", "Beta")],
                "lotValues": [
                    {"relatedLot": "LA", "status": "active",
                     "value": {"amount": 180000.0, "valueAddedTaxIncluded": False}},
                    {"relatedLot": "LB", "status": "active",
                     "value": {"amount": 90000.0, "valueAddedTaxIncluded": False}},
                ],
            },
        ],
        "awards": [
            {"id": "A20", "status": "active", "lotID": "LA", "bid_id": "B20",
             "date": "2022-06-01T12:00:00+03:00", "value": {"amount": 150000.0},
             "suppliers": [org("111", "Alpha")]},
            {"id": "A21", "status": "active", "lotID": "LB", "bid_id": "B21",
             "date": "2022-06-01T12:00:00+03:00", "value": {"amount": 90000.0},
             "suppliers": [org("222", "Beta")]},
        ],
        "contracts": [
            {"id": "C20", "awardID": "A20", "status": "active",
             "dateSigned": "2022-06-10T00:00:00+03:00",
             "period": {"startDate": "2022-06-10T00:00:00+03:00",
                        "endDate": "2022-12-31T00:00:00+02:00"},
             "value": {"amount": 150000.0, "valueAddedTaxIncluded": False},
             "suppliers": [org("111", "Alpha")]},
            {"id": "C21", "awardID": "A21", "status": "active",
             "dateSigned": "2022-06-10T00:00:00+03:00",
             "period": {"startDate": "2022-06-10T00:00:00+03:00",
                        "endDate": "2022-12-31T00:00:00+02:00"},
             "value": {"amount": 90000.0, "valueAddedTaxIncluded": False},
             "suppliers": [org("222", "Beta")]},
        ],
    }


def registry(contract_id: str, tender_id: str, **kw) -> dict:
    """A registry contract document with the real key names."""
    doc = {
        "id": contract_id,
        "_tender_id": tender_id,
        "status": kw.get("status", "terminated"),
        "dateSigned": kw.get("dateSigned", "2021-03-25T00:00:00+02:00"),
        "dateModified": kw.get("dateModified", "2022-04-01T00:00:00+03:00"),
        "period": kw.get("period", {"startDate": "2021-03-25T00:00:00+02:00",
                                    "endDate": "2021-12-31T00:00:00+02:00"}),
        "value": kw.get("value", {"amount": 80000.0, "valueAddedTaxIncluded": False}),
        "changes": kw.get("changes", []),
        # Always returned by the API as a static vocabulary, never as evidence.
        "contractChangeRationaleTypes": {
            k: {"title_en": k}
            for k in [
                "durationExtension", "fiscalYearExtension", "itemPriceVariation",
                "priceReduction", "qualityImprovement", "taxRate", "thirdParty",
                "volumeCuts", "priceClarification",
            ]
        },
        "suppliers": [org("111", "Alpha")],
    }
    if "amountPaid" in kw:
        doc["amountPaid"] = kw["amountPaid"]
    return doc


def change(date: str, *rationales: str, status: str = "active") -> dict:
    return {
        "id": f"ch-{date}",
        "status": status,
        "date": date,
        "dateSigned": date,
        "rationaleTypes": list(rationales),
        "rationale": "synthetic",
    }
