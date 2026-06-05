"""
Phase 1: Customer read operations.

Two strategies:
  - find_one: standard/pipeline modes — plain document fetch with projection.
  - aggregate: aggregation mode — fetch + compute at6 ($stdDevPop) and
    window_reset ($dateDiff) server-side in one round trip.
"""

from datetime import datetime
from typing import Optional

from pymongo.asynchronous.database import AsyncDatabase

# Projection for customer find_one — only fetch fields needed for scoring
CUSTOMER_PROJECTION = {
    "_id": 0,
    "customer_id": 1,
    "e1": 1, "f1": 1, "y": 1,
    "flags": 1,
    "av1": 1, "av2": 1,
    "service_ever": 1,
    "b24_count": 1, "b24_list": 1,
    "pot_master_id_dp": 1,
    "rolling": 1,
}


async def find_customer(
    db: AsyncDatabase,
    customer_id: str,
) -> Optional[dict]:
    """Standard/pipeline mode: plain find_one with projection."""
    return await db.customers.find_one(
        {"customer_id": customer_id},
        CUSTOMER_PROJECTION,
    )


async def aggregate_customer_read(
    db: AsyncDatabase,
    customer_id: str,
    request_at3: float,
    request_z1: datetime,
    recent_amounts_limit: int,
    cumulative_window_hours: float,
) -> Optional[dict]:
    """
    Aggregation mode: read customer + compute at6 and window_reset server-side.

    Returns a customer document with extra fields:
    - '_computed_at6': population std dev of the simulated post-append at3_recent
    - '_window_reset': boolean — whether the cumulative window has expired

    All derived computations happen here in the read phase (shared lock), so the
    subsequent write in Phase 3 uses plain $set/$push/$inc with pre-computed
    values, minimizing the exclusive write lock window.

    PERFORMANCE NOTE: Aggregation mode uses 2 DB round trips (aggregate read +
    standard update_one) vs pipeline mode's single update_one. At high TPS
    (10K+) with large customer pools (35M+), pipeline mode shows better tail
    latency because:
      - 1 round trip = 1x chance of network jitter (vs 2x for aggregation)
      - Half the connection pool pressure
      - Atomic read-modify-write with no staleness gap

    Aggregation mode's advantage — shorter exclusive lock window — only
    materializes under significant same-customer contention, which is rare
    at scale (~0.03% at 10K TPS / 35M customers). Prefer pipeline mode as
    the default; reserve aggregation mode for workloads with genuinely high
    same-customer contention (small customer pools or hot-account patterns).
    """
    pipeline = [
        {"$match": {"customer_id": customer_id}},

        # Simulate the post-append at3_recent array
        {"$set": {
            "_new_recent": {
                "$slice": [
                    {"$concatArrays": [
                        {"$ifNull": ["$rolling.at3_recent", []]},
                        [request_at3]
                    ]},
                    -recent_amounts_limit
                ]
            }
        }},

        # Compute at6 (population std dev) + window reset — all server-side
        {"$set": {
            "_computed_at6": {"$stdDevPop": "$_new_recent"},

            "_window_reset": {
                "$cond": {
                    "if": {"$eq": [{"$ifNull": ["$rolling.window_start", None]}, None]},
                    "then": True,
                    "else": {
                        "$gt": [
                            {"$dateDiff": {
                                "startDate": "$rolling.window_start",
                                "endDate": request_z1,
                                "unit": "second",
                            }},
                            cumulative_window_hours * 3600
                        ]
                    }
                }
            },
        }},

        {"$project": {
            **CUSTOMER_PROJECTION,
            "_computed_at6": 1,
            "_window_reset": 1,
        }},
    ]

    cursor = await db.customers.aggregate(pipeline)
    try:
        return await cursor.next()
    except StopAsyncIteration:
        return None
