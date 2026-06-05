"""
Health check endpoints using PyMongo Async API.

Provides:
- /health: Basic health check (database, sharding, indexes)
- /health/detailed: Extended health check with pool stats and cache info
"""

import logging

from fastapi import APIRouter

from app.db import get_db, get_pool_stats
from app.cache import get_cache_stats
from app.config import get_settings
from app.indexes import verify_sharding, INDEX_DEFINITIONS
from app.models.requests import (
    HealthResponse,
    DetailedHealthResponse,
    CollectionStatus,
    ShardingStatus,
    PoolStats,
    CacheStats,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.

    Returns database connection status, sharding configuration,
    collection status, and index verification.
    """
    try:
        db = await get_db()

        # Check database connection (async)
        await db.command("ping")
        database_status = "connected"

        # Check sharding
        sharding_info = await verify_sharding(db)
        sharding_status = ShardingStatus(
            enabled=sharding_info["enabled"],
            shards=sharding_info["shards"],
        )

        # Check collections (async)
        existing_collections = set(await db.list_collection_names())
        expected_collections = [
            "customers",
            "transactions",
            "blacklist_locations",
            "holidays",
            "rules",
        ]

        collections = {}
        for col_name in expected_collections:
            exists = col_name in existing_collections
            sharded = sharding_info.get("collections", {}).get(col_name, False)
            collections[col_name] = CollectionStatus(
                exists=exists,
                sharded=sharded,
            )

        # Verify indexes (async)
        indexes_status = "verified"
        for collection_name, indexes in INDEX_DEFINITIONS.items():
            if collection_name not in existing_collections:
                continue
            collection = db[collection_name]
            existing_indexes = await collection.index_information()

            for index in indexes:
                index_name = index["options"]["name"]
                if index_name not in existing_indexes:
                    indexes_status = "missing"
                    logger.warning(
                        f"Missing index {index_name} on {collection_name}"
                    )
                    break

            if indexes_status == "missing":
                break

        return HealthResponse(
            status="healthy",
            database=database_status,
            sharding=sharding_status,
            collections=collections,
            indexes=indexes_status,
        )

    except Exception as e:
        logger.exception(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            database="disconnected",
            sharding=ShardingStatus(enabled=False, shards=0),
            collections={},
            indexes="missing",
        )


@router.get("/health/detailed", response_model=DetailedHealthResponse)
async def detailed_health_check() -> DetailedHealthResponse:
    """
    Detailed health check with connection pool stats and cache info.

    Returns all standard health info plus:
    - MongoDB connection pool statistics (topology, nodes, pool size, compression)
    - In-memory cache statistics (holidays, blacklist counts and TTL)

    Useful for monitoring and debugging production performance.
    """
    try:
        db = await get_db()
        settings = get_settings()

        # Check database connection (async)
        await db.command("ping")
        database_status = "connected"

        # Check sharding
        sharding_info = await verify_sharding(db)
        sharding_status = ShardingStatus(
            enabled=sharding_info["enabled"],
            shards=sharding_info["shards"],
        )

        # Check collections (async)
        existing_collections = set(await db.list_collection_names())
        expected_collections = [
            "customers",
            "transactions",
            "blacklist_locations",
            "holidays",
            "rules",
        ]

        collections = {}
        for col_name in expected_collections:
            exists = col_name in existing_collections
            sharded = sharding_info.get("collections", {}).get(col_name, False)
            collections[col_name] = CollectionStatus(
                exists=exists,
                sharded=sharded,
            )

        # Verify indexes (async)
        indexes_status = "verified"
        for collection_name, indexes in INDEX_DEFINITIONS.items():
            if collection_name not in existing_collections:
                continue
            collection = db[collection_name]
            existing_indexes = await collection.index_information()

            for index in indexes:
                index_name = index["options"]["name"]
                if index_name not in existing_indexes:
                    indexes_status = "missing"
                    logger.warning(
                        f"Missing index {index_name} on {collection_name}"
                    )
                    break

            if indexes_status == "missing":
                break

        # Get connection pool stats
        pool_stats_data = await get_pool_stats()
        pool_stats = None
        if pool_stats_data:
            pool_stats = PoolStats(
                topology_type=pool_stats_data["topology_type"],
                nodes=pool_stats_data["nodes"],
                max_pool_size=pool_stats_data["max_pool_size"],
                min_pool_size=pool_stats_data["min_pool_size"],
                max_idle_time_ms=pool_stats_data["max_idle_time_ms"],
                wait_queue_timeout_ms=pool_stats_data["wait_queue_timeout_ms"],
                compression=pool_stats_data["compression"],
                read_preference=pool_stats_data["read_preference"],
                retry_writes=pool_stats_data["retry_writes"],
            )

        # Get cache stats
        cache_stats_data = get_cache_stats()
        cache_stats = CacheStats(
            holidays_cached=cache_stats_data["holidays"].get("count", 0),
            blacklist_cached=cache_stats_data["blacklist"].get("count", 0),
            cache_ttl_seconds=settings.cache_ttl_seconds if hasattr(settings, 'cache_ttl_seconds') else 600,
        )

        return DetailedHealthResponse(
            status="healthy",
            database=database_status,
            sharding=sharding_status,
            collections=collections,
            indexes=indexes_status,
            pool_stats=pool_stats,
            cache_stats=cache_stats,
        )

    except Exception as e:
        logger.exception(f"Detailed health check failed: {e}")
        return DetailedHealthResponse(
            status="unhealthy",
            database="disconnected",
            sharding=ShardingStatus(enabled=False, shards=0),
            collections={},
            indexes="missing",
            pool_stats=None,
            cache_stats=None,
        )
