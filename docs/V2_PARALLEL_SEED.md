# V2 Parallel Seed Script

## Overview

`backend_v2/seed/main.py` is a 6-phase parallel seeder that populates the V2 fraud detection database with customers, transactions, blacklist reference data, and supporting collections.

The bottleneck in large seeds (40M customers, 100M transactions) is **CPU-bound Python generation** -- building transaction documents with realistic fraud patterns, rolling state computation, and random distributions. MongoDB insert throughput is not the constraint. Fork-based multiprocessing achieves a 20-30x speedup on Phase 3 by spreading transaction generation across workers.

## Architecture

### Fork-based multiprocessing with `Pool`

- Uses `multiprocessing.Pool` with fork semantics (default on Linux).
- Each worker runs `_init_worker()` once, which creates its own `MongoClient(maxPoolSize=10)` and loads `Settings`.
- The parent `MongoClient` is **closed before forking** to avoid inherited socket/file-descriptor issues.
- `random.seed()` is called per worker to re-seed from OS entropy -- without this, all workers would produce identical random sequences since fork duplicates the parent's PRNG state.

### Read-only caches (copy-on-write)

Blacklist tables (`pot_bf`, `pot_bf24`, `pot_sm`, etc.) and service config (`pot_sl_va`) are loaded into `SeedCaches` in the parent process **before** the Pool is created. Workers inherit this data through fork copy-on-write memory, avoiding redundant MongoDB reads. The caches are never mutated by workers.

## Usage

All commands run from `backend_v2/`:

```bash
# Test mode: 5 customers, 20 transactions, single process
python -m seed.main --test

# Auto workers (cpu_count // 2), default 10K customers + 50K txns
python -m seed.main

# Explicit worker count
python -m seed.main --workers 32

# Full production seed (40M customers, 100M transactions)
SEED_CUSTOMERS=40000000 SEED_TRANSACTIONS=100000000 SEED_COMPUTE_FRAUD_SCORES=false python -m seed.main --workers 32
```

## Phase Breakdown

### Phase 1: Reference Data (single process)

Seeds blacklist collections (`pot_bf`, `pot_bf24`, `pot_sm`, `pot_anj`, `pot_pp`, `pot_cb`) and service config (`pot_sl_va`). Then loads all reference data into `SeedCaches` for workers to inherit. Small and fast -- typically < 5 seconds.

### Phase 2: Customer Insertion (N workers)

Each worker generates and inserts its share of customers using `insert_many(ordered=False)` in batches of `SEED_BATCH_SIZE` (default 10K). Work is divided evenly: worker `i` gets `num_customers // N` customers (plus 1 extra for the first `num_customers % N` workers).

### Phase 3: Transaction Generation (N workers, chunked) -- the big win

This is where parallelization matters most. Transaction generation is CPU-bound: each transaction requires random field generation, rolling state computation, and optional fraud score calculation.

**Chunking strategy:**
- Customers are divided into chunks of `SEED_CHUNK_SIZE` (default 500K).
- Each chunk gets an equal share of the total transaction count.
- Each chunk covers an independent time slice of the `SEED_TIME_RANGE_DAYS` window.
- Workers pick up chunks from the pool. A chunk loads its customer subset, generates transactions with `expovariate` distribution per customer, inserts in batches, then bulk-writes the updated rolling state back to the customers collection.

Workers never overlap on customers or time ranges -- chunks are fully independent.

**Hex-range pagination (critical for sharded collections):**

The initial implementation used `sort("customer_id").skip(N).limit(chunk_size)` to paginate through customers. This worked fine locally but **completely stalled at production scale** (40M customers, 4 shards) -- all 32 workers blocked for 15+ minutes with 0 transactions inserted, CPU 99.9% idle.

The root cause is that `skip(N)` on a sharded collection is `O(N)`: mongos must request documents from all shards in sorted order and advance through N documents in the merge-sorted stream before returning results. With 40M customers across 4 shards, `skip(20_000_000)` requires scanning ~20M documents.

The fix uses **hex-range boundaries** that leverage the known `CUST-{12hex}` customer_id format:

```python
def _hex_chunk_boundaries(total_chunks: int) -> list:
    HEX_MAX = 16 ** 12  # FFFFFFFFFFFF + 1
    boundaries = []
    for i in range(total_chunks):
        lo = (HEX_MAX * i) // total_chunks
        hi = (HEX_MAX * (i + 1)) // total_chunks
        lower = f"CUST-{lo:012X}"
        upper = f"CUST-{hi:012X}" if i < total_chunks - 1 else None
        boundaries.append((lower, upper))
    return boundaries
```

Each chunk queries its range with `{"customer_id": {"$gte": lower, "$lt": upper}}` -- an `O(1)` shard-targeted range scan (no sort, no skip). Since `customer_id` is the shard key, mongos routes each range query directly to the shard(s) owning that range.

Why this works:
- `secrets.token_hex(6)` generates uniformly distributed hex strings
- Dividing the hex keyspace (`000000000000` to `FFFFFFFFFFFF`) into N equal ranges gives roughly equal customer counts per chunk
- Range queries on the shard key are shard-targeted (O(1) routing)
- No sort required -- chunks process customers in natural order within their range

### Phase 4: Warm-to-Now (N workers)

Sets `rolling.z1_prev` to `now()` for `SEED_WARM_TO_NOW_PCT` (default 5%) of customers. These customers are ready for immediate fraud testing without a warmup transaction. Customer IDs are randomly sampled and split across workers for parallel `bulk_write`.

### Phase 5: Beneficiary Overflow (single process)

Seeds `pot_nb_overflow` entries for customers whose beneficiary lists exceed the embed limit (500). Single process because it depends on reading all customer IDs first.

### Phase 6: Consolidated txn_lookups (single process)

Seeds the `txn_lookups` collection. Single process, typically fast.

## Reset Script

**Always run reset before seeding** to ensure clean indexes and sharding:

```bash
# Full reset: drop all collections, recreate indexes, enable sharding, verify
python -m seed.reset_collections --force

# Preview what would happen
python -m seed.reset_collections --dry-run

# Skip drop, just apply sharding (if collections already exist with correct indexes)
python -m seed.reset_collections --shard-only

# Verify current state only
python -m seed.reset_collections --verify-only
```

Collections managed by reset (defined in `V2_COLLECTIONS`):
`customers`, `transactions`, `pot_bf`, `pot_bf24`, `pot_sm`, `pot_anj`, `pot_pp`, `pot_cb`, `pot_sl_va`, `pot_nb_overflow`, `txn_lookups`, `load_tests`

Sharded collections (defined in `app/indexes.py`):
| Collection | Shard Key | Unique |
|---|---|---|
| `customers` | `{ customer_id: 1 }` | Yes |
| `transactions` | `{ customer_id: 1, shard_key_month: 1, _id: 1 }` | No |
| `pot_nb_overflow` | `{ customer_id: 1, b2: 1 }` | Yes |

## Performance Expectations

### Phase 3 is the bottleneck

On a **c6i.16xlarge (64 vCPU)** with **32 workers** seeding 100M transactions:

- Phase 3 dominates total time (90%+ of wall clock).
- 32 workers give roughly **20-30x speedup** over single-process.
- Each worker generates ~3M transactions (100M / 32 workers), inserting in 10K batches.

### MongoDB connection count

```
32 workers x 10 maxPoolSize = 320 connections
```

Atlas M60 supports 10K concurrent connections -- 320 is well within limits.

### Memory per worker

Each worker loads one chunk of customers (up to `SEED_CHUNK_SIZE` = 500K) and maintains rolling state in memory. Expect **~500MB per worker** for a 500K-customer chunk. On a c6i.16xlarge (128 GB RAM), 32 workers at 500MB = ~16 GB, leaving ample headroom.

## Worker Count Guidance

| Environment | vCPU | Recommended Workers | Notes |
|---|---|---|---|
| Local dev | 8 | 4 (auto) | Default `cpu_count // 2` |
| c6i.4xlarge | 16 | 8 (auto) | |
| c6i.16xlarge | 64 | 32 | Best for production seeds |
| `--test` mode | any | 1 (forced) | Always single process |

- Workers are auto-capped to `min(num_workers, total_chunks)` -- more workers than chunks is wasteful.
- Default (`cpu_count // 2`) leaves headroom for MongoDB driver threads and OS.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SEED_CUSTOMERS` | 10,000 | Total customers to generate |
| `SEED_TRANSACTIONS` | 50,000 | Total transactions to generate |
| `SEED_BATCH_SIZE` | 10,000 | Customer insert batch size |
| `SEED_TXN_BATCH_SIZE` | 10,000 | Transaction insert batch size |
| `SEED_CUSTOMER_UPDATE_BATCH` | 5,000 | Bulk write batch for customer rolling state |
| `SEED_CHUNK_SIZE` | 500,000 | Customers per chunk in Phase 3 |
| `SEED_WARM_TO_NOW_PCT` | 0.05 | Fraction of customers with `z1_prev` set to now |
| `SEED_TIME_RANGE_DAYS` | 30 | Transaction time window |
| `SEED_MAX_TXNS_PER_CUSTOMER` | 100 | Cap per customer (prevents skew) |
| `SEED_COMPUTE_FRAUD_SCORES` | true | Set `false` for faster seeding when scores not needed |

## Typical Production Workflow

```bash
cd backend_v2

# 1. Reset collections (drop + indexes + sharding)
python -m seed.reset_collections --force

# 2. Seed (40M customers, 100M transactions, no fraud scores for speed)
SEED_CUSTOMERS=40000000 \
SEED_TRANSACTIONS=100000000 \
SEED_COMPUTE_FRAUD_SCORES=false \
python -m seed.main --workers 32

# 3. Verify
python -m seed.reset_collections --verify-only
```
