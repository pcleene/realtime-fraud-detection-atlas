# MongoDB Performance Optimizations

This document covers the performance optimizations implemented to achieve sub-50ms scoring latency at 10K+ TPS on MongoDB Atlas.

## Table of Contents

1. [Overview](#overview)
2. [In-Memory Caching](#in-memory-caching)
   - [Holiday Cache](#holiday-cache)
   - [Blacklist Location Cache](#blacklist-location-cache)
   - [Cache Toggle](#cache-toggle)
3. [Connection Pool Optimization](#connection-pool-optimization)
4. [Customer Sampling for Load Tests](#customer-sampling-for-load-tests)
5. [Write Contention Analysis](#write-contention-analysis)

---

## Overview

The fraud scoring hot path is constrained to 5 MongoDB operations:

| Operation | Collection | Type | Target Latency |
|-----------|------------|------|----------------|
| 1. Fetch customer with features | `customers` | Read | < 5ms |
| 2. Geospatial blacklist check | `blacklist_locations` | Read | < 5ms |
| 3. Holiday date check | `holidays` | Read | < 2ms |
| 4. Update customer features | `customers` | Write | < 5ms |
| 5. Insert transaction | `transactions` | Write | < 5ms |

**Total target: < 50ms** (including HTTP overhead, serialization, rule evaluation)

### Optimization Strategy

To minimize MongoDB round-trips and reduce P99 latency:

1. **Cache static reference data** - Holidays and blacklist locations rarely change
2. **Optimize connection pooling** - Pre-warm connections, use compression
3. **Even shard distribution** - Chunk-based customer sampling for load tests
4. **Minimize write contention** - Scale customer pool with TPS

---

## In-Memory Caching

### Holiday Cache

**File:** `backend/app/cache.py`
**Commit:** `5c11162` - feat: Add in-memory cache for holidays collection

Holidays are static reference data that changes rarely (once per year). Instead of querying MongoDB on every transaction, we cache all holidays in memory.

```python
# Cache structure
_holiday_cache: Dict[str, Any] = {
    "holidays": [],        # List of Holiday documents
    "loaded_at": None,     # datetime when cache was populated
}

# TTL: 10 minutes (configurable via CACHE_TTL_SECONDS)
```

**How it works:**
1. On first request, load all holidays from MongoDB into memory
2. For each transaction, check if `timestamp` falls within any cached holiday's date range
3. Cache expires after TTL; next request refreshes from MongoDB

**Impact:**
- Eliminates 1 MongoDB query per transaction
- Holiday check: ~0.1ms (in-memory) vs ~2ms (MongoDB)
- Savings at 10K TPS: **20 seconds of latency/second**

### Blacklist Location Cache

**File:** `backend/app/cache.py`
**Commit:** `95c8bbf` - feat: Add blacklist location caching with haversine distance

Blacklist locations are fraud hotspots stored with geospatial coordinates. The original implementation used MongoDB's `$nearSphere` operator, which requires a database query per transaction.

The optimized version loads all blacklist locations into memory and performs distance calculations using the Haversine formula.

```python
# Cache structure
_blacklist_cache: Dict[str, Any] = {
    "locations": [],       # List of BlacklistLocation documents
    "loaded_at": None,     # datetime when cache was populated
}

# Haversine distance calculation (in-memory)
def haversine_distance(lat1, lon1, lat2, lon2) -> float:
    """Calculate great-circle distance in meters."""
    R = 6371000  # Earth's radius in meters
    # ... spherical law of cosines
    return distance_meters
```

**How it works:**
1. On first request, load all blacklist locations from MongoDB
2. For each transaction, iterate through cached locations and calculate distance
3. Find nearest location within radius (default: 500m)
4. Cache expires after TTL; refreshes from MongoDB

**Impact:**
- Eliminates 1 geospatial query per transaction
- Blacklist check: ~0.5ms (in-memory) vs ~5ms (MongoDB with 2dsphere index)
- Savings at 10K TPS: **45 seconds of latency/second**

### Cache Toggle

**File:** `backend/app/config.py`
**Commit:** `b143369` - feat: Add USE_CACHE toggle to preserve original MongoDB queries

For benchmarking and A/B testing, a toggle was added to disable caching and use original MongoDB queries.

```python
# Environment variable
USE_CACHE=true   # Use in-memory cache (default)
USE_CACHE=false  # Use MongoDB queries (for comparison)
```

**Usage:**
```bash
# Benchmark with cache
USE_CACHE=true make dev

# Benchmark without cache (original behavior)
USE_CACHE=false make dev
```

### Cache Statistics

The `/health/detailed` endpoint exposes cache statistics:

```json
{
  "cache_stats": {
    "holidays_cached": 15,
    "blacklist_cached": 25,
    "cache_ttl_seconds": 600
  }
}
```

---

## Connection Pool Optimization

**File:** `backend/app/db.py`
**Commit:** `754b216` - feat: Add connection pool optimization and query projections

MongoDB connection pooling was optimized for high-throughput workloads.

### Connection Pool Settings

```python
# Optimized for 10K+ TPS
AsyncMongoClient(
    uri,
    maxPoolSize=200,          # Max connections per node
    minPoolSize=10,           # Pre-warmed connections
    maxIdleTimeMS=60000,      # Keep connections alive 60s
    waitQueueTimeoutMS=5000,  # Fail fast if pool exhausted
    compressors=["zstd"],     # Compression for Atlas PrivateLink
    retryWrites=True,         # Auto-retry transient failures
    readPreference="primaryPreferred",  # Read from primary, fallback to secondary
)
```

### Key Optimizations

| Setting | Value | Rationale |
|---------|-------|-----------|
| `maxPoolSize` | 200 | Support 200 concurrent requests per process |
| `minPoolSize` | 10 | Pre-warm connections to avoid cold-start latency |
| `maxIdleTimeMS` | 60000 | Keep connections alive during low traffic |
| `compressors` | zstd | ~30% bandwidth reduction over PrivateLink |
| `retryWrites` | true | Automatic retry on primary election |

### Query Projections

All queries now use projections to fetch only required fields:

```python
# Before (fetches entire document)
await db.customers.find_one({"customer_id": cid})

# After (fetches only needed fields)
await db.customers.find_one(
    {"customer_id": cid},
    {"customer_id": 1, "account_ids": 1, "features": 1}
)
```

**Impact:**
- Reduces network transfer by ~60% for customer documents
- Particularly effective over PrivateLink where bandwidth matters

### Pool Statistics

The `/health/detailed` endpoint exposes pool statistics:

```json
{
  "pool_stats": {
    "topology_type": "ReplicaSetWithPrimary",
    "nodes": 3,
    "max_pool_size": 200,
    "min_pool_size": 10,
    "max_idle_time_ms": 60000,
    "compression": "zstd",
    "read_preference": "primaryPreferred"
  }
}
```

---

## Customer Sampling for Load Tests

**File:** `backend/app/services/customer_sampling.py`
**Commit:** `071b13d` - feat: Add chunk-based customer sampling for even shard distribution

When load testing against a sharded MongoDB cluster, customer selection significantly impacts benchmark accuracy. Random sampling can concentrate traffic on a single shard, causing artificial hotspots.

### Sampling Strategies

#### 1. Chunk-Based Sampling (Default)

Samples customers proportionally from each MongoDB chunk to ensure even shard distribution.

```python
# How it works:
# 1. Query config.collections to get collection UUID (MongoDB 5.0+)
# 2. Query config.chunks by UUID for chunk boundaries
# 3. Calculate samples per chunk: total_size / num_chunks
# 4. Sample from each chunk using $match + $sample
# 5. Shuffle results for random access order

customers = await get_sampled_customers(
    db,
    size=10000,
    method="chunk_based",  # Default
)
```

**MongoDB 5.0+ UUID-based chunks:**

MongoDB 5.0+ changed from namespace-based (`ns`) to UUID-based chunk storage. The implementation first queries `config.collections` to get the collection UUID, then queries `config.chunks` by that UUID. Falls back to `ns`-based query for older MongoDB versions.

**Example distribution (3 shards, 6 chunks):**
```
Shard 0: Chunk 0-1 → 1667 + 1667 = 3334 customers
Shard 1: Chunk 2-3 → 1667 + 1667 = 3334 customers
Shard 2: Chunk 4-5 → 1666 + 1666 = 3332 customers
Total: 10000 customers evenly distributed
```

#### 2. Random Sampling (Fallback)

Uses MongoDB's `$sample` aggregation. Simple but can concentrate on one shard.

```python
# Fallback when chunk-based fails or explicitly requested
customers = await get_sampled_customers(
    db,
    size=10000,
    method="random",
)
```

### Customer Pool Caching

Sampled customers are cached to ensure consistency across test runs:

```python
# Cache configuration
CUSTOMER_CACHE_TTL = 3600  # 1 hour

# Cache key includes: size + method
# Different size or method = new sample
```

**Cache endpoints:**
- `GET /loadtest/customer-pool` - Get sampled customers
- `GET /loadtest/customer-pool/stats` - View cache statistics
- `POST /loadtest/customer-pool/invalidate` - Force refresh

### Load Test Configuration

```python
class LoadTestConfig(BaseModel):
    target_tps: int = 100                    # Target transactions per second
    customer_pool_size: Optional[int] = None # Default: auto-calculated
    sampling_method: str = "chunk_based"     # or "random"
    force_refresh_customers: bool = False    # Bypass cache
```

**Pool size auto-calculation:**
```
pool_size = min(target_tps * 10, 10000)

Examples:
- 100 TPS  → 1000 customers  → 0.1 writes/sec/customer
- 1000 TPS → 10000 customers → 0.1 writes/sec/customer
- 10000 TPS → 10000 customers → 1 write/sec/customer
```

---

## Write Contention Analysis

### The Problem

Each transaction updates a customer document:
```python
# Update customer features after scoring
await db.customers.update_one(
    {"customer_id": cid},
    {"$set": {
        "features.latest_time_transaction": timestamp,
        "features.latest_location": [lon, lat]
    }}
)
```

MongoDB uses **document-level locking**. If multiple transactions target the same customer simultaneously, they queue up.

### Write Contention Math

| Customers | TPS | Writes/sec/customer | Lock time/sec | Contention |
|-----------|-----|---------------------|---------------|------------|
| 1,000 | 10,000 | 10 | 50ms (5%) | **High** |
| 5,000 | 10,000 | 2 | 10ms (1%) | Medium |
| 10,000 | 10,000 | 1 | 5ms (0.5%) | **Optimal** |

**Formula:**
```
writes_per_sec_per_customer = TPS / customer_count
lock_time_per_sec = writes_per_sec_per_customer × 5ms
contention_pct = lock_time_per_sec / 1000ms × 100
```

### Why 10K Customers?

At 10K TPS with 10K customers:
- 1 write/sec/customer
- 5ms lock time per second per document (0.5% contention)
- Each customer updated once per second on average

This matches realistic production patterns where customers don't transact multiple times per second.

### Impact on Velocity Rule

The velocity rule triggers when consecutive transactions are < 10 seconds apart:

| Customers | TPS | Avg gap between same-customer transactions |
|-----------|-----|-------------------------------------------|
| 1,000 | 10,000 | 100ms (constant velocity triggers) |
| 10,000 | 10,000 | 1000ms (realistic gaps) |

With 1K customers at 10K TPS, the velocity rule triggers on nearly every transaction (unrealistic). With 10K customers, gaps are ~1 second, which is more realistic but still below the 10-second threshold.

### Recommendations

1. **For realistic benchmarks:** Use 10K+ customers at high TPS
2. **For velocity rule testing:** Use smaller pool or inject fraud scenarios
3. **For write contention testing:** Vary pool size and monitor P99 latency

---

## Summary of Commits

| Commit | Description | Impact |
|--------|-------------|--------|
| `5c11162` | Holiday caching | -2ms/txn |
| `95c8bbf` | Blacklist caching with haversine | -5ms/txn |
| `b143369` | USE_CACHE toggle | A/B testing capability |
| `754b216` | Connection pool + projections | -30% bandwidth, warm connections |
| `071b13d` | Chunk-based customer sampling | Even shard distribution |
| `622187b` | Configurable pool size + write contention logging | Visibility into lock contention |
| `9aadc06` | UUID-based chunk queries for MongoDB 5.0+ | Fix chunk-based sampling on Atlas |

**Total latency reduction:** ~7-10ms per transaction (from caching alone)

---

## Quick Reference

### Enable/Disable Caching
```bash
USE_CACHE=true make dev   # With cache (default)
USE_CACHE=false make dev  # Without cache
```

### View Cache Statistics
```bash
curl http://localhost:8000/health/detailed | jq '.cache_stats'
```

### Load Test with Chunk-Based Sampling
```bash
curl -X POST http://localhost:8000/loadtest/start \
  -H "Content-Type: application/json" \
  -d '{
    "target_tps": 1000,
    "duration_seconds": 60,
    "customer_pool_size": 10000,
    "sampling_method": "chunk_based"
  }'
```

### Invalidate Customer Cache
```bash
curl -X POST http://localhost:8000/loadtest/customer-pool/invalidate
```
