"""
V2 Index + Shard Key Definitions — Single source of truth.

All V2 collections:
- customers (sharded)
- transactions (sharded)
- pot_bf, pot_bf24, pot_sm, pot_anj, pot_pp, pot_cb (blacklist collections, in-memory)
- pot_sl_va (service config, in-memory)
- pot_nb_overflow (beneficiary overflow for >500 entries)
- load_tests
"""

import logging
from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger(__name__)

# =============================================================================
# Shard Key Definitions (only customers + transactions are sharded)
# =============================================================================

SHARD_KEY_DEFINITIONS = {
    "customers": {"customer_id": 1},
    "transactions": {"customer_id": 1, "shard_key_month": 1, "_id": 1},
    "pot_nb_overflow": {"customer_id": 1, "b2": 1},
}

# Collections where the shard key must enforce uniqueness across all shards
SHARD_UNIQUE_KEYS = {"customers", "pot_nb_overflow"}

# =============================================================================
# Index Definitions — all V2 collections
# =============================================================================

INDEX_DEFINITIONS = {
    # customers: _id is auto-generated ObjectId. customer_id is the business key
    # and shard key (unique). The shard key index handles all hot path queries.
    "customers": [],
    "transactions": [
        {
            "keys": [("customer_id", ASCENDING), ("z1", DESCENDING)],
            "options": {"name": "customer_z1"},
        },
        {
            "keys": [("z1", DESCENDING), ("fraud_score.risk_level", DESCENDING)],
            "options": {"name": "z1_risk_level_desc"},
        },
        {
            "keys": [("fraud_score.triggered_count", ASCENDING)],
            "options": {"name": "triggered_count", "sparse": True},
        },
    ],
    # Transaction-level blacklists (small, loaded into memory — indexes for batch refresh)
    "pot_bf": [
        {
            "keys": [("b23", ASCENDING)],
            "options": {"unique": True, "name": "b23_unique"},
        },
    ],
    "pot_bf24": [
        {
            "keys": [("b23", ASCENDING)],
            "options": {"name": "b23_idx"},
        },
    ],
    "pot_sm": [
        {
            "keys": [("n3", ASCENDING)],
            "options": {"unique": True, "name": "n3_unique"},
        },
    ],
    "pot_anj": [
        {
            "keys": [("b23", ASCENDING)],
            "options": {"unique": True, "name": "b23_unique"},
        },
    ],
    "pot_pp": [
        {
            "keys": [("b23", ASCENDING)],
            "options": {"unique": True, "name": "b23_unique"},
        },
    ],
    "pot_cb": [
        {
            "keys": [("b23", ASCENDING)],
            "options": {"unique": True, "name": "b23_unique"},
        },
    ],
    # Merged service config
    "pot_sl_va": [
        {
            "keys": [("service", ASCENDING)],
            "options": {"unique": True, "name": "service_unique"},
        },
    ],
    # Overflow for high-volume beneficiary lists (>500)
    "pot_nb_overflow": [
        {
            "keys": [("customer_id", ASCENDING), ("b2", ASCENDING)],
            "options": {"unique": True, "name": "customer_b2_unique"},
        },
    ],
    # Consolidated transaction-level lookups (single-field index, no compound needed)
    "txn_lookups": [
        {
            "keys": [("lookup_value", ASCENDING)],
            "options": {"name": "idx_lookup_value"},
        },
    ],
    # Load test tracking
    "load_tests": [
        {
            "keys": [("test_id", ASCENDING)],
            "options": {"name": "test_id_1"},
        },
    ],
}


async def create_all_indexes(db: AsyncDatabase) -> None:
    """Create all V2 indexes from definitions."""
    for collection_name, indexes in INDEX_DEFINITIONS.items():
        collection = db[collection_name]
        existing = await collection.index_information()

        for index_def in indexes:
            name = index_def["options"]["name"]
            if name in existing:
                logger.debug(f"Index {name} already exists on {collection_name}")
                continue

            try:
                await collection.create_index(
                    index_def["keys"],
                    **index_def["options"],
                )
                logger.info(f"Created index {name} on {collection_name}")
            except Exception as e:
                logger.warning(f"Failed to create index {name} on {collection_name}: {e}")


async def verify_indexes(db: AsyncDatabase) -> bool:
    """Verify all required indexes exist."""
    all_ok = True
    for collection_name, indexes in INDEX_DEFINITIONS.items():
        try:
            existing = await db[collection_name].index_information()
            for index_def in indexes:
                name = index_def["options"]["name"]
                if name not in existing:
                    logger.warning(f"Missing index {name} on {collection_name}")
                    all_ok = False
        except Exception as e:
            logger.warning(f"Failed to verify indexes on {collection_name}: {e}")
            all_ok = False
    return all_ok


async def verify_sharding(db: AsyncDatabase) -> dict:
    """Verify sharding configuration for V2 collections."""
    result = {"enabled": False, "shards": 0, "collections": {}}
    try:
        config_db = db.client.get_database("config")
        databases = await config_db.databases.find_one({"_id": db.name})
        if databases and databases.get("partitioned"):
            result["enabled"] = True

        shards_cursor = config_db.shards.find({})
        shards = await shards_cursor.to_list(length=100)
        result["shards"] = len(shards)

        for coll_name in SHARD_KEY_DEFINITIONS:
            ns = f"{db.name}.{coll_name}"
            coll_doc = await config_db.collections.find_one({"_id": ns})
            result["collections"][coll_name] = coll_doc is not None
    except Exception as e:
        logger.debug(f"Sharding check failed (expected on non-sharded): {e}")
    return result
