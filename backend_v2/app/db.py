"""
Database connection module using PyMongo Async API.

Uses AsyncMongoClient for native async I/O without thread pools.
Identical to V1 connection config (proven at 19.5K TPS), with V2 app name.
"""

import logging
from typing import Any, Dict, Optional

from pymongo import AsyncMongoClient, ReadPreference
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import ConnectionFailure

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: Optional[AsyncMongoClient] = None
_db: Optional[AsyncDatabase] = None

CLIENT_OPTIONS: Dict[str, Any] = {
    "maxPoolSize": 10,                  # 10 × 129 workers × 8 EC2 = 10,320 (within Atlas 18K limit)
    "minPoolSize": 3,
    "maxIdleTimeMS": 45000,
    "waitQueueTimeoutMS": 2000,         # Fail fast — don't queue 10s at 50K TPS
    "connectTimeoutMS": 5000,           # PrivateLink connects in <1s
    "socketTimeoutMS": 5000,            # No op should take >5s at 50ms SLA
    "serverSelectionTimeoutMS": 5000,   # Fail fast if topology is broken
    "compressors": ["zstd", "snappy", "zlib"],
    "retryWrites": True,
    "retryReads": True,
    "w": "majority",
    "readPreference": "nearest",
    "appName": "RegionalBank-fraud-v2-api",
}


async def connect_db() -> None:
    """Connect to MongoDB using AsyncMongoClient with optimized settings."""
    global _client, _db
    settings = get_settings()

    uri_display = settings.mongodb_uri.split("@")[-1] if "@" in settings.mongodb_uri else settings.mongodb_uri
    logger.info(f"Connecting to MongoDB at {uri_display}")

    _client = AsyncMongoClient(settings.mongodb_uri, **CLIENT_OPTIONS)

    try:
        await _client.admin.command("ping")
        logger.info(
            f"MongoDB connected: maxPoolSize={CLIENT_OPTIONS['maxPoolSize']}, "
            f"compression={CLIENT_OPTIONS['compressors'][0]}, "
            f"readPreference={CLIENT_OPTIONS['readPreference']}"
        )
    except ConnectionFailure as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise

    _db = _client[settings.db_name]


async def close_db() -> None:
    """Close MongoDB connection."""
    global _client, _db
    if _client:
        await _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed")


async def get_db() -> AsyncDatabase:
    """Get async database instance."""
    if _db is None:
        await connect_db()
    return _db


def get_client() -> Optional[AsyncMongoClient]:
    """Get the MongoDB client instance (for monitoring/stats)."""
    return _client


async def get_pool_stats() -> Optional[Dict[str, Any]]:
    """Get connection pool and topology statistics for monitoring."""
    if _client is None:
        return None
    try:
        topology = _client.topology_description
        return {
            "topology_type": topology.topology_type_name,
            "nodes": len(_client.nodes),
            "max_pool_size": CLIENT_OPTIONS["maxPoolSize"],
            "min_pool_size": CLIENT_OPTIONS["minPoolSize"],
            "max_idle_time_ms": CLIENT_OPTIONS["maxIdleTimeMS"],
            "wait_queue_timeout_ms": CLIENT_OPTIONS["waitQueueTimeoutMS"],
            "compression": CLIENT_OPTIONS["compressors"][0],
            "read_preference": CLIENT_OPTIONS["readPreference"],
            "retry_writes": CLIENT_OPTIONS["retryWrites"],
        }
    except Exception as e:
        logger.warning(f"Failed to get pool stats: {e}")
        return None


def get_db_sync():
    """Get database instance (synchronous) - for seeding scripts only."""
    from pymongo import MongoClient
    settings = get_settings()
    client = MongoClient(settings.mongodb_uri)
    return client[settings.db_name]
