# Regional Bank Fraud Detection POC - Client Walkthrough

**Document Purpose:** Technical presentation guide for demonstrating the POC to Regional Bank stakeholders.

**Last Updated:** January 12, 2026

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Business Context](#2-business-context)
3. [Solution Architecture](#3-solution-architecture)
4. [How Fraud Scoring Works](#4-how-fraud-scoring-works)
5. [Test Data & Methodology](#5-test-data--methodology)
6. [Performance Results](#6-performance-results)
7. [Results Interpretation](#7-results-interpretation)
8. [Live Demo Guide](#8-live-demo-guide)
9. [Technical Highlights](#9-technical-highlights)
10. [Recommendations & Next Steps](#10-recommendations--next-steps)

---

## 1. Executive Summary

### What We Built

A **real-time fraud detection system** that scores every transaction in under 50 milliseconds, using MongoDB Atlas as a unified data platform to replace the existing Redis (36 shards) + Oracle architecture.

### Key Results

| Metric | Achieved | Target | Status |
|--------|----------|--------|--------|
| **Throughput** | 10,144 TPS sustained | 10,000 TPS | ✅ **Exceeded** |
| **Peak Throughput** | 19,500 TPS | - | 195% of target |
| **Avg Latency** | 18ms | <50ms | ✅ **64% under** |
| **P99 Latency** | 50ms | <100ms | ✅ **50% under** |
| **Data Volume Tested** | 35M customers, 83M transactions | - | Production scale |

### What This Means

- **MongoDB can handle RegionalBank's fraud detection workload** at production scale
- **Simpler architecture:** 3 MongoDB shards vs 36 Redis shards + Oracle
- **Lower operational complexity:** Single database platform, no cache invalidation
- **Consistent performance:** Sub-50ms latency even under 10K+ TPS load

---

## 2. Business Context

### Current Architecture Challenges

| Challenge | Current State | Impact |
|-----------|---------------|--------|
| **Complexity** | 36 Redis shards + Oracle DB | High operational overhead |
| **Cache Invalidation** | Manual TTL management | Risk of stale data |
| **Query Flexibility** | Limited by Redis data model | Cannot run ad-hoc analytics |
| **Scaling** | Horizontal scaling is complex | Difficult capacity planning |

### POC Objectives

1. **Prove MongoDB can achieve <50ms latency** for transaction scoring
2. **Demonstrate 10,000 TPS throughput** (RegionalBank's peak requirement)
3. **Show simplified architecture** with fewer moving parts
4. **Validate sharding strategy** for 50M+ customers

### Success Criteria Met

| Criterion | Target | Achieved | Result |
|-----------|--------|----------|--------|
| Scoring latency | <50ms avg | 18ms | ✅ Pass |
| P99 latency | <100ms | 50ms | ✅ Pass |
| Throughput | 10K TPS | 10.1K sustained, 19.5K peak | ✅ Pass |
| Data scale | Production representative | 35M customers, 83M txns | ✅ Pass |

---

## 3. Solution Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TRANSACTION FLOW                                                            │
│                                                                              │
│  [Mobile App]  [ATM]  [Internet Banking]  [Branch POS]                      │
│        │         │           │                │                              │
│        └─────────┴───────────┴────────────────┘                              │
│                              │                                               │
│                              ▼                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Application Load Balancer (AWS)                                      │   │
│  │  - Distributes requests across API servers                            │   │
│  │  - Health checks every 30 seconds                                     │   │
│  └──────────────────────────────────┬───────────────────────────────────┘   │
│                                     │                                        │
│            ┌────────────────────────┼────────────────────────┐              │
│            │                        │                        │              │
│            ▼                        ▼                        ▼              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│  │  API Server #1  │    │  API Server #2  │    │  API Server #N  │         │
│  │  129 workers    │    │  129 workers    │    │  (scalable)     │         │
│  │  FastAPI/Python │    │  FastAPI/Python │    │                 │         │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘         │
│           │                      │                      │                   │
│           └──────────────────────┼──────────────────────┘                   │
│                                  │ PrivateLink (no public internet)         │
│                                  ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  MongoDB Atlas (M60, 3 Shards)                                        │   │
│  │                                                                        │   │
│  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐                  │   │
│  │  │  Shard 0    │   │  Shard 1    │   │  Shard 2    │                  │   │
│  │  │  11.3M cust │   │  11.6M cust │   │  12.1M cust │                  │   │
│  │  │  27M txns   │   │  27M txns   │   │  29M txns   │                  │   │
│  │  └─────────────┘   └─────────────┘   └─────────────┘                  │   │
│  │                                                                        │   │
│  │  Data evenly distributed (~33% per shard)                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why This Architecture Works

| Design Decision | Benefit |
|-----------------|---------|
| **Embedded customer features** | Single query gets all scoring data (no joins) |
| **Random customer IDs** | Even distribution across shards (no hot spots) |
| **PrivateLink connectivity** | ~1-2ms network latency to MongoDB |
| **Stateless API servers** | Horizontal scaling without coordination |

### Infrastructure Summary (POC)

| Component | Specification | Purpose |
|-----------|---------------|---------|
| **API Servers** | 2× c6i.16xlarge (64 vCPU, 128GB) | Transaction processing |
| **MongoDB Atlas** | M60, 3 shards | Data storage & queries |
| **Load Generator** | c6i.8xlarge, 16 Locust workers | Generate 10K+ TPS |
| **Region** | ap-southeast-1 (Singapore) | Low latency to Indonesia |

---

## 4. How Fraud Scoring Works

### The Scoring Pipeline

Every transaction goes through a **5-rule evaluation** in parallel:

```
Transaction Received
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  PHASE 1: Parallel Database Reads (~4ms)                       │
│                                                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │ Customer    │  │ Blacklist   │  │ Holiday     │            │
│  │ Lookup      │  │ Check       │  │ Check       │            │
│  │ (features)  │  │ (geospatial)│  │ (date range)│            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  PHASE 2: Rule Evaluation (<1ms)                               │
│                                                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │ Velocity    │  │ Impossible  │  │ Password    │            │
│  │ Check       │  │ Travel      │  │ Frequency   │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│                                                                │
│  + Blacklist result + Holiday result from Phase 1              │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  PHASE 3: Parallel Database Writes (~10ms)                     │
│                                                                │
│  ┌───────────────────┐  ┌───────────────────┐                 │
│  │ Update Customer   │  │ Insert Transaction │                 │
│  │ Features          │  │ with Score         │                 │
│  └───────────────────┘  └───────────────────┘                 │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
   Risk Score Returned (0-100)
```

### The Five Fraud Rules

| Rule | What It Detects | Score | Threshold |
|------|-----------------|-------|-----------|
| **Velocity** | Transactions too fast (bot/script) | +20 | <10 seconds apart |
| **Impossible Travel** | Two locations too quickly (stolen credentials) | +30 | >800 km/h travel speed |
| **Blacklist Proximity** | Near known fraud hotspot | +10 to +35 | Within 500m of location |
| **Password Frequency** | Suspicious password changes | +15 | <7 days between changes |
| **Holiday** | High-risk holiday periods | +10 | During Lebaran, etc. |

### Risk Classification

| Score Range | Risk Level | Recommended Action |
|-------------|------------|-------------------|
| 0-39 | **Low** | Auto-approve |
| 40-69 | **Medium** | Additional verification |
| 70-100 | **High** | Manual review / block |

### Example Scoring

```json
{
  "transaction": {
    "customer_id": "CUST-7F3A2B1C9E4D",
    "amount": 15000000,
    "location": "Jakarta Selatan",
    "timestamp": "2026-01-12T10:03:10Z"
  },
  "scoring_result": {
    "final_score": 45,
    "risk_level": "medium",
    "rules_triggered": [
      { "rule": "blacklist_proximity", "score": 35, "reason": "Near fraud_hub" },
      { "rule": "holiday", "score": 10, "reason": "Cuti bersama period" }
    ],
    "processing_time_ms": 14
  }
}
```

---

## 5. Test Data & Methodology

### Mock Data Overview

We generated **realistic Indonesian banking data** to simulate production conditions:

| Data Type | Volume | Characteristics |
|-----------|--------|-----------------|
| **Customers** | 35,000,000 | Random IDs, 17 provinces, 8 ethnic name groups |
| **Transactions** | 83,000,000 | Realistic timestamps, amounts, merchants |
| **Blacklist Locations** | 100+ | Known fraud hotspots in Indonesian cities |
| **Holidays** | 2024-2026 | Indonesian national holidays & cuti bersama |

### Customer Distribution

Data is distributed across Indonesia's major provinces:

| Province | % of Customers | Sample Cities |
|----------|----------------|---------------|
| DKI Jakarta | 18% | Jakarta Pusat, Selatan, Timur |
| Jawa Barat | 15% | Bandung, Bekasi, Bogor |
| Jawa Timur | 12% | Surabaya, Malang |
| Jawa Tengah | 10% | Semarang, Solo |
| Other (13 provinces) | 45% | Various |

### Transaction Patterns

```
Realistic Time-of-Day Distribution:

Volume
  │
  │              ┌───┐
  │         ┌───┐│   │      ┌───────┐
  │    ┌───┐│   ││   │ ┌───┐│       │
  │    │   ││   ││   │ │   ││       │
  │    │   ││   ││   │ │   ││       │
  └────┴───┴┴───┴┴───┴─┴───┴┴───────┴──────
       6am  9am  12pm 3pm  6pm  9pm  12am

Peak hours: 12-1pm (lunch), 7-9pm (evening)
Dead hours: 2-5am (minimal transactions)
```

### Load Test Configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Locust Users** | 200 | Optimal for 10K TPS |
| **Spawn Rate** | 40/sec | Gradual ramp-up |
| **Customer Pool** | 100,000 | Random selection for realistic distribution |
| **Test Duration** | 60 seconds | Sustained load validation |

### Test Methodology

1. **Warmup:** 20 users for 30 seconds (stabilize connections)
2. **Ramp-up:** Scale to target users over 5 seconds
3. **Sustained Load:** Maintain for 60 seconds
4. **Cooldown:** Graceful stop and statistics collection

---

## 6. Performance Results

### Summary Dashboard

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LOAD TEST RESULTS - January 12, 2026 (60-second sustained test)            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  THROUGHPUT                          LATENCY                                │
│  ┌────────────────────┐              ┌────────────────────┐                 │
│  │ Current: 10,144    │              │ Avg:    18ms       │                 │
│  │ Peak:    19,500    │              │ P50:    16ms       │                 │
│  │ Target:  10,000 ✓  │              │ P95:    29ms       │                 │
│  └────────────────────┘              │ P99:    50ms       │                 │
│                                      │ Target: <50ms ✓    │                 │
│  REQUESTS                            └────────────────────┘                 │
│  ┌────────────────────┐                                                     │
│  │ Total:    561,900  │              FAILURE RATE                           │
│  │ Success:  560,700  │              ┌────────────────────┐                 │
│  │ Failed:     1,200  │              │ 0.2% (acceptable)  │                 │
│  └────────────────────┘              └────────────────────┘                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Latency Breakdown

Where does the 18ms go?

```
Total End-to-End: 18ms
│
├── Network (Load Generator → ALB → API): ~3ms (17%)
│
├── Scoring Phase: ~4ms (22%)
│   ├── Customer fetch: ~2ms
│   ├── Blacklist check: <0.1ms (in-memory cache + haversine)
│   ├── Holiday check: <0.1ms (in-memory cache)
│   └── Rule evaluation: <0.1ms
│
└── Persistence Phase: ~10ms (55%)
    ├── Customer feature update: ~5ms
    └── Transaction insert: ~5ms
```

### Comparison: Target vs Achieved

| Metric | Target | Achieved | Margin |
|--------|--------|----------|--------|
| Avg Latency | <50ms | 18ms | **64% faster** |
| P99 Latency | <100ms | 50ms | **50% faster** |
| TPS | 10,000 | 10,144 | **1.4% over** |
| Peak TPS | N/A | 19,500 | **95% headroom** |

### Shard Distribution

Data is evenly distributed across all 3 shards:

| Shard | Customers | % | Transactions | % |
|-------|-----------|---|--------------|---|
| Shard 0 | 11,347,802 | 32.4% | 26,932,291 | 32.5% |
| Shard 1 | 11,600,385 | 33.1% | 26,616,581 | 32.2% |
| Config* | 12,051,813 | 34.4% | 29,238,944 | 35.3% |

*MongoDB 8.0 embedded config server also stores application data.

---

## 7. Results Interpretation

### What the Numbers Mean

#### TPS (Transactions Per Second)

- **10,144 TPS sustained** = System can process 10,144 transactions every second
- **At peak hours**, RegionalBank processes ~5,000-8,000 TPS
- **95% headroom** means we can handle traffic spikes without degradation

#### Latency Percentiles

| Percentile | Meaning | Our Result |
|------------|---------|------------|
| **P50 (16ms)** | Half of requests are faster than this | Excellent baseline |
| **P95 (29ms)** | 95% of requests are faster than this | Very consistent |
| **P99 (50ms)** | 99% of requests are faster than this | Meets target |

#### Failure Rate (0.2%)

- **1,200 failures out of 561,900 requests**
- Causes: Network timeouts, momentary load spikes
- **Acceptable for POC** - production would have retry logic

### Key Insights

1. **MongoDB performs consistently under load**
   - No latency degradation at 10K TPS
   - Balancer can run during normal operations

2. **Architecture scales linearly**
   - 2 API servers → 10K TPS
   - 4 API servers → 20K TPS (projected)

3. **Database is not the bottleneck**
   - App processing: 14ms
   - MongoDB: <5ms per query
   - Most time is network + serialization

---

## 8. Live Demo Guide

### Demo Environment Access

| Component | URL | Notes |
|-----------|-----|-------|
| **Frontend UI** | http://[ALB-DNS]:3000 | Main demo interface |
| **API Docs** | http://[ALB-DNS]:8000/docs | Swagger/OpenAPI |
| **Health Check** | http://[ALB-DNS]/health | System status |

### Demo Scenario 1: Single Transaction Scoring

1. Open the **Scoring** tab in the UI
2. Click **"Load Random Customer"** to get a warm customer
3. Modify the transaction details:
   - Set amount to a large value (e.g., 50,000,000 IDR)
   - Location: Jakarta (or near a blacklist location for higher score)
4. Click **"Score Transaction"**
5. Show the **scoring breakdown** - explain each rule

### Demo Scenario 2: Load Test

1. Open the **Load Testing** tab
2. Select **"Bastion (External)"** mode
3. Set parameters:
   - Target TPS: 10,000
   - Duration: 30 seconds
4. Click **"Start Load Test"**
5. Observe:
   - TPS ramping up
   - Latency staying under 50ms
   - Risk distribution (most transactions are low risk)

### Demo Scenario 3: Fraud Injection

1. Use the API to submit a crafted fraudulent transaction:
   ```bash
   curl -X POST http://[ALB]/score-transaction \
     -H "Content-Type: application/json" \
     -d '{
       "customer_id": "[CUSTOMER_ID]",
       "amount": 100000000,
       "lat": -6.2088,
       "lon": 106.8456,
       "timestamp": "2026-01-12T10:00:05Z"
     }'
   ```
2. Submit again with timestamp 3 seconds later → **Velocity rule triggers**
3. Show the increased risk score

---

## 9. Technical Highlights

### Why MongoDB Over Redis + Oracle

| Aspect | Redis + Oracle | MongoDB Atlas |
|--------|----------------|---------------|
| **Shards** | 36 Redis | 3 MongoDB |
| **Systems** | 2 (cache + DB) | 1 |
| **Consistency** | Eventual | Strong |
| **Query Flexibility** | Limited | Full (aggregations, geo) |
| **Operational** | Complex | Managed service |

### Key Technical Decisions

| Decision | Why |
|----------|-----|
| **Embedded features in customer doc** | Single query for scoring (no joins) |
| **Random customer IDs (CUST-7F3A2B1C)** | Even shard distribution |
| **PyMongo Async API** | 2.5x faster than sequential |
| **Geospatial indexes** | Fast blacklist proximity checks |
| **PrivateLink connectivity** | ~1ms network latency |

### Code Quality

- **FastAPI** with async/await throughout
- **Pydantic** for request/response validation
- **Comprehensive timing metrics** in every response
- **Parallel database operations** for minimum latency

---

## 10. Recommendations & Next Steps

### Immediate Recommendations

| Item | Priority | Effort |
|------|----------|--------|
| **Enable HTTPS** | High | 1 day |
| **Add authentication** | High | 2 days |
| **Set up CloudWatch alerts** | Medium | 1 day |
| **Document runbooks** | Medium | 2 days |

### Production Considerations

1. **Multi-region deployment** for disaster recovery
2. **MongoDB Atlas backup configuration** (PITR)
3. **Log aggregation** (CloudWatch or ELK)
4. **API rate limiting** per customer
5. **Integration with existing RegionalBank systems**

### Scaling Recommendations

| TPS Target | EC2 Instances | MongoDB Tier |
|------------|---------------|--------------|
| 10,000 | 2× c6i.16xlarge | M60 (3 shards) |
| 20,000 | 4× c6i.16xlarge | M60 (3 shards) |
| 50,000 | 6× c6i.16xlarge | M80 (5 shards) |

### Cost Estimate (Production)

| Component | Monthly Cost |
|-----------|--------------|
| 2× c6i.16xlarge EC2 | ~$3,500 |
| MongoDB Atlas M60 (3 shards) | ~$4,000 |
| ALB + NAT Gateway | ~$200 |
| PrivateLink | ~$50 |
| **Total** | **~$7,750/month** |

---

## Appendix: Related Documentation

| Document | Description |
|----------|-------------|
| [SCORING-SYSTEM-DEEP-DIVE.md](./SCORING-SYSTEM-DEEP-DIVE.md) | Complete technical explanation of scoring |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Database design and sharding strategy |
| [PERFORMANCE-TUNING.md](./PERFORMANCE-TUNING.md) | How we achieved 19K TPS |
| [LOAD-TESTING.md](./LOAD-TESTING.md) | Load testing methodology |
| DEPLOYMENT-RUNBOOK.md | Operational commands reference |
| LOAD-TEST-SESSION-2026-01-12.md | Detailed test session notes |

---

*Document prepared for Regional Bank POC presentation - January 2026*
