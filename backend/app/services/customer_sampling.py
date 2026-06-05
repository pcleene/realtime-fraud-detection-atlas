"""
Customer Sampling Service for Load Testing.

Provides two sampling strategies for selecting customers:

1. **Chunk-based sampling (default)**: Samples customers proportionally from each
   MongoDB chunk, ensuring even shard distribution during load tests. This prevents
   hot-sharding when all test traffic hits a single shard.

2. **Random sampling (fallback)**: Uses MongoDB's $sample aggregation. Simple but
   can concentrate on one shard, causing write contention.

Both strategies support caching:
- Cache TTL-based expiration (default 1 hour)
- Fixed sampling between tests (same customers until cache expires/invalidated)
- Force refresh via API param

Usage:
    # Get 10,000 customers with chunk-based sampling (default)
    customers = await get_sampled_customers(db, size=10000)

    # Force random sampling
    customers = await get_sampled_customers(db, size=10000, method="random")

    # Force cache refresh
    customers = await get_sampled_customers(db, size=10000, force_refresh=True)
"""

import logging
import random
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

from bson import MinKey, MaxKey
from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Cache TTL in seconds (1 hour - long enough for test consistency)
CUSTOMER_CACHE_TTL = 3600

# Sampling method type
SamplingMethod = Literal["chunk_based", "random"]


# =============================================================================
# Cache Storage
# =============================================================================

_customer_cache: Dict[str, Any] = {
    "customers": None,           # List of sampled customers
    "loaded_at": None,          # When cache was loaded
    "method": None,             # Method used ("chunk_based" or "random")
    "size": None,               # Number of customers cached
    "chunk_distribution": None, # Chunk distribution info (for debugging)
}


# =============================================================================
# Chunk-Based Sampling
# =============================================================================

async def get_chunk_boundaries(db: AsyncDatabase) -> List[Dict[str, Any]]:
    """
    Get chunk boundaries for the customers collection from config.chunks.

    Works with MongoDB 5.0+ UUID-based chunk format.

    Returns:
        List of chunk documents with min/max bounds
    """
    try:
        # Get the config database (requires admin access or Atlas M10+)
        config_db = db.client.get_database("config")

        # MongoDB 5.0+ uses UUID-based chunks instead of namespace
        # First, get the collection UUID from config.collections
        namespace = f"{db.name}.customers"
        coll_doc = await config_db.collections.find_one({"_id": namespace})

        if coll_doc and "uuid" in coll_doc:
            # Query chunks by UUID (MongoDB 5.0+ format)
            collection_uuid = coll_doc["uuid"]
            cursor = config_db.chunks.find(
                {"uuid": collection_uuid},
                {"min": 1, "max": 1, "shard": 1}
            ).sort("min", 1)
            chunks = await cursor.to_list(length=1000)
            logger.info(f"Found {len(chunks)} chunks for {namespace} (UUID-based)")
        else:
            # Fallback to namespace-based query (MongoDB <5.0)
            cursor = config_db.chunks.find(
                {"ns": namespace},
                {"min": 1, "max": 1, "shard": 1}
            ).sort("min", 1)
            chunks = await cursor.to_list(length=1000)
            logger.info(f"Found {len(chunks)} chunks for {namespace} (ns-based)")

        return chunks

    except Exception as e:
        logger.warning(f"Failed to get chunk boundaries: {e}")
        return []


async def sample_from_chunk(
    db: AsyncDatabase,
    min_key: Any,
    max_key: Any,
    sample_size: int,
) -> List[Dict[str, str]]:
    """
    Sample customers from a specific chunk range.

    Uses range query + $sample for efficiency.

    Args:
        db: Database instance
        min_key: Chunk minimum key value (customer_id)
        max_key: Chunk maximum key value (customer_id)
        sample_size: Number of customers to sample from this chunk

    Returns:
        List of customer dicts with customer_id and account_id
    """
    try:
        # Build range query
        query: Dict[str, Any] = {}

        def is_min_key(val: Any) -> bool:
            """Check if value is MongoDB MinKey (start of range)."""
            return isinstance(val, MinKey) or str(val).startswith("MinKey")

        def is_max_key(val: Any) -> bool:
            """Check if value is MongoDB MaxKey (end of range)."""
            return isinstance(val, MaxKey) or str(val).startswith("MaxKey")

        def extract_key_value(key_obj: Any) -> Optional[str]:
            """Extract the actual key value from chunk boundary."""
            if key_obj is None or is_min_key(key_obj) or is_max_key(key_obj):
                return None
            if isinstance(key_obj, dict) and "customer_id" in key_obj:
                return key_obj["customer_id"]
            if isinstance(key_obj, str):
                return key_obj
            return None

        # Handle min boundary
        min_val = extract_key_value(min_key)
        if min_val is not None:
            query["customer_id"] = {"$gte": min_val}

        # Handle max boundary
        max_val = extract_key_value(max_key)
        if max_val is not None:
            if "customer_id" in query:
                query["customer_id"]["$lt"] = max_val
            else:
                query["customer_id"] = {"$lt": max_val}

        # Sample from the range
        pipeline = [
            {"$match": query} if query else {"$match": {}},
            {"$sample": {"size": sample_size}},
            {"$project": {"customer_id": 1, "account_ids": 1}},
        ]

        # Skip empty $match if no query
        if not query:
            pipeline = pipeline[1:]

        cursor = await db.customers.aggregate(pipeline)
        docs = await cursor.to_list(length=sample_size)

        customers = []
        for doc in docs:
            account_ids = doc.get("account_ids", [])
            customers.append({
                "customer_id": doc["customer_id"],
                "account_id": account_ids[0] if account_ids else "ACC-00000000",
            })

        return customers

    except Exception as e:
        logger.warning(f"Failed to sample from chunk [{min_key} -> {max_key}]: {e}")
        return []


async def get_customers_chunk_based(
    db: AsyncDatabase,
    size: int,
) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """
    Sample customers proportionally from each chunk.

    Ensures even distribution across shards by sampling proportionally
    from each chunk based on the total requested size.

    Args:
        db: Database instance
        size: Total number of customers to sample

    Returns:
        Tuple of (customer list, chunk distribution info)
    """
    chunks = await get_chunk_boundaries(db)

    if not chunks:
        logger.warning("No chunks found, falling back to random sampling")
        customers = await get_customers_random(db, size)
        return customers, {"method": "random_fallback", "reason": "no_chunks"}

    # Calculate samples per chunk (proportional distribution)
    num_chunks = len(chunks)
    base_per_chunk = size // num_chunks
    remainder = size % num_chunks

    logger.info(
        f"Chunk-based sampling: {size} customers from {num_chunks} chunks "
        f"(~{base_per_chunk} per chunk)"
    )

    # Sample from each chunk
    all_customers: List[Dict[str, str]] = []
    chunk_info = []

    for i, chunk in enumerate(chunks):
        # Give extra to first chunks to handle remainder
        chunk_size = base_per_chunk + (1 if i < remainder else 0)

        if chunk_size == 0:
            continue

        min_key = chunk.get("min", {}).get("customer_id")
        max_key = chunk.get("max", {}).get("customer_id")
        shard = chunk.get("shard", "unknown")

        customers = await sample_from_chunk(db, min_key, max_key, chunk_size)
        all_customers.extend(customers)

        chunk_info.append({
            "shard": shard,
            "min": str(min_key)[:20] if min_key else "MinKey",
            "max": str(max_key)[:20] if max_key else "MaxKey",
            "requested": chunk_size,
            "sampled": len(customers),
        })

        logger.debug(
            f"  Chunk {i+1}/{num_chunks} ({shard}): "
            f"sampled {len(customers)}/{chunk_size} customers"
        )

    # Shuffle to randomize order (otherwise sorted by chunk)
    random.shuffle(all_customers)

    distribution = {
        "method": "chunk_based",
        "num_chunks": num_chunks,
        "chunks": chunk_info,
        "total_sampled": len(all_customers),
    }

    logger.info(
        f"Chunk-based sampling complete: {len(all_customers)} customers "
        f"from {num_chunks} chunks"
    )

    return all_customers, distribution


# =============================================================================
# Random Sampling (Fallback)
# =============================================================================

async def get_customers_random(
    db: AsyncDatabase,
    size: int,
) -> List[Dict[str, str]]:
    """
    Sample customers randomly using MongoDB $sample.

    Simple but can concentrate on one shard.

    Args:
        db: Database instance
        size: Number of customers to sample

    Returns:
        List of customer dicts with customer_id and account_id
    """
    cursor = await db.customers.aggregate([
        {"$sample": {"size": size}},
        {"$project": {"customer_id": 1, "account_ids": 1}}
    ])
    docs = await cursor.to_list(length=size)

    customers = []
    for doc in docs:
        account_ids = doc.get("account_ids", [])
        customers.append({
            "customer_id": doc["customer_id"],
            "account_id": account_ids[0] if account_ids else "ACC-00000000",
        })

    logger.info(f"Random sampling complete: {len(customers)} customers")
    return customers


# =============================================================================
# Main API with Caching
# =============================================================================

async def get_sampled_customers(
    db: AsyncDatabase,
    size: int = 10000,
    method: SamplingMethod = "chunk_based",
    force_refresh: bool = False,
) -> List[Dict[str, str]]:
    """
    Get sampled customers for load testing with caching.

    Customers are cached to ensure the same set is used across test runs.
    Cache is TTL-based (1 hour default) and can be force-refreshed.

    Args:
        db: Database instance
        size: Number of customers to sample
        method: Sampling method ("chunk_based" or "random")
        force_refresh: Force cache refresh regardless of TTL

    Returns:
        List of customer dicts with customer_id and account_id
    """
    global _customer_cache

    # Check if cache is valid
    if not force_refresh and _customer_cache["customers"] is not None:
        cache_age = (datetime.utcnow() - _customer_cache["loaded_at"]).total_seconds()

        # Cache hit if: not expired AND same size AND same method
        if (
            cache_age < CUSTOMER_CACHE_TTL
            and _customer_cache["size"] == size
            and _customer_cache["method"] == method
        ):
            logger.info(
                f"Using cached customers: {len(_customer_cache['customers'])} "
                f"(age: {cache_age:.0f}s, method: {_customer_cache['method']})"
            )
            return _customer_cache["customers"]

        # Log why we're refreshing
        reasons = []
        if cache_age >= CUSTOMER_CACHE_TTL:
            reasons.append(f"expired ({cache_age:.0f}s > {CUSTOMER_CACHE_TTL}s)")
        if _customer_cache["size"] != size:
            reasons.append(f"size mismatch ({_customer_cache['size']} != {size})")
        if _customer_cache["method"] != method:
            reasons.append(f"method mismatch ({_customer_cache['method']} != {method})")
        logger.info(f"Cache invalid: {', '.join(reasons)}")

    # Load customers based on method
    distribution = None
    if method == "chunk_based":
        customers, distribution = await get_customers_chunk_based(db, size)
        # Fall back to random if chunk-based fails to get enough customers
        if len(customers) < size * 0.8:  # Less than 80% of requested
            logger.warning(
                f"Chunk-based only got {len(customers)}/{size}, "
                f"supplementing with random sampling"
            )
            additional = await get_customers_random(db, size - len(customers))
            customers.extend(additional)
            if distribution:
                distribution["supplemented_with_random"] = len(additional)
    else:
        customers = await get_customers_random(db, size)
        distribution = {"method": "random"}

    # Update cache
    _customer_cache = {
        "customers": customers,
        "loaded_at": datetime.utcnow(),
        "method": method,
        "size": size,
        "chunk_distribution": distribution,
    }

    logger.info(
        f"Cached {len(customers)} customers (method: {method}, "
        f"TTL: {CUSTOMER_CACHE_TTL}s)"
    )

    return customers


def get_customer_cache_stats() -> Dict[str, Any]:
    """
    Get current customer cache statistics.

    Returns:
        Dict with cache stats
    """
    global _customer_cache

    if _customer_cache["customers"] is None:
        return {
            "loaded": False,
            "count": 0,
            "method": None,
            "age_seconds": None,
            "ttl_remaining_seconds": None,
            "chunk_distribution": None,
        }

    age = (datetime.utcnow() - _customer_cache["loaded_at"]).total_seconds()
    ttl_remaining = max(0, CUSTOMER_CACHE_TTL - age)

    return {
        "loaded": True,
        "count": _customer_cache["size"],
        "method": _customer_cache["method"],
        "age_seconds": round(age, 1),
        "ttl_remaining_seconds": round(ttl_remaining, 1),
        "chunk_distribution": _customer_cache["chunk_distribution"],
    }


def invalidate_customer_cache() -> None:
    """
    Invalidate the customer cache.

    Next call to get_sampled_customers will re-sample.
    """
    global _customer_cache
    _customer_cache = {
        "customers": None,
        "loaded_at": None,
        "method": None,
        "size": None,
        "chunk_distribution": None,
    }
    logger.info("Customer cache invalidated")
