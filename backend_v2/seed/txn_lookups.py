"""
Seed the consolidated txn_lookups collection from existing separate collections.

Reads from already-seeded pot_bf, pot_bf24, pot_sm, pot_anj, pot_pp, pot_cb, pot_sl_va
and transforms each entry into {type, lookup_value, metadata} format with prefixed lookup_value.

At production scale this processes ~2.1M entries:
  pot_bf: 470K, pot_bf24: 49K, pot_sm: 132K, pot_anj: 470K,
  pot_pp: 1.7K, pot_cb: 1M, pot_sl_va: ~28 (sl + va)

Must run AFTER separate blacklist/service collections are populated (Phase 1).
Uses streaming batch inserts to keep memory bounded regardless of collection sizes.
"""

import logging
from pymongo.database import Database

logger = logging.getLogger(__name__)

INSERT_BATCH_SIZE = 10_000

# (source_collection, type, prefix, value_field, metadata_fields)
SEED_MAPPING = [
    ("pot_bf",   "bf",   "account",  "b23",  []),
    ("pot_bf24", "bf24", "account",  "b23",  ["a23", "b13", "customer_id", "z1"]),
    ("pot_sm",   "sm",   "merchant", "n3",   []),
    ("pot_anj",  "anj",  "account",  "b23",  []),
    ("pot_pp",   "pp",   "provider", "b23",  ["q2"]),
    ("pot_cb",   "cb",   "account",  "b23",  ["c23"]),
]


def _flush_batch(collection, batch: list) -> int:
    """Insert a batch and return count inserted."""
    if not batch:
        return 0
    try:
        result = collection.insert_many(batch, ordered=False)
        return len(result.inserted_ids)
    except Exception as e:
        from pymongo.errors import BulkWriteError
        if isinstance(e, BulkWriteError):
            return e.details.get("nInserted", 0)
        logger.warning(f"  txn_lookups batch insert error: {e}")
        return 0


def seed_txn_lookups(db: Database, *, test_mode: bool = False) -> int:
    """Seed txn_lookups from existing separate collections.

    Streams through source collections and inserts in batches to keep
    memory bounded. Returns total documents inserted.
    """
    db.txn_lookups.delete_many({})
    collection = db.txn_lookups

    total = 0
    batch = []

    # Process each source collection
    for src_coll, doc_type, prefix, value_field, meta_fields in SEED_MAPPING:
        count = 0
        cursor = db[src_coll].find({}, batch_size=10_000)
        for src_doc in cursor:
            raw_value = src_doc.get(value_field)
            if raw_value is None:
                continue

            # Lowercase merchant names for consistent lookup
            if prefix == "merchant":
                raw_value = str(raw_value).lower()

            lookup_doc = {
                "type": doc_type,
                "lookup_value": f"{prefix}::{raw_value}",
            }

            # Add metadata if any fields are present
            if meta_fields:
                metadata = {}
                for field in meta_fields:
                    if field in src_doc:
                        metadata[field] = src_doc[field]
                if metadata:
                    lookup_doc["metadata"] = metadata

            batch.append(lookup_doc)
            count += 1

            if len(batch) >= INSERT_BATCH_SIZE:
                total += _flush_batch(collection, batch)
                batch.clear()

        logger.info(f"  txn_lookups: {count:,} entries from {src_coll} ({doc_type})")

    # Process pot_sl_va (generates two entries per service: sl + va)
    sl_count = 0
    va_count = 0
    cursor = db.pot_sl_va.find({})
    for src_doc in cursor:
        svc = src_doc.get("service")
        if svc is None:
            continue

        # pot_sl entry (service transaction limit)
        if "x" in src_doc:
            batch.append({
                "type": "sl",
                "lookup_value": f"service::{svc}",
                "metadata": {"x": src_doc["x"]},
            })
            sl_count += 1

        # pot_va entry (service amount thresholds)
        if "at1" in src_doc and "at2" in src_doc:
            batch.append({
                "type": "va",
                "lookup_value": f"service::{svc}",
                "metadata": {"at1": src_doc["at1"], "at2": src_doc["at2"]},
            })
            va_count += 1

        if len(batch) >= INSERT_BATCH_SIZE:
            total += _flush_batch(collection, batch)
            batch.clear()

    logger.info(f"  txn_lookups: {sl_count} entries from pot_sl_va (sl)")
    logger.info(f"  txn_lookups: {va_count} entries from pot_sl_va (va)")

    # Flush remaining
    total += _flush_batch(collection, batch)
    batch.clear()

    # Create index (idempotent)
    db.txn_lookups.create_index("lookup_value", name="idx_lookup_value")

    logger.info(f"  txn_lookups: {total:,} total documents seeded")
    return total
