"""V2 health check endpoints with cache stats."""

import logging

from fastapi import APIRouter

from app.db import get_db, get_pool_stats
from app.cache import get_cache_stats
from app.indexes import verify_sharding, INDEX_DEFINITIONS
from app.models.requests import (
    HealthResponse, DetailedHealthResponse, CollectionStatus,
    ShardingStatus, PoolStats, CacheStats, ErrorResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()

EXPECTED_COLLECTIONS = [
    "customers", "transactions",
    "pot_bf", "pot_bf24", "pot_sm", "pot_anj", "pot_pp", "pot_cb",
    "pot_sl_va", "pot_nb_overflow", "load_tests",
]


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    try:
        db = await get_db()
        await db.command("ping")

        sharding_info = await verify_sharding(db)
        sharding_status = ShardingStatus(
            enabled=sharding_info["enabled"], shards=sharding_info["shards"]
        )

        existing_collections = set(await db.list_collection_names())
        collections = {}
        for col_name in EXPECTED_COLLECTIONS:
            exists = col_name in existing_collections
            sharded = sharding_info.get("collections", {}).get(col_name, False)
            collections[col_name] = CollectionStatus(exists=exists, sharded=sharded)

        indexes_status = "verified"
        for collection_name, indexes in INDEX_DEFINITIONS.items():
            if collection_name not in existing_collections:
                continue
            existing_indexes = await db[collection_name].index_information()
            for index in indexes:
                if index["options"]["name"] not in existing_indexes:
                    indexes_status = "missing"
                    break
            if indexes_status == "missing":
                break

        return HealthResponse(
            status="healthy", database="connected",
            sharding=sharding_status, collections=collections,
            indexes=indexes_status,
        )
    except Exception as e:
        logger.exception(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy", database="disconnected",
            sharding=ShardingStatus(enabled=False, shards=0),
            collections={}, indexes="missing",
        )


@router.get("/health/detailed", response_model=DetailedHealthResponse)
async def detailed_health_check() -> DetailedHealthResponse:
    try:
        db = await get_db()
        await db.command("ping")

        sharding_info = await verify_sharding(db)
        sharding_status = ShardingStatus(
            enabled=sharding_info["enabled"], shards=sharding_info["shards"]
        )

        existing_collections = set(await db.list_collection_names())
        collections = {}
        for col_name in EXPECTED_COLLECTIONS:
            exists = col_name in existing_collections
            sharded = sharding_info.get("collections", {}).get(col_name, False)
            collections[col_name] = CollectionStatus(exists=exists, sharded=sharded)

        pool_stats_data = await get_pool_stats()
        pool_stats = None
        if pool_stats_data:
            pool_stats = PoolStats(**{
                k: pool_stats_data[k] for k in PoolStats.model_fields if k in pool_stats_data
            })

        cache_data = get_cache_stats()
        bl = cache_data.get("blacklists", {})
        sc = cache_data.get("service_config", {})
        cache_stats = CacheStats(
            blacklist_entries=bl.get("total_entries", 0),
            service_config_entries=sc.get("service_limits", 0) + sc.get("avg_bounds", 0),
            cache_ttl_seconds=3600,
        )

        return DetailedHealthResponse(
            status="healthy", database="connected",
            sharding=sharding_status, collections=collections,
            indexes="verified", pool_stats=pool_stats, cache_stats=cache_stats,
        )
    except Exception as e:
        logger.exception(f"Detailed health check failed: {e}")
        return DetailedHealthResponse(
            status="unhealthy", database="disconnected",
            sharding=ShardingStatus(enabled=False, shards=0),
            collections={}, indexes="missing",
        )
