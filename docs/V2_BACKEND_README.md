# V2 Backend -- Regional Bank Fraud Detection

## Overview

V2 extends V1's 5 fraud rules to **31 rules** across 24 relational source tables, targeting **50K TPS** with **<20ms latency**. V2 lives in `backend_v2/` and runs on port **8001** alongside V1 on port 8000. Both share the same Atlas cluster but use separate databases (`RegionalBank_fraud` vs `RegionalBank_fraud_v2`).

## Architecture

### Hot Path (3-4 DB ops, <20ms)

```
Request → find_one/aggregate(customers) → [optional: $in(txn_lookups)] → CPU: 31 rules → asyncio.gather(update_one(customers), insert_one(transactions))
```

| Phase | Operation | Target |
|-------|-----------|--------|
| 1 | `find_one` or `aggregate` on customers | Fetch mega-document (mode-dependent) |
| 1.5 | `find` with `$in` on txn_lookups | DB-based blacklist lookups (lookup_mode=db only) |
| 2 | CPU-only rule evaluation | All 31 rules, no I/O |
| 3a | `update_one` on customers | Update rolling fields (parallel) |
| 3b | `insert_one` on transactions | Store scored transaction (parallel, insert_mode=sync) |

A rare extra op (`find_one` on `pot_nb_overflow`) triggers only when `b24_count > 500` AND beneficiary not found in embedded list (<1% of customers).

### Runtime Mode Toggles

Modes are stored in MongoDB (`runtime_config` collection) and cached per worker with a 2-second TTL. Changes propagate to all workers across all instances within 2 seconds.

| Toggle | Options | Default | Effect |
|--------|---------|---------|--------|
| `update_mode` | `standard`, `pipeline`, `aggregation` | `pipeline` | How customer rolling fields + at6 are computed |
| `lookup_mode` | `memory`, `db` | `memory` | Where transaction-level blacklists come from |
| `insert_mode` | `sync`, `none` | `sync` | Whether to persist scored transactions |

**Update modes:**
- **standard** — Python computes at6 + window reset; plain `$set/$push/$inc` update
- **pipeline** — Single atomic update_one with 3-stage aggregation pipeline; computes at6 via `$reduce/$sqrt` server-side
- **aggregation** — Phase 1 aggregation computes at6 via `$stdDevPop`; Phase 3 writes with standard operators (2 round trips)

**Insert modes:**
- **sync** — `asyncio.gather()` runs update_customer + insert_transaction in parallel
- **none** — Skip transaction insert entirely; returns txn_id = "score-only" (+30% TPS at 50K)

### In-Memory Caches

Transaction-level blacklists are loaded into memory at startup (~135MB/worker):

| Cache | Collection | Size Estimate | Used By |
|-------|------------|--------------|---------|
| `dest_accounts` | pot_bf | Set of accounts | var_1 |
| `fraud_cascade` | pot_bf24 | Dict keyed by b23 | var_2 |
| `suspicious_merchants` | pot_sm | Set of names (lowercase) | var_5 |
| `gambling_accounts` | pot_anj | Set of accounts | var_6 |
| `loan_providers` | pot_pp | Dict account->provider | var_9 |
| `watchlist_accounts` | pot_cb | Set of accounts | var_23 |
| `service_limits` | pot_sl_va | Dict service->limit | var_12, var_14 |
| `avg_bounds` | pot_sl_va | Dict service->(lower,upper) | var_14 |

### Collections (11 total)

| Collection | Sharded | Purpose |
|------------|---------|---------|
| customers | Yes | Consolidated customer mega-documents |
| transactions | Yes | Scored transactions with fraud_score |
| pot_bf | No | Fraud blacklist (destination accounts) |
| pot_bf24 | No | 24h fraud cascade |
| pot_sm | No | Suspicious merchants |
| pot_anj | No | Gambling-linked accounts |
| pot_pp | No | Loan provider accounts |
| pot_cb | No | Compliance watchlist |
| pot_sl_va | No | Service limits + average bounds |
| pot_nb_overflow | No | Beneficiary overflow (>500) |
| txn_lookups | No | Consolidated blacklist lookups (lookup_mode=db) |
| runtime_config | No | Mode toggles (update/lookup/insert) |
| load_tests | No | Load test tracking |

## 31 Fraud Rules

### Blacklist Rules (9)

| Rule | Description | Source | Weight |
|------|------------|--------|--------|
| var_1 | Destination on fraud blacklist | pot_bf (cache) | 15 |
| var_2 | Customer/dest in 24h fraud cascade | pot_bf24 (cache) | 15 |
| var_3 | Email blacklisted | Pre-computed flag | 10 |
| var_4 | Risky device type | Pre-computed flag | 5 |
| var_5 | Suspicious merchant name | pot_sm (cache) | 10 |
| var_6 | Gambling-linked destination | pot_anj (cache) | 10 |
| var_7 | Phone blacklisted | Pre-computed flag | 10 |
| var_23 | Compliance watchlist | pot_cb (cache) | 10 |
| var_25 | High-risk device | Pre-computed flag | 5 |

### Velocity Rules (5)

| Rule | Description | Source | Weight |
|------|------------|--------|--------|
| var_8 | Rapid transaction (<10s gap) | Customer rolling.z1_prev | 8 |
| var_10 | Same-day transaction | Customer rolling.z1_prev | 5 |
| var_13 | Unusual transaction hour | Customer rolling.z3/z4 | 5 |
| var_24 | Post-card-change transaction | Customer rolling.w2_latest | 8 |
| var_26 | Post-provisioning transaction | Customer rolling.pt_latest | 8 |

### Amount Rules (11)

| Rule | Description | Source | Weight |
|------|------------|--------|--------|
| var_12 | Amount vs service limit | pot_sl_va (cache) | 5 |
| var_14 | Amount outside historical avg | pot_sl_va (cache) | 5 |
| var_15 | Amount-to-balance ratio | Customer rolling.bl | 8 |
| var_16 | Repetitive amount pattern | Customer rolling.at3_recent | 5 |
| var_17 | Amount spike (vs previous) | Customer rolling.at3_prev | 5 |
| var_18 | Cumulative amount vs balance | Customer rolling.at3_sum | 8 |
| var_19 | Post-provisioning cumulative | Customer rolling.pt_latest + at3_sum | 8 |
| var_20 | Exact amount repetition (3+) | Customer rolling.at3_recent | 5 |
| var_21 | Amount drop | Customer rolling.at3_prev | 3 |
| var_28 | Amount volatility (std dev) | Customer av1 threshold | 5 |
| var_29 | Cumulative sum threshold | Customer av2 threshold | 5 |

### Behavioral Rules (3)

| Rule | Description | Source | Weight |
|------|------------|--------|--------|
| var_9 | Loan money-out pattern | Customer rolling.pot_i_recent | 10 |
| var_11 | First-time service usage | Customer service_ever | 3 |
| var_22 | Unknown beneficiary | Customer b24_list + overflow | 5 |

### Pattern Rules (2)

| Rule | Description | Source | Weight |
|------|------------|--------|--------|
| var_30 | Repetitive purpose code | Customer rolling.tp_recent | 3 |
| var_31 | Purpose-to-amount ratio anomaly | Transaction tp + at3 | 3 |

Risk levels: 0-39 = low, 40-69 = medium, 70-100 = high

## File Structure

```
backend_v2/
├── app/
│   ├── main.py                    # FastAPI app with lifespan
│   ├── config.py                  # 31 weights + thresholds (env vars)
│   ├── runtime_config.py          # MongoDB-backed mode toggles (2s TTL cache)
│   ├── db.py                      # Async PyMongo connection
│   ├── cache.py                   # BlacklistCache + ServiceConfigCache
│   ├── indexes.py                 # Index + shard key definitions
│   ├── models/
│   │   ├── customer.py            # CustomerV2 mega-document model
│   │   ├── transaction.py         # TransactionV2 + FraudScore + RuleResult
│   │   └── requests.py            # ScoreTransactionRequest/Response
│   ├── services/
│   │   ├── fraud/                 # Fraud scoring package (3-phase orchestrator)
│   │   │   ├── __init__.py        # Re-exports FraudScoringServiceV2
│   │   │   ├── service.py         # Main orchestrator: Phase 1 → 2 → 3
│   │   │   ├── reads.py           # Phase 1: find_customer() + aggregate_customer_read()
│   │   │   └── writes.py          # Phase 3: build_customer_update() (3 modes) + insert
│   │   ├── lookup_service.py      # DB-based txn_lookups query (lookup_mode=db)
│   │   ├── customer_sampling.py   # Customer pool for load testing
│   │   ├── locust_sampler.py      # Transaction sampling (1-in-500)
│   │   └── rules/
│   │       ├── blacklist.py       # var_1-7, 23, 25
│   │       ├── velocity.py        # var_8, 10, 13, 24, 26
│   │       ├── amount.py          # var_12, 14-21, 28, 29
│   │       ├── behavioral.py      # var_9, 11, 22
│   │       └── pattern.py         # var_30, 31
│   ├── routes/
│   │   ├── score.py               # POST /score-transaction
│   │   ├── config.py              # GET/POST /config/{update,lookup,insert}-mode
│   │   ├── health.py              # /health + /health/detailed
│   │   ├── mock.py                # /mock/customers
│   │   ├── loadtest.py            # Load test stats
│   │   └── locust_proxy.py        # Locust proxy
│   └── utils/
│       ├── timing.py              # TimingBreakdown
│       ├── scoring.py             # calculate_final_score()
│       └── ids.py                 # ID generation
├── seed/
│   ├── main.py                    # Two-phase seeder
│   ├── customers.py               # V2 customer generation
│   ├── transactions.py            # V2 transaction generation
│   ├── blacklists.py              # Seed 6 blacklist collections + pot_sl_va
│   ├── pot_nb_overflow.py         # Seed overflow beneficiaries
│   ├── reset_collections.py       # Drop + recreate collections
│   └── data/
│       ├── devices.py             # Device models (normal + risky + high-risk)
│       ├── blacklist_data.py      # Blacklist entry generators
│       ├── fraud_scenarios.py     # Service codes, purpose codes, channels
│       └── loan_providers.py      # Loan provider names
├── loadtest/
│   ├── locustfile.py              # V2 Locust file
│   └── common.py                  # Shared utilities
├── tests/                         # 88 unit tests
│   ├── test_rules_blacklist.py    # 9 blacklist rules
│   ├── test_rules_velocity.py     # 5 velocity rules
│   ├── test_rules_amount.py       # 11 amount rules
│   ├── test_rules_behavioral.py   # 3 behavioral rules
│   ├── test_rules_pattern.py      # 2 pattern rules
│   ├── test_scoring.py            # Integration (all rules)
│   └── test_api.py                # API validation
├── Dockerfile                     # Port 8001
├── gunicorn.conf.py               # Port 8001, proc_name RegionalBank-fraud-v2-api
├── requirements.txt               # Python dependencies
└── .env.example                   # All config with defaults
```

Also at the repo root:
- `scripts/atlas-setup-v2.js` -- mongosh script for V2 collections
- `docker-compose.v2.yml` -- Docker deployment for V2

## Quick Start

```bash
# Install V2 dependencies
make install-v2

# Copy and configure .env
cp backend_v2/.env.example backend_v2/.env
# Edit backend_v2/.env with your MONGODB_URI

# Run Atlas setup (indexes + sharding)
make atlas-setup-v2

# Seed test data
make seed-v2-test    # 5 customers (quick validation)
make seed-v2         # 10K customers
make seed-v2-medium  # 100K customers

# Run V2 API
make dev-v2          # Port 8001

# Run V1 + V2 + Frontend together
make dev-both        # V1:8000, V2:8001, Frontend:3000

# Run tests
make test-v2         # 88 tests, ~0.5s
```

## Configuration

All settings are environment variables with sensible defaults. See `backend_v2/.env.example` for the full list.

Key settings:
- `MONGODB_URI` -- Atlas connection string (required)
- `DB_NAME` -- Database name (default: `RegionalBank_fraud_v2`)
- `WEIGHT_VAR_*` -- Per-rule weights (31 variables)
- `MIN_TXN_GAP_SECONDS`, `AMOUNT_TO_BALANCE_RATIO`, etc. -- Rule thresholds

## Testing

```bash
# All tests
make test-v2

# Specific test file
cd backend_v2 && . .venv/bin/activate && pytest tests/test_rules_blacklist.py -v

# Specific test
cd backend_v2 && . .venv/bin/activate && pytest tests/test_rules_velocity.py::TestVar8::test_triggered_rapid_transaction -v
```

Tests are pure unit tests -- no MongoDB connection required. All rules are tested as pure functions.

## Key Differences from V1

| Aspect | V1 | V2 |
|--------|----|----|
| Rules | 5 | 31 |
| Port | 8000 | 8001 |
| Database | RegionalBank_fraud | RegionalBank_fraud_v2 |
| Customer document | ~500 bytes | ~1.7KB (mega-doc) |
| Blacklist strategy | DB query (geospatial) | In-memory cache (~135MB/worker) |
| Holiday check | DB query | Removed (not in RegionalBank V2 spec) |
| DB ops/transaction | 5 (find, geo, holiday, update, insert) | 3 (find, update, insert) |
| Field names | Human-readable | Masked (at3, z1, b2, etc.) |
| Rule storage | Full analysis array in MongoDB | Flat rule_scores map (~200-300 bytes) |
| API response | Same as stored | Enriched analysis (CPU-only, not stored) |

## Hybrid Storage Strategy

**In MongoDB (compact):** `fraud_score.rule_scores` is a flat map `{"var_1": 0, "var_8": 8, ...}` (~200-300 bytes). Non-zero values indicate triggered rules.

**In API response (enriched):** `analysis` array with rule names, categories, and details. Generated at response time (CPU-only), not stored.

This saves ~10x write throughput vs storing full analysis arrays at 50K TPS.
