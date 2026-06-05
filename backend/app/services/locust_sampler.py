"""
Locust Load Test Sampler

This module provides transaction sampling for Locust load tests.
When Locust drives traffic to /score-transaction, this sampler:
1. Detects if there's an active Locust test (cached with TTL)
2. Samples transactions at a configurable rate (1-in-N)
3. Updates the load_tests document with atomic MongoDB operations

The sampling is distributed-safe: multiple EC2s can sample concurrently
using atomic $inc and $push with $slice operations.
"""

import logging
import random
import time
from datetime import datetime
from typing import Optional, Dict, Any

from loadtest.common import MAX_RECENT_TRANSACTIONS, MAX_LATENCY_SAMPLES

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# How often to check MongoDB for active test (seconds)
CACHE_TTL_SECONDS = 2.0

# Sample rate: 1 in N transactions (at 10K TPS, 1-in-100 = 100 samples/sec)
SAMPLE_RATE = 100

# =============================================================================
# Cache for active Locust test
# =============================================================================

_active_test_cache: Dict[str, Any] = {
    "test_id": None,
    "timestamp": 0.0,
}


async def get_active_locust_test(db) -> Optional[str]:
    """
    Get the active Locust test ID, using a cached value if fresh.

    This minimizes MongoDB queries at high TPS. With 2-second TTL:
    - First request in window: 1 query
    - All other requests: 0 queries (use cache)
    - At 10K TPS over 2 seconds = 20K requests, only 1 query per EC2

    Returns:
        test_id if there's an active Locust test, None otherwise
    """
    global _active_test_cache

    now = time.time()
    if now - _active_test_cache["timestamp"] < CACHE_TTL_SECONDS:
        return _active_test_cache["test_id"]

    # Refresh cache from MongoDB
    try:
        test = await db.load_tests.find_one(
            {"source": "locust", "status": "running"},
            {"test_id": 1}
        )
        _active_test_cache["test_id"] = test["test_id"] if test else None
        _active_test_cache["timestamp"] = now

        if test:
            logger.debug(f"[SAMPLER] Active Locust test: {test['test_id']}")

        return _active_test_cache["test_id"]
    except Exception as e:
        logger.warning(f"[SAMPLER] Error checking for active test: {e}")
        return None


def clear_cache():
    """Clear the active test cache. Called when a test is stopped."""
    global _active_test_cache
    _active_test_cache = {"test_id": None, "timestamp": 0.0}


def should_sample() -> bool:
    """
    Determine if this transaction should be sampled.

    Returns True with probability 1/SAMPLE_RATE.
    """
    return random.randint(1, SAMPLE_RATE) == 1


# =============================================================================
# Sampling Logic
# =============================================================================

async def sample_transaction(
    db,
    test_id: str,
    customer_id: str,
    amount: float,
    channel: str,
    risk_level: str,
    latency_ms: float,
    scoring_ms: float = 0.0,
    persist_ms: float = 0.0,
) -> None:
    """
    Record a sampled transaction to the load_tests document.

    Uses atomic MongoDB operations that are safe for concurrent updates
    from multiple EC2 instances.

    Args:
        db: Database connection
        test_id: The active Locust test ID
        customer_id: Customer ID from the transaction
        amount: Transaction amount
        channel: Transaction channel
        risk_level: Computed risk level (low/medium/high)
        latency_ms: Total response time in milliseconds
        scoring_ms: Time for reads + rule evaluation (before writes)
        persist_ms: Time for customer update + transaction insert (writes)
    """
    try:
        # Prepare the transaction sample
        transaction_sample = {
            "customer_id": customer_id,
            "amount": amount,
            "channel": channel,
            "risk_level": risk_level,
            "latency_ms": round(latency_ms, 2),
            "scoring_ms": round(scoring_ms, 2),
            "persist_ms": round(persist_ms, 2),
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Atomic update with $inc for counters and $push with $slice for bounded arrays
        await db.load_tests.update_one(
            {"test_id": test_id, "status": "running"},
            {
                "$inc": {
                    "total_transactions": 1,
                    "successful": 1,
                    f"risk_distribution.{risk_level}": 1,
                    "latency_stats.sum": latency_ms,
                    "latency_stats.count": 1,
                    "latency_stats.scoring_sum": scoring_ms,
                    "latency_stats.persist_sum": persist_ms,
                },
                "$push": {
                    "recent_transactions": {
                        "$each": [transaction_sample],
                        "$slice": -MAX_RECENT_TRANSACTIONS,  # Keep last 50
                    },
                    "latency_stats.samples": {
                        "$each": [latency_ms],
                        "$slice": -MAX_LATENCY_SAMPLES,  # Keep last 1000
                    },
                },
                "$min": {"latency_stats.min": latency_ms},
                "$max": {"latency_stats.max": latency_ms},
            }
        )

        logger.debug(
            f"[SAMPLER] Recorded sample: test={test_id}, "
            f"risk={risk_level}, latency={latency_ms:.1f}ms (scoring={scoring_ms:.1f}ms, persist={persist_ms:.1f}ms)"
        )

    except Exception as e:
        # Don't fail the request if sampling fails
        logger.warning(f"[SAMPLER] Error recording sample: {e}")


async def maybe_sample_transaction(
    db,
    customer_id: str,
    amount: float,
    channel: str,
    risk_level: str,
    latency_ms: float,
    scoring_ms: float = 0.0,
    persist_ms: float = 0.0,
) -> None:
    """
    Check if there's an active Locust test and maybe sample this transaction.

    This is the main entry point called from the score endpoint.
    It's designed to be fast and non-blocking:
    - Uses cached test_id (no query if cache is fresh)
    - Random sampling (1 in SAMPLE_RATE)
    - Async MongoDB update (doesn't block response)

    Args:
        db: Database connection
        customer_id: Customer ID from the transaction
        amount: Transaction amount
        channel: Transaction channel
        risk_level: Computed risk level (low/medium/high)
        latency_ms: Total response time in milliseconds
        scoring_ms: Time for reads + rule evaluation (before writes)
        persist_ms: Time for customer update + transaction insert (writes)
    """
    # Check for active test (cached)
    test_id = await get_active_locust_test(db)
    if not test_id:
        return

    # Random sampling
    if not should_sample():
        return

    # Record the sample
    await sample_transaction(
        db=db,
        test_id=test_id,
        customer_id=customer_id,
        amount=amount,
        channel=channel,
        risk_level=risk_level,
        latency_ms=latency_ms,
        scoring_ms=scoring_ms,
        persist_ms=persist_ms,
    )
