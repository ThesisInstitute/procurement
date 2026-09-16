"""A synthetic Prozorro world with a known, planted bidder effect.

Documents are built in the same shape as the real ones so the whole chain
(parse -> labels -> features -> models -> transfer) runs over them.  Each
bidder carries a latent extension propensity, so the transfer test has a true
answer to recover, and the lot-only placebo has a true answer of zero.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from tests.fixtures import org

DIVISIONS = ["45", "33", "09", "15", "50", "30", "71", "79"]
REGIONS = ["Київська область", "Львівська область", "Одеська область", "Харківська область"]


def _iso(d: date) -> str:
    return f"{d.isoformat()}T00:00:00+02:00"


def build_world(
    n_tenders: int = 1400,
    n_bidders: int = 70,
    n_buyers: int = 40,
    seed: int = 11,
    bidder_effect: float = 0.45,
) -> tuple[list[dict], list[dict]]:
    """Return (tender documents, registry contract documents)."""
    rng = random.Random(seed)
    bidders = [
        {
            "edrpou": f"{30000000 + i}",
            "name": f"Bidder {i}",
            # Latent propensity, the thing the transfer test must recover.
            "theta": rng.betavariate(2, 5),
        }
        for i in range(n_bidders)
    ]
    buyers = [
        {"edrpou": f"{40000000 + i}", "name": f"Buyer {i}", "region": rng.choice(REGIONS)}
        for i in range(n_buyers)
    ]
    div_effect = {d: rng.uniform(-0.12, 0.12) for d in DIVISIONS}

    tenders: list[dict] = []
    registries: list[dict] = []
    start = date(2019, 1, 1)
    span = (date(2022, 12, 31) - start).days
    for k in range(n_tenders):
        tstart = start + timedelta(days=rng.randint(0, span))
        buyer = rng.choice(buyers)
        n_lots = 1 if rng.random() < 0.75 else 2
        tid = f"T{k}"
        human = f"UA-{tstart.isoformat()}-{k:06d}-a"
        lots, items, bids, awards, contracts = [], [], [], [], []
        tender_total = 0.0
        for li in range(n_lots):
            lot_id = f"{tid}L{li}"
            expected = round(rng.lognormvariate(12.5, 1.1), 2)
            tender_total += expected
            division = rng.choice(DIVISIONS)
            lots.append(
                {
                    "id": lot_id,
                    "status": "complete",
                    "value": {"amount": expected, "currency": "UAH",
                              "valueAddedTaxIncluded": False},
                }
            )
            items.append(
                {"relatedLot": lot_id,
                 "classification": {"scheme": "ДК021", "id": f"{division}100000-0"}}
            )
            n_bid = rng.choice([2, 2, 3, 3, 4, 5])
            pool = rng.sample(bidders, n_bid)
            priced = []
            for j, b in enumerate(pool):
                disc = rng.uniform(0.01, 0.40)
                amount = round(expected * (1 - disc), 2)
                bid_id = f"{lot_id}B{j}"
                priced.append((bid_id, b, amount))
                existing = next((x for x in bids if x["id"] == bid_id), None)
                entry = {
                    "relatedLot": lot_id,
                    "status": "active",
                    "value": {"amount": amount, "valueAddedTaxIncluded": False},
                }
                if existing:
                    existing["lotValues"].append(entry)
                else:
                    bids.append(
                        {
                            "id": bid_id,
                            "status": "active",
                            "date": _iso(tstart + timedelta(days=4)),
                            "tenderers": [org(b["edrpou"], b["name"])],
                            "lotValues": [entry],
                        }
                    )
            priced.sort(key=lambda x: x[2])
            disqualified = rng.random() < 0.12 and len(priced) >= 2
            if disqualified:
                awards.append(
                    {
                        "id": f"{lot_id}Ax",
                        "status": "unsuccessful",
                        "lotID": lot_id,
                        "bid_id": priced[0][0],
                        "date": _iso(tstart + timedelta(days=14)),
                        "suppliers": [org(priced[0][1]["edrpou"], priced[0][1]["name"])],
                    }
                )
                win_bid, win_b, win_amt = priced[1]
            else:
                win_bid, win_b, win_amt = priced[0]
            award_id = f"{lot_id}A"
            awards.append(
                {
                    "id": award_id,
                    "status": "active",
                    "lotID": lot_id,
                    "bid_id": win_bid,
                    "date": _iso(tstart + timedelta(days=16)),
                    "value": {"amount": win_amt},
                    "suppliers": [org(win_b["edrpou"], win_b["name"])],
                }
            )
            signed = tstart + timedelta(days=20)
            end = signed + timedelta(days=300)
            cid = f"{lot_id}C"
            contracts.append(
                {
                    "id": cid,
                    "awardID": award_id,
                    "status": "active",
                    "dateSigned": _iso(signed),
                    "period": {"startDate": _iso(signed), "endDate": _iso(end)},
                    "value": {"amount": win_amt, "currency": "UAH",
                              "valueAddedTaxIncluded": False},
                    "suppliers": [org(win_b["edrpou"], win_b["name"])],
                }
            )
            p_ext = min(
                0.95,
                max(0.02, 0.18 + bidder_effect * (win_b["theta"] - 0.28) + div_effect[division]),
            )
            extended = rng.random() < p_ext
            changes = []
            reg_end = end
            if extended:
                change_date = signed + timedelta(days=250)
                changes.append(
                    {
                        "id": f"{cid}ch",
                        "status": "active",
                        "date": _iso(change_date),
                        "dateSigned": _iso(change_date),
                        "rationaleTypes": ["durationExtension"],
                    }
                )
                reg_end = end + timedelta(days=rng.choice([60, 120, 200, 365]))
            registries.append(
                {
                    "id": cid,
                    "_tender_id": tid,
                    "status": "terminated",
                    "dateSigned": _iso(signed),
                    "dateModified": _iso(reg_end + timedelta(days=30)),
                    "period": {"startDate": _iso(signed), "endDate": _iso(reg_end)},
                    "value": {"amount": round(win_amt * rng.uniform(0.92, 1.25), 2),
                              "valueAddedTaxIncluded": False},
                    "amountPaid": {"amount": round(win_amt * rng.uniform(0.6, 1.0), 2),
                                   "valueAddedTaxIncluded": False},
                    "changes": changes,
                    "suppliers": [org(win_b["edrpou"], win_b["name"])],
                }
            )
        tenders.append(
            {
                "id": tid,
                "tenderID": human,
                "procurementMethodType": rng.choice(
                    ["aboveThreshold", "aboveThresholdUA", "aboveThresholdEU"]
                ),
                "status": "complete",
                "mainProcurementCategory": rng.choice(["goods", "services", "works"]),
                "procuringEntity": dict(
                    org(buyer["edrpou"], buyer["name"], buyer["region"]), kind="general"
                ),
                "value": {"amount": round(tender_total, 2), "currency": "UAH",
                          "valueAddedTaxIncluded": False},
                "tenderPeriod": {"startDate": _iso(tstart)},
                "awardPeriod": {"endDate": _iso(tstart + timedelta(days=16))},
                "lots": lots,
                "items": items,
                "bids": bids,
                "awards": awards,
                "contracts": contracts,
            }
        )
    return tenders, registries
