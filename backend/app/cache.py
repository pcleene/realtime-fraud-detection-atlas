"""
In-Memory Cache for Small Collections using aiocache.

Caches small, rarely-changing collections to eliminate redundant MongoDB queries
at high TPS. Each Gunicorn worker maintains its own copy (~7KB overhead per worker).

Cached Collections:
- holidays (~30 documents, ~5KB) - date range queries for holiday detection
- blacklist_locations (~30 documents, ~2KB) - geospatial proximity checks using haversine

Architecture:
    Worker 1: [holidays cache, blacklist cache] → TTL refresh every 10 min
    Worker 2: [holidays cache, blacklist cache] → TTL refresh every 10 min
    ...
    Worker N: [holidays cache, blacklist cache] → TTL refresh every 10 min

Memory footprint: ~7KB per worker × 129 workers = ~900KB total per EC2

Performance:
- Holidays: O(n) date range check where n=~30
- Blacklist: O(n) haversine distance calculations where n=~30
  - 30 haversine calculations: ~0.01ms (pure CPU math)
  - vs MongoDB $nearSphere: ~1-200ms (network round-trip)
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

from aiocache import Cache
from aiocache.decorators import cached
from pymongo.asynchronous.database import AsyncDatabase

from app.utils.geo import haversine_m

logger = logging.getLogger(__name__)

# Cache TTL in seconds (10 minutes)
CACHE_TTL = 600

# In-memory cache instances
_holidays_cache: Optional[List[Dict[str, Any]]] = None
_holidays_loaded_at: Optional[datetime] = None

_blacklist_cache: Optional[List[Dict[str, Any]]] = None
_blacklist_loaded_at: Optional[datetime] = None


async def load_holidays(db: AsyncDatabase) -> List[Dict[str, Any]]:
    """
    Load all holidays from MongoDB into memory.

    Args:
        db: AsyncDatabase instance

    Returns:
        List of holiday documents
    """
    global _holidays_cache, _holidays_loaded_at

    cursor = db.holidays.find({})
    holidays = await cursor.to_list(length=1000)  # Max 1000 holidays

    _holidays_cache = holidays
    _holidays_loaded_at = datetime.utcnow()

    logger.info(f"Loaded {len(holidays)} holidays into cache")
    return holidays


async def get_holidays(db: AsyncDatabase) -> List[Dict[str, Any]]:
    """
    Get holidays from cache, loading if needed.

    Uses simple TTL-based expiration. Cache is refreshed:
    - On first access
    - When TTL expires (10 minutes)
    - When explicitly invalidated

    Args:
        db: AsyncDatabase instance

    Returns:
        List of holiday documents from cache
    """
    global _holidays_cache, _holidays_loaded_at

    # Check if cache needs refresh
    if _holidays_cache is None or _holidays_loaded_at is None:
        return await load_holidays(db)

    # Check TTL expiration
    elapsed = (datetime.utcnow() - _holidays_loaded_at).total_seconds()
    if elapsed > CACHE_TTL:
        logger.info(f"Holiday cache expired after {elapsed:.0f}s, refreshing...")
        return await load_holidays(db)

    return _holidays_cache


def check_holiday_in_cache(txn_date: datetime, holidays: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Check if a transaction date falls within any cached holiday.

    Performs in-memory date range check instead of MongoDB query.

    Args:
        txn_date: Transaction date (normalized to start of day)
        holidays: List of holiday documents from cache

    Returns:
        Matching holiday document, or None if no match
    """
    for holiday in holidays:
        date_range = holiday.get("date_range", {})
        start = date_range.get("start")
        end = date_range.get("end")

        if start and end:
            # Handle both datetime objects and strings
            if isinstance(start, str):
                start = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if isinstance(end, str):
                end = datetime.fromisoformat(end.replace("Z", "+00:00"))

            # Normalize to naive datetime for comparison
            if start.tzinfo:
                start = start.replace(tzinfo=None)
            if end.tzinfo:
                end = end.replace(tzinfo=None)
            if txn_date.tzinfo:
                txn_date = txn_date.replace(tzinfo=None)

            if start <= txn_date <= end:
                return holiday

    return None


# =============================================================================
# Blacklist Cache Functions
# =============================================================================


async def load_blacklist(db: AsyncDatabase) -> List[Dict[str, Any]]:
    """
    Load all blacklist locations from MongoDB into memory.

    Args:
        db: AsyncDatabase instance

    Returns:
        List of blacklist location documents
    """
    global _blacklist_cache, _blacklist_loaded_at

    cursor = db.blacklist_locations.find({})
    blacklist = await cursor.to_list(length=1000)  # Max 1000 locations

    _blacklist_cache = blacklist
    _blacklist_loaded_at = datetime.utcnow()

    logger.info(f"Loaded {len(blacklist)} blacklist locations into cache")
    return blacklist


async def get_blacklist(db: AsyncDatabase) -> List[Dict[str, Any]]:
    """
    Get blacklist locations from cache, loading if needed.

    Uses simple TTL-based expiration. Cache is refreshed:
    - On first access
    - When TTL expires (10 minutes)
    - When explicitly invalidated

    Args:
        db: AsyncDatabase instance

    Returns:
        List of blacklist location documents from cache
    """
    global _blacklist_cache, _blacklist_loaded_at

    # Check if cache needs refresh
    if _blacklist_cache is None or _blacklist_loaded_at is None:
        return await load_blacklist(db)

    # Check TTL expiration
    elapsed = (datetime.utcnow() - _blacklist_loaded_at).total_seconds()
    if elapsed > CACHE_TTL:
        logger.info(f"Blacklist cache expired after {elapsed:.0f}s, refreshing...")
        return await load_blacklist(db)

    return _blacklist_cache


def check_blacklist_proximity_in_cache(
    lon: float,
    lat: float,
    blacklist: List[Dict[str, Any]],
    radius_meters: float,
) -> Optional[Dict[str, Any]]:
    """
    Check if a transaction location is near any cached blacklist location.

    Uses haversine formula for distance calculation instead of MongoDB $nearSphere.
    O(n) where n is typically ~30 blacklist locations.

    Args:
        lon: Transaction longitude
        lat: Transaction latitude
        blacklist: List of blacklist location documents from cache
        radius_meters: Maximum distance in meters to consider "nearby"

    Returns:
        First matching blacklist location within radius, or None if no match
    """
    for location in blacklist:
        loc = location.get("location", {})
        coords = loc.get("coordinates", [])

        if len(coords) >= 2:
            bl_lon, bl_lat = coords[0], coords[1]
            distance_m = haversine_m(lon, lat, bl_lon, bl_lat)

            if distance_m <= radius_meters:
                return location

    return None


# =============================================================================
# Cache Management Functions
# =============================================================================


async def warmup_cache(db: AsyncDatabase) -> Dict[str, int]:
    """
    Pre-warm all caches on application startup.

    Called during FastAPI lifespan startup to ensure caches are ready
    before serving requests.

    Args:
        db: AsyncDatabase instance

    Returns:
        Dict with cache statistics
    """
    holidays = await load_holidays(db)
    blacklist = await load_blacklist(db)

    return {
        "holidays_count": len(holidays),
        "blacklist_count": len(blacklist),
        "cache_ttl_seconds": CACHE_TTL,
    }


def invalidate_cache() -> None:
    """
    Invalidate all caches.

    Called when cached data is updated. Next access will reload from MongoDB.
    """
    global _holidays_cache, _holidays_loaded_at
    global _blacklist_cache, _blacklist_loaded_at

    _holidays_cache = None
    _holidays_loaded_at = None
    _blacklist_cache = None
    _blacklist_loaded_at = None
    logger.info("All caches invalidated")


def get_cache_stats() -> Dict[str, Any]:
    """
    Get current cache statistics.

    Returns:
        Dict with cache stats for all caches
    """
    global _holidays_cache, _holidays_loaded_at
    global _blacklist_cache, _blacklist_loaded_at

    stats = {"holidays": {}, "blacklist": {}}

    # Holiday stats
    if _holidays_cache is None or _holidays_loaded_at is None:
        stats["holidays"] = {
            "loaded": False,
            "count": 0,
            "age_seconds": None,
            "ttl_remaining_seconds": None,
        }
    else:
        age = (datetime.utcnow() - _holidays_loaded_at).total_seconds()
        ttl_remaining = max(0, CACHE_TTL - age)
        stats["holidays"] = {
            "loaded": True,
            "count": len(_holidays_cache),
            "age_seconds": round(age, 1),
            "ttl_remaining_seconds": round(ttl_remaining, 1),
        }

    # Blacklist stats
    if _blacklist_cache is None or _blacklist_loaded_at is None:
        stats["blacklist"] = {
            "loaded": False,
            "count": 0,
            "age_seconds": None,
            "ttl_remaining_seconds": None,
        }
    else:
        age = (datetime.utcnow() - _blacklist_loaded_at).total_seconds()
        ttl_remaining = max(0, CACHE_TTL - age)
        stats["blacklist"] = {
            "loaded": True,
            "count": len(_blacklist_cache),
            "age_seconds": round(age, 1),
            "ttl_remaining_seconds": round(ttl_remaining, 1),
        }

    return stats
