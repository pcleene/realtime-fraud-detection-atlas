"""Drop and recreate all V2 collections + indexes + sharding.

Single script that does the full cycle:
  1. Drop all V2 collections
  2. Recreate indexes (from indexes.py definitions)
  3. Enable sharding on the database
  4. Shard collections (customers, transactions, pot_nb_overflow)
  5. Verify everything

Usage:
  python -m seed.reset_collections --force          # Drop + rebuild + shard
  python -m seed.reset_collections --dry-run        # Preview only
  python -m seed.reset_collections --shard-only     # Skip drop, just shard
"""

import argparse
import logging
import sys
import time

from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

V2_COLLECTIONS = [
    "customers", "transactions",
    "pot_bf", "pot_bf24", "pot_sm", "pot_anj", "pot_pp", "pot_cb",
    "pot_sl_va", "pot_nb_overflow", "txn_lookups", "load_tests",
]


def drop_collections(db, existing):
    """Phase 1: Drop all V2 collections."""
    logger.info("=== Phase 1: Drop collections ===")
    for coll_name in V2_COLLECTIONS:
        if coll_name in existing:
            db.drop_collection(coll_name)
            logger.info(f"  Dropped: {coll_name}")
        else:
            logger.info(f"  Skipped (not found): {coll_name}")


def create_indexes(db):
    """Phase 2: Recreate all indexes from definitions."""
    from app.indexes import INDEX_DEFINITIONS

    logger.info("=== Phase 2: Create indexes ===")
    for coll_name, indexes in INDEX_DEFINITIONS.items():
        for idx_def in indexes:
            name = idx_def["options"]["name"]
            try:
                db[coll_name].create_index(idx_def["keys"], **idx_def["options"])
                logger.info(f"  Created index {name} on {coll_name}")
            except Exception as e:
                logger.warning(f"  Failed to create index {name} on {coll_name}: {e}")


def enable_and_shard(client, db_name):
    """Phase 3: Enable sharding on database + shard collections."""
    from app.indexes import SHARD_KEY_DEFINITIONS, SHARD_UNIQUE_KEYS

    logger.info("=== Phase 3: Enable sharding + shard collections ===")
    admin = client.admin

    # Enable sharding on the database
    try:
        admin.command("enableSharding", db_name)
        logger.info(f"  Database sharding enabled: {db_name}")
    except Exception as e:
        msg = str(e)
        if "already enabled" in msg or "already sharded" in msg:
            logger.info(f"  Database sharding already enabled: {db_name}")
        else:
            logger.warning(f"  Enable sharding warning: {e}")

    # Shard each collection defined in SHARD_KEY_DEFINITIONS
    for coll_name, shard_key in SHARD_KEY_DEFINITIONS.items():
        ns = f"{db_name}.{coll_name}"
        unique = coll_name in SHARD_UNIQUE_KEYS
        try:
            admin.command("shardCollection", ns, key=shard_key, unique=unique)
            unique_tag = " (unique)" if unique else ""
            logger.info(f"  Sharded {coll_name}: {shard_key}{unique_tag}")
        except Exception as e:
            msg = str(e)
            if "already sharded" in msg:
                logger.info(f"  Already sharded: {coll_name}")
            else:
                logger.warning(f"  Shard warning for {coll_name}: {e}")


def verify(client, db_name):
    """Phase 4: Verify indexes and sharding."""
    from app.indexes import INDEX_DEFINITIONS, SHARD_KEY_DEFINITIONS

    logger.info("=== Phase 4: Verify ===")
    db = client[db_name]
    config_db = client.get_database("config")
    all_ok = True

    # Check shard count
    try:
        shards = list(config_db.shards.find({}))
        logger.info(f"  Cluster shards: {len(shards)}")
    except Exception:
        logger.info("  Could not read shard count (may not have config access)")

    # Check database sharding
    try:
        db_doc = config_db.databases.find_one({"_id": db_name})
        if db_doc and db_doc.get("partitioned"):
            logger.info(f"  Database {db_name}: sharding enabled")
        else:
            logger.warning(f"  Database {db_name}: sharding NOT enabled")
            all_ok = False
    except Exception:
        logger.info("  Could not verify database sharding (non-critical)")

    # Check collection sharding
    for coll_name in SHARD_KEY_DEFINITIONS:
        ns = f"{db_name}.{coll_name}"
        try:
            coll_doc = config_db.collections.find_one({"_id": ns})
            if coll_doc:
                logger.info(f"  {coll_name}: sharded ✓")
            else:
                logger.warning(f"  {coll_name}: NOT sharded ✗")
                all_ok = False
        except Exception:
            logger.info(f"  Could not verify sharding for {coll_name}")

    # Check indexes
    for coll_name, indexes in INDEX_DEFINITIONS.items():
        try:
            existing = db[coll_name].index_information()
            for idx_def in indexes:
                name = idx_def["options"]["name"]
                if name in existing:
                    logger.info(f"  {coll_name}.{name}: exists ✓")
                else:
                    logger.warning(f"  {coll_name}.{name}: MISSING ✗")
                    all_ok = False
        except Exception as e:
            logger.warning(f"  Could not verify indexes on {coll_name}: {e}")
            all_ok = False

    if all_ok:
        logger.info("\n  All checks passed ✓")
    else:
        logger.warning("\n  Some checks failed — review warnings above")

    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Reset V2 collections + indexes + sharding")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    parser.add_argument("--shard-only", action="store_true", help="Skip drop, just enable sharding")
    parser.add_argument("--verify-only", action="store_true", help="Only verify current state")
    args = parser.parse_args()

    sys.path.insert(0, ".")
    from app.config import get_settings
    settings = get_settings()

    client = MongoClient(settings.mongodb_uri)
    db = client[settings.db_name]

    if args.verify_only:
        verify(client, settings.db_name)
        client.close()
        return

    existing = set(db.list_collection_names())

    if args.dry_run:
        from app.indexes import INDEX_DEFINITIONS, SHARD_KEY_DEFINITIONS
        print(f"\nDatabase: {settings.db_name}")
        print(f"\nCollections to drop: {[c for c in V2_COLLECTIONS if c in existing]}")
        print(f"Collections missing: {[c for c in V2_COLLECTIONS if c not in existing]}")
        print(f"\nIndexes to create: {sum(len(v) for v in INDEX_DEFINITIONS.values())} across {len(INDEX_DEFINITIONS)} collections")
        print(f"\nCollections to shard: {list(SHARD_KEY_DEFINITIONS.keys())}")
        for name, key in SHARD_KEY_DEFINITIONS.items():
            print(f"  {name}: {key}")
        client.close()
        return

    if not args.shard_only and not args.force:
        print(f"\nThis will DROP + REBUILD all V2 collections in '{settings.db_name}':")
        for c in V2_COLLECTIONS:
            status = "EXISTS" if c in existing else "not found"
            print(f"  - {c} ({status})")
        print(f"\nThen shard: customers, transactions, pot_nb_overflow")
        confirm = input("\nType 'yes' to confirm: ")
        if confirm != "yes":
            print("Aborted.")
            client.close()
            return

    start = time.time()

    if not args.shard_only:
        drop_collections(db, existing)
        create_indexes(db)

    enable_and_shard(client, settings.db_name)
    verify(client, settings.db_name)

    elapsed = time.time() - start
    logger.info(f"\nCompleted in {elapsed:.1f}s")
    client.close()


if __name__ == "__main__":
    main()
