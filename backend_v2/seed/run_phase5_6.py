"""
Standalone script to run Phase 5 (pot_nb_overflow) + Phase 6 (txn_lookups) only.

Does NOT touch customers, transactions, or any other collection.
Both seed functions call delete_many({}) internally before inserting,
so any stale data is cleared automatically.

Usage (on bastion):
    cd /home/ssm-user/RegionalBank_fraud_detection/backend_v2
    python -m seed.run_phase5_6
"""

import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

sys.path.insert(0, ".")

from pymongo import MongoClient
from app.config import get_settings


def main():
    settings = get_settings()
    uri = settings.mongodb_uri
    db_name = settings.db_name

    logger.info(f"Connecting to database: {db_name}")
    client = MongoClient(uri)
    db = client[db_name]

    # Safety: verify we have customers before proceeding
    cust_count = db.customers.estimated_document_count()
    logger.info(f"Customers in DB: {cust_count:,}")
    if cust_count == 0:
        logger.error("No customers found — aborting to avoid running against wrong DB.")
        client.close()
        return

    # --- Phase 5: pot_nb_overflow ---
    logger.info("\n=== Phase 5: Beneficiary Overflow ===")
    p5_start = time.time()

    from seed.pot_nb_overflow import seed_overflow
    overflow_count = seed_overflow(db, test_mode=False)

    p5_time = time.time() - p5_start
    logger.info(f"Phase 5 complete: {overflow_count:,} overflow entries ({p5_time:.1f}s)")

    # --- Phase 6: txn_lookups ---
    logger.info("\n=== Phase 6: Consolidated txn_lookups ===")
    p6_start = time.time()

    from seed.txn_lookups import seed_txn_lookups
    txn_lookups_count = seed_txn_lookups(db, test_mode=False)

    p6_time = time.time() - p6_start
    logger.info(f"Phase 6 complete: {txn_lookups_count:,} txn_lookups ({p6_time:.1f}s)")

    client.close()

    logger.info(f"\nDone. Phase 5: {p5_time:.1f}s, Phase 6: {p6_time:.1f}s")


if __name__ == "__main__":
    main()
