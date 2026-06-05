---
name: locust-load-testing
description: Write effective Locust load testing scripts for high-throughput API testing. Includes troubleshooting for customer pool issues, wait time configuration bugs, distributed testing, and recovery procedures. Use this skill when creating load tests, stress tests, or performance benchmarks for APIs, when asked about testing throughput or latency, when validating scalability of web services, when troubleshooting load test issues, or when you need to simulate thousands of concurrent users.
---

# Locust Load Testing

Locust is a Python-based load testing framework that lets you define user behavior in code.

## Critical Issues We've Encountered

These are real production issues that caused significant debugging time:

### Issue 1: wait_time Configuration Bug (CRITICAL)

**Symptom:** Achieving only ~50-60% of target TPS

**Diagnosis:**
```bash
# Check wait_time in locustfile
grep "wait_time = between" locustfile.py
# If you see between(9, 11) instead of between(0.001, 0.01), that's the problem
```

**Root Cause:** Wrong wait_time active in locustfile.py

| wait_time | TPS per User | 200 Users | Result |
|-----------|--------------|-----------|--------|
| `between(9, 11)` | 0.1 TPS | 20 TPS | **WRONG** |
| `between(0.001, 0.01)` | 100-200 TPS | 10K+ TPS | **CORRECT** |

**Fix:**
```python
class FraudAPIUser(HttpUser):
    # For throughput testing - USE THIS
    wait_time = between(0.001, 0.01)  # 1-10ms = 10K TPS with 200 users

    # For realistic simulation - COMMENT OUT for throughput tests
    # wait_time = between(9, 11)  # ~10s = only 0.1 TPS per user
```

### Issue 2: 1M Customer Pool Crash (CRITICAL)

**Symptom:** API becomes unresponsive, 100% failure rate, ALB 60s timeout

**Root Cause:** Loading 1M customer IDs in single response exceeds ALB timeout

**Safe Limits:**

| Pool Size | Status | Notes |
|-----------|--------|-------|
| 100K | ✅ Safe | Works reliably |
| 200K | ⚠️ Risky | Near ALB timeout |
| 300K+ | ❌ Crashes | Exceeds timeout |
| 1M | ❌ FATAL | Makes instances unresponsive |

**Solution Options:**
```python
# Option 1: Paginated loading (recommended)
async def load_customers_paginated(client, total: int, page_size: int = 50000):
    customers = []
    offset = 0
    while offset < total:
        response = client.get(f"/mock/customers?limit={page_size}&offset={offset}")
        if response.status_code == 200:
            batch = response.json().get("customers", [])
            customers.extend([c["customer_id"] for c in batch])
            offset += page_size
    return customers

# Option 2: Generate random IDs (fast but won't match DB)
import secrets
def generate_customer_id():
    return f"CUST-{secrets.token_hex(6).upper()}"
CUSTOMER_POOL = [generate_customer_id() for _ in range(1_000_000)]

# Option 3: Pre-load from file
with open("customer_ids.txt") as f:
    CUSTOMER_POOL = [line.strip() for line in f]
```

### Issue 3: Customer Pool Empty After Crash

**Symptom:** High TPS shown but "App Processing" shows 0ms, all requests return 404

**Root Cause:** After crash/restart, Locust workers have empty customer pools, fall back to generating random IDs that don't exist in database

**Diagnosis:**
```bash
# Check API logs - should see 200s not 404s
sudo docker logs --tail 20 RegionalBank_fraud_detection-api-1 2>&1 | grep score
# If you see "Customer not found: CUST-XXXXXX" with 404s, pool is stale
```

**Fix:**
```bash
# Restart Locust to reload customer pool
cd /home/ssm-user/RegionalBank_fraud_detection/backend/loadtest
./stop_locust_service.sh
./start_locust_service.sh 16  # 16 workers
```

### Issue 4: Customer IDs Must Match Database Format

**Symptom:** All requests return 404, Locust shows success (catch_response marks 404 as success)

**Root Cause:** Generated customer IDs don't match the format/IDs in database

**Fix:** Customer IDs must be in exact format: `CUST-{12 hex digits uppercase}`
```python
# Correct format
customer_id = f"CUST-{secrets.token_hex(6).upper()}"  # e.g., CUST-A1B2C3D4E5F6
```

### Issue 5: Test Not Recording App Metrics

**Symptom:** Locust UI shows stats but "App Processing" metrics show 0

**Root Cause:** Test started via Locust UI directly instead of through API

**How It Works:**
1. Frontend calls `/loadtest/external/start` → creates `load_tests` doc with `status: "running"`
2. API checks for running test and samples 1-in-100 successful transactions
3. Frontend polls `/loadtest/progress/{test_id}` for metrics

**Fix - Start via API:**
```bash
# Start test (creates load_tests document for sampling)
curl -X POST "http://your-alb.amazonaws.com/loadtest/external/start" \
  -H "Content-Type: application/json" \
  -d '{"user_count": 400, "spawn_rate": 40, "target": "bastion"}'

# Check active test
curl "http://your-alb.amazonaws.com/loadtest/external/active-test"

# Stop test
curl "http://your-alb.amazonaws.com/loadtest/external/stop?target=bastion"
```

## Installation

```bash
pip install locust
```

## Basic Structure

```python
"""
Load test for API.

Usage:
    # Web UI mode
    locust -f locustfile.py --host=http://localhost:8000

    # Headless mode (CI/CD)
    locust -f locustfile.py --host=http://localhost:8000 \
        --headless --users 100 --spawn-rate 10 --run-time 60s
"""

from locust import HttpUser, task, between, events
import random
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class APIUser(HttpUser):
    """Simulates a user making API requests."""

    # Wait time between requests per user
    wait_time = between(0.001, 0.01)  # 1-10ms for high throughput
    # wait_time = between(1, 3)  # 1-3s for realistic user simulation

    def on_start(self):
        """Called when user starts. Setup resources here."""
        pass

    @task(20)
    def main_endpoint(self):
        """Main task with high weight."""
        payload = {"key": "value"}
        with self.client.post("/api/endpoint", json=payload, catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status {response.status_code}: {response.text[:100]}")

    @task(1)
    def health_check(self):
        """Low-weight background task."""
        self.client.get("/health")
```

## High-Throughput Load Test Pattern

For 10K+ TPS testing, use this optimized pattern:

```python
from locust import HttpUser, task, between, events
import random
import string
from datetime import datetime, timezone

# Pre-generated test data pool
# CRITICAL: Use large pool to avoid hitting same records repeatedly
DATA_POOL = []
DATA_POOL_SIZE = 100000  # 100K items prevents contention
DATA_POOL_LOADED = False


def generate_id():
    """Generate random ID."""
    return f"ID-{''.join(random.choices(string.hexdigits.upper(), k=12))}"


def generate_payload(item_id: str = None):
    """Generate realistic API payload."""
    if not item_id:
        item_id = random.choice(DATA_POOL) if DATA_POOL else generate_id()

    return {
        "item_id": item_id,
        "amount": random.randint(1000, 100000),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "category": random.choice(["A", "B", "C", "D"]),
        "metadata": {
            "source": random.choice(["web", "mobile", "api"]),
            "version": "1.0",
        }
    }


class HighThroughputUser(HttpUser):
    """Optimized for maximum throughput testing."""

    # Minimal wait time for max TPS
    wait_time = between(0.001, 0.01)  # 1-10ms

    def on_start(self):
        """Load data pool on first user start."""
        global DATA_POOL, DATA_POOL_LOADED

        if not DATA_POOL_LOADED:
            try:
                # Try loading from API
                logger.info(f"Loading {DATA_POOL_SIZE} items into pool...")
                response = self.client.get(
                    f"/api/items?limit={DATA_POOL_SIZE}",
                    timeout=60,
                    name="/api/items (pool load)"  # Separate in stats
                )
                if response.status_code == 200:
                    items = response.json().get("items", [])
                    DATA_POOL.extend([item["id"] for item in items])
                    logger.info(f"Loaded {len(DATA_POOL)} items")
            except Exception as e:
                logger.warning(f"Failed to load pool: {e}")

            # Fallback to generated IDs
            if not DATA_POOL:
                DATA_POOL.extend([generate_id() for _ in range(1000)])
                logger.info("Using generated fallback IDs")

            DATA_POOL_LOADED = True

    @task
    def process_item(self):
        """Main processing endpoint."""
        payload = generate_payload()
        with self.client.post(
            "/api/process",
            json=payload,
            catch_response=True,
            timeout=30
        ) as response:
            if response.status_code in [200, 404, 422]:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")


class RealisticUser(HttpUser):
    """Simulates realistic user behavior."""

    wait_time = between(1, 5)  # 1-5s between actions

    @task(10)
    def view_item(self):
        """View item (common action)."""
        item_id = random.choice(DATA_POOL) if DATA_POOL else generate_id()
        self.client.get(f"/api/items/{item_id}")

    @task(3)
    def search(self):
        """Search (occasional action)."""
        query = random.choice(["foo", "bar", "baz"])
        self.client.get(f"/api/search?q={query}")

    @task(1)
    def create_item(self):
        """Create item (rare action)."""
        self.client.post("/api/items", json=generate_payload())
```

## Event Hooks for Reporting

```python
@events.init_command_line_parser.add_listener
def add_custom_arguments(parser):
    """Add custom CLI arguments."""
    parser.add_argument(
        "--data-pool-size",
        type=int,
        default=100000,
        help="Number of items to load into test pool"
    )


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when test starts."""
    logger.info(f"Starting load test against {environment.host}")
    logger.info("Target: 10,000 TPS with <50ms P50 latency")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print summary statistics when test ends."""
    stats = environment.stats
    total = stats.total

    print("\n" + "=" * 60)
    print("LOAD TEST RESULTS")
    print("=" * 60)
    print(f"Total Requests:     {total.num_requests:,}")
    print(f"Failed Requests:    {total.num_failures:,}")
    print(f"Failure Rate:       {(total.num_failures / max(total.num_requests, 1)) * 100:.2f}%")
    print("-" * 60)
    print(f"Requests/sec (RPS): {total.current_rps:.2f}")
    print("-" * 60)
    print("Response Times:")
    print(f"  Average:          {total.avg_response_time:.2f}ms")
    print(f"  Median (P50):     {total.get_response_time_percentile(0.50):.2f}ms")
    print(f"  P90:              {total.get_response_time_percentile(0.90):.2f}ms")
    print(f"  P95:              {total.get_response_time_percentile(0.95):.2f}ms")
    print(f"  P99:              {total.get_response_time_percentile(0.99):.2f}ms")
    print(f"  Min:              {total.min_response_time:.2f}ms")
    print(f"  Max:              {total.max_response_time:.2f}ms")
    print("=" * 60)

    # Performance assessment
    p50 = total.get_response_time_percentile(0.50)
    p99 = total.get_response_time_percentile(0.99)
    rps = total.current_rps
    error_rate = (total.num_failures / max(total.num_requests, 1)) * 100

    print("\nPERFORMANCE ASSESSMENT:")
    print(f"  P50 < 50ms:        {'PASS' if p50 < 50 else 'FAIL'} ({p50:.2f}ms)")
    print(f"  P99 < 500ms:       {'PASS' if p99 < 500 else 'FAIL'} ({p99:.2f}ms)")
    print(f"  Error rate < 0.1%: {'PASS' if error_rate < 0.1 else 'FAIL'} ({error_rate:.2f}%)")
    print(f"  RPS > 10,000:      {'PASS' if rps > 10000 else 'FAIL'} ({rps:.2f})")
    print("=" * 60 + "\n")
```

## Running Locust

```bash
# Web UI mode (default port 8089)
locust -f locustfile.py --host=http://localhost:8000

# Headless mode for CI/CD
locust -f locustfile.py \
    --host=http://api.example.com \
    --headless \
    --users 1000 \
    --spawn-rate 100 \
    --run-time 60s

# Distributed mode for 10K+ TPS
# Terminal 1 - Master
locust -f locustfile.py --master --host=http://api.example.com

# Terminal 2-N - Workers
locust -f locustfile.py --worker --master-host=127.0.0.1

# Specify user class
locust -f locustfile.py --host=... HighThroughputUser
```

## Task Weights

Task weights determine relative frequency:

```python
class APIUser(HttpUser):
    @task(20)
    def read_item(self):
        """20x more likely than weight-1 tasks"""
        pass

    @task(5)
    def update_item(self):
        """5x more likely than weight-1 tasks"""
        pass

    @task(1)
    def delete_item(self):
        """Base frequency"""
        pass
```

Distribution: read=77%, update=19%, delete=4%

## Wait Time Strategies

```python
from locust import constant, between, constant_pacing

# Fixed wait
wait_time = constant(1)  # Always 1 second

# Random range
wait_time = between(1, 5)  # 1-5 seconds

# For high TPS testing
wait_time = between(0.001, 0.01)  # 1-10ms

# Fixed request rate per user
wait_time = constant_pacing(0.1)  # 10 requests/second/user
```

## Handling Response Validation

```python
@task
def process_order(self):
    payload = generate_order()
    with self.client.post("/orders", json=payload, catch_response=True) as response:
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "confirmed":
                response.success()
            else:
                response.failure(f"Unexpected status: {data.get('status')}")
        elif response.status_code == 400:
            # Validation error - expected for some test data
            response.success()  # Count as success if expected
        elif response.status_code == 404:
            # Resource not found - might be expected
            response.success()
        else:
            response.failure(f"Unexpected status: {response.status_code}")
```

## Throughput Tuning Guide

| Users | Wait Time | Expected TPS | Use Case |
|-------|-----------|--------------|----------|
| 10    | 1-3s      | 3-10         | Smoke test |
| 100   | 0.1-0.5s  | 200-1000     | Light load |
| 500   | 0.01-0.05s| 2000-5000    | Medium load |
| 1000  | 0.001-0.01s| 5000-10000  | High load |
| 2000+ | 0ms       | 10000+       | Stress test |

For TPS > 10K, use distributed mode with multiple workers.

## TPS Calculation Formula

```
TPS = users × (1000 / (latency_ms + wait_time_ms))
```

**Example with fast wait_time:**
- 200 users
- 6ms latency
- 5ms avg wait (between 0.001-0.01)
- TPS = 200 × (1000 / 11) = ~18K TPS theoretical

**Example with slow wait_time (BUG):**
- 200 users
- 10s avg wait (between 9-11)
- TPS = 200 × (1000 / 10000) = 20 TPS ← **This is why 50% target is a sign of wrong wait_time**

## Distributed Testing for 10K+ TPS

For production load testing at scale:

```bash
# On bastion/master
locust -f locustfile.py --master --host=http://api.example.com

# Start 16 workers
./start_locust_service.sh 16

# Or manually start workers
for i in {1..16}; do
    locust -f locustfile.py --worker --master-host=127.0.0.1 &
done
```

**Infrastructure for 10K+ TPS:**

| Component | Recommendation |
|-----------|---------------|
| Bastion | c6i.8xlarge (32 vCPU) |
| Workers | 16 (2 per vCPU core is fine) |
| Customer Pool | 100K (safe limit) |
| Wait Time | 0.001-0.01s (1-10ms) |

## Common Mistakes

1. **Small data pool causes contention**:
   ```python
   # Wrong - 100 IDs hit repeatedly
   DATA_POOL = [generate_id() for _ in range(100)]

   # Correct - 100K IDs spread load
   DATA_POOL = [generate_id() for _ in range(100000)]
   ```

2. **Not using catch_response for custom validation**:
   ```python
   # Wrong - 400 counted as failure even if expected
   self.client.post("/api", json=payload)

   # Correct - handle expected errors
   with self.client.post("/api", json=payload, catch_response=True) as r:
       if r.status_code in [200, 400]:
           r.success()
   ```

3. **Pool loading counted in stats**:
   ```python
   # Wrong - pool load affects latency stats
   self.client.get("/api/items?limit=100000")

   # Correct - name it separately
   self.client.get("/api/items?limit=100000", name="/api/items (warmup)")
   ```

4. **Missing timeout for slow endpoints**:
   ```python
   # Wrong - uses default timeout
   self.client.post("/slow-endpoint", json=data)

   # Correct - explicit timeout
   self.client.post("/slow-endpoint", json=data, timeout=30)
   ```

5. **Wrong wait_time active** (most common issue):
   ```python
   # Wrong - only 0.1 TPS per user
   wait_time = between(9, 11)

   # Correct - 100+ TPS per user
   wait_time = between(0.001, 0.01)
   ```

6. **Not restarting Locust after crash**:
   ```bash
   # After any infrastructure crash, ALWAYS restart Locust
   ./stop_locust_service.sh
   ./start_locust_service.sh 16
   # Workers cache customer pool - stale pool = random IDs = 404s
   ```

7. **Starting test via Locust UI instead of API**:
   ```bash
   # Wrong - no app metrics captured
   # Starting test directly in Locust UI at :8089

   # Correct - creates sampling document
   curl -X POST "http://your-alb/loadtest/external/start" \
     -d '{"user_count": 400, "spawn_rate": 40}'
   ```

## Performance Insights

### Why Fresh Containers = Better Performance

After restarting Docker containers, we observed 30% better TPS (19.5K vs ~15K). Reasons:

1. **Memory Fragmentation** - Python GC doesn't return memory to OS; fresh start = clean memory
2. **Connection Pool State** - Stale/errored connections cleared; fresh pools optimize distribution
3. **Docker Overlay Filesystem** - Writable layer cleared; cleaner I/O patterns
4. **Linux Kernel Caches** - TCP states, file descriptors, buffer caches reset

**Recommendation:** For sustained high-throughput testing (hours+), restart Docker periodically:
```bash
sudo systemctl restart docker
# Wait 30s for containers to stabilize before testing
```

### Latency Breakdown

| Metric | What It Measures | Typical Value |
|--------|------------------|---------------|
| Locust (End-to-End) | Bastion → EC2 → App → EC2 → Bastion | 18ms |
| App Processing | MongoDB queries + scoring + writes | 15ms |
| Network Overhead | Difference (Locust - App) | ~3ms |

### Results Reference (Production Load Test)

| Metric | Value | Notes |
|--------|-------|-------|
| Peak TPS | 19,500 | 195% of 10K target |
| P50 Latency | 16ms | Locust end-to-end |
| P99 Latency | 50ms | With MongoDB balancer active |
| Failure Rate | 0.2% | Acceptable for POC |
| Total Requests | 561,900 | 60-second sustained test |

## Quick Verification Commands

```bash
# Verify wait_time is correct
grep "wait_time = between" locustfile.py
# Expected: wait_time = between(0.001, 0.01)

# Check if customer pool loaded
curl http://localhost:8089/stats | jq '.stats[0].num_requests'

# Check API for 404s (indicates pool issue)
sudo docker logs --tail 20 api-container 2>&1 | grep -c "404"
# If high 404 count, restart Locust to reload pool

# Verify workers are running
curl http://localhost:8089/swarm | jq '.workers'
```

## Key Lessons Learned

1. **wait_time is CRITICAL** - `between(9,11)` vs `between(0.001,0.01)` is 1000x difference in TPS
2. **100K customer pool is safe limit** - Don't exceed without pagination
3. **Always restart Locust after infrastructure crash** - Workers cache customer pool
4. **Start tests via API, not Locust UI** - Required for app metrics sampling
5. **Customer IDs must match DB format** - `CUST-{12 hex uppercase}`
6. **Fresh containers = better performance** - Restart Docker periodically under high load
7. **Formula: targetTps / 50 = users** - Only valid when wait_time is correctly configured
8. **Check API logs for 404s** - High TPS but no App Processing = customer pool issue
9. **Use `name=` parameter for warmup requests** - Keeps stats clean
10. **Network overhead is ~3ms** - Difference between Locust and App latency
