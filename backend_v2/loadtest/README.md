# V2 Locust Load Testing

## Overview

Locust load tests for the V2 fraud scoring engine. Payloads are generated with **realistic hit rates** so that blacklist rules, beneficiary checks, and overflow lookups actually trigger during load tests — not just the happy path.

## Quick Start

```bash
# Local (single process)
locust -f loadtest/locustfile.py --host http://localhost:8001

# Distributed (master + workers on bastion)
locust -f loadtest/locustfile.py --host http://alb.amazonaws.com --master --expect-workers 16
```

## Startup Data Loading

At test start, Locust loads two datasets from the backend (once, not during the test):

### 1. Enriched Customer Pool

**Endpoint:** `GET /mock/customers?limit=100000&skip=N` (paginated, up to 500K)

Each customer includes:

| Field | Description |
|-------|-------------|
| `customer_id` | Customer identifier |
| `b1` | Source account number (from `rolling.b1`) |
| `b24_sample` | Up to 5 known beneficiaries (from `b24_list`) |

Memory: ~80MB for 500K customers.

### 2. Blacklist + Overflow Samples

**Endpoint:** `GET /mock/blacklist-sample` (single call, ~41KB)

| Sample | Collection | Field | Size | Used by |
|--------|------------|-------|------|---------|
| `pot_bf` | pot_bf | b23 | 1,000 | var_1 (fraud blacklist) |
| `pot_anj` | pot_anj | b23 | 500 | var_6 (gambling accounts) |
| `pot_cb` | pot_cb | b23 | 500 | var_23 (watchlist) |
| `pot_sm` | pot_sm | n3 | 200 | var_5 (suspicious merchants) |
| `overflow_pairs` | pot_nb_overflow | customer_id + b2 | 200 | var_22 overflow path |

## Payload Generation

### Hit-Rate Constants

All configurable at the top of `locustfile.py`:

```python
KNOWN_BENEFICIARY_RATE = 0.90     # 90% -> known b2 from b24_sample (var_22 does NOT fire)
BLACKLIST_BF_RATE = 0.015         # 1.5% of unknown b2s -> pot_bf match (var_1 fires)
BLACKLIST_ANJ_RATE = 0.009        # 0.9% of unknown b2s -> pot_anj match (var_6 fires)
BLACKLIST_CB_RATE = 0.015         # 1.5% of unknown b2s -> pot_cb match (var_23 fires)
SUSPICIOUS_MERCHANT_RATE = 0.05   # 5% of n2 values -> pot_sm match (var_5 fires)
OVERFLOW_HIT_RATE = 0.000005      # 0.0005% of ALL txns -> real overflow pair (var_22 overflow path)
```

### Decision Flow for `b2` (destination account)

```
Roll random()
  |
  |-- < 0.90 AND customer has b24_sample?
  |     YES -> pick from b24_sample (known beneficiary, var_22 won't fire)
  |
  |-- Otherwise (unknown beneficiary, ~10% of txns):
        |
        |-- Roll random()
        |     < 1.5%  -> pick from pot_bf sample (var_1 fires)
        |     < 2.4%  -> pick from pot_anj sample (var_6 fires)
        |     < 3.9%  -> pick from pot_cb sample (var_23 fires)
        |     else    -> truly random 10-digit number (no blacklist hit)
```

### Decision Flow for `n2` (merchant name)

```
Roll random()
  |-- < 5%  -> pick from pot_sm sample (var_5 fires)
  |-- else  -> random "Merchant-XXXXXX" string
```

### Overflow Path

Extremely rare (0.0005% of all transactions). When triggered:
- Locust overrides **both** `customer_id` and `b2` with a real `pot_nb_overflow` entry
- The scoring engine's `find_one` on `pot_nb_overflow` returns a match
- var_22 takes the "known via overflow" path (beneficiary found in overflow collection)
- At 50K TPS, this fires ~1 time every 4 seconds

### Field Sources

| Payload Field | Source |
|---------------|--------|
| `customer_id` | Customer pool (or overflow pair) |
| `b1` | Customer's `rolling.b1` (fallback: random) |
| `b2` | Realistic generation (see above) |
| `n2` | Realistic generation (see above) |
| `c2` | Random `BENEFICIARY-XXXXXXXX` |
| `d2` | Random from `DESTINATION_BANKS` |
| `at3` | Random 10,000 - 5,000,000 |
| `tp` | Random from `PURPOSE_CODES` |
| `at7` | Random from [0, 1000, 2500] |
| `service` | Random from `SERVICE_CODES` |
| `z1` | Current UTC timestamp |
| `h1` | Random from `DEVICES` |
| `channel` | Random from `CHANNELS` |

## Expected Scoring Distribution

| Rule | Before (random payloads) | After (realistic payloads) |
|------|--------------------------|----------------------------|
| var_1 (pot_bf) | ~0.005% | ~0.15% overall |
| var_5 (pot_sm) | ~0.8% | ~5% |
| var_6 (pot_anj) | ~0.005% | ~0.09% overall |
| var_22 (unknown beneficiary) | 100% | ~10% |
| var_23 (pot_cb) | ~0.01% | ~0.15% overall |
| Overflow FOUND | 0% (never tested) | ~0.0005% (~1 hit/4s at 50K TPS) |

## Files

| File | Purpose |
|------|---------|
| `locustfile.py` | Main Locust test: pool loading, realistic payload generation, HTTP task |
| `common.py` | Shared helper `generate_v2_transaction_payload()` with same realistic logic |

## Verification

After deploying, run a short test (100 TPS x 30s) and check:

1. **Risk distribution in UI** — should show mixed levels, not all clustering at one score
2. **var_22** — should fire ~10% of the time, not 100%
3. **Blacklist rules** — some var_1/var_5/var_6/var_23 hits visible in sampled transactions
4. **Latency** — should be unchanged (DB operation profile is identical)
