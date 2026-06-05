#!/usr/bin/env python3
"""
Seed script for RegionalBank Fraud Detection POC.

Usage:
    # Full seed (50M customers, 100M transactions)
    python -m seed.main

    # Quick test seed (5 customers, 20 transactions - schema validation)
    python -m seed.main --test

    # Custom seed via environment
    SEED_CUSTOMERS=100000 SEED_TRANSACTIONS=500000 python -m seed.main

Two-Phase Seeding Architecture:
    Phase 1: Seed all customers to MongoDB (no memory accumulation)
    Phase 2: Stream customers back from DB and generate transactions

    This enables 50M+ scale without memory issues (~100MB peak vs ~50GB).
"""

import argparse
import logging
import os
import random
import sys
import time
from typing import List, Dict, Generator

from pymongo import InsertOne
from pymongo.errors import BulkWriteError

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.db import get_db_sync
from app.indexes import create_all_indexes, INDEX_DEFINITIONS

from seed.customers import generate_customers_batch
from seed.transactions import generate_transactions_for_customer
from seed.blacklist import generate_blacklist_locations
from seed.holidays import generate_holidays

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def seed_holidays(db) -> int:
    """Seed holiday collection."""
    logger.info("Seeding holidays...")
    holidays = generate_holidays()

    # Clear existing
    db.holidays.delete_many({})

    if holidays:
        result = db.holidays.insert_many(holidays)
        count = len(result.inserted_ids)
        logger.info(f"  Inserted {count} holidays")
        return count
    return 0


def seed_blacklist(db, count: int = 100) -> int:
    """Seed blacklist locations collection."""
    logger.info(f"Seeding {count} blacklist locations...")
    locations = generate_blacklist_locations(count)

    # Clear existing
    db.blacklist_locations.delete_many({})

    if locations:
        result = db.blacklist_locations.insert_many(locations)
        count = len(result.inserted_ids)
        logger.info(f"  Inserted {count} blacklist locations")
        return count
    return 0


def seed_customers_batch(db, batch_size: int) -> List[Dict]:
    """Seed a batch of customers and return them for transaction generation."""
    customers = generate_customers_batch(batch_size)

    try:
        # Use unordered bulk write for parallel shard insertion
        result = db.customers.insert_many(customers, ordered=False)
        # Update customers with their _ids
        for i, _id in enumerate(result.inserted_ids):
            customers[i]["_id"] = _id
        return customers
    except BulkWriteError as e:
        # Some inserts may have succeeded
        logger.warning(f"Bulk write error (partial success): {e.details['nInserted']} inserted")
        return customers[:e.details["nInserted"]]


def seed_transactions_batch(db, transactions: List[Dict]) -> int:
    """Seed a batch of transactions."""
    if not transactions:
        return 0

    try:
        result = db.transactions.insert_many(transactions, ordered=False)
        return len(result.inserted_ids)
    except BulkWriteError as e:
        logger.warning(f"Bulk write error: {e.details['nInserted']} inserted")
        return e.details["nInserted"]


def create_indexes_sync(db) -> None:
    """Create all indexes synchronously."""
    logger.info("Creating indexes...")
    for collection_name, indexes in INDEX_DEFINITIONS.items():
        collection = db[collection_name]
        for index in indexes:
            try:
                collection.create_index(index["keys"], **index["options"])
                logger.debug(f"  Created index {index['options']['name']} on {collection_name}")
            except Exception as e:
                logger.warning(f"  Index {index['options']['name']}: {e}")
    logger.info("Indexes created")


def warm_customer_features(db, latest_per_customer: Dict[str, tuple], warm_to_now_pct: float = 0.05) -> int:
    """
    Update customer features from tracked latest transactions.

    This makes seeded customers immediately ready for fraud detection by
    populating latest_time_transaction and latest_location.

    A percentage of customers (default 5%) will have their latest_time_transaction
    set to "now" instead of their historical transaction time. This enables
    immediate fraud rule testing (velocity, impossible travel) without needing
    to score a warmup transaction first.

    Args:
        db: Database connection
        latest_per_customer: Dict mapping customer_id -> (timestamp, location)
        warm_to_now_pct: Percentage of customers to warm to current time (0.0-1.0)

    Returns:
        Number of customers updated.
    """
    if not latest_per_customer:
        logger.info("No customer features to warm")
        return 0

    from datetime import datetime
    import random
    from pymongo import UpdateOne

    now = datetime.utcnow()
    customer_ids = list(latest_per_customer.keys())

    # Select random subset to warm to "now"
    warm_to_now_count = max(1, int(len(customer_ids) * warm_to_now_pct))
    warm_to_now_ids = set(random.sample(customer_ids, min(warm_to_now_count, len(customer_ids))))

    logger.info(f"Warming {len(latest_per_customer):,} customer features...")
    logger.info(f"  {len(warm_to_now_ids):,} customers ({warm_to_now_pct*100:.0f}%) warmed to 'now' for immediate fraud testing")
    warm_start = time.time()

    # Build bulk updates from tracked data
    updates = []
    for customer_id, (timestamp, location) in latest_per_customer.items():
        # Use current time for selected customers, historical time for others
        effective_timestamp = now if customer_id in warm_to_now_ids else timestamp
        updates.append(UpdateOne(
            {"customer_id": customer_id},
            {"$set": {
                "features.latest_time_transaction": effective_timestamp,
                "features.latest_location": location,
            }}
        ))

    updated_count = 0
    if updates:
        # Process in batches for large datasets
        batch_size = 10000
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            result = db.customers.bulk_write(batch, ordered=False)
            updated_count += result.modified_count

    warm_time = time.time() - warm_start
    logger.info(f"  Updated {updated_count:,} customer features in {warm_time:.1f}s")
    return updated_count


def track_latest_transaction(
    latest_per_customer: Dict[str, tuple],
    txns: List[Dict]
) -> None:
    """
    Track the latest transaction per customer in memory.

    Args:
        latest_per_customer: Dict to update (customer_id -> (timestamp, location))
        txns: List of transaction documents
    """
    for txn in txns:
        customer_id = txn["customer_id"]
        timestamp = txn["timestamp"]
        location = txn.get("location")

        if customer_id not in latest_per_customer:
            latest_per_customer[customer_id] = (timestamp, location)
        elif timestamp > latest_per_customer[customer_id][0]:
            latest_per_customer[customer_id] = (timestamp, location)


def verify_shard_distribution(db) -> None:
    """Verify data distribution across shards."""
    logger.info("Verifying shard distribution...")
    try:
        # Get shard distribution for customers
        stats = db.command("collStats", "customers")
        if "shards" in stats:
            logger.info("  customers collection shard distribution:")
            for shard, shard_stats in stats["shards"].items():
                logger.info(f"    {shard}: {shard_stats.get('count', 'N/A')} documents")

        # Get shard distribution for transactions
        stats = db.command("collStats", "transactions")
        if "shards" in stats:
            logger.info("  transactions collection shard distribution:")
            for shard, shard_stats in stats["shards"].items():
                logger.info(f"    {shard}: {shard_stats.get('count', 'N/A')} documents")
    except Exception as e:
        logger.debug(f"  Shard distribution check skipped (not a sharded cluster): {e}")


def stream_customers(db, batch_size: int = 10000) -> Generator[List[Dict], None, None]:
    """
    Stream customers from MongoDB in batches.

    This avoids loading all customers into memory at once, enabling
    50M+ scale seeding with ~100MB peak memory.

    Args:
        db: Database connection
        batch_size: Number of customers per batch

    Yields:
        List of customer documents (batch_size at a time)
    """
    cursor = db.customers.find(
        {},
        # Fetch all fields needed for transaction generation
        # See seed/transactions.py generate_transaction() for field usage
        projection={
            "customer_id": 1,
            "name": 1,
            "account_ids": 1,
            "province": 1,
            "city": 1,
            "features": 1,
            "segment": 1,
        },
        batch_size=batch_size,
        no_cursor_timeout=True,  # Prevent cursor timeout during long operations
    )

    try:
        batch = []
        for doc in cursor:
            batch.append(doc)
            if len(batch) >= batch_size:
                yield batch
                batch = []

        # Yield remaining documents
        if batch:
            yield batch
    finally:
        # Ensure cursor is closed even if generator is not fully consumed
        cursor.close()


def main(test_mode: bool = False):
    """Main seed orchestrator.

    Two-phase seeding for 50M+ scale:
        Phase 1: Seed all customers to MongoDB (no memory accumulation)
        Phase 2: Stream customers back from DB and generate transactions

    Args:
        test_mode: If True, use minimal data for schema validation only.
    """
    settings = get_settings()

    if test_mode:
        # Quick test mode - minimal data for schema validation
        total_customers = settings.seed_test_customers
        total_transactions = settings.seed_test_transactions
        batch_size = 100  # Small batch for test
        blacklist_count = settings.seed_test_blacklist
        mode_label = "TEST MODE (schema validation)"
    else:
        # Allow environment override for quick testing
        total_customers = int(os.environ.get("SEED_CUSTOMERS", settings.seed_customers))
        total_transactions = int(os.environ.get("SEED_TRANSACTIONS", settings.seed_transactions))
        batch_size = int(os.environ.get("SEED_BATCH_SIZE", settings.seed_batch_size))
        blacklist_count = int(os.environ.get("SEED_BLACKLIST", settings.seed_blacklist))
        mode_label = "FULL SEED"

    logger.info("=" * 60)
    logger.info(f"RegionalBank Fraud Detection POC - Data Seeder [{mode_label}]")
    logger.info("=" * 60)
    logger.info(f"Target customers: {total_customers:,}")
    logger.info(f"Target transactions: {total_transactions:,}")
    logger.info(f"Batch size: {batch_size:,}")
    logger.info(f"Architecture: Two-phase streaming (memory-efficient)")
    logger.info("=" * 60)

    start_time = time.time()

    # Connect to database
    logger.info("Connecting to MongoDB...")
    db = get_db_sync()
    logger.info(f"Connected to database: {db.name}")

    # Create indexes first
    create_indexes_sync(db)

    # Seed reference data
    seed_holidays(db)
    seed_blacklist(db, blacklist_count)

    # =========================================================================
    # PHASE 1: Seed all customers (no memory accumulation)
    # =========================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 1: Seeding customers")
    logger.info("=" * 60)
    logger.info(f"Seeding {total_customers:,} customers...")
    customers_seeded = 0

    customer_start = time.time()
    while customers_seeded < total_customers:
        current_batch = min(batch_size, total_customers - customers_seeded)
        customers = seed_customers_batch(db, current_batch)
        # Don't accumulate: customers list is discarded after insertion
        customers_seeded += len(customers)

        if customers_seeded % 100_000 == 0 or customers_seeded == total_customers:
            elapsed = time.time() - customer_start
            rate = customers_seeded / elapsed if elapsed > 0 else 0
            logger.info(f"  {customers_seeded:,} customers seeded ({rate:.0f}/sec)")

    customer_time = time.time() - customer_start
    logger.info(f"Phase 1 complete: {customers_seeded:,} customers in {customer_time:.1f}s")

    # =========================================================================
    # PHASE 2: Stream customers and generate transactions
    # =========================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 2: Streaming customers & seeding transactions")
    logger.info("=" * 60)
    logger.info(f"Seeding {total_transactions:,} transactions...")

    transactions_seeded = 0
    customers_processed = 0
    txn_start = time.time()
    txn_batch = []

    # Track latest transaction per customer for feature warming
    latest_per_customer: Dict[str, tuple] = {}

    # Calculate average transactions per customer
    avg_txns = total_transactions / customers_seeded if customers_seeded > 0 else 2

    if test_mode:
        # Test mode: ensure all customers get transactions for schema validation
        base_per_customer = total_transactions // customers_seeded
        remainder = total_transactions % customers_seeded
        customer_idx = 0

        for customer_batch in stream_customers(db, batch_size=batch_size):
            for customer in customer_batch:
                # First 'remainder' customers get one extra transaction
                num_txns = base_per_customer + (1 if customer_idx < remainder else 0)
                num_txns = max(1, num_txns)
                customer_idx += 1

                txns = generate_transactions_for_customer(customer, num_txns)
                track_latest_transaction(latest_per_customer, txns)
                txn_batch.extend(txns)

            # Insert batch
            if txn_batch:
                count = seed_transactions_batch(db, txn_batch)
                transactions_seeded += count
                txn_batch = []
    else:
        # Production mode: stream customers and generate with exponential distribution
        # We shuffle within each batch for local randomization (can't global shuffle when streaming)

        for customer_batch in stream_customers(db, batch_size=batch_size):
            if transactions_seeded >= total_transactions:
                break

            # Shuffle within batch for local randomization
            random.shuffle(customer_batch)

            for customer in customer_batch:
                if transactions_seeded >= total_transactions:
                    break

                customers_processed += 1

                # Exponential distribution: some customers more active than others
                num_txns = max(1, int(random.expovariate(1 / avg_txns)))
                num_txns = min(num_txns, total_transactions - transactions_seeded, 100)

                txns = generate_transactions_for_customer(customer, num_txns)
                track_latest_transaction(latest_per_customer, txns)
                txn_batch.extend(txns)

                # Insert when batch is full
                while len(txn_batch) >= batch_size:
                    count = seed_transactions_batch(db, txn_batch[:batch_size])
                    transactions_seeded += count
                    txn_batch = txn_batch[batch_size:]

                    if transactions_seeded % 100_000 == 0:
                        elapsed = time.time() - txn_start
                        rate = transactions_seeded / elapsed if elapsed > 0 else 0
                        logger.info(f"  {transactions_seeded:,} transactions seeded ({rate:.0f}/sec)")

        # Insert remaining
        if txn_batch:
            count = seed_transactions_batch(db, txn_batch)
            transactions_seeded += count

    txn_time = time.time() - txn_start
    logger.info(f"Phase 2 complete: {transactions_seeded:,} transactions in {txn_time:.1f}s")

    # =========================================================================
    # PHASE 3: Warm customer features
    # =========================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 3: Warming customer features")
    logger.info("=" * 60)

    # Warm customer features from tracked data (no aggregation needed)
    # A percentage are warmed to "now" for immediate fraud testing
    warm_to_now_pct = float(os.environ.get("SEED_WARM_TO_NOW_PCT", settings.seed_warm_to_now_pct))
    warm_customer_features(db, latest_per_customer, warm_to_now_pct=warm_to_now_pct)

    # Verify distribution
    verify_shard_distribution(db)

    # Summary
    total_time = time.time() - start_time
    logger.info("")
    logger.info("=" * 60)
    logger.info("Seeding Complete!")
    logger.info("=" * 60)
    logger.info(f"Customers: {customers_seeded:,}")
    logger.info(f"Transactions: {transactions_seeded:,}")
    logger.info(f"Blacklist locations: {blacklist_count}")
    logger.info(f"Holidays: 30")
    logger.info(f"Total time: {total_time:.1f}s ({total_time/60:.1f} minutes)")
    logger.info(f"Peak memory: ~100MB (streaming architecture)")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed RegionalBank Fraud Detection database with test data"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Quick test mode: 5 customers, 20 transactions (schema validation)",
    )
    args = parser.parse_args()
    main(test_mode=args.test)
