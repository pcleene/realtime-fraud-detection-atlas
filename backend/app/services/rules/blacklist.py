"""
Blacklist Proximity Rule - detects transactions near known fraud hotspots.

Two modes available (toggle USE_CACHE):
1. Cache mode (default): In-memory haversine calculations - fastest at high TPS
2. MongoDB mode: $nearSphere with 2dsphere index - useful for debugging/single instance

Cache is pre-warmed on startup and refreshed every 10 minutes.
"""

import time
from typing import Optional, Tuple

from pymongo.asynchronous.database import AsyncDatabase

from app.config import get_settings
from app.models.transaction import RuleAnalysis
from app.cache import get_blacklist, check_blacklist_proximity_in_cache

# Toggle between cache mode and direct MongoDB query
# Set to False to use original MongoDB $nearSphere query (useful for debugging)
USE_CACHE = True


async def check_blacklist_proximity(
    db: AsyncDatabase,
    lon: Optional[float],
    lat: Optional[float],
) -> Tuple[RuleAnalysis, float]:
    """
    Blacklist proximity check - detects transactions near known fraud hotspots.

    Uses in-memory cache with haversine by default (USE_CACHE=True).
    Set USE_CACHE=False to use MongoDB $nearSphere with 2dsphere index.

    Args:
        db: AsyncDatabase instance
        lon: Transaction longitude
        lat: Transaction latitude

    Returns:
        Tuple of (RuleAnalysis, elapsed_ms)
    """
    settings = get_settings()
    radius_meters = settings.blacklist_radius_meters

    t0 = time.perf_counter()

    if lon is None or lat is None:
        return RuleAnalysis(
            rule="blacklist_proximity",
            score=0,
            triggered=False,
            details={
                "category": None,
                "nearby": False,
                "threshold_m": radius_meters,
            },
        ), 0.0

    if USE_CACHE:
        # === CACHE MODE (default) ===
        # Get blacklist locations from cache (loads from DB if not cached)
        blacklist = await get_blacklist(db)
        # Check proximity in-memory using haversine (no MongoDB query)
        nearby = check_blacklist_proximity_in_cache(lon, lat, blacklist, radius_meters)
    else:
        # === MONGODB MODE (original) ===
        # Query for nearby blacklist location using $nearSphere with 2dsphere index
        # Requires index: db.blacklist_locations.createIndex({"location": "2dsphere"})
        nearby = await db.blacklist_locations.find_one({
            "location": {
                "$nearSphere": {
                    "$geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "$maxDistance": radius_meters,
                }
            }
        })

    elapsed_ms = (time.perf_counter() - t0) * 1000

    if nearby:
        category = nearby["category"]
        weight = settings.blacklist_weights.get(category, 10)

        return RuleAnalysis(
            rule="blacklist_proximity",
            score=weight,
            triggered=True,
            details={
                "category": category,
                "nearby": True,
                "threshold_m": radius_meters,
            },
        ), elapsed_ms

    return RuleAnalysis(
        rule="blacklist_proximity",
        score=0,
        triggered=False,
        details={
            "category": None,
            "nearby": False,
            "threshold_m": radius_meters,
        },
    ), elapsed_ms
