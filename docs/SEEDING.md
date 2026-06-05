# Production Data Seeding Guide

This document covers seeding the MongoDB Atlas cluster with production-scale data for the RegionalBank Fraud Detection POC.

## Production Seeding Results (January 2026)

### Final Data Counts

| Collection | Count | Size | Notes |
|------------|-------|------|-------|
| **customers** | 35,000,000 | 11.44 GiB | Matches RegionalBank's actual customer count |
| **transactions** | 67,733,909 | 45.27 GiB | ~1.9 transactions per customer |
| **blacklist_locations** | 100 | <1 MB | Fraud hotspots across Indonesia |
| **holidays** | 30 | <1 MB | Indonesian holidays for 2024-2026 |

### Shard Distribution

**Customers (5 chunks):**

| Shard | Docs | % | Data |
|-------|------|---|------|
| config | 12,051,813 | 34.43% | 3.94 GiB |
| shard-1 | 11,600,385 | 33.14% | 3.79 GiB |
| shard-0 | 11,347,802 | 32.42% | 3.71 GiB |

**Transactions (6 chunks):**

| Shard | Docs | % | Data |
|-------|------|---|------|
| config | 22,811,415 | 33.67% | 15.24 GiB |
| shard-1 | 22,494,820 | 33.21% | 15.03 GiB |
| shard-0 | 22,427,674 | 33.11% | 14.99 GiB |

### Feature Warming Status

| Metric | Count | Notes |
|--------|-------|-------|
| **Total customers** | 35,000,000 | All have features populated |
| **With features** | 35,000,000 (100%) | `latest_time_transaction` + `latest_location` |
| **Warm-to-now** | ~2,000,000 (5.7%) | Ready for immediate fraud rule testing |

---

## Seeding Commands

### Quick Reference

```bash
# From EC2 instance (via SSM or SSH)
cd /home/ssm-user/RegionalBank_fraud_detection

# Reset collections (drops and recreates indexes/shard keys)
docker compose run --rm api python -m seed.reset_collections

# Seed production data (35M customers, 70M transactions)
SEED_CUSTOMERS=35000000 SEED_TRANSACTIONS=70000000 \
  docker compose run --rm api python -m seed.main

# Seed smaller test data
SEED_CUSTOMERS=100000 SEED_TRANSACTIONS=200000 \
  docker compose run --rm api python -m seed.main
```

### Makefile Targets

```bash
make seed-reset        # Drop collections, recreate indexes
make seed-test         # 5 customers, 20 transactions (quick validation)
make seed              # 10K customers, 50K transactions
make seed-medium       # 100K customers, 500K transactions
```

---

## Seeding Phases

The seed script (`backend/seed/main.py`) runs in three phases:

### Phase 1: Seed Customers

- Creates customer documents with embedded features structure
- Uses random hex IDs (`CUST-{hex12}`) for even shard distribution
- Includes realistic Indonesian demographic data (names, provinces, cities)
- Rate: ~22,000-23,000 customers/sec

### Phase 2: Stream & Seed Transactions

- Streams customers from database in batches
- Generates transactions using exponential distribution (some customers more active)
- Each customer gets at least 1 transaction (`max(1, expovariate(...))`)
- Tracks latest transaction per customer for Phase 3
- Rate: ~7,400-7,800 transactions/sec

### Phase 3: Warm Customer Features

- Bulk updates all customers with their latest transaction timestamp and location
- 5% of customers get "warm-to-now" timestamps (for immediate fraud testing)
- Rate: ~2,600 updates/sec
- **This phase takes the longest** (~2 hours for 35M customers)

---

## Warm-to-Now Customers

### What It Does

During Phase 3, 5% of customers get their `features.latest_time_transaction` set to the seed run time instead of their historical transaction time.

| Customer Type | last_time_transaction | First Load Test Txn | Triggers Velocity? |
|---------------|----------------------|---------------------|-------------------|
| Normal (95%) | Historical (e.g., 2025-10-02) | 2026-01-15 | No (months gap) |
| Warm-to-now (5%) | Seed time (e.g., 2026-01-09) | 2026-01-15 | Possible if rapid |

### Why It Matters

- **Velocity rule** triggers when transactions are < 10 seconds apart
- **Impossible travel rule** checks speed between transaction locations
- Without warm-to-now, ALL first load test transactions would have huge time gaps

### Finding Warm-to-Now Customers

```javascript
// Find a customer ready for immediate fraud testing
db.customers.findOne({
  "features.latest_time_transaction": {
    $gte: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)  // Last 7 days
  }
})
```

### Refreshing Before Demo

If the seed was run days ago, warm-to-now timestamps become stale. Options:

1. **Run a quick load test first** - Updates customer features naturally
2. **Manual refresh** (run before demo):
   ```javascript
   // Warm 10K random customers to "now"
   db.customers.aggregate([
     { $sample: { size: 10000 } },
     { $project: { customer_id: 1 } }
   ]).forEach(c => {
     db.customers.updateOne(
       { customer_id: c.customer_id },
       { $set: { "features.latest_time_transaction": new Date() } }
     )
   })
   ```

---

## Timing Estimates

| Data Size | Customers | Transactions | Phase 1 | Phase 2 | Phase 3 | Total |
|-----------|-----------|--------------|---------|---------|---------|-------|
| Test | 5 | 20 | <1s | <1s | <1s | <1s |
| Small | 10K | 50K | 30s | 1min | 5s | ~2min |
| Medium | 100K | 500K | 5min | 10min | 1min | ~16min |
| **Production** | **35M** | **70M** | **25min** | **2.5hr** | **2hr** | **~5hr** |

---

## Verification Commands

### Check Collection Counts

```javascript
db.customers.countDocuments()           // 35,000,000
db.transactions.countDocuments()        // 67,733,909
db.blacklist_locations.countDocuments() // 100
db.holidays.countDocuments()            // 30
```

### Check Shard Distribution

```javascript
db.customers.getShardDistribution()
db.transactions.getShardDistribution()
```

### Check Warming Status

```javascript
// Total warmed
db.customers.countDocuments({
  "features.latest_time_transaction": { $ne: null }
})

// Warm-to-now count
db.customers.countDocuments({
  "features.latest_time_transaction": {
    $gte: new Date(Date.now() - 24 * 60 * 60 * 1000)
  }
})
```

### Check Balancer

```javascript
sh.getBalancerState()      // Should be true
sh.isBalancerRunning()     // Check if actively migrating
```

---

## Troubleshooting

### Seed Process Killed / Incomplete

If the seed process was interrupted:

1. Check how much data exists:
   ```javascript
   db.customers.countDocuments()
   db.transactions.countDocuments()
   ```

2. If customers exist but transactions are missing, you can reseed transactions only by modifying the seed script or running Phase 2 manually.

3. If warming is incomplete:
   ```javascript
   // Check warming progress
   db.customers.countDocuments({"features.latest_time_transaction": {$ne: null}})
   ```

### Null Features After Seeding

If customers have null `latest_time_transaction`:
- Phase 3 (warming) may not have completed
- Check seed container logs for errors
- Re-run warming manually if needed

### Uneven Shard Distribution

Distribution should be ~33% per shard. If uneven:
1. Check balancer is enabled: `sh.getBalancerState()`
2. Wait for balancer to migrate chunks
3. Check for hotspot keys (shouldn't happen with random hex IDs)

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SEED_CUSTOMERS` | 10000 | Number of customers to seed |
| `SEED_TRANSACTIONS` | 50000 | Number of transactions to seed |
| `SEED_WARM_TO_NOW_PCT` | 0.05 | Percentage of customers to warm to "now" |
| `SEED_BATCH_SIZE` | 10000 | Batch size for bulk operations |

### Adjusting for Instance Size

Larger instances can handle larger batch sizes:

```bash
# For c6i.16xlarge
SEED_BATCH_SIZE=50000 SEED_CUSTOMERS=35000000 ...
```

---

## Document History

| Date | Author | Changes |
|------|--------|---------|
| 2026-01-10 | Claude + Paul | Initial creation after 35M customer production seed |
