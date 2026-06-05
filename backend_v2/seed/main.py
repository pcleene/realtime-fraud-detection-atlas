"""
V2 Parallel Chunked Pagination Seeder.

6-phase seeding with multiprocessing for 20-30x speedup on large seeds:

  Phase 1: Reference data (single process — small, fast)
  Phase 2: Customer insertion (parallel across N workers)
  Phase 3: Transaction generation + customer state warming (parallel by chunk)
  Phase 4: Warm-to-now (parallel bulk_write across workers)
  Phase 5: Beneficiary overflow (single process)
  Phase 6: Consolidated txn_lookups (single process)

Workers use fork-based multiprocessing. Each worker gets its own MongoClient.
Read-only caches (blacklists, service config) are loaded once before forking
and shared via copy-on-write memory.

Usage:
    python -m seed.main --test               # 5 customers, 20 txns (single process)
    python -m seed.main                      # Auto workers (cpu_count // 2)
    python -m seed.main --workers 32         # 32 parallel workers
    SEED_CUSTOMERS=40000000 python -m seed.main --workers 32
"""

import argparse
import ctypes
import gc
import logging
import math
import multiprocessing as mp
import random
import sys
import time
from datetime import datetime, timedelta

from pymongo import MongoClient, UpdateOne

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(process)d] %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Module-level state for forked workers
# =============================================================================
# _shared_caches: set in parent BEFORE Pool creation; inherited via fork COW.
# _worker_*: set PER WORKER in _init_worker; each gets its own MongoClient.

_shared_caches = None
_worker_client = None
_worker_db = None
_worker_settings = None


def _init_worker(mongodb_uri: str, db_name: str):
    """Worker initializer: own MongoClient + settings. Called once per process."""
    global _worker_client, _worker_db, _worker_settings
    random.seed()  # Re-seed from OS entropy (fork duplicates parent's random state)
    _worker_client = MongoClient(mongodb_uri, maxPoolSize=10)
    _worker_db = _worker_client[db_name]
    sys.path.insert(0, ".")
    from app.config import get_settings
    _worker_settings = get_settings()


def _release_memory():
    """Force Python to return freed memory to the OS.

    After processing a chunk, Python's allocator holds freed memory internally.
    gc.collect() frees unreferenced objects, then malloc_trim() returns unused
    heap pages to the OS. Without this, 32 workers × 4GB each = 128GB claimed
    even though the data is freed — causing OOM deadlocks.
    """
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass  # Not on Linux, or libc not available


# =============================================================================
# Phase 2 worker: Customer insertion
# =============================================================================

def _customer_worker(args):
    """Generate and insert customers. Returns count inserted."""
    worker_id, count = args
    from seed.customers import generate_customer_batch

    db = _worker_db
    batch_size = _worker_settings.seed_batch_size
    inserted = 0

    for start in range(0, count, batch_size):
        current = min(batch_size, count - start)
        batch = generate_customer_batch(current)
        try:
            result = db.customers.insert_many(batch, ordered=False)
            inserted += len(result.inserted_ids)
        except Exception as e:
            from pymongo.errors import BulkWriteError
            if isinstance(e, BulkWriteError):
                inserted += e.details.get("nInserted", 0)
            else:
                logger.warning(f"[W{worker_id}] Customer insert error: {e}")

        if inserted > 0 and (start + current) % (batch_size * 20) == 0:
            logger.info(f"[W{worker_id}] Customers: {inserted:,}/{count:,}")

    logger.info(f"[W{worker_id}] Customers done: {inserted:,}")
    return inserted


# =============================================================================
# Phase 3 worker: Chunk transaction generation
# =============================================================================

def _hex_chunk_boundaries(total_chunks: int) -> list:
    """Compute hex-range boundaries for customer_id CUST-{12 hex} space.

    Returns list of (lower, upper) tuples where each is a customer_id string.
    Range queries on the shard key are O(1) — unlike skip/limit which is O(N).
    """
    HEX_MAX = 16 ** 12  # FFFFFFFFFFFF + 1
    boundaries = []
    for i in range(total_chunks):
        lo = (HEX_MAX * i) // total_chunks
        hi = (HEX_MAX * (i + 1)) // total_chunks
        lower = f"CUST-{lo:012X}"
        upper = f"CUST-{hi:012X}" if i < total_chunks - 1 else None  # last chunk: no upper bound
        boundaries.append((lower, upper))
    return boundaries


def _chunk_worker(chunk_args):
    """Process one chunk: load customers -> generate txns -> insert -> bulk_write.

    Returns (chunk_idx, txns_generated, txns_inserted, customers_updated).
    """
    (chunk_idx, total_chunks,
     lower_bound, upper_bound,
     txns_per_chunk, remainder_txns,
     time_range_start_ts, chunk_time_span_secs,
     test_mode, max_txns_per_customer) = chunk_args

    from seed.transactions import generate_transaction, update_rolling_state, random_datetime

    db = _worker_db
    settings = _worker_settings
    caches = _shared_caches
    txn_batch_size = settings.seed_txn_batch_size
    cust_update_batch = settings.seed_customer_update_batch
    t0 = time.time()

    time_range_start = datetime.fromtimestamp(time_range_start_ts, tz=None)
    chunk_time_span = timedelta(seconds=chunk_time_span_secs)

    # --- Step A: Load chunk's customers via range query (shard-targeted, no skip) ---
    query = {"customer_id": {"$gte": lower_bound}}
    if upper_bound is not None:
        query["customer_id"]["$lt"] = upper_bound

    cursor = db.customers.find(
        query,
        {"_id": 0, "customer_id": 1, "rolling": 1, "flags": 1,
         "av1": 1, "av2": 1, "service_ever": 1, "b24_count": 1, "b24_list": 1},
        batch_size=10_000,
    )

    rolling_state = {}
    chunk_cids = []
    for doc in cursor:
        cid = doc["customer_id"]
        chunk_cids.append(cid)
        r = doc.get("rolling", {})
        rolling_state[cid] = {
            "z1_prev": None, "at3_prev": None, "at3_prev2": None,
            "at3_recent": [], "tp_recent": [], "at3_sum": 0, "at6": 0,
            "window_start": None, "bl_window_start": None,
            "bl": r.get("bl"), "b1": r.get("b1"),
            "z3": r.get("z3"), "z4": r.get("z4"),
            "pt_latest": r.get("pt_latest"), "w2_latest": r.get("w2_latest"),
            "pot_i_recent": r.get("pot_i_recent", []),
            "flags": doc.get("flags", {}),
            "av1": doc.get("av1"), "av2": doc.get("av2"),
            "service_ever": list(doc.get("service_ever", [])),
            "b24_list": list(doc.get("b24_list", [])),
            "b24_count": doc.get("b24_count", 0),
        }

    if not chunk_cids:
        return (chunk_idx, 0, 0, 0)

    load_time = time.time() - t0

    # --- Step B: Transaction quota ---
    chunk_txn_count = txns_per_chunk + (remainder_txns if chunk_idx == total_chunks - 1 else 0)

    # --- Step C: Generate transactions ---
    chunk_start_dt = time_range_start + chunk_idx * chunk_time_span
    chunk_end_dt = chunk_start_dt + chunk_time_span
    txn_buffer = []
    txns_generated = 0
    txns_inserted = 0

    if test_mode:
        base = chunk_txn_count // len(chunk_cids)
        extra = chunk_txn_count % len(chunk_cids)
        for i, cid in enumerate(chunk_cids):
            n = base + (1 if i < extra else 0)
            if n <= 0:
                continue
            times = sorted(random_datetime(chunk_start_dt, chunk_end_dt) for _ in range(n))
            for z1 in times:
                txn = generate_transaction(cid, rolling_state[cid]["b1"], rolling_state[cid], z1, caches, settings)
                update_rolling_state(rolling_state[cid], txn, settings)
                txn_buffer.append(txn)
                txns_generated += 1
                if len(txn_buffer) >= txn_batch_size:
                    db.transactions.insert_many(txn_buffer, ordered=False)
                    txns_inserted += len(txn_buffer)
                    txn_buffer.clear()
    else:
        avg = chunk_txn_count / len(chunk_cids) if chunk_cids else 1
        remaining = chunk_txn_count
        for cid in chunk_cids:
            if remaining <= 0:
                break
            n = max(1, int(random.expovariate(1 / avg)))
            n = min(n, remaining, max_txns_per_customer)
            remaining -= n
            times = sorted(random_datetime(chunk_start_dt, chunk_end_dt) for _ in range(n))
            for z1 in times:
                txn = generate_transaction(cid, rolling_state[cid]["b1"], rolling_state[cid], z1, caches, settings)
                update_rolling_state(rolling_state[cid], txn, settings)
                txn_buffer.append(txn)
                txns_generated += 1
                if len(txn_buffer) >= txn_batch_size:
                    db.transactions.insert_many(txn_buffer, ordered=False)
                    txns_inserted += len(txn_buffer)
                    txn_buffer.clear()

    # --- Step D: Flush remaining ---
    if txn_buffer:
        db.transactions.insert_many(txn_buffer, ordered=False)
        txns_inserted += len(txn_buffer)
        txn_buffer.clear()

    gen_time = time.time() - t0 - load_time

    # --- Step E: Streaming bulk_write customer rolling state updates ---
    # Build and flush in batches instead of accumulating all UpdateOne objects at once.
    # At 500K customers, the full list of UpdateOne objects costs ~1.5GB — streaming
    # keeps peak memory per batch to ~15MB (5K updates × ~3KB each).
    update_batch = []
    custs_updated = 0
    for cid, rs in rolling_state.items():
        if rs["z1_prev"] is not None:
            custs_updated += 1
            update_batch.append(UpdateOne(
                {"customer_id": cid},
                {"$set": {
                    "rolling.z1_prev": rs["z1_prev"],
                    "rolling.at3_prev": rs["at3_prev"],
                    "rolling.at3_prev2": rs["at3_prev2"],
                    "rolling.at3_recent": rs["at3_recent"][-settings.recent_amounts_limit:],
                    "rolling.tp_recent": rs["tp_recent"][-settings.recent_purposes_limit:],
                    "rolling.at3_sum": rs["at3_sum"],
                    "rolling.at6": rs["at6"],
                    "rolling.window_start": rs["window_start"],
                    "rolling.bl_window_start": rs["bl_window_start"],
                    "service_ever": rs["service_ever"],
                    "b24_count": rs["b24_count"],
                    "b24_list": rs["b24_list"][:settings.beneficiary_embed_limit],
                }}
            ))
            if len(update_batch) >= cust_update_batch:
                db.customers.bulk_write(update_batch, ordered=False)
                update_batch.clear()

    if update_batch:
        db.customers.bulk_write(update_batch, ordered=False)
        update_batch.clear()

    elapsed = time.time() - t0
    logger.info(
        f"Chunk {chunk_idx + 1}/{total_chunks}: "
        f"{txns_generated:,} txns, {custs_updated:,}/{len(chunk_cids):,} custs "
        f"(load={load_time:.1f}s gen={gen_time:.1f}s total={elapsed:.1f}s)"
    )

    # Free rolling_state and force memory return to OS between chunks
    del rolling_state, chunk_cids
    _release_memory()

    return (chunk_idx, txns_generated, txns_inserted, custs_updated)


# =============================================================================
# Phase 4 worker: Warm-to-now
# =============================================================================

def _warm_worker(args):
    """Bulk_write warm-to-now for a batch of customer IDs. Returns count updated."""
    cid_batch, now_ts = args
    now = datetime.fromtimestamp(now_ts, tz=None)
    updates = [UpdateOne({"customer_id": cid}, {"$set": {"rolling.z1_prev": now}}) for cid in cid_batch]
    updated = 0
    for i in range(0, len(updates), 10_000):
        result = _worker_db.customers.bulk_write(updates[i:i + 10_000], ordered=False)
        updated += result.modified_count
    return updated


# =============================================================================
# Main
# =============================================================================

def main():
    global _shared_caches, _worker_client, _worker_db, _worker_settings

    parser = argparse.ArgumentParser(description="V2 Parallel Database Seeder")
    parser.add_argument("--test", action="store_true", help="Quick test (5 customers, 20 txns)")
    parser.add_argument("--workers", "-w", type=int, default=0,
                        help="Parallel workers (default: cpu_count // 2, test: 1)")
    args = parser.parse_args()

    sys.path.insert(0, ".")
    from app.config import get_settings
    settings = get_settings()

    if args.test:
        num_customers, num_transactions, test_mode = 5, 20, True
        num_workers = 1
    else:
        num_customers = settings.seed_customers
        num_transactions = settings.seed_transactions
        test_mode = False
        num_workers = args.workers or max(1, mp.cpu_count() // 2)

    batch_size = settings.seed_batch_size
    chunk_size = min(settings.seed_chunk_size, num_customers)
    warm_pct = settings.seed_warm_to_now_pct
    mongodb_uri = settings.mongodb_uri
    db_name = settings.db_name
    use_mp = num_workers > 1

    logger.info(f"V2 Parallel Seeder: db={db_name}, workers={num_workers}")
    logger.info(f"  Customers: {num_customers:,}  Transactions: {num_transactions:,}")
    logger.info(f"  Batch: {batch_size:,}  Chunk: {chunk_size:,}  Warm: {warm_pct*100:.0f}%")
    logger.info(f"  Fraud scores: {settings.seed_compute_fraud_scores}")

    total_start = time.time()

    # =================================================================
    # Phase 1: Reference data + cache loading (single process)
    # =================================================================
    logger.info("\n=== Phase 1: Reference Data ===")

    client = MongoClient(mongodb_uri)
    db = client[db_name]

    from seed.blacklists import seed_blacklists, seed_service_config
    bl_stats = seed_blacklists(db, test_mode=test_mode)
    sc_stats = seed_service_config(db, test_mode=test_mode)

    # Load caches BEFORE forking — workers inherit via fork copy-on-write
    from seed.scoring import SeedCaches
    _shared_caches = SeedCaches(db)

    client.close()  # Must close parent MongoClient before forking

    phase1_time = time.time() - total_start
    logger.info(f"Phase 1 complete ({phase1_time:.1f}s)")

    # =================================================================
    # Phase 2: Customers (parallel)
    # =================================================================
    logger.info(f"\n=== Phase 2: Customers ({num_workers} workers) ===")
    p2_start = time.time()

    if use_mp:
        per_w = num_customers // num_workers
        rem = num_customers % num_workers
        work = [(i, per_w + (1 if i < rem else 0)) for i in range(num_workers)]
        with mp.Pool(num_workers, _init_worker, (mongodb_uri, db_name)) as pool:
            results = pool.map(_customer_worker, work, chunksize=1)
        customers_inserted = sum(results)
    else:
        # Single process: set globals and call worker directly
        _worker_client = MongoClient(mongodb_uri)
        _worker_db = _worker_client[db_name]
        _worker_settings = settings
        customers_inserted = _customer_worker((0, num_customers))
        _worker_client.close()

    phase2_time = time.time() - p2_start
    logger.info(f"Phase 2 complete: {customers_inserted:,} customers ({phase2_time:.1f}s)")

    if customers_inserted == 0:
        logger.error("No customers inserted! Aborting.")
        return

    # =================================================================
    # Phase 3: Transactions (parallel by chunk — hex-range pagination)
    # =================================================================
    total_chunks = math.ceil(customers_inserted / chunk_size)
    active_workers = min(num_workers, total_chunks)
    logger.info(f"\n=== Phase 3: Transactions ({active_workers} workers, {total_chunks} chunks) ===")
    p3_start = time.time()

    # Pre-compute hex-range boundaries for shard-targeted queries (no skip/limit)
    hex_boundaries = _hex_chunk_boundaries(total_chunks)

    txns_per_chunk = num_transactions // total_chunks
    remainder_txns = num_transactions % total_chunks
    time_range_days = settings.seed_time_range_days
    time_range_start = datetime.utcnow() - timedelta(days=time_range_days)
    chunk_time_span = timedelta(days=time_range_days) / total_chunks

    chunk_args_list = [
        (idx, total_chunks,
         hex_boundaries[idx][0], hex_boundaries[idx][1],  # lower, upper bounds
         txns_per_chunk, remainder_txns,
         time_range_start.timestamp(), chunk_time_span.total_seconds(),
         test_mode, settings.seed_max_txns_per_customer)
        for idx in range(total_chunks)
    ]

    if use_mp:
        with mp.Pool(active_workers, _init_worker, (mongodb_uri, db_name)) as pool:
            results = pool.map(_chunk_worker, chunk_args_list, chunksize=1)
        total_transactions_inserted = sum(r[2] for r in results)
    else:
        # Single process: use main connection
        _worker_client = MongoClient(mongodb_uri)
        _worker_db = _worker_client[db_name]
        _worker_settings = settings
        total_transactions_inserted = 0
        for ca in chunk_args_list:
            r = _chunk_worker(ca)
            total_transactions_inserted += r[2]
        _worker_client.close()

    phase3_time = time.time() - p3_start
    logger.info(f"Phase 3 complete: {total_transactions_inserted:,} transactions ({phase3_time:.1f}s)")

    # =================================================================
    # Phase 4: Warm-to-now (parallel)
    # =================================================================
    logger.info(f"\n=== Phase 4: Warm-to-Now ({num_workers} workers) ===")
    p4_start = time.time()

    warm_count = int(customers_inserted * warm_pct)
    warm_updated = 0

    if warm_count > 0:
        # Read all customer IDs (temporary client, closed before forking)
        tmp_client = MongoClient(mongodb_uri)
        tmp_db = tmp_client[db_name]
        all_ids = [doc["customer_id"] for doc in
                   tmp_db.customers.find({}, {"_id": 0, "customer_id": 1}, batch_size=50_000)]
        tmp_client.close()

        warm_ids = random.sample(all_ids, min(warm_count, len(all_ids)))
        del all_ids

        now_ts = datetime.utcnow().timestamp()

        if use_mp:
            batch_per_w = max(1, len(warm_ids) // num_workers + 1)
            batches = [warm_ids[i:i + batch_per_w] for i in range(0, len(warm_ids), batch_per_w)]
            warm_args = [(b, now_ts) for b in batches if b]
            with mp.Pool(min(num_workers, len(warm_args)), _init_worker, (mongodb_uri, db_name)) as pool:
                results = pool.map(_warm_worker, warm_args, chunksize=1)
            warm_updated = sum(results)
        else:
            _worker_client = MongoClient(mongodb_uri)
            _worker_db = _worker_client[db_name]
            _worker_settings = settings
            warm_updated = _warm_worker((warm_ids, now_ts))
            _worker_client.close()

    phase4_time = time.time() - p4_start
    logger.info(f"Phase 4 complete: {warm_updated:,} customers warmed ({phase4_time:.1f}s)")

    # =================================================================
    # Phase 5: Beneficiary overflow (single process)
    # =================================================================
    logger.info("\n=== Phase 5: Beneficiary Overflow ===")
    p5_start = time.time()

    client = MongoClient(mongodb_uri)
    db = client[db_name]

    from seed.pot_nb_overflow import seed_overflow
    overflow_count = seed_overflow(db, test_mode=test_mode)

    phase5_time = time.time() - p5_start
    logger.info(f"Phase 5 complete: {overflow_count:,} overflow entries ({phase5_time:.1f}s)")

    # =================================================================
    # Phase 6: Consolidated txn_lookups (single process)
    # =================================================================
    logger.info("\n=== Phase 6: Consolidated txn_lookups ===")
    p6_start = time.time()

    from seed.txn_lookups import seed_txn_lookups
    txn_lookups_count = seed_txn_lookups(db, test_mode=test_mode)

    phase6_time = time.time() - p6_start
    logger.info(f"Phase 6 complete: {txn_lookups_count:,} txn_lookups ({phase6_time:.1f}s)")

    client.close()

    # =================================================================
    # Summary
    # =================================================================
    total_time = time.time() - total_start
    logger.info(f"\n{'='*60}")
    logger.info(f"V2 Parallel Seeding Complete ({total_time:.1f}s)")
    logger.info(f"{'='*60}")
    logger.info(f"  Database: {db_name}")
    logger.info(f"  Workers: {num_workers}")
    logger.info(f"  Customers: {customers_inserted:,}")
    logger.info(f"  Transactions: {total_transactions_inserted:,}")
    logger.info(f"  Blacklists: {bl_stats}")
    logger.info(f"  Service config: {sc_stats}")
    logger.info(f"  Overflow: {overflow_count:,}")
    logger.info(f"  txn_lookups: {txn_lookups_count:,}")
    logger.info(f"  Warm-to-now: {warm_updated:,} ({warm_pct*100:.0f}%)")
    logger.info(f"  Timing: P1={phase1_time:.1f}s P2={phase2_time:.1f}s "
                f"P3={phase3_time:.1f}s P4={phase4_time:.1f}s "
                f"P5={phase5_time:.1f}s P6={phase6_time:.1f}s")


if __name__ == "__main__":
    main()
