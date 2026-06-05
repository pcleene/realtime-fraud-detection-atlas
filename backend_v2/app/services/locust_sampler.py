"""
V2 Locust Load Test Sampler -- Transaction sampling for Locust-driven traffic.

Uses a rolling 1000-sample window with pre-computed percentiles.
Each sample update atomically pushes the new latency, slices to 1000,
and recomputes P50/P95/P99 via a pipeline update with $sortArray.
The read path just grabs the stored values — no client-side sorting.
"""

import logging
import random
import time
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 2.0
SAMPLE_RATE = 500  # 1-in-500 at 50K TPS = 100 MongoDB updates/sec (safe for load_tests collection)
MAX_RECENT_TRANSACTIONS = 50
MAX_LATENCY_SAMPLES = 1000

_active_test_cache: Dict[str, Any] = {"test_id": None, "timestamp": 0.0}


async def get_active_locust_test(db) -> Optional[str]:
    global _active_test_cache
    now = time.time()
    if now - _active_test_cache["timestamp"] < CACHE_TTL_SECONDS:
        return _active_test_cache["test_id"]

    try:
        test = await db.load_tests.find_one({"source": "locust", "status": "running"}, {"test_id": 1})
        _active_test_cache["test_id"] = test["test_id"] if test else None
        _active_test_cache["timestamp"] = now
        return _active_test_cache["test_id"]
    except Exception as e:
        logger.warning(f"[SAMPLER] Error checking active test: {e}")
        return None


def clear_cache():
    global _active_test_cache
    _active_test_cache = {"test_id": None, "timestamp": 0.0}


def should_sample() -> bool:
    return random.randint(1, SAMPLE_RATE) == 1


async def sample_transaction(
    db, test_id, customer_id, amount, channel, risk_level,
    latency_ms, scoring_ms=0.0, persist_ms=0.0,
) -> None:
    try:
        sample = {
            "customer_id": customer_id, "amount": amount,
            "channel": channel, "risk_level": risk_level,
            "latency_ms": round(latency_ms, 2),
            "scoring_ms": round(scoring_ms, 2),
            "persist_ms": round(persist_ms, 2),
            "timestamp": datetime.utcnow().isoformat(),
        }
        latency_ms = round(latency_ms, 2)
        scoring_ms = round(scoring_ms, 2)
        persist_ms = round(persist_ms, 2)

        # Pipeline update: push sample, recompute percentiles atomically.
        # Stage 1: increment counters, push to arrays, update min/max.
        # Stage 2: sort samples and compute P50/P95/P99.
        await db.load_tests.update_one(
            {"test_id": test_id, "status": "running"},
            [
                # Stage 1: accumulate
                {"$set": {
                    "total_transactions": {"$add": ["$total_transactions", 1]},
                    "successful": {"$add": ["$successful", 1]},
                    f"risk_distribution.{risk_level}": {
                        "$add": [{"$ifNull": [f"$risk_distribution.{risk_level}", 0]}, 1]
                    },
                    "latency_stats.sum": {"$add": ["$latency_stats.sum", latency_ms]},
                    "latency_stats.count": {"$add": ["$latency_stats.count", 1]},
                    "latency_stats.scoring_sum": {"$add": ["$latency_stats.scoring_sum", scoring_ms]},
                    "latency_stats.persist_sum": {"$add": ["$latency_stats.persist_sum", persist_ms]},
                    "latency_stats.min": {
                        "$min": [{"$ifNull": ["$latency_stats.min", latency_ms]}, latency_ms]
                    },
                    "latency_stats.max": {
                        "$max": [{"$ifNull": ["$latency_stats.max", latency_ms]}, latency_ms]
                    },
                    "latency_stats.samples": {
                        "$slice": [
                            {"$concatArrays": [
                                {"$ifNull": ["$latency_stats.samples", []]},
                                [latency_ms],
                            ]},
                            -MAX_LATENCY_SAMPLES,
                        ]
                    },
                    "recent_transactions": {
                        "$slice": [
                            {"$concatArrays": [
                                {"$ifNull": ["$recent_transactions", []]},
                                [sample],
                            ]},
                            -MAX_RECENT_TRANSACTIONS,
                        ]
                    },
                }},
                # Stage 2: sort samples and compute rolling percentiles
                {"$set": {
                    "latency_stats.computed": {
                        "$let": {
                            "vars": {
                                "sorted": {"$sortArray": {
                                    "input": "$latency_stats.samples",
                                    "sortBy": 1,
                                }},
                                "cnt": {"$size": "$latency_stats.samples"},
                            },
                            "in": {
                                "avg": {"$avg": "$latency_stats.samples"},
                                "p50": {"$arrayElemAt": [
                                    "$$sorted",
                                    {"$min": [
                                        {"$subtract": ["$$cnt", 1]},
                                        {"$floor": {"$multiply": [0.5, "$$cnt"]}},
                                    ]},
                                ]},
                                "p95": {"$arrayElemAt": [
                                    "$$sorted",
                                    {"$min": [
                                        {"$subtract": ["$$cnt", 1]},
                                        {"$floor": {"$multiply": [0.95, "$$cnt"]}},
                                    ]},
                                ]},
                                "p99": {"$arrayElemAt": [
                                    "$$sorted",
                                    {"$min": [
                                        {"$subtract": ["$$cnt", 1]},
                                        {"$floor": {"$multiply": [0.99, "$$cnt"]}},
                                    ]},
                                ]},
                            },
                        }
                    }
                }},
            ],
        )
    except Exception as e:
        logger.warning(f"[SAMPLER] Error recording sample: {e}")


async def maybe_sample_transaction(
    db, customer_id, amount, channel, risk_level,
    latency_ms, scoring_ms=0.0, persist_ms=0.0,
) -> None:
    test_id = await get_active_locust_test(db)
    if not test_id:
        return
    if not should_sample():
        return
    await sample_transaction(
        db, test_id, customer_id, amount, channel, risk_level,
        latency_ms, scoring_ms, persist_ms,
    )
