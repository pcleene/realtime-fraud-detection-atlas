"""Seed pot_nb_overflow for customers with >500 beneficiaries.

At production scale (40M customers), ~0.5% (~200K) have b24_count > 500.
Their excess beneficiaries spill to pot_nb_overflow, queried only when
the embedded b24_list doesn't contain the destination account (var_22).
"""

import logging
import random

logger = logging.getLogger(__name__)

INSERT_BATCH_SIZE = 10_000


def seed_overflow(db, *, test_mode: bool = False) -> int:
    """Seed overflow beneficiaries for high-volume customers.

    Queries customers collection for b24_count > 500, then generates
    the excess entries. Each entry is a (customer_id, b2) pair representing
    a known beneficiary beyond the embedded limit.
    """
    overflow_customers = list(db.customers.find(
        {"b24_count": {"$gt": 500}},
        {"_id": 0, "customer_id": 1, "b24_count": 1},
        batch_size=10_000,
    ))

    if not overflow_customers:
        logger.info("  No overflow customers found (b24_count <= 500)")
        return 0

    logger.info(f"  Found {len(overflow_customers):,} overflow customers")

    db.pot_nb_overflow.delete_many({})
    total = 0
    batch = []

    for cust in overflow_customers:
        cid = cust["customer_id"]
        extra_count = cust["b24_count"] - 500
        # Cap per-customer overflow: test=100, prod=2000 (covers max observed 2,095)
        cap = 100 if test_mode else 2_000
        entries_to_create = min(extra_count, cap)

        for _ in range(entries_to_create):
            batch.append({
                "customer_id": cid,
                "b2": f"{random.randint(1000000000, 9999999999)}",
            })

            if len(batch) >= INSERT_BATCH_SIZE:
                try:
                    result = db.pot_nb_overflow.insert_many(batch, ordered=False)
                    total += len(result.inserted_ids)
                except Exception as e:
                    from pymongo.errors import BulkWriteError
                    if isinstance(e, BulkWriteError):
                        total += e.details.get("nInserted", 0)
                    else:
                        logger.warning(f"  Overflow batch insert error: {e}")
                batch.clear()

    # Flush remaining
    if batch:
        try:
            result = db.pot_nb_overflow.insert_many(batch, ordered=False)
            total += len(result.inserted_ids)
        except Exception as e:
            from pymongo.errors import BulkWriteError
            if isinstance(e, BulkWriteError):
                total += e.details.get("nInserted", 0)
            else:
                logger.warning(f"  Overflow final batch error: {e}")

    logger.info(f"  Seeded pot_nb_overflow: {total:,} entries for {len(overflow_customers):,} customers")
    return total
