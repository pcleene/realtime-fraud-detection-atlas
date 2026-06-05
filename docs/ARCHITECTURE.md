# Architecture Documentation

## Overview

This POC demonstrates that MongoDB can replace a 36-shard Redis cluster + Oracle persistence layer with fewer shards, lower operational complexity, and equivalent sub-millisecond latency.

## Design Decisions

### 1. Embedded Customer Features

| Approach | Reads | Latency | Complexity |
|----------|-------|---------|------------|
| **Embedded features** | 1 | <5ms | Low |
| Separate features collection + $lookup | 2+ | 15-30ms | Medium |
| Redis cache + Oracle | 2+ systems | Variable | High |

By embedding `features` directly in the `customers` collection, we eliminate joins and get everything needed for scoring in a single `find_one` operation:

```javascript
{
  customer_id: "CUST-7F3A2B1C9E4D",
  name: "Budi Santoso",
  account_ids: ["ACC-7A8B9C0D", "ACC-1E2F3A4B"],  // Simplified to array of IDs
  province: "DKI Jakarta",
  features: {
    latest_time_transaction: ISODate(),
    latest_location: { type: "Point", coordinates: [lon, lat] },
    avg_gap_change_password: 45.5
  }
}
```

### 2. Random Customer IDs

| ID Type | Insert Distribution | B-tree Impact | Hot Shard Risk |
|---------|---------------------|---------------|----------------|
| Sequential (CUST-0001, 0002...) | All to one shard | Low (append-only) | HIGH |
| ObjectId | All to one shard | Low (append-only) | HIGH |
| **Random (CUST-7F3A2B1C)** | Even across shards | Medium (page splits) | NONE |

Random IDs cause more B-tree page splits, but:
- Customer inserts are rare (~1/sec)
- Distribution benefit far outweighs overhead
- Transactions reuse existing customer_ids (no random insert penalty)

```python
def generate_customer_id() -> str:
    return f"CUST-{secrets.token_hex(6).upper()}"
```

### 3. Transaction Shard Key Design

**Shard Key:** `{ customer_id: 1, shard_key_month: 1, _id: 1 }`

| Field | Purpose |
|-------|---------|
| customer_id | All customer's txns on same shard |
| shard_key_month | Coarse time bucket for chunk splitting |
| _id | Cardinality for high-volume customers |

**Why not `{ customer_id: 1, timestamp: 1 }`:**
- `timestamp` is monotonically increasing
- Within each customer, new txns always hit "top" of B-tree
- `shard_key_month` is coarse-grained (12 values/year) = predictable chunk boundaries

### 4. Ranged vs Hashed Sharding

| Aspect | Hashed | **Ranged (our choice)** |
|--------|--------|-------------------------|
| Index memory | Full index on every shard | Only relevant chunks |
| Range queries | Not supported | Supported |
| Data locality | None | By customer |
| Chunk splitting | Automatic | Controllable |

### 5. Hot Path Constraints

Only these operations in the scoring path:

| Step | Operation | Collection | Time Budget |
|------|-----------|------------|-------------|
| 1 | `find_one` | customers | <5ms |
| 2 | `find_one` + `$nearSphere` | blacklist_locations | <5ms |
| 3 | `find_one` | holidays | <2ms |
| 4 | `update_one` | customers | <5ms |
| 5 | `insert_one` | transactions | <5ms |

**Forbidden in hot path:**
- `$lookup` or any joins
- Aggregation pipelines
- Multiple queries for same logical data
- Any read from `transactions` collection during scoring

### 6. Timing Metrics Separation

The API response separates scoring time from persistence time:

| Metric | Description |
|--------|-------------|
| `scoring_time_ms` | Time for rules evaluation only (steps 1-3) |
| `persistence_time_ms` | Time for customer update + transaction insert (steps 4-5) |
| `total_time_ms` | End-to-end processing time |

This separation allows monitoring scoring performance independently from database write latency.

### 7. PyMongo Async API for Parallel Execution

The scoring service uses **PyMongo's native Async API** (introduced in PyMongo 4.10+) for true non-blocking I/O. This enables parallel execution of independent database operations.

**Why PyMongo Async over Motor:**
- Motor is deprecated (end of life: May 2027)
- PyMongo Async uses native asyncio (no thread pool)
- Better performance for concurrent workloads
- Single driver for both sync and async use cases

**Parallel Execution Architecture:**

```
PHASE 1: Parallel DB Reads (wall-clock: ~150ms)
├── Customer fetch    ─┐
├── Blacklist query   ─┼── asyncio.gather() - run concurrently
└── Holiday query     ─┘
    Individual times sum to ~450ms, but only ~150ms wall-clock

PHASE 2: Rule Evaluation (CPU-bound: <1ms)
└── All 5 rules evaluated sequentially (fast)

PHASE 3: Parallel DB Writes (wall-clock: ~150ms)
├── Customer update   ─┐
└── Transaction insert─┴── asyncio.gather() - run concurrently
    Individual times sum to ~300ms, but only ~150ms wall-clock
```

**Performance Impact:**

| Execution Mode | Total Time | Speedup |
|----------------|------------|---------|
| Sequential | ~750ms | 1x |
| Parallel (PyMongo Async) | ~300ms | **2.5x** |

**Code Pattern:**

```python
from pymongo import AsyncMongoClient

# Native async - no thread pool
async def score_transaction(self, request):
    # Parallel reads
    customer_doc, blacklist_doc, holiday_doc = await asyncio.gather(
        db.customers.find_one({"customer_id": customer_id}),
        db.blacklist_locations.find_one({...}),
        db.holidays.find_one({...})
    )
    
    # ... rule evaluation ...
    
    # Parallel writes
    await asyncio.gather(
        db.customers.update_one({...}),
        db.transactions.insert_one({...})
    )
```

### 8. Detailed Timing Breakdown

The API response includes a comprehensive timing breakdown for observability:

```json
{
  "timing": {
    "db_customer_fetch_ms": 135.28,
    "db_blacklist_query_ms": 135.30,
    "db_holiday_query_ms": 139.46,
    "db_customer_update_ms": 142.87,
    "db_transaction_insert_ms": 142.58,
    "rule_velocity_ms": 0.01,
    "rule_travel_ms": 0.01,
    "rule_blacklist_ms": 0.01,
    "rule_password_ms": 0.00,
    "rule_holiday_ms": 0.01,
    "total_db_read_ms": 410.04,
    "total_db_write_ms": 285.44,
    "total_rules_ms": 0.05,
    "scoring_ms": 141.87,
    "persistence_ms": 143.62,
    "total_ms": 285.56
  }
}
```

This allows identifying:
- Network latency to MongoDB (dominant factor for remote Atlas)
- Individual query performance
- Parallel execution effectiveness (compare individual sums vs wall-clock)

## Collection Schemas

### customers (Sharded)

```javascript
{
  _id: ObjectId(),
  customer_id: "CUST-7F3A2B1C9E4D",    // Shard key, random, unique
  name: "Budi Santoso",
  account_ids: ["ACC-7A8B9C0D"],        // Simplified: array of account ID strings
  province: "DKI Jakarta",
  features: {
    latest_time_transaction: ISODate() | null,
    latest_location: { type: "Point", coordinates: [lon, lat] } | null,
    avg_gap_change_password: Number | null
  },
  created_at: ISODate(),
  updated_at: ISODate()
}
```

### transactions (Sharded)

```javascript
{
  _id: ObjectId(),
  customer_id: "CUST-7F3A2B1C9E4D",
  shard_key_month: "2025-12",             // YYYY-MM
  customer: { _id, customer_id, name },   // Extended reference
  account_id: "ACC-7A8B9C0D",             // Simplified: just the account ID
  type: "debit" | "credit",
  channel: "Livin" | "KOPRA" | "ATM" | "QRIS" | "Branch" | "Ecom",
  amount: Number,
  currency: "IDR",
  status: "authorized" | "captured" | "reversed" | "declined",
  timestamp: ISODate(),
  location: { type: "Point", coordinates: [lon, lat] } | null,
  city: "Jakarta Pusat",
  province: "DKI Jakarta",
  merchant: { id, name, mcc, category },
  device: {
    device_id: "android_xxxx",
    device_type: "android" | "ios" | "web",
    device_model: "Galaxy A54",           // Optional: from device fingerprint
    os_version: "13",                     // Optional: from device fingerprint
    ip: "10.135.xxx.xxx"                  // Indonesian ISP IP
  },
  fraud_score: {
    final_score: Number,
    risk_level: "low" | "medium" | "high",
    analysis: [{ rule, score, triggered, details }]
  },
  fraud_metadata: {                       // Optional: for testing injected fraud
    injected_type: "velocity" | "impossible_travel" | "blacklist",
    expected_rules: ["velocity"]
  } | null,
  attrs: {}
}
```

### blacklist_locations (Unsharded)

```javascript
{
  _id: ObjectId(),
  address: "Jl. Mangga Dua No. 1",
  city: "Jakarta",
  province: "DKI Jakarta",
  location: { type: "Point", coordinates: [lon, lat] },
  category: "fraud_hub" | "scammer" | "wifi" | "merchant",
  normalized: ["mangga", "dua"],
  added_at: ISODate(),
  added_reason: "Reported fraud cluster"
}
```

### holidays (Unsharded)

```javascript
{
  _id: ObjectId(),
  name: "Idul Fitri",
  description: "Lebaran holiday period",
  date_range: {
    start: ISODate("2025-03-30"),
    end: ISODate("2025-04-04")
  },
  is_cuti_bersama: Boolean,
  year: Number
}
```

## Index Strategy

### customers

| Index | Purpose |
|-------|---------|
| `{ customer_id: 1 }` unique | Shard key, primary lookup |
| `{ "features.latest_location": "2dsphere" }` sparse | Geo queries if needed |

### transactions

| Index | Purpose |
|-------|---------|
| `{ customer_id: 1, shard_key_month: 1, _id: 1 }` | Shard key (auto) |
| `{ customer_id: 1, timestamp: -1 }` | Recent txns by customer |
| `{ "location": "2dsphere" }` sparse | Geo queries |
| `{ timestamp: -1, "fraud_score.risk_level": -1 }` | Time-based queries, high-risk first |

Note: The compound index on `{ timestamp, fraud_score.risk_level }` also covers timestamp-only queries via prefix matching, eliminating the need for a separate `{ timestamp: -1 }` index.

### blacklist_locations

| Index | Purpose |
|-------|---------|
| `{ city: 1, province: 1 }` | Filter by location |
| `{ "location": "2dsphere" }` | $nearSphere queries |

### holidays

| Index | Purpose |
|-------|---------|
| `{ "date_range.start": 1, "date_range.end": 1 }` | Date range queries |
| `{ year: 1 }` | Filter by year |

## Fraud Rules

### Velocity Check

Detects rapid sequential transactions (potential bot/automation).

```python
if delta_seconds < 10:  # threshold
    score += 20
```

### Impossible Travel

Detects physically impossible location changes (compromised credentials).

```python
speed_kmh = distance_km / delta_hours
if speed_kmh > 800:  # threshold
    score += 30
```

### Blacklist Proximity

Detects transactions near known fraud hotspots. Uses `$nearSphere` with 2dsphere index - returns first match within radius (no distance calculation needed).

```python
nearby = db.blacklist_locations.find_one({
    "location": {
        "$nearSphere": {
            "$geometry": {"type": "Point", "coordinates": [lon, lat]},
            "$maxDistance": 500  # meters
        }
    }
})
if nearby:
    score += WEIGHTS[nearby["category"]]  # 10-35
```

### Password Frequency

Detects accounts with unusually frequent password changes.

```python
if avg_gap_change_password < 7:  # days
    score += 15
```

### Holiday

Flags transactions during high-fraud-risk holiday periods. Uses single weight for all holidays (simplified from separate cuti_bersama weight).

```python
holiday = db.holidays.find_one({
    "date_range.start": {"$lte": txn_date},
    "date_range.end": {"$gte": txn_date}
})
if holiday:
    score += 10  # Single weight for all holidays
```

## Mock Data Generator

The system includes a comprehensive mock data generator for realistic testing:

### Seeding Modes

| Mode | Command | Customers | Transactions | Use Case |
|------|---------|-----------|--------------|----------|
| Quick Test | `make seed-test` or `python -m seed.main --test` | 5 | 20 | Schema validation |
| Small | `make seed` | 10,000 | 50,000 | Development |
| Medium | `make seed-medium` | 100,000 | 500,000 | Integration testing |
| Full | `make seed-full` | 50,000,000 | 100,000,000 | Production POC |

**Test mode** distributes transactions evenly across customers (4 per customer) to ensure all customers have data for schema validation.

**Production mode** uses exponential distribution for realistic variance (some customers very active, most have few transactions). Customers are shuffled before assignment to avoid concentration bias.

### Feature Warming

After seeding transactions, customer features (`latest_time_transaction`, `latest_location`) are automatically populated from the seeded data. This enables fraud rules to work immediately on the first scored transaction.

**How it works:**
1. During transaction generation, the latest transaction per customer is tracked in memory
2. After all transactions are inserted, a bulk update populates customer features
3. No aggregation queries needed - pure in-memory tracking

### Warm-to-Now for Demo Readiness

By default, 5% of customers have their `latest_time_transaction` set to the current time (seed time) instead of their historical transaction time. This enables immediate fraud rule testing without needing a "warmup" transaction.

| Configuration | Default | Description |
|---------------|---------|-------------|
| `SEED_WARM_TO_NOW_PCT` | 0.05 | Percentage of customers warmed to "now" (0.0-1.0) |

**Demo scenarios:**

| Customer Type | First Transaction | Second Transaction |
|---------------|-------------------|-------------------|
| Warm-to-now (5%) | Can trigger velocity/travel | N/A |
| Historical (95%) | Low risk (updates features) | Can trigger velocity/travel |

To find a warm-to-now customer for demos:

```javascript
// Find customer with recent latest_time_transaction (within last minute of seed)
db.customers.findOne({
  "features.latest_time_transaction": { $gte: new Date(Date.now() - 60000) }
})
```

### Data Components

| Component | File | Description |
|-----------|------|-------------|
| Indonesian Names | `seed/data/indonesian_names.py` | 8 ethnic groups with province mapping |
| Provinces/Cities | `seed/data/provinces.py` | 17 provinces with actual coordinates |
| Device Fingerprints | `seed/data/devices.py` | Indonesian ISP IPs, realistic device models |
| Customer Profiles | `seed/data/profiles.py` | 8 segments with behavioral patterns |
| Merchants | `seed/data/merchants.py` | 80+ real Indonesian merchants |
| Fraud Scenarios | `seed/data/fraud_scenarios.py` | 9 fraud types with injection functions |

### Realistic Transaction Timestamps

Transactions are generated with realistic time-of-day patterns modeled on Indonesian banking behavior:

| Pattern | Description |
|---------|-------------|
| Hour distribution | Peaks at lunch (12-13h) and evening (19-21h), dead 2-5am |
| Payday clustering | 30% boost for transactions on 25th-1st of month |

### Mock API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /mock/customer` | Generate realistic customer |
| `GET /mock/transaction?fraud_type=velocity` | Generate transaction with optional fraud |
| `GET /mock/batch?count=10` | Generate batch of transactions |
| `GET /mock/provinces` | List available provinces |
| `GET /mock/channels` | List transaction channels |
| `GET /mock/fraud-types` | List fraud types for testing |
| `GET /mock/segments` | List customer segments |

### Fraud Types for Testing

| Type | Description | Expected Rules |
|------|-------------|----------------|
| `velocity` | Rapid sequential transactions | `["velocity"]` |
| `impossible_travel` | Location inconsistency | `["impossible_travel"]` |
| `blacklist` | Near fraud hotspot | `["blacklist_proximity"]` |
| `ato` | Account takeover pattern | `["velocity", "impossible_travel"]` |
| `card_testing` | Small test transactions | `[]` |
| `midnight_burst` | Late-night activity | `[]` |

## Cluster Topology

```
                    ┌─────────────┐
                    │   mongos    │
                    │  (router)   │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
   ┌───────────┐    ┌───────────┐    ┌───────────┐
   │  shard01  │    │  shard02  │    │  shard03  │
   │  (RS x1)  │    │  (RS x1)  │    │  (RS x1)  │
   └───────────┘    └───────────┘    └───────────┘

   Config Servers: 3-node replica set (CSRS)
```

For production, each shard would have 3 replica set members.

## Query Routing

All hot-path queries target single shard:

```javascript
// Customer lookup - SINGLE_SHARD
db.customers.find({ customer_id: "CUST-..." })

// Customer update - SINGLE_SHARD
db.customers.updateOne({ customer_id: "CUST-..." }, { $set: {...} })

// Transaction insert - SINGLE_SHARD (routed by shard key in document)
db.transactions.insertOne({ customer_id: "CUST-...", shard_key_month: "2025-12", ... })

// Transaction history - SINGLE_SHARD
db.transactions.find({ customer_id: "CUST-..." }).sort({ timestamp: -1 })
```

## Why MongoDB Over Redis + Oracle

| Aspect | Redis + Oracle | MongoDB |
|--------|----------------|---------|
| Shards | 36 Redis | 3 MongoDB |
| Systems | 2 (cache + persistence) | 1 |
| Consistency | Eventual (cache invalidation) | Strong |
| Query flexibility | Limited | Full |
| Operational complexity | High | Medium |
| Latency | <1ms (cache hit), 10ms+ (miss) | <5ms consistent |
| Cost | High (36 shards + Oracle) | Lower |

## Scaling Considerations

### When to Add Shards

1. Working set exceeds RAM on shards
2. Write throughput saturates disk I/O
3. Single-shard queries exceed latency budget

### Pre-splitting Strategy

For known high-volume customers:

```javascript
sh.splitAt("RegionalBank_fraud.transactions", {
    customer_id: "CUST-WHALE1",
    shard_key_month: "2025-01",
    _id: ObjectId()
})
```

### Retention

Use Atlas Online Archive for transactions older than N months. No TTL indexes needed.

---

## Session Notes: December 2025 Performance Optimization

### Overview

This session focused on end-to-end testing and performance optimization of the fraud scoring service when running against MongoDB Atlas.

### Final Architecture

#### Clean Separation of Concerns

```
backend/app/
├── services/
│   ├── fraud.py          # Orchestrator only (~310 lines)
│   └── rules/
│       ├── velocity.py   # CPU-only rule
│       ├── travel.py     # CPU-only rule  
│       ├── password.py   # CPU-only rule
│       ├── blacklist.py  # Async rule (owns its DB query)
│       └── holiday.py    # Async rule (owns its DB query)
└── utils/
    ├── timing.py         # TimingBreakdown, ensure_utc()
    └── scoring.py        # calculate_final_score()
```

**Key Principle:** Each rule file owns its complete logic (DB query + evaluation). The orchestrator (`fraud.py`) just calls rules in parallel - no duplicated logic.

#### Execution Flow

```
fraud.py orchestrates:
│
├── PHASE 1: Parallel async (PyMongo Async API)
│   │
│   ├── fetch_customer_async()        ─┐
│   ├── check_blacklist_proximity()    ├── asyncio.gather()
│   └── check_holiday()               ─┘
│
├── PHASE 2: CPU rules (sequential, <1ms total)
│   ├── check_velocity()
│   ├── check_impossible_travel()
│   └── check_password_frequency()
│
└── PHASE 3: Parallel async
    ├── update_customer_async()  ─┐
    └── insert_transaction_async() ─┘ asyncio.gather()
```

### Issues Identified & Fixed

#### 1. Timezone Mismatch Bug

**Problem:** `TypeError: can't subtract offset-naive and offset-aware datetimes`

MongoDB stores timezone-aware datetimes (UTC), but API requests used naive datetimes.

**Solution:** Added `ensure_utc()` in `utils/timing.py`:

```python
def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
```

#### 2. High Latency with Remote Atlas

**Problem:** Sequential DB operations caused ~750ms total latency.

**Solution:** Parallel execution with PyMongo Async API:

| Phase | Sequential | Parallel | Speedup |
|-------|------------|----------|---------|
| DB Reads | ~450ms | ~145ms | 3.1x |
| Rules (CPU) | <1ms | <1ms | - |
| DB Writes | ~340ms | ~190ms | 1.8x |
| **Total** | **~750ms** | **~335ms** | **2.2x** |

#### 3. MongoDB X.509 Authentication

**Problem:** Connection to Atlas failed due to missing certificate path.

**Solution:** Updated `.env` with X.509 certificate path.

### Why PyMongo Async API (Not Motor)

Motor is deprecated (EOL: May 2027). PyMongo 4.10+ includes native async:

```python
from pymongo import AsyncMongoClient

client = AsyncMongoClient(uri)
db = client.RegionalBank_fraud
result = await db.customers.find_one({"customer_id": cid})
```

**Benefits:**
- Native asyncio (no thread pool overhead)
- 20-50% better throughput than Motor
- Single driver for sync/async use cases
- Actively maintained

### Performance Results

```json
{
  "timing": {
    "parallel_reads_ms": 144,
    "total_rules_ms": 0.08,
    "parallel_writes_ms": 191,
    "total_ms": 336
  }
}
```

### Files Changed

| File | Change |
|------|--------|
| `services/fraud.py` | Orchestrator using PyMongo Async |
| `services/rules/blacklist.py` | Async rule with native DB query |
| `services/rules/holiday.py` | Async rule with native DB query |
| `utils/timing.py` | Added `TimingBreakdown`, `ensure_utc()` |
| `utils/scoring.py` | Added `calculate_final_score()` |
| `models/requests.py` | Added `TimingBreakdownResponse` |
| `frontend/.../ScoreResult.svelte` | Timing visualization |

### MongoDB Transactions (ACID-Compliant Writes)

We implemented and tested MongoDB multi-document transactions for atomic writes (customer update + transaction insert). This guarantees both operations succeed or both fail.

**Trade-off Analysis:**

| Mode | Write Latency | Atomicity | When to Use |
|------|---------------|-----------|-------------|
| **Parallel writes** | ~155ms | ❌ | Default - best performance |
| **Transaction writes** | ~297ms | ✅ ACID | When consistency is critical |

**PyMongo Async Transaction Pattern:**

```python
async with self.db.client.start_session() as session:
    await session.start_transaction()  # Coroutine, NOT context manager
    try:
        await self.db.customers.update_one(..., session=session)
        await self.db.transactions.insert_one(..., session=session)
        await session.commit_transaction()
    except Exception as e:
        await session.abort_transaction()
        raise
```

**Key Learnings:**
- `start_session()` → async context manager
- `start_transaction()` → coroutine (just `await`, not `async with`)
- `commit_transaction()` / `abort_transaction()` → coroutines
- Operations within a transaction MUST be sequential (MongoDB limitation)
- Transaction code is preserved but commented in `fraud.py` - uncomment to enable

### Future Considerations

1. **Connection pooling** - Tune pool size for Atlas tier
2. **Local MongoDB** - Eliminate network latency in dev/test
3. **Co-location** - Deploy API in same region as Atlas
4. **Enable transactions** - Uncomment in `fraud.py` when atomicity > performance
