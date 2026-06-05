"""
Seed all 6 V2 blacklist collections + pot_sl_va service config.

Production-scale volumes from RegionalBank documentation:
  pot_bf:   470K    pot_bf24: 49K     pot_sm:  132K
  pot_anj:  470K    pot_pp:   1.7K    pot_cb:  1M
  pot_sl_va: 14 (one per service code, both limit + avg bounds)

Total: ~2.1M blacklist entries, ~130-170 MB in-memory cache.
"""

import logging
from pymongo import MongoClient

from seed.data.blacklist_data import (
    PROD_COUNTS, TEST_COUNTS,
    generate_pot_bf, generate_pot_bf24, generate_pot_sm,
    generate_pot_anj, generate_pot_pp, generate_pot_cb,
)

logger = logging.getLogger(__name__)

INSERT_BATCH_SIZE = 10_000


def _seed_collection(db, coll_name: str, generator, count: int) -> int:
    """Seed a single collection from a generator with batched inserts."""
    db[coll_name].delete_many({})

    total = 0
    batch = []
    for doc in generator(count):
        batch.append(doc)
        if len(batch) >= INSERT_BATCH_SIZE:
            try:
                result = db[coll_name].insert_many(batch, ordered=False)
                total += len(result.inserted_ids)
            except Exception as e:
                # Duplicate key errors are expected for unique indexes
                # (random account numbers can collide at scale)
                from pymongo.errors import BulkWriteError
                if isinstance(e, BulkWriteError):
                    total += e.details.get("nInserted", 0)
                else:
                    logger.warning(f"  {coll_name} batch insert error: {e}")
            batch.clear()

    # Flush remaining
    if batch:
        try:
            result = db[coll_name].insert_many(batch, ordered=False)
            total += len(result.inserted_ids)
        except Exception as e:
            from pymongo.errors import BulkWriteError
            if isinstance(e, BulkWriteError):
                total += e.details.get("nInserted", 0)
            else:
                logger.warning(f"  {coll_name} final batch error: {e}")

    logger.info(f"  Seeded {coll_name}: {total:,} entries (target: {count:,})")
    return total


def seed_blacklists(db, *, test_mode: bool = False) -> dict:
    """Seed all 6 blacklist collections at production scale."""
    counts = TEST_COUNTS if test_mode else PROD_COUNTS

    generators = {
        "pot_bf": generate_pot_bf,
        "pot_bf24": generate_pot_bf24,
        "pot_sm": generate_pot_sm,
        "pot_anj": generate_pot_anj,
        "pot_pp": generate_pot_pp,
        "pot_cb": generate_pot_cb,
    }

    stats = {}
    for coll_name, gen_fn in generators.items():
        count = counts[coll_name]
        stats[coll_name] = _seed_collection(db, coll_name, gen_fn, count)

    total = sum(stats.values())
    logger.info(f"  Blacklist total: {total:,} entries across {len(stats)} collections")
    return stats


def seed_service_config(db, *, test_mode: bool = False) -> dict:
    """Seed pot_sl_va (merged service limits + avg bounds).

    Production has ~13 service limits + ~28 avg bounds.
    We generate one entry per service code with both fields.
    """
    from seed.data.fraud_scenarios import SERVICE_CODES

    configs = []
    for svc in SERVICE_CODES:
        configs.append({
            "service": svc,
            "x": 10_000_000,          # max transaction limit (IDR)
            "at1": 50_000,             # avg lower bound (IDR)
            "at2": 5_000_000,          # avg upper bound (IDR)
        })

    db.pot_sl_va.delete_many({})
    if configs:
        result = db.pot_sl_va.insert_many(configs)
        count = len(result.inserted_ids)
    else:
        count = 0

    logger.info(f"  Seeded pot_sl_va: {count} service configs")
    return {"pot_sl_va": count}
