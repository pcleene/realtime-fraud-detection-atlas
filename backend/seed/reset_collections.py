#!/usr/bin/env python3
"""
Reset collections for RegionalBank Fraud Detection POC.

Drops all data collections and recreates indexes + shard keys.
Use this before re-seeding at scale (50M+) - much faster than mass deletes.

Usage:
    # Interactive mode (prompts for confirmation)
    python -m seed.reset_collections

    # Force mode (no confirmation - use in scripts)
    python -m seed.reset_collections --force

    # Dry run (show what would be dropped)
    python -m seed.reset_collections --dry-run

WARNING: This is destructive! All data will be lost.

Note on Sharding:
    When collections are dropped, their shard configuration is also removed.
    This script will attempt to re-shard collections if the cluster supports it.
    If sharding fails (e.g., on a non-sharded cluster), indexes are still created.
"""

import argparse
import logging
import os
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.db import get_db_sync
from app.indexes import INDEX_DEFINITIONS, SHARD_KEY_DEFINITIONS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Collections to reset (order matters for foreign key-like relationships)
COLLECTIONS_TO_RESET = [
    "transactions",      # Drop first (references customers)
    "customers",
    "blacklist_locations",
    "holidays",
    "load_tests",        # Load test state
    "rules",             # Rule configurations (if any)
]


def get_collection_stats(db, collection_name: str) -> dict:
    """Get collection document count and size."""
    try:
        stats = db.command("collStats", collection_name)
        return {
            "count": stats.get("count", 0),
            "size_mb": round(stats.get("size", 0) / (1024 * 1024), 2),
            "storage_mb": round(stats.get("storageSize", 0) / (1024 * 1024), 2),
        }
    except Exception:
        return {"count": 0, "size_mb": 0, "storage_mb": 0}


def drop_collection(db, collection_name: str, dry_run: bool = False) -> bool:
    """Drop a single collection."""
    stats = get_collection_stats(db, collection_name)

    if stats["count"] == 0:
        logger.info(f"  {collection_name}: empty (skipping)")
        return True

    if dry_run:
        logger.info(f"  {collection_name}: would drop {stats['count']:,} docs ({stats['size_mb']:.1f} MB)")
        return True

    try:
        start = time.time()
        db[collection_name].drop()
        elapsed = time.time() - start
        logger.info(f"  {collection_name}: dropped {stats['count']:,} docs ({stats['size_mb']:.1f} MB) in {elapsed:.2f}s")
        return True
    except Exception as e:
        logger.error(f"  {collection_name}: failed to drop - {e}")
        return False


def create_indexes(db, dry_run: bool = False) -> int:
    """Recreate all indexes from INDEX_DEFINITIONS."""
    created = 0

    for collection_name, indexes in INDEX_DEFINITIONS.items():
        for index in indexes:
            index_name = index["options"].get("name", "unnamed")

            if dry_run:
                logger.info(f"  {collection_name}.{index_name}: would create")
                created += 1
                continue

            try:
                db[collection_name].create_index(index["keys"], **index["options"])
                logger.info(f"  {collection_name}.{index_name}: created")
                created += 1
            except Exception as e:
                logger.warning(f"  {collection_name}.{index_name}: {e}")

    return created


def setup_sharding(db, dry_run: bool = False) -> int:
    """
    Setup sharding for collections that require it.

    Note: This requires the cluster to support sharding (M30+ on Atlas)
    and the database to already have sharding enabled.
    """
    sharded = 0
    db_name = db.name

    for collection_name, shard_key in SHARD_KEY_DEFINITIONS.items():
        if dry_run:
            logger.info(f"  {collection_name}: would shard with key {shard_key}")
            sharded += 1
            continue

        try:
            # shardCollection command must be run on admin database
            result = db.client.admin.command(
                "shardCollection",
                f"{db_name}.{collection_name}",
                key=shard_key
            )
            logger.info(f"  {collection_name}: sharded with key {shard_key}")
            sharded += 1
        except Exception as e:
            error_msg = str(e)
            if "already sharded" in error_msg.lower():
                logger.info(f"  {collection_name}: already sharded")
                sharded += 1
            elif "sharding not enabled" in error_msg.lower() or "not supported" in error_msg.lower():
                logger.warning(f"  {collection_name}: sharding not available (non-sharded cluster)")
            else:
                logger.warning(f"  {collection_name}: sharding failed - {e}")

    return sharded


def check_sharding_enabled(db) -> bool:
    """Check if the database has sharding enabled."""
    try:
        # Try to get shard status
        result = db.client.admin.command("listShards")
        return len(result.get("shards", [])) > 0
    except Exception:
        return False


def reset_collections(force: bool = False, dry_run: bool = False):
    """Main reset function."""
    settings = get_settings()

    logger.info("=" * 60)
    logger.info("RegionalBank Fraud Detection - Collection Reset")
    logger.info("=" * 60)

    if dry_run:
        logger.info("MODE: Dry run (no changes will be made)")
    elif force:
        logger.info("MODE: Force (no confirmation)")
    else:
        logger.info("MODE: Interactive")

    logger.info("")

    # Connect to database
    logger.info("Connecting to MongoDB...")
    db = get_db_sync()
    logger.info(f"Database: {db.name}")

    # Check if sharding is available
    sharding_available = check_sharding_enabled(db)
    if sharding_available:
        logger.info("Cluster: Sharded (will re-shard after drop)")
    else:
        logger.info("Cluster: Non-sharded (indexes only)")
    logger.info("")

    # Show current state
    logger.info("Current collection status:")
    total_docs = 0
    total_size = 0
    for collection_name in COLLECTIONS_TO_RESET:
        stats = get_collection_stats(db, collection_name)
        total_docs += stats["count"]
        total_size += stats["size_mb"]
        if stats["count"] > 0:
            logger.info(f"  {collection_name}: {stats['count']:,} docs ({stats['size_mb']:.1f} MB)")
        else:
            logger.info(f"  {collection_name}: empty")

    logger.info(f"  TOTAL: {total_docs:,} docs ({total_size:.1f} MB)")
    logger.info("")

    if total_docs == 0:
        logger.info("All collections are empty. Nothing to reset.")
        return

    # Confirmation
    if not dry_run and not force:
        logger.info("WARNING: This will permanently delete all data!")
        response = input("Type 'yes' to confirm: ")
        if response.lower() != "yes":
            logger.info("Aborted.")
            return
        logger.info("")

    # Drop collections
    start_time = time.time()
    logger.info("Dropping collections...")
    dropped = 0
    for collection_name in COLLECTIONS_TO_RESET:
        if drop_collection(db, collection_name, dry_run):
            dropped += 1

    drop_time = time.time() - start_time
    logger.info(f"Dropped {dropped}/{len(COLLECTIONS_TO_RESET)} collections in {drop_time:.2f}s")
    logger.info("")

    # Recreate indexes
    logger.info("Creating indexes...")
    index_start = time.time()
    created = create_indexes(db, dry_run)
    index_time = time.time() - index_start
    logger.info(f"Created {created} indexes in {index_time:.2f}s")
    logger.info("")

    # Setup sharding (if available)
    sharded = 0
    if sharding_available:
        logger.info("Setting up shard keys...")
        shard_start = time.time()
        sharded = setup_sharding(db, dry_run)
        shard_time = time.time() - shard_start
        logger.info(f"Configured {sharded} shard keys in {shard_time:.2f}s")
        logger.info("")

    # Summary
    total_time = time.time() - start_time
    logger.info("=" * 60)
    if dry_run:
        logger.info("Dry run complete - no changes made")
    else:
        logger.info("Reset complete!")
    logger.info("=" * 60)
    logger.info(f"Collections reset: {dropped}")
    logger.info(f"Indexes created: {created}")
    if sharding_available:
        logger.info(f"Shard keys configured: {sharded}")
    logger.info(f"Total time: {total_time:.2f}s")
    logger.info("")
    logger.info("Next steps:")
    logger.info("  python -m seed.main           # Full seed (50M customers)")
    logger.info("  python -m seed.main --test    # Quick test seed (5 customers)")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reset RegionalBank Fraud Detection collections (drop and recreate indexes + shard keys)"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Skip confirmation prompt (use in scripts)",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be dropped without making changes",
    )
    args = parser.parse_args()

    reset_collections(force=args.force, dry_run=args.dry_run)
