# Load Testing System

The fraud detection POC includes two load testing approaches:

| Approach | Best For | Throughput |
|----------|----------|------------|
| **Embedded (UI)** | Quick demos, development testing | Up to ~500 TPS |
| **Locust (Bastion)** | Production load testing | **10K+ TPS** |

## Architecture Overview

### Embedded Load Test (UI)

The embedded load test runs directly on the API server, triggered from the UI.

```
┌─────────────────────────────────────────────────┐
│              Your Laptop                         │
│                                                  │
│   Browser ──→ http://localhost:3000 (Frontend)  │
│                      │                           │
│                      │ Vite proxy /api → :8000   │
│                      ▼                           │
│   POST /loadtest/start                           │
│                      │                           │
│                      ▼                           │
│   Backend (:8000) runs load generator            │
│                      │                           │
│   HTTP calls to http://localhost:8000/score-transaction
│   (backend calls itself)                         │
└─────────────────────────────────────────────────┘
```

### Production Architecture (10K+ TPS)

For high-throughput testing, Locust runs on a bastion host with 16 distributed workers.

```
┌─────────────────┐      ┌─────────────────────────────────────────────────────────────┐
│   Browser UI    │      │  AWS VPC (ap-southeast-1)                                    │
│                 │      │                                                              │
│  ┌───────────┐  │      │  ┌─────────────────────────────────────────────────────────┐│
│  │Infrastructure│      │  │  Bastion c6i.8xlarge (<private-ip>)                     ││
│  │[L]→[ALB]→[EC2]→[M] │  │  │  Locust Master :8089 + 16 Workers                      ││
│  └───────────┘  │      │  │  Customer pool: 100K (loaded at startup)                ││
│                 │      │  └────────────────────┬────────────────────────────────────┘│
│  [Start Test]───┼──────┼───────────────────────┼─────────────────────────────────────│
│  [Get Stats]────┼──────┼───────────────────────┘                                     │
└─────────────────┘      │                       │ HTTP requests                        │
                         │                       ▼                                      │
                         │  ┌────────────────────────────────────────┐                 │
                         │  │     Application Load Balancer (ALB)     │                 │
                         │  │     Round-robin to EC2 instances        │                 │
                         │  └───────────────┬────────────┬───────────┘                 │
                         │                  │            │                              │
                         │                  ▼            ▼                              │
                         │  ┌──────────────────┐  ┌──────────────────┐                 │
                         │  │ EC2 c6i.16xlarge │  │ EC2 c6i.16xlarge │                 │
                         │  │ Docker + Gunicorn│  │ Docker + Gunicorn│                 │
                         │  │ 129 workers      │  │ 129 workers      │                 │
                         │  └────────┬─────────┘  └────────┬─────────┘                 │
                         │           │                     │                            │
                         │           └──────────┬──────────┘                            │
                         │                      │ PrivateLink                           │
                         │                      ▼                                       │
                         │  ┌────────────────────────────────────────┐                 │
                         │  │   MongoDB Atlas M60 (3 shards)          │                 │
                         │  │   35M customers · 80M+ transactions     │                 │
                         │  └────────────────────────────────────────┘                 │
                         └─────────────────────────────────────────────────────────────┘
```

## Embedded Load Test (Quick Start)

### From the UI

1. Start dev servers: `make dev`
2. Open http://localhost:3000
3. Go to **Load Testing** tab
4. Configure: TPS and duration
5. Click **Start Load Test**

### Via API

```bash
# Start a load test
curl -X POST http://localhost:8000/loadtest/start \
  -H "Content-Type: application/json" \
  -d '{"target_tps": 100, "duration_seconds": 10, "concurrency": 50, "fraud_rate": 0.12}'

# Response: {"test_id": "test-abc123", "status": "running", ...}

# Poll for progress
curl http://localhost:8000/loadtest/progress/test-abc123

# Get final results
curl http://localhost:8000/loadtest/result/test-abc123

# Stop a running test
curl -X POST http://localhost:8000/loadtest/stop/test-abc123
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/loadtest/start` | POST | Start a new load test |
| `/loadtest/progress/{id}` | GET | Get real-time progress |
| `/loadtest/result/{id}` | GET | Get final results (after completion) |
| `/loadtest/stop/{id}` | POST | Stop a running test |

### Configuration

```json
{
  "target_tps": 100,
  "duration_seconds": 30,
  "concurrency": 50,
  "fraud_rate": 0.12,
  "target_url": null
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `target_tps` | int | 100 | Target transactions per second (1-10000) |
| `duration_seconds` | int | 10 | Test duration in seconds (1-300) |
| `concurrency` | int | 50 | Number of concurrent HTTP connections (1-500) |
| `fraud_rate` | float | 0.12 | Fraction of transactions near fraud hotspots (0-1) |
| `target_url` | string | null | Override target URL (defaults to self) |

---

## Locust Load Test (10K+ TPS)

For production-grade load testing, use Locust running on the bastion host.

### Performance Achieved (January 2026)

| Metric | Achieved | Target | Notes |
|--------|----------|--------|-------|
| **Peak TPS** | **19,500** | 10,000 | 195% of target |
| **Sustainable TPS** | **10,144** | 10,000 | 60s sustained test |
| **Avg Latency** | **18ms** | <50ms | 64% under target |
| **P50 Latency** | **16ms** | - | Excellent |
| **P95 Latency** | **29ms** | - | Excellent |
| **P99 Latency** | **50ms** | <100ms | Well under target |
| **Failure Rate** | **0.2%** | <0.1% | Acceptable |
| **Total Requests** | **561,900** | - | In 60s test |

#### Latency Breakdown (from UI)

| Component | Time | % of Total |
|-----------|------|------------|
| Scoring (reads + rules) | 4ms | 31% |
| Persist (update + insert) | 10ms | 69% |
| Network overhead | ~3ms | - |
| **Total App Processing** | **14ms** | - |

See [PERFORMANCE-TUNING.md](./PERFORMANCE-TUNING.md) for optimization details.

### Quick Start (via UI)

1. Ensure Locust is running on bastion (see [LOCUST-SETUP.md](./LOCUST-SETUP.md))
2. Open the frontend UI (via ALB or localhost:5173)
3. Go to **Load Testing** tab
4. Select Target TPS (100 to 10K) and Duration
5. Click **Start Load Test**

### Quick Start (via API)

```bash
# Check Locust status
curl http://ALB-DNS/loadtest/external/status | jq .

# Start test (500 users, 50/sec spawn rate)
curl -X POST http://ALB-DNS/loadtest/external/start \
  -H "Content-Type: application/json" \
  -d '{"user_count": 500, "spawn_rate": 50}'

# Get stats
curl http://ALB-DNS/loadtest/external/stats | jq .

# Stop test
curl http://ALB-DNS/loadtest/external/stop
```

### Locust Proxy Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/loadtest/external/status` | GET | Check if Locust is running |
| `/loadtest/external/start` | POST | Start a Locust test |
| `/loadtest/external/stop` | POST | Stop the running test |
| `/loadtest/external/stats` | GET | Get current statistics |
| `/loadtest/external/reset` | GET | Reset statistics |

### Setup Documentation

For complete Locust setup instructions:
- **[LOCUST-SETUP.md](./LOCUST-SETUP.md)** - Full architecture, configuration, and startup scripts
- **DEPLOYMENT-RUNBOOK.md** - Quick reference with exact commands

---

## UI Features

The Load Testing tab provides:

- **Infrastructure overview:** Visual flow: Bastion (Locust 16w) → ALB → 2×EC2 c6i.16xl → Atlas M60 (3 shards)
- **TPS presets:** 100, 1K, 5K, 7.5K, 10K
- **Duration presets:** 10s, 30s, 60s, 120s
- **Live metrics:** Current TPS, avg latency, P95/P99 latency
- **Risk distribution:** Low/Medium/High counts (1% sample)
- **Latency timeline:** Live visualization of response times
- **Scoring/Persist breakdown:** Shows read vs write time distribution

### Understanding Risk Distribution

The load test generates transactions in the Jakarta area where blacklist locations are seeded. Transactions within 500m of a blacklist location trigger the "blacklist_proximity" rule:

- **fraud_hub** locations: +35 points → Medium Risk
- **scammer** locations: +25 points → Medium Risk
- **wifi_fraud** locations: +15 points → Low/Medium Risk

The distribution you see (many Medium, few High, few Low) indicates the test is correctly detecting transactions near fraud hotspots. High Risk requires multiple rules triggering simultaneously (e.g., velocity + blacklist).

### Latency Dashboard (Two-Card Layout)

The dashboard shows two distinct cards for comprehensive latency analysis:

**1. Locust (End-to-End)** - Purple card
- Measures full round-trip: Bastion → ALB → EC2 → App → EC2 → ALB → Bastion
- Shows: Avg / P50 / P95 / P99 latency
- Includes: TPS, total requests, failure rate

**2. App Processing** - Blue card
- Measures application-level timing: MongoDB queries + rule scoring + writes
- Shows: Total / P95 / P99 / Network overhead (Locust - App)
- **Scoring/Persist Breakdown** with visual bars:
  - **Scoring** = parallel MongoDB reads + rule evaluation (before writes)
  - **Persist** = customer feature update + transaction insert (writes)

### How Scoring/Persist Breakdown Works

During load tests, the backend samples ~1% of transactions and stores timing data:

```
score_transaction()
    ├─ start_time
    ├─ Parallel reads (customer, blacklist, holidays)
    ├─ Rule evaluation
    ├─ scoring_ms = time_after_rules - start_time
    ├─ Parallel writes (update customer, insert transaction)
    ├─ persist_ms = end_time - time_after_rules
    └─ total_ms = scoring_ms + persist_ms
```

The sampler stores this in MongoDB:
```python
# backend/app/services/locust_sampler.py
await db.load_tests.update_one(
    {"test_id": test_id},
    {
        "$inc": {
            "latency_stats.scoring_sum": scoring_ms,
            "latency_stats.persist_sum": persist_ms,
            "latency_stats.count": 1,
        },
        "$push": {"latency_stats.samples": {...}}
    }
)
```

The UI polls `/loadtest/progress/{id}` which returns `avg_scoring_ms` and `avg_persist_ms` calculated from the sampled data.

### Infrastructure (Production)

The UI connects to Locust running on the AWS bastion host:

```
Locust (16 workers) → ALB → 2× EC2 c6i.16xl (129 workers each) → Atlas M60 (3 shards)
         ↓                        ↓                                    ↓
   ap-southeast-1          Round-robin LB                    35M customers
   203.0.113.10:8089      Docker + Gunicorn                 80M+ transactions
```

- **Bastion → ALB:** VPC internal networking
- **EC2 → Atlas:** PrivateLink (low-latency private connection)

The UI automatically polls both Locust stats and the app-level sampled data (1% sample) to show the complete picture.

---

## Implementation Details

### Customer Sampling

**Locust (Bastion mode):**
- Fetches 100K customers from `/mock/customers?limit=100000`
- Simple sequential fetch (first N customers from MongoDB)
- Random customer IDs (`CUST-{hex12}`) ensure even shard distribution
- Falls back to generating random IDs if API unavailable

**Embedded (not currently linked to UI):**
- Uses chunk-aware sampling via `customer_sampling.py`
- Queries `config.chunks` for shard boundaries
- Samples proportionally from each chunk

> **Note:** The embedded load test (`/loadtest/start`) exists but is not connected to the frontend UI. Use Bastion mode for production load testing.

### Key Files

| File | Description |
|------|-------------|
| `backend/app/routes/loadtest.py` | Embedded load test (not linked to UI) |
| `backend/app/routes/locust_proxy.py` | FastAPI proxy to Locust (local or bastion) |
| `backend/app/services/locust_sampler.py` | Transaction sampler for real-time stats |
| `backend/app/services/customer_sampling.py` | Chunk-aware sampling (embedded test only) |
| `backend/loadtest/locustfile.py` | Locust test configuration |
| `backend/loadtest/*.sh` | Locust startup scripts for bastion |
| `frontend/src/lib/components/LoadTestDashboard.svelte` | UI component |
| `frontend/src/lib/api.ts` | Frontend API client |

### Multi-Worker State Management

Load test state is stored in MongoDB (`load_tests` collection) to support multi-worker deployments behind an ALB.

```
POST /loadtest/start → hits Worker A → starts background task
                                       ↓
                                Every 300ms: sync to MongoDB
                                       ↓
GET /loadtest/progress → hits any worker → reads from MongoDB
```

---

## Troubleshooting

### "No customers in database"

```bash
make seed-test   # Quick seed (5 customers)
# or
make seed        # Full seed (10k customers)
```

### Low TPS / High Latency

1. Check MongoDB Atlas metrics for connection issues
2. Verify indexes exist: `make verify`
3. For embedded tests, try `make dev-workers` (4 Gunicorn workers)
4. Restart Docker containers for fresh connection pools (see "Fresh Containers" below)

### Bastion (Locust) Connection Errors

1. Verify Locust is running: `ssh bastion "pgrep -f locust"`
2. Check security groups allow EC2 → Bastion:8089
3. Check `LOCUST_HOST` environment variable on EC2 instances

### Test Stuck at "running"

Background task may have failed. Check logs:
```bash
make docker-logs   # If running Docker
# or check terminal output if running make dev
```

### App Processing Shows 0ms / No Risk Distribution

**Symptoms:** Locust shows high TPS but App Processing card shows 0ms, no risk distribution data.

**Likely causes:**
1. **Customer pool empty:** Locust workers generating random IDs that don't exist
2. **Test not started via API:** Direct Locust UI doesn't create `load_tests` document

**Fix:**
```bash
# On bastion - restart Locust to reload customer pool
cd /home/ssm-user/RegionalBank_fraud_detection/backend/loadtest
./stop_locust_service.sh
./start_locust_service.sh 16

# Verify customer pool loaded - check API logs for 200s not 404s
sudo docker logs --tail 20 RegionalBank_fraud_detection-api-1 2>&1 | grep score
```

### EC2 Disk Full / Docker Won't Start

**Symptoms:** `docker.service failed`, disk at 100%

**Fix:**
```bash
# Check disk
df -h /

# If full, extend EBS volume (from your laptop)
aws ec2 modify-volume --volume-id vol-XXXX --size 50

# On EC2, extend filesystem
sudo growpart /dev/nvme0n1 1
sudo xfs_growfs /

# Restart Docker
sudo systemctl restart containerd && sleep 3 && sudo systemctl restart docker
```

### Instance Unresponsive After Crash

**Fix:** Stop/Start (NOT reboot):
```bash
aws ec2 stop-instances --instance-ids i-XXXX
aws ec2 wait instance-stopped --instance-ids i-XXXX
aws ec2 start-instances --instance-ids i-XXXX
```

---

## Maintenance

### Fresh Containers = Better Performance

After extended testing, restart Docker for optimal performance:
```bash
sudo systemctl restart docker
# Wait 30s for containers to stabilize
```

**Why:** Memory fragmentation, stale connection pools, and accumulated state degrade performance over time.

### Disk Cleanup

```bash
# Check disk
df -h /

# Prune unused Docker data
docker system prune -f

# Check log sizes
du -sh /var/lib/docker/containers/*/*-json.log
```

### Restart Locust (reload customer pool)

```bash
# On bastion
cd /home/ssm-user/RegionalBank_fraud_detection/backend/loadtest
./stop_locust_service.sh
./start_locust_service.sh 16
```

---

## Customer Pool Scaling

Current limit: **100K customers** (safe). Larger pools crash due to ALB timeout.

See LOAD-TEST-SESSION-2026-01-12.md for:
- Why 100K is actually sufficient for POC
- Future options: pagination, streaming, file-based loading

---

## Related Documentation

- [LOCUST-SETUP.md](./LOCUST-SETUP.md) - Detailed Locust configuration
- DEPLOYMENT-RUNBOOK.md - Quick reference commands
- [INFRASTRUCTURE.md](./INFRASTRUCTURE.md) - AWS deployment architecture
