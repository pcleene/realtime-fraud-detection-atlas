"""
Holiday Rule - flags transactions during holidays (higher fraud risk periods).

Two modes available (toggle USE_CACHE):
1. Cache mode (default): In-memory cache with TTL refresh - fastest at high TPS
2. MongoDB mode: Direct query with date range - useful for debugging/single instance

Cache is pre-warmed on startup and refreshed every 10 minutes.
"""

import time
from datetime import datetime
from typing import Tuple

from pymongo.asynchronous.database import AsyncDatabase

from app.config import get_settings
from app.models.transaction import RuleAnalysis
from app.cache import get_holidays, check_holiday_in_cache

# Toggle between cache mode and direct MongoDB query
# Set to False to use original MongoDB query (useful for debugging)
USE_CACHE = True


async def check_holiday(
    db: AsyncDatabase,
    timestamp: datetime,
) -> Tuple[RuleAnalysis, float]:
    """
    Holiday check - flags transactions during holidays (higher fraud risk periods).

    Uses in-memory cache by default (USE_CACHE=True) for high TPS performance.
    Set USE_CACHE=False to use direct MongoDB queries.

    Args:
        db: AsyncDatabase instance
        timestamp: Transaction timestamp

    Returns:
        Tuple of (RuleAnalysis, elapsed_ms)
    """
    settings = get_settings()

    t0 = time.perf_counter()

    # Normalize to start of day for date comparison
    txn_date = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)

    if USE_CACHE:
        # === CACHE MODE (default) ===
        # Get holidays from cache (loads from DB if not cached)
        holidays = await get_holidays(db)
        # Check in-memory (no MongoDB query)
        holiday = check_holiday_in_cache(txn_date, holidays)
    else:
        # === MONGODB MODE (original) ===
        # Direct query for holiday within date range
        holiday = await db.holidays.find_one({
            "date_range.start": {"$lte": txn_date},
            "date_range.end": {"$gte": txn_date},
        })

    elapsed_ms = (time.perf_counter() - t0) * 1000

    if holiday:
        return RuleAnalysis(
            rule="holiday",
            score=settings.weight_holiday,
            triggered=True,
            details={
                "holiday_name": holiday["name"],
            },
        ), elapsed_ms

    return RuleAnalysis(
        rule="holiday",
        score=0,
        triggered=False,
        details=None,
    ), elapsed_ms