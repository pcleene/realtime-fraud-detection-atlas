"""
Database connection module using PyMongo Async API.

Uses AsyncMongoClient for native async I/O without thread pools.

Optimized for high throughput (10K+ TPS) with:
- Connection pooling tuned for 129 workers per EC2
- Compression to reduce network transfer
- Read preference for lowest latency
- Retry logic for resilience
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

# =============================================================================
# Optimized Connection Settings for High Throughput
# =============================================================================
#
# Pool sizing notes for production (129 workers × 2 EC2s = 258 workers):
# - maxPoolSize=10 per worker = 2,580 theoretical max connections
# - MongoDB Atlas M30 supports 1,500 connections
# - In practice, connection reuse means actual connections << theoretical max
# - Monitor Atlas connection metrics and adjust if needed
#
# For local testing with single uvicorn worker, these settings are conservative
# but won't cause issues.
# =============================================================================

CLIENT_OPTIONS: Dict[str, Any] = {
    # Connection Pool - tuned for 10K+ TPS
    # At 180ms/txn with 10K TPS = 1,800 concurrent connections needed
    # 258 workers × 15 pool = 3,870 max (M30 supports 1,500; upgrade to M50 for 3,000)
    "maxPoolSize": 15,           # Max connections per worker (adjust based on Atlas tier)
    "minPoolSize": 3,            # Keep connections warm for burst traffic
    "maxIdleTimeMS": 45000,      # 45s idle timeout (close unused connections)
    "waitQueueTimeoutMS": 10000, # 10s wait for connection from pool

    # Timeouts
    "connectTimeoutMS": 20000,   # 20s to establish connection
    "socketTimeoutMS": 30000,    # 30s for operations
    "serverSelectionTimeoutMS": 30000,  # 30s to select server

    # Compression (reduces network transfer ~60-80%)
    # zstd > snappy > zlib in compression ratio, falls back if not available
    "compressors": ["zstd", "snappy", "zlib"],

    # Read/Write settings
    "retryWrites": True,         # Auto-retry transient write failures
    "retryReads": True,          # Auto-retry transient read failures
    "w": "majority",             # Write concern - durable writes
    "readPreference": "nearest", # Read from lowest latency node (good for PrivateLink)

    # App identification (helps with Atlas monitoring/debugging)
    "appName": "RegionalBank-fraud-api",
}


async def connect_db() -> None:
    """Connect to MongoDB using AsyncMongoClient with optimized settings."""
    global _client, _db
    settings = get_settings()

    # Log connection (mask credentials in URI for safety)
    uri_display = settings.mongodb_uri.split("@")[-1] if "@" in settings.mongodb_uri else settings.mongodb_uri
    logger.info(f"Connecting to MongoDB at {uri_display}")

    # Create client with optimized options
    _client = AsyncMongoClient(settings.mongodb_uri, **CLIENT_OPTIONS)

    # Verify connection
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
    """
    Get connection pool and topology statistics for monitoring.

    Returns:
        Dict with topology info, node count, and pool configuration
    """
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
    """
    Get database instance (synchronous) - for seeding scripts only.
    
    Note: This uses the synchronous MongoClient, not AsyncMongoClient.
    Only use this for CLI scripts that don't run in an async context.
    """
    from pymongo import MongoClient
    settings = get_settings()
    client = MongoClient(settings.mongodb_uri)
    return client[settings.db_name]
