"""V2 Mock data endpoints for load testing."""

import asyncio
import logging
import random
import secrets
from datetime import datetime

from fastapi import APIRouter, Query, Depends

from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mock", tags=["mock"])

SERVICE_CODES = [5, 12, 16, 17, 30, 31, 32, 33, 34, 35, 36, 37, 38, 46]
SERVICE_NAMES = ["Y", "X", "N", "A", "B", "C", "D", "E"]
PURPOSE_CODES = [0, 300, 55555]
DESTINATION_BANKS = ["BRI", "BTN", "RegionalBank", "Bank BCA", "BNI", "CIMB"]


@router.get("/customers")
async def get_customers(
    limit: int = Query(100000, ge=1, le=500000),
    db=Depends(get_db),
):
    """Get random customer sample for load testing.

    Uses $sample for random selection. Returns customer_id,
    b1 (source account), and up to 5 beneficiaries from b24_list.

    For even shard distribution, callers should make multiple
    smaller requests (e.g. 5x20K) rather than one large one.
    """
    pipeline = [
        {"$sample": {"size": limit}},
        {"$project": {
            "_id": 0,
            "customer_id": 1,
            "rolling.b1": 1,
            "b24_list": 1,
        }},
    ]
    cursor = await db.customers.aggregate(pipeline)
    customers = await cursor.to_list(length=limit)
    return {
        "customers": [
            {
                "customer_id": doc["customer_id"],
                "b1": doc.get("rolling", {}).get("b1"),
                "b24_sample": (doc.get("b24_list") or [])[:5],
            }
            for doc in customers
        ],
        "count": len(customers),
    }


@router.get("/blacklist-sample")
async def get_blacklist_sample(db=Depends(get_db)):
    """Get a sample of real blacklist values for realistic load testing.

    Returns small samples from each pot_* collection so Locust can
    generate transactions that actually hit blacklist rules.
    Loaded once at Locust startup -- not called during the test.
    """

    async def _sample(collection_name: str, field: str, size: int) -> list:
        """Get random sample from a collection using $sample."""
        cursor = await db[collection_name].aggregate([
            {"$sample": {"size": size}},
            {"$project": {"_id": 0, field: 1}},
        ])
        docs = await cursor.to_list(length=size)
        return [doc[field] for doc in docs if field in doc]

    overflow_cursor = await db.pot_nb_overflow.aggregate([
        {"$sample": {"size": 200}},
        {"$project": {"_id": 0, "customer_id": 1, "b2": 1}},
    ])
    overflow_docs = await overflow_cursor.to_list(length=200)
    overflow_pairs = [
        {"customer_id": d["customer_id"], "b2": d["b2"]}
        for d in overflow_docs
        if "customer_id" in d and "b2" in d
    ]

    return {
        "pot_bf": await _sample("pot_bf", "b23", 1000),
        "pot_anj": await _sample("pot_anj", "b23", 500),
        "pot_cb": await _sample("pot_cb", "b23", 500),
        "pot_sm": await _sample("pot_sm", "n3", 200),
        "overflow_pairs": overflow_pairs,
    }


@router.get("/transaction")
async def generate_mock_transaction():
    """Generate a mock V2 transaction payload."""
    return {
        "customer_id": f"CUST-{secrets.token_hex(6).upper()}",
        "b1": f"{random.randint(1000000000, 9999999999)}",
        "b2": f"{random.randint(1000000000, 9999999999)}",
        "c2": f"BENEFICIARY-{secrets.token_hex(4).upper()}",
        "d2": random.choice(DESTINATION_BANKS),
        "n2": f"Merchant-{secrets.token_hex(3).upper()}",
        "at3": random.randint(10000, 5000000),
        "tp": random.choice(PURPOSE_CODES),
        "at7": random.choice([0, 1000, 2500]),
        "service": random.choice(SERVICE_CODES),
        "service_name": random.choice(SERVICE_NAMES),
        "z1": datetime.utcnow().isoformat() + "Z",
        "h1": random.choice(["samsung SM-A546B", "OPPO CPH2565", "Xiaomi 2209116AG"]),
        "is_financial": 1,
        "channel": random.choice(["Livin", "KOPRA", "ATM", "QRIS"]),
    }
