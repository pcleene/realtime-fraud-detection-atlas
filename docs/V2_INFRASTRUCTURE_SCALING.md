# V2 Infrastructure Scaling — 50K TPS Target

## The Math

| Metric | V1 (achieved) | V2 (target) | Multiplier |
|--------|---------------|-------------|------------|
| TPS | 10,144 sustained (19.5K peak) | 50,000 sustained | ~5× |
| DB ops/sec | 30K (10K × 3 ops) | 150K (50K × 3 ops) | 5× |
| Read throughput | ~17 MB/s (10K × 1.7KB) | ~85 MB/s (50K × 1.7KB) | 5× |
| Write throughput | ~15 MB/s | ~75 MB/s | 5× |

V1 used 2× c6i.16xlarge EC2 instances (129 workers each, 258 total workers) behind an ALB, with a 3-shard M60 Atlas cluster. We need to scale each layer for 5× throughput.

---

## MongoDB Atlas Layer

### Can 3 Shards Handle 150K ops/sec?

Short answer: very likely yes, but 4-5 shards gives comfortable headroom.

Each M60 shard is a 3-node replica set with 64 GB RAM and dedicated NVMe SSDs. With WiredTiger compression and our 1.7KB average document size, the working set fits comfortably in RAM.

**Per-shard capacity estimates (M60):**

| Metric | Conservative | Optimistic |
|--------|-------------|------------|
| Read ops/sec | 30,000–40,000 | 50,000+ |
| Write ops/sec | 15,000–25,000 | 30,000+ |
| Combined ops/sec | 40,000–50,000 | 60,000+ |

Our 150K ops split across shards:
- 3 shards: ~50K ops/shard — tight on writes, workable on reads
- 4 shards: ~37.5K ops/shard — comfortable
- 5 shards: ~30K ops/shard — very comfortable, plenty of headroom for spikes

**Recommendation:** Start with **4 shards (M60)**, scale to 5 if P99 latency creeps up under sustained load. This is still dramatically fewer than 36 Redis shards.

The customer read and update hit the same shard (range sharding on customer_id). The transaction insert also co-locates (compound shard key includes customer_id). So each transaction's 3 ops land on the same shard — no scatter-gather.

### Connection Budget

Each Gunicorn worker opens its own connection pool (maxPoolSize=15). The math:

| Config | Workers/EC2 | EC2 Count | Total Workers | Connections (@ 15/worker) |
|--------|-------------|-----------|---------------|--------------------------|
| V1 | 129 | 2 | 258 | 3,870 |
| V2 (conservative) | 129 | 5 | 645 | 9,675 |
| V2 (aggressive) | 129 | 8 | 1,032 | 15,480 |

M60 supports ~16,000 connections per shard (configurable). At 5 EC2s we're fine. At 8 EC2s we'd be approaching limits — reduce maxPoolSize to 10 if needed.

**Important:** With `readPreference=nearest` and PrivateLink, all connections route through the private network with <1ms latency. No internet hops.

---

## Application Layer (EC2 Scaling)

### V1 Baseline

| Component | V1 Config | V1 Result |
|-----------|-----------|-----------|
| Instance type | c6i.16xlarge (64 vCPU, 128 GB RAM) | Good fit for compute-bound scoring |
| Workers per instance | 129 (2 × 64 + 1) | Full CPU utilization |
| Instances | 2 | 10K TPS sustained |
| Load balancer | ALB | Round-robin distribution |

### V2 Scaling Estimate

V2 scoring is heavier per transaction (31 rules vs 5), but the rules are all CPU-bound — no extra I/O. The extra CPU cost per request is modest (pure Python comparisons, set lookups, arithmetic). Estimated overhead: 0.1–0.3ms more CPU time per request.

The bottleneck at 50K TPS is not per-request CPU time — it's concurrent connection handling. Each worker handles one request at a time (async I/O lets it overlap with DB wait time, but CPU work is single-threaded per worker).

**Worker throughput estimate:**

Each worker can handle requests at roughly the inverse of the total time per request. At 18ms average (V1), one worker handles ~55 requests/second. For V2 with slightly more CPU work, call it ~50 requests/second per worker.

| Target TPS | Workers Needed (@ 50 req/s/worker) | EC2 Count (129 workers/instance) |
|------------|-------------------------------------|----------------------------------|
| 50,000 | 1,000 | 8 |
| 50,000 (with 25% headroom) | 1,250 | 10 |

**Recommendation: 8–10 × c6i.16xlarge instances.**

That's 4–5× more EC2s than V1, which makes sense for 5× the throughput. The scaling is roughly linear because each request is independent.

### Can We Use Smaller Instances?

Yes, if you want more granularity. The key metric is total vCPU across the fleet:

| Option | Instance Type | vCPU Each | Count | Total vCPU | Workers | Monthly Cost (est.) |
|--------|--------------|-----------|-------|-----------|---------|-------------------|
| A (big) | c6i.16xlarge | 64 | 8 | 512 | 1,032 | ~$16,000 |
| B (medium) | c6i.8xlarge | 32 | 16 | 512 | 1,040 | ~$16,000 |
| C (small) | c6i.4xlarge | 16 | 32 | 512 | 1,056 | ~$16,000 |

Cost is similar (compute pricing is linear). The tradeoffs:

- **Fewer big instances**: Simpler to manage, fewer ALB targets. But losing one instance is a bigger capacity hit (12.5% vs 3%).
- **More small instances**: Better fault tolerance, smoother auto-scaling. But more operational overhead, more connections to Atlas.

For a POC demo, **Option A (8× c6i.16xlarge)** is simplest. For production, Option B or C gives better resilience.

### Auto Scaling Group Config

```hcl
resource "aws_autoscaling_group" "api" {
  min_size         = 4     # minimum viable at ~25K TPS
  max_size         = 12    # headroom for spikes
  desired_capacity = 8     # target for 50K TPS

  health_check_type         = "ELB"
  health_check_grace_period = 120

  target_tracking_scaling_policy {
    target_value = 70.0    # scale out at 70% CPU
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
  }
}
```

### Docker Resource Limits (per EC2)

**Critical:** V1's default Docker limits (7 CPUs, 14GB) were a severe bottleneck. Update for c6i.16xlarge:

```yaml
deploy:
  resources:
    limits:
      cpus: "60"        # leave 4 vCPU for OS + monitoring
      memory: "120G"    # leave 8 GB for OS
```

### In-Memory Cache Impact

Each Gunicorn worker loads its own copy of the transaction-level blacklists (~150MB). With 129 workers per EC2, that's 129 × 150MB = **~19 GB per instance** for caches alone.

On a c6i.16xlarge (128 GB RAM), this leaves ~100 GB for Python, connection pools, and OS. Comfortable.

If memory becomes a concern, consider using a shared-memory approach (multiprocessing.shared_memory or mmap) to load the caches once per instance instead of once per worker. This would reduce cache memory from ~19 GB to ~150 MB per instance. Worth doing for production but not required for the POC.

---

## ALB Configuration

The ALB needs to handle 50K req/sec. AWS ALBs scale automatically, but you should pre-warm:

```bash
# Request ALB pre-warming through AWS support
# Specify: 50,000 requests/sec, average request size 2KB, average response size 5KB
```

ALB config:
```hcl
resource "aws_lb" "api" {
  internal           = false
  load_balancer_type = "application"
  idle_timeout       = 60     # seconds

  # Enable cross-zone load balancing for even distribution
  enable_cross_zone_load_balancing = true
}

resource "aws_lb_target_group" "api" {
  port                 = 8000
  protocol             = "HTTP"
  deregistration_delay = 30

  health_check {
    path                = "/health"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  stickiness {
    enabled = false    # no sticky sessions — any instance can score any customer
  }
}
```

---

## Locust Bastion — The Real Bottleneck

This is where you're right to be worried. Generating 50K HTTP requests/second from a single bastion is significantly harder than you'd think.

### V1 Locust Setup

V1 used a single bastion running Locust with 16 workers, generating 10K TPS. That was already pushing it.

### The Problem at 50K TPS

Locust is Python-based (asyncio/gevent). Each Locust worker is a single Python process. Python's GIL limits per-process throughput. A single Locust worker on a c6i.4xlarge can generate roughly 2,000–3,000 HTTP requests/second (depending on response time and payload size).

| Target TPS | Workers Needed (@ 2,500 req/s/worker) | vCPU Needed (@ 1 worker/vCPU) |
|-----------|--------------------------------------|-------------------------------|
| 10,000 | 4–5 | 8–10 (1× c6i.4xlarge) |
| 50,000 | 20–25 | 32–40 |

**A single c6i.4xlarge (16 vCPU) is NOT enough for 50K TPS.** You need either a bigger bastion or multiple bastions.

### Option 1: One Big Bastion (Simplest)

Use a c6i.16xlarge (64 vCPU) as the bastion. Run Locust in distributed mode with 1 master + 48 workers (leave headroom for the master and OS).

```bash
# On the bastion
locust -f locustfile.py --master --host=http://internal-alb.amazonaws.com &

for i in $(seq 1 48); do
  locust -f locustfile.py --worker --master-host=127.0.0.1 &
done
```

At 2,500 req/s per worker × 48 workers = **~120K req/s theoretical capacity**, which gives comfortable headroom for 50K sustained.

**Cost:** One c6i.16xlarge for the bastion during load testing only. Shut it down when not testing.

**Customer pool consideration:** V1 loads 100K customers into each worker's memory. At 48 workers × ~80 MB per pool = ~3.8 GB. No problem on a 128 GB instance.

### Option 2: Multiple Bastions (More Realistic for Production Load Testing)

Run 3–4 c6i.4xlarge bastions, each with 12 Locust workers. One runs the master, the others connect as remote workers.

```bash
# Bastion 1 (master + 12 workers)
locust -f locustfile.py --master --expect-workers=48 &
for i in $(seq 1 12); do locust -f locustfile.py --worker --master-host=127.0.0.1 & done

# Bastion 2, 3, 4 (12 workers each, connecting to master)
for i in $(seq 1 12); do locust -f locustfile.py --worker --master-host=bastion1-ip & done
```

This is more complex to orchestrate but spreads the network load across multiple ENIs. A single ENI has bandwidth limits (~10 Gbps on c6i.4xlarge) that could become a bottleneck at very high request rates with large payloads.

### Option 3: Replace Locust with a Compiled Load Generator

For pure HTTP throughput, tools like **wrk2**, **vegeta**, or **k6** are significantly more efficient than Python-based Locust:

| Tool | Language | TPS per vCPU | Notes |
|------|----------|-------------|-------|
| Locust | Python | ~2,500 | Rich UI, custom logic, but GIL-limited |
| k6 | Go | ~10,000–15,000 | Scriptable (JS), good metrics, open source |
| wrk2 | C | ~20,000+ | Bare metal speed, limited scripting |
| vegeta | Go | ~15,000+ | Simple HTTP load, good for CI/CD |

**k6** is the best middle ground: fast enough to generate 50K TPS from a single c6i.4xlarge, scriptable enough to randomize customer IDs and payloads, and has a built-in metrics dashboard.

However, your V1 Locust setup already has the customer pool loading, the custom request logic, and the integration with the frontend dashboard. Rewriting in k6 is a project.

**Recommendation for the POC:** Use **Option 1 (one big bastion, c6i.16xlarge, 48 Locust workers)**. It's the simplest change from V1 and will comfortably hit 50K TPS. If you need to go beyond 50K or want a permanent load testing solution, consider k6.

### Network Considerations

At 50K req/sec with ~2KB request and ~5KB response:
- Outbound from bastion: 50K × 2KB = **100 MB/s** (~800 Mbps)
- Inbound to bastion: 50K × 5KB = **250 MB/s** (~2 Gbps)

A c6i.16xlarge has 25 Gbps network bandwidth — plenty of headroom. A c6i.4xlarge has 12.5 Gbps — also fine for a single bastion.

**Important:** The bastion should be in the **same AZ** as the ALB to minimize network latency. If the bastion is in a different AZ, you add ~0.5-1ms per request, which inflates your measured latency and doesn't reflect real-world performance (clients won't come from the same AZ).

---

## Customer Pool Strategy (Lessons from V1)

### The 1M Customer Pool Crash

In V1 we attempted to load 1M customer IDs into the Locust pool via `/mock/customers?limit=1000000`. This crashed the API instances — the root cause was **serializing 1M IDs into a single JSON response (~20MB) exceeded the ALB's 60-second timeout**, making the instances unresponsive. Cascading failures followed: SSM agent went dark, disk filled up from Docker logs, and the entire stack required manual recovery.

Tested limits from V1:

| Pool Size | Status | Issue |
|-----------|--------|-------|
| 100K | Safe | Proven in production, reliable |
| 200K | Risky | Near ALB timeout, untested |
| 300K+ | Crashes | Exceeds 60s ALB timeout |
| 1M | Crashes hard | Serialization timeout, cascading failures |

### Why a Bigger Pool Matters at 50K TPS

At 50K TPS with a 100K customer pool, each customer gets hit on average every **2 seconds**. That's a problem for two reasons:

1. **Write contention:** Two concurrent requests for the same customer means two `update_one` operations competing for the same document. MongoDB handles this with document-level locking, but at high concurrency it adds retry overhead and inflates P99.
2. **False velocity triggers:** var_8 flags transactions <10 seconds apart. At 2-second spacing, every single transaction would trigger velocity — making the fraud distribution unrealistic.

### Target: 500K–1M Pool with Paginated Loading

To get realistic spacing at 50K TPS, we want each customer hit roughly every 10–20 seconds. That means a pool of 500K–1M customers.

**The solution is paginated loading** — don't try to fetch all IDs in one request:

```python
# In locustfile.py setup
async def load_customer_pool(host, target_size=500000, page_size=50000):
    """Load customer pool in pages to avoid ALB timeout."""
    customers = []
    skip = 0
    while len(customers) < target_size:
        resp = requests.get(f"{host}/mock/customers?limit={page_size}&skip={skip}")
        batch = resp.json()
        if not batch:
            break
        customers.extend(batch)
        skip += page_size
    return customers
```

The `/mock/customers` endpoint needs a `skip` parameter (add to V2). Each page of 50K takes ~3 seconds to serialize — well within ALB timeout.

**Memory impact:** 500K customer IDs at ~50 bytes each = ~25 MB per Locust worker. At 48 workers = ~1.2 GB total. Trivial on a c6i.16xlarge (128 GB).

### Transaction Spacing Strategy

Even with a large pool, random selection can cluster. To guarantee minimum spacing between transactions for the same customer, use a **shuffle-and-rotate** approach:

```python
import random
from collections import deque

class FraudUser(HttpUser):
    customer_queue = None

    def on_start(self):
        if FraudUser.customer_queue is None:
            # Shared across all users in this worker
            pool = load_customer_pool(self.host, target_size=500000)
            random.shuffle(pool)
            FraudUser.customer_queue = deque(pool)

    @task
    def score_transaction(self):
        # Round-robin through shuffled pool — guarantees max spacing
        customer = FraudUser.customer_queue[0]
        FraudUser.customer_queue.rotate(-1)
        # ... build and send request
```

With 500K customers across 48 workers, each worker cycles through ~10,400 customers. At ~1,000 req/s per worker, each customer gets hit every ~10 seconds — right at the velocity threshold, giving a realistic mix of triggered and non-triggered velocity checks.

| Pool Size | Workers | Customers/Worker | Avg Gap at 50K TPS |
|-----------|---------|-----------------|-------------------|
| 100K | 48 | ~2,100 | ~2s (too fast — all velocity triggers) |
| 250K | 48 | ~5,200 | ~5s (borderline) |
| 500K | 48 | ~10,400 | ~10s (matches threshold — realistic) |
| 1M | 48 | ~20,800 | ~20s (comfortable, ~10% velocity triggers) |

**Recommendation:** Target **500K** for a balanced fraud distribution. Go to 1M if you want lower velocity trigger rates. Use paginated loading either way.

---

## V1 Optimizations to Carry Forward

These are proven at 19.5K TPS peak. They're non-negotiable for V2.

### 1. Parallel I/O (asyncio.gather)
Phase 1 reads and Phase 3 writes run in parallel. This is the single biggest latency win — cuts wall-clock time nearly in half vs sequential. In particular, the **customer update and transaction insert must run in parallel** (Phase 3) — V1 proved this with asyncio.gather. Running them sequentially would add ~5ms to every request.

### 2. Connection Pooling + Read Preference
maxPoolSize=15 per worker, minPoolSize=3 (keep warm), compression=zstd. Don't change these unless Atlas connection limits force it. **readPreference must be set to `nearest`** in the connection string — this allows reads to go to the closest replica set member (typically the primary in the same AZ via PrivateLink), eliminating cross-AZ latency. This was a meaningful latency win in V1 and is even more important at 50K TPS where every 0.5ms matters.

### 3. Projection on find_one
Only fetch fields needed for scoring. The V2 customer document is larger (~1.7KB vs ~500 bytes in V1), so projection becomes even more important. Don't fetch b24_list if you're not evaluating var_22 (though in practice you always will).

### 4. In-Memory Caching
V1 cached holidays and blacklist locations (~7KB per worker). V2 caches transaction-level blacklists (~150MB per worker). Same pattern, bigger data. The TTL refresh pattern (atomic swap) prevents stale reads.

### 5. Gunicorn Worker Formula
2 × vCPU + 1. Don't over-provision workers — more workers = more connection pools = more Atlas connections. 129 workers on c6i.16xlarge is the sweet spot.

### 6. Non-Monotonic Customer IDs
CUST-{hex12} distributes evenly across range shards. Do NOT switch to sequential IDs.

### 7. Shard Key Design
Customers: `{customer_id: 1}` (range). Transactions: `{customer_id: 1, shard_key_month: 1, _id: 1}`. This co-locates all 3 operations for a given customer on the same shard.

### 8. Docker Resource Limits
Explicitly set CPU and memory limits to match the instance size. The V1 default of 7 CPUs was a 10× bottleneck on a 64 vCPU instance.

### 9. PrivateLink
All traffic between EC2 and Atlas stays on the private network. No internet routing, no TLS overhead on public endpoints. ~0.3ms saved per round-trip vs public connection.

### 10. Read Preference = Nearest
Reads go to the nearest replica set member (usually the primary in the same AZ). Eliminates cross-AZ latency for reads.

---

## Summary: V2 Infrastructure Shopping List

| Component | V1 | V2 | Notes |
|-----------|----|----|-------|
| Atlas cluster | M60, 3 shards | M60, 4-5 shards | Scale to 5 if P99 > 30ms |
| API EC2 instances | 2× c6i.16xlarge | 8–10× c6i.16xlarge | ASG min=4, max=12 |
| Workers per EC2 | 129 | 129 | Same formula |
| Total workers | 258 | 1,032–1,290 | Linear scaling |
| ALB | Standard | Pre-warmed | Request pre-warming via AWS support |
| Bastion (Locust) | 1× c6i.4xlarge, 16 workers | 1× c6i.16xlarge, 48 workers | Or 4× c6i.4xlarge distributed |
| PrivateLink | Yes | Yes | Non-negotiable |
| VPC | Single AZ sufficient | Multi-AZ recommended | For production resilience |

### Estimated Monthly Cost (POC, on-demand pricing, us-east-1)

| Component | Unit Cost | Count | Monthly |
|-----------|-----------|-------|---------|
| c6i.16xlarge (API) | ~$2.00/hr | 8 | ~$11,520 |
| c6i.16xlarge (bastion) | ~$2.00/hr | 1 (only during testing) | ~$200 (100 hrs) |
| Atlas M60 (4 shards) | ~$4,200/mo per shard | 4 | ~$16,800 |
| ALB | ~$0.008/LCU-hr | 1 | ~$500 |
| PrivateLink | ~$0.01/GB + $0.01/hr | 1 | ~$300 |
| NAT Gateway | ~$0.045/hr + $0.045/GB | 1 | ~$200 |
| **Total** | | | **~$29,520/mo** |

For the POC demo (run for a few days, not a full month), actual cost would be a fraction of this. Scale down to 4 EC2s and 3 shards when not actively load testing.

---

## Quick Start: Scaling from V1 to V2

1. **Atlas:** Add 1-2 shards to existing cluster (online, no downtime)
2. **Terraform:** Update `desired_capacity` from 2 to 8 in ASG, `instance_type` stays c6i.16xlarge
3. **Docker:** Verify resource limits match instance size (cpus: 60, memory: 120G)
4. **Bastion:** Launch a c6i.16xlarge, run 48 Locust workers
5. **ALB:** Request pre-warming from AWS support
6. **Test incrementally:** 10K → 25K → 40K → 50K TPS, checking P99 at each step
7. **Monitor:** Atlas metrics (ops/sec, connections, disk IOPS), EC2 metrics (CPU, network), ALB metrics (5xx rate, latency)
