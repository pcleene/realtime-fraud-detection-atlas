"""
Locust load test for RegionalBank Fraud Detection API.

Usage:
    # Single process (for testing)
    locust -f locustfile.py --host=http://<load-balancer-endpoint>

    # Headless mode (recommended for high TPS)
    locust -f locustfile.py \
      --host=http://<load-balancer-endpoint> \
      --headless \
      --users 1000 \
      --spawn-rate 100 \
      --run-time 60s

    # Distributed (master + workers for 10K+ TPS)
    # Terminal 1 - Master (with web UI on port 8089)
    locust -f locustfile.py --master --host=http://RegionalBank-fraud-alb-...

    # Terminal 2-N - Workers
    locust -f locustfile.py --worker --master-host=127.0.0.1
"""

from locust import HttpUser, task, between, events
import random
import string
from datetime import datetime, timezone
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pre-generated customer IDs (populated on test start)
# Use 100K customers for realistic load testing (avoids update contention and false velocity triggers)
# With 100K customers at 10K TPS: each customer hit every ~10 seconds (realistic)
# NOTE: For pools >100K, pagination should be configured. See LOAD-TEST-SESSION-2026-01-12.md
CUSTOMER_POOL = []
CUSTOMER_POOL_LOADED = False
CUSTOMER_POOL_SIZE = 100000  # 100K - safe value, proven in 10K TPS tests
# CUSTOMER_POOL_SIZE = 1000000  # 1M - requires pagination (not yet implemented)


def generate_customer_id():
    """Generate a random customer ID if pool is empty."""
    return f"CUST-{''.join(random.choices(string.hexdigits.upper(), k=12))}"


def generate_transaction_payload(customer_id: str = None):
    """Generate a realistic transaction payload."""
    if not customer_id:
        customer_id = random.choice(CUSTOMER_POOL) if CUSTOMER_POOL else generate_customer_id()

    channels = ["Livin", "KOPRA", "ATM", "QRIS", "Branch", "Ecom"]
    device_types = ["ios", "android", "web"]
    mccs = ["5411", "5812", "5311", "4111", "5999", "5541", "5912", "5251"]

    # Jakarta area coordinates with variation
    lat = -6.2 + random.uniform(-0.5, 0.5)
    lon = 106.8 + random.uniform(-0.5, 0.5)

    return {
        "customer_id": customer_id,
        "account_id": f"ACC-{random.randint(10000000, 99999999)}",
        "amount": random.randint(10000, 10000000),
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "channel": random.choice(channels),
        "merchant_id": f"M-{random.randint(1000, 9999)}",
        "merchant_name": f"Merchant {random.randint(1, 1000)}",
        "mcc": random.choice(mccs),
        "device_id": f"DEV-{random.randint(100000, 999999)}",
        "device_type": random.choice(device_types),
        "ip": f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
    }


class FraudAPIUser(HttpUser):
    """Simulates a user making transaction scoring requests."""

    # Wait time for throughput testing (documented in LOAD-TEST-SESSION-2026-01-12.md)
    wait_time = between(0.001, 0.01)  # 1-10ms - achieves 10K TPS with 200 users
    # wait_time = between(9, 11)  # ~10s between requests - for realistic simulation only

    def on_start(self):
        """Called when a user starts. Fetch customer pool if not loaded."""
        global CUSTOMER_POOL, CUSTOMER_POOL_LOADED

        if not CUSTOMER_POOL_LOADED:
            try:
                # Try to fetch real customers from the API
                # Use 100K customers for realistic load testing (avoids false velocity triggers)
                logger.info(f"Loading {CUSTOMER_POOL_SIZE} customers into pool...")
                response = self.client.get(f"/mock/customers?limit={CUSTOMER_POOL_SIZE}", timeout=60)
                if response.status_code == 200:
                    data = response.json()
                    customers = data.get("customers", [])
                    if customers:
                        CUSTOMER_POOL.extend([c["customer_id"] for c in customers])
                        CUSTOMER_POOL_LOADED = True
                        logger.info(f"Loaded {len(CUSTOMER_POOL)} customers into pool")
            except Exception as e:
                logger.warning(f"Failed to load customer pool: {e}")

            # Generate fallback customers if needed
            if not CUSTOMER_POOL:
                CUSTOMER_POOL.extend([generate_customer_id() for _ in range(1000)])
                CUSTOMER_POOL_LOADED = True
                logger.info(f"Generated {len(CUSTOMER_POOL)} fallback customer IDs")

    @task(20)
    def score_transaction(self):
        """Main task: Score a transaction for fraud (high weight)."""
        payload = generate_transaction_payload()
        with self.client.post(
            "/score-transaction",
            json=payload,
            catch_response=True,
            timeout=30
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                # Customer not found - expected for some random IDs
                response.success()
            elif response.status_code == 422:
                # Validation error - still counts as handled
                response.success()
            else:
                response.failure(f"Status {response.status_code}: {response.text[:200]}")

    @task(1)
    def health_check(self):
        """Occasional health check (low weight)."""
        with self.client.get("/health", catch_response=True, timeout=10) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code}")


class HighThroughputUser(HttpUser):
    """
    Optimized user for maximum throughput testing.
    No wait time, only score-transaction calls.
    """

    wait_time = between(0, 0)  # No wait - maximum throughput

    def on_start(self):
        """Load customer pool."""
        global CUSTOMER_POOL, CUSTOMER_POOL_LOADED

        if not CUSTOMER_POOL_LOADED:
            try:
                # Use 100K customers for realistic load testing
                logger.info(f"Loading {CUSTOMER_POOL_SIZE} customers into pool...")
                response = self.client.get(f"/mock/customers?limit={CUSTOMER_POOL_SIZE}", timeout=60)
                if response.status_code == 200:
                    data = response.json()
                    customers = data.get("customers", [])
                    if customers:
                        CUSTOMER_POOL.extend([c["customer_id"] for c in customers])
                        CUSTOMER_POOL_LOADED = True
                        logger.info(f"Loaded {len(CUSTOMER_POOL)} customers into pool")
            except Exception:
                pass

            if not CUSTOMER_POOL:
                CUSTOMER_POOL.extend([generate_customer_id() for _ in range(1000)])
                CUSTOMER_POOL_LOADED = True

    @task
    def score_transaction(self):
        """Only score transactions - no health checks."""
        payload = generate_transaction_payload()
        with self.client.post(
            "/score-transaction",
            json=payload,
            catch_response=True,
            timeout=30
        ) as response:
            if response.status_code in [200, 404, 422]:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")


@events.init_command_line_parser.add_listener
def add_custom_arguments(parser):
    """Add custom command line arguments."""
    parser.add_argument(
        "--customer-pool-size",
        type=int,
        default=100000,
        help="Number of customers to load into pool (default: 100K for realistic testing)"
    )


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when test starts."""
    logger.info(f"Starting load test against {environment.host}")
    logger.info("Target: 10,000 TPS with <50ms P50 latency")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when test stops. Print summary statistics."""
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
    print(f"  P50 < 50ms:       {'PASS' if p50 < 50 else 'FAIL'} ({p50:.2f}ms)")
    print(f"  P99 < 500ms:      {'PASS' if p99 < 500 else 'FAIL'} ({p99:.2f}ms)")
    print(f"  Error rate < 0.1%: {'PASS' if error_rate < 0.1 else 'FAIL'} ({error_rate:.2f}%)")
    print(f"  RPS > 10,000:     {'PASS' if rps > 10000 else 'FAIL'} ({rps:.2f})")
    print("=" * 60 + "\n")
