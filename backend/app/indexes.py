"""
Index and shard key management for MongoDB.

This module is the single source of truth for:
- INDEX_DEFINITIONS: All collection indexes
- SHARD_KEY_DEFINITIONS: Shard keys for sharded collections

Used by:
- app/main.py (async index creation on startup)
- seed/main.py (sync index creation during seeding)
- seed/reset_collections.py (recreation after drop)
- scripts/atlas-setup.js (manual Atlas setup - keep in sync!)
"""

import logging
from pymongo import ASCENDING, DESCENDING, GEOSPHERE
from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger(__name__)

# Shard key definitions for sharded collections
# Must match scripts/atlas-setup.js
SHARD_KEY_DEFINITIONS = {
    "customers": {"customer_id": 1},
    "transactions": {"customer_id": 1, "shard_key_month": 1, "_id": 1},
}

INDEX_DEFINITIONS = {
    "customers": [
        {
            "keys": [("customer_id", ASCENDING)],
            "options": {"unique": True, "name": "customer_id_unique"},
        },
        {
            "keys": [("features.latest_location", GEOSPHERE)],
            "options": {"name": "features_location_2dsphere", "sparse": True},
        },
    ],
    "transactions": [
        {
            "keys": [("customer_id", ASCENDING), ("timestamp", DESCENDING)],
            "options": {"name": "customer_timestamp"},
        },
        {
            "keys": [("location", GEOSPHERE)],
            "options": {"name": "location_2dsphere", "sparse": True},
        },
        {
            "keys": [
                ("timestamp", DESCENDING),
                ("fraud_score.risk_level", DESCENDING),
            ],
            "options": {"name": "timestamp_risk_level_desc"},
        },
    ],
    "blacklist_locations": [
        {
            "keys": [("city", ASCENDING), ("province", ASCENDING)],
            "options": {"name": "city_province"},
        },
        {
            "keys": [("location", GEOSPHERE)],
            "options": {"name": "location_2dsphere"},
        },
    ],
    "holidays": [
        {
            "keys": [
                ("date_range.start", ASCENDING),
                ("date_range.end", ASCENDING),
            ],
            "options": {"name": "date_range"},
        },
        {
            "keys": [("year", ASCENDING)],
            "options": {"name": "year"},
        },
    ],
    "rules": [
        {
            "keys": [("active", ASCENDING), ("type", ASCENDING)],
            "options": {"name": "active_type"},
        },
    ],
    "load_tests": [
        {
            "keys": [("test_id", ASCENDING)],
            "options": {"name": "test_id_1"},
        },
    ],
}


async def create_all_indexes(db: AsyncDatabase) -> None:
    """Create all indexes. Idempotent - safe to run multiple times."""
    for collection_name, indexes in INDEX_DEFINITIONS.items():
        collection = db[collection_name]
        for index in indexes:
            try:
                await collection.create_index(index["keys"], **index["options"])
                logger.debug(
                    f"Created index {index['options']['name']} on {collection_name}"
                )
            except Exception as e:
                logger.warning(
                    f"Index creation for {index['options']['name']} on {collection_name}: {e}"
                )


async def verify_indexes(db: AsyncDatabase) -> None:
    """Verify all expected indexes exist."""
    for collection_name, indexes in INDEX_DEFINITIONS.items():
        collection = db[collection_name]
        existing = await collection.index_information()

        for index in indexes:
            index_name = index["options"]["name"]
            if index_name not in existing:
                logger.warning(f"Missing index {index_name} on {collection_name}")


async def verify_sharding(db: AsyncDatabase) -> dict:
    """Verify sharding configuration."""
    try:
        # Check if sharding is enabled
        config_db = db.client.config
        databases = await config_db.databases.find({"_id": db.name}).to_list()

        if not databases:
            return {"enabled": False, "shards": 0, "collections": {}}

        is_sharded = databases[0].get("partitioned", False)

        # Get shard count
        shards = await config_db.shards.find().to_list()
        shard_count = len(shards)

        # Check sharded collections
        sharded_collections = {}
        collections = await config_db.collections.find(
            {"_id": {"$regex": f"^{db.name}\\."}}
        ).to_list()
        for col in collections:
            col_name = col["_id"].split(".")[-1]
            sharded_collections[col_name] = True

        return {
            "enabled": is_sharded or len(sharded_collections) > 0,
            "shards": shard_count,
            "collections": sharded_collections,
        }
    except Exception as e:
        logger.debug(f"Sharding check failed (may not be a sharded cluster): {e}")
        return {"enabled": False, "shards": 0, "collections": {}}
