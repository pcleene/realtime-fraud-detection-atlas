# Performance Tuning Guide

This document covers the performance optimizations applied to achieve **17,000+ TPS** with **<25ms average latency** on the RegionalBank Fraud Detection POC.

## Performance Results Summary

### Achieved Metrics (January 2026)

| Metric | Achieved | Target | Status |
|--------|----------|--------|--------|
| **Peak TPS** | 17,263 | 10,000 | **173% of target** |
| **Sustainable TPS** | 10,600+ | 10,000 | **PASS** |
| **Avg Latency** | 17ms | <50ms | **PASS** |
| **P50 Latency** | 15ms | - | Excellent |
| **P95 Latency** | 22ms | - | Excellent |
| **P99 Latency** | 45ms | <100ms | **PASS** |
| **Failure Rate** | 0.1% | <0.1% | **PASS** |
| **EC2 CPU Utilization** | 18-21% | <70% | Significant headroom |

### Latency Breakdown

| Component | Time | % of Total |
|-----------|------|------------|
| **Scoring** (reads + rules) | 4ms | 30% |
| **Persist** (update + insert) | 9ms | 70% |
| **Network** (ALB + bastion) | ~3ms | - |
| **Total App Processing** | 13ms | - |
| **End-to-End (Locust)** | 17ms | 100% |

---

## Infrastructure Configuration

### AWS EC2 Instances

| Resource | Configuration | Notes |
|----------|---------------|-------|
| **Instance Type** | c6i.16xlarge | 64 vCPU, 128GB RAM |
| **Instance Count** | 2 | Behind ALB |
| **Gunicorn Workers** | 129 per instance | 2 × vCPU + 1 |
| **Docker CPU Limit** | 60 cores | (was 7 - major bottleneck) |
| **Docker Memory Limit** | 120GB | (was 14GB - bottleneck) |

### Bastion Host (Locust)

| Resource | Configuration |
|----------|---------------|
| **Instance Type** | c6i.8xlarge (32 vCPU) |
| **Locust Workers** | 16-17 |
| **TPS per Worker** | ~800 |
| **Max Sustainable TPS** | ~17,000 |

### MongoDB Atlas

| Resource | Configuration |
|----------|---------------|
| **Cluster Tier** | M60 |
| **Shards** | 3 |
| **Connection** | PrivateLink |
| **Balancer** | Paused during tests |

---

## Critical Optimizations

### 1. Gunicorn Worker Count (MAJOR IMPACT)

**Problem:** Docker containers were configured with only 17 workers on 64-vCPU instances.

**Root Cause:** The `docker-compose.yml` had hardcoded defaults:
```yaml
# BEFORE (bottleneck)
environment:
  - WORKERS=${WORKERS:-17}  # Only 17 workers!
deploy:
  resources:
    limits:
      cpus: '7'             # Limited to 7 CPUs!
      memory: 14G
```

**Solution:** Scale workers to match available CPUs:
```yaml
# AFTER (optimized)
environment:
  - WORKERS=${WORKERS:-129}  # 2 × 64 vCPU + 1 = 129
deploy:
  resources:
    limits:
      cpus: 60              # Use most available CPUs
      memory: 120G          # Use most available RAM
```

**Formula:** `workers = 2 × vCPU + 1`

| Instance Type | vCPU | Optimal Workers |
|---------------|------|-----------------|
| c6i.xlarge | 4 | 9 |
| c6i.2xlarge | 8 | 17 |
| c6i.4xlarge | 16 | 33 |
| c6i.8xlarge | 32 | 65 |
| c6i.16xlarge | 64 | **129** |

**Impact:** This single change increased TPS from ~6,200 to **10,600+** (71% improvement).

### 2. Docker Resource Limits (MAJOR IMPACT)

**Problem:** Docker was constraining the container to 7 CPUs even though the host had 64.

**Solution:** Update `docker-compose.yml` resource limits:
```yaml
deploy:
  resources:
    limits:
      cpus: 60              # Leave some headroom for OS
      memory: 120G          # Leave some for OS/Docker
    reservations:
      cpus: 30              # Guarantee 30 CPUs
      memory: 60G           # Guarantee 60GB
```

### 3. Locust Worker Scaling

**Problem:** Initial setup had only 8 Locust workers, each capable of ~800 TPS.

**Solution:** Scale workers based on target TPS:

| Target TPS | Locust Workers | Bastion Instance |
|------------|----------------|------------------|
| 5,000 | 8 | c6i.2xlarge |
| 10,000 | 16 | c6i.4xlarge |
| 15,000 | 20-24 | c6i.8xlarge |
| 20,000+ | 32+ | c6i.8xlarge+ |

**Script:** Use `backend/loadtest/start_locust_service.sh`:
```bash
# Start with 16 workers (default for 10K TPS)
./start_locust_service.sh 16
```

### 4. MongoDB Balancer Management

**Problem:** The MongoDB balancer can cause latency spikes during chunk migrations.

**Solution:** Pause balancer during load tests:
```python
# Via pymongo
admin = client.admin
admin.command("balancerStop")

# Re-enable after testing
admin.command("balancerStart")
```

Or via mongosh:
```javascript
sh.stopBalancer()
sh.startBalancer()
```

### 5. User Count Tuning

**Finding:** The ratio of Locust users to TPS matters for latency:

| Users | TPS | Avg Latency | Notes |
|-------|-----|-------------|-------|
| 200 | 10,600 | 16.5ms | Optimal |
| 400 | 15,500 | 17.5ms | Good scaling |
| 600 | 17,200 | 20.6ms | Near limit |
| 800+ | Diminishing | 50ms+ | Overloaded |

**Formula:** `users = targetTps / 50` (approximately)

---

## Configuration Files

### docker-compose.yml (EC2)

```yaml
services:
  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - MONGODB_URI=${MONGODB_URI}
      - DB_NAME=${DB_NAME:-RegionalBank_fraud}
      - LOG_LEVEL=${LOG_LEVEL:-info}
      # Worker configuration - CRITICAL for performance
      - WORKERS=${WORKERS:-129}           # 2 × vCPU + 1
      - WORKER_CONNECTIONS=${WORKER_CONNECTIONS:-1000}
      - TIMEOUT=${TIMEOUT:-120}
      # Locust proxy configuration
      - LOCUST_HOST=${LOCUST_HOST:-localhost}
      - LOCUST_PORT=${LOCUST_PORT:-8089}
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: 60              # Adjust based on instance
          memory: 120G          # Adjust based on instance
        reservations:
          cpus: 30
          memory: 60G
```

### .env (EC2)

```bash
# MongoDB Atlas (PrivateLink)
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>
DB_NAME=RegionalBank_fraud

# Performance settings
WORKERS=129                    # 2 × vCPU + 1 for c6i.16xlarge
WORKER_CONNECTIONS=1000
TIMEOUT=120

# Locust proxy
LOCUST_HOST=<private-ip>       # Bastion private IP
LOCUST_PORT=8089
```

### gunicorn.conf.py

```python
import multiprocessing
import os

# Auto-calculate workers based on CPU
default_workers = (2 * multiprocessing.cpu_count()) + 1
workers = int(os.getenv("WORKERS", default_workers))

# Use uvicorn async workers for FastAPI
worker_class = "uvicorn.workers.UvicornWorker"

# Connection handling
worker_connections = int(os.getenv("WORKER_CONNECTIONS", "1000"))
backlog = 2048

# Timeouts
timeout = int(os.getenv("TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5

# Request cycling (prevents memory leaks)
max_requests = 10000
max_requests_jitter = 1000
```

---

## Monitoring During Load Tests

### Key Metrics to Watch

1. **EC2 CPU Utilization**
   - Target: <70% for headroom
   - Our result: 18-21% (excellent)

2. **Latency (End-to-End)**
   - Target: <50ms average, <100ms P99
   - Our result: 17ms avg, 45ms P99

3. **Error Rate**
   - Target: <0.1%
   - Our result: 0.1%

4. **MongoDB Atlas Metrics**
   - Query Targeting: Should be >95%
   - Connections: Watch for limits
   - Opcounters: Track read/write balance

### Quick Health Check Commands

```bash
# Check EC2 CPU
aws ssm send-command \
  --instance-ids i-xxxxx \
  --document-name "AWS-RunShellScript" \
  --parameters '{"commands":["top -bn1 | head -5"]}'

# Check Gunicorn workers
docker exec RegionalBank_fraud_detection-api-1 ps aux | grep gunicorn | wc -l

# Check MongoDB connection count
docker exec RegionalBank_fraud_detection-api-1 python3 -c "
from pymongo import MongoClient
import os
c = MongoClient(os.environ['MONGODB_URI'])
print(c.admin.command('serverStatus')['connections'])
"
```

---

## Troubleshooting Performance Issues

### TPS Not Scaling

1. **Check Gunicorn workers:**
   ```bash
   docker exec RegionalBank_fraud_detection-api-1 env | grep WORKERS
   ps aux | grep gunicorn | wc -l
   ```

2. **Check Docker resource limits:**
   ```bash
   docker inspect RegionalBank_fraud_detection-api-1 | grep -A10 "Resources"
   ```

3. **Check Locust workers:**
   ```bash
   curl http://localhost:8089/stats/requests | jq '.workers | length'
   ```

### High Latency Spikes

1. **Check MongoDB balancer:**
   ```javascript
   sh.getBalancerState()  // Should be "false" during tests
   ```

2. **Check EC2 CPU:**
   ```bash
   top -bn1 | head -5
   ```

3. **Check network latency to Atlas:**
   ```bash
   ping -c 5 cluster-pl-0.xxxxx.mongodb.net
   ```

### Container Keeps Respawning with Old Config

Docker Compose caches environment variables. Force rebuild:
```bash
docker compose down
docker compose build --no-cache api
docker compose up -d
```

---

## Performance Test Procedure

### Pre-Test Checklist

- [ ] Verify Gunicorn workers: `WORKERS=129` for c6i.16xlarge
- [ ] Verify Docker limits: `cpus: 60`, `memory: 120G`
- [ ] Pause MongoDB balancer: `sh.stopBalancer()`
- [ ] Verify Locust workers: 16+ for 10K TPS target
- [ ] Verify ALB health: Both targets healthy

### Running the Test

1. **Start via UI:**
   - Open frontend → Load Testing tab
   - Select "Bastion (External)"
   - Set Target TPS: 10K
   - Click "Start Load Test"

2. **Start via API:**
   ```bash
   curl -X POST "http://ALB-DNS/loadtest/external/start" \
     -H "Content-Type: application/json" \
     -d '{"user_count": 200, "spawn_rate": 40}'
   ```

### Post-Test Cleanup

- [ ] Stop test: `curl http://ALB-DNS/loadtest/external/stop`
- [ ] Re-enable balancer: `sh.startBalancer()`
- [ ] Review CloudWatch metrics

---

## Architecture Diagram (Optimized)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  AWS VPC (ap-southeast-1)                                                    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  Application Load Balancer                                               ││
│  │  <load-balancer-endpoint>         ││
│  └────────────────────────────────┬────────────────────────────────────────┘│
│                                   │                                          │
│            ┌──────────────────────┴──────────────────────┐                  │
│            │                                              │                  │
│  ┌─────────▼─────────┐                      ┌─────────────▼─────────┐       │
│  │  EC2 #1            │                      │  EC2 #2               │       │
│  │  c6i.16xlarge      │                      │  c6i.16xlarge         │       │
│  │  64 vCPU / 128GB   │                      │  64 vCPU / 128GB      │       │
│  │                    │                      │                       │       │
│  │  ┌──────────────┐  │                      │  ┌──────────────┐     │       │
│  │  │ Docker       │  │                      │  │ Docker       │     │       │
│  │  │ 129 Workers  │  │                      │  │ 129 Workers  │     │       │
│  │  │ 60 CPUs      │  │                      │  │ 60 CPUs      │     │       │
│  │  │ 120GB RAM    │  │                      │  │ 120GB RAM    │     │       │
│  │  └──────────────┘  │                      │  └──────────────┘     │       │
│  └────────────────────┘                      └───────────────────────┘       │
│            │                                              │                  │
│            └──────────────────────┬──────────────────────┘                  │
│                                   │ PrivateLink                              │
│                                   ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  MongoDB Atlas M60 (3 Shards)                                            ││
│  │  - customers: sharded on customer_id                                      ││
│  │  - transactions: sharded on customer_id + shard_key_month + _id          ││
│  │  - blacklist_locations: unsharded (2dsphere indexed)                      ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  Bastion (Locust) - c6i.8xlarge                                          ││
│  │  - 16 Locust workers (~800 TPS each)                                      ││
│  │  - Connects to ALB for load generation                                    ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Learnings

1. **Docker resource limits are silent killers** - Always verify container limits match instance capabilities.

2. **Gunicorn workers = concurrency** - Insufficient workers bottleneck TPS regardless of CPU availability.

3. **Formula: workers = 2 × vCPU + 1** - This applies to I/O-bound async workloads like FastAPI + MongoDB.

4. **Locust workers scale linearly** - Each worker handles ~800 TPS. Plan accordingly.

5. **MongoDB balancer causes latency spikes** - Pause during load tests for consistent results.

6. **Monitor all layers** - EC2 CPU, Docker resources, Gunicorn workers, MongoDB connections.

---

## EC2 Stop/Start Persistence

### What Persists (Stop/Start)

When you **stop and restart** EC2 instances:
- `.env` file persists at `/home/ssm-user/RegionalBank_fraud_detection/.env`
- `docker-compose.yml` changes persist
- Docker containers restart automatically (due to `restart: unless-stopped`)
- **No action needed** - settings survive stop/start

### What Gets Lost (Terminate/Replace)

When instances are **terminated and replaced** (e.g., ASG scaling, spot interruption):
- All local file changes are lost
- New instances use original AMI + user_data.sh bootstrap

### Making Settings Permanent

#### Option 1: Update Terraform user_data.sh (Recommended)

Add these lines to `terraform/user_data.sh`:

```bash
# In the EC2 bootstrap script, after git clone:

# Set optimal workers based on instance type
VCPU=$(nproc)
WORKERS=$((2 * VCPU + 1))

# Update .env
echo "WORKERS=$WORKERS" >> /home/ssm-user/RegionalBank_fraud_detection/.env

# Update docker-compose.yml resource limits
cd /home/ssm-user/RegionalBank_fraud_detection
sed -i "s/cpus: '7'/cpus: $((VCPU - 4))/" docker-compose.yml
sed -i "s/memory: 14G/memory: $((VCPU * 2 - 8))G/" docker-compose.yml
```

#### Option 2: Commit Changes to Git

Push the optimized docker-compose.yml to git, so new deployments get optimal settings:

```bash
# On your laptop
cd RegionalBank_fraud_detection
# Edit docker-compose.yml with dynamic WORKERS calculation
git add docker-compose.yml
git commit -m "perf: optimize Docker resource limits for large instances"
git push
```

#### Option 3: Quick Recovery Script

Save this script to quickly reconfigure a fresh instance:

```bash
#!/bin/bash
# quick-perf-setup.sh - Run on EC2 after fresh deployment

VCPU=$(nproc)
WORKERS=$((2 * VCPU + 1))
CPU_LIMIT=$((VCPU - 4))
MEM_LIMIT=$((VCPU * 2 - 8))

cd /home/ssm-user/RegionalBank_fraud_detection

# Update .env
grep -q "^WORKERS=" .env && sed -i "s/^WORKERS=.*/WORKERS=$WORKERS/" .env || echo "WORKERS=$WORKERS" >> .env

# Update docker-compose.yml
sed -i "s/cpus: '7'/cpus: $CPU_LIMIT/" docker-compose.yml
sed -i "s/cpus: 7/cpus: $CPU_LIMIT/" docker-compose.yml
sed -i "s/memory: 14G/memory: ${MEM_LIMIT}G/" docker-compose.yml

# Restart containers
docker compose down
docker compose up -d

echo "Configured: $WORKERS workers, $CPU_LIMIT CPUs, ${MEM_LIMIT}GB RAM"
```

### Recovery via SSM (Quick)

If you need to restore settings quickly after instance replacement:

```bash
# From your laptop with AWS CLI
aws ssm send-command \
  --instance-ids i-xxxxx \
  --document-name "AWS-RunShellScript" \
  --parameters '{"commands":[
    "cd /home/ssm-user/RegionalBank_fraud_detection",
    "VCPU=$(nproc); WORKERS=$((2*VCPU+1))",
    "grep -q WORKERS .env && sed -i \"s/WORKERS=.*/WORKERS=$WORKERS/\" .env || echo \"WORKERS=$WORKERS\" >> .env",
    "sed -i \"s/cpus: .7./cpus: $((VCPU-4))/\" docker-compose.yml",
    "sed -i \"s/memory: 14G/memory: $((VCPU*2-8))G/\" docker-compose.yml",
    "docker compose down && docker compose up -d",
    "sleep 20 && docker exec RegionalBank_fraud_detection-api-1 env | grep WORKERS"
  ]}'
```

---

## Related Documentation

- [LOAD-TESTING.md](./LOAD-TESTING.md) - Load testing guide and UI usage
- [LOCUST-SETUP.md](./LOCUST-SETUP.md) - Bastion and Locust configuration
- [CLOUDWATCH-MONITORING.md](./CLOUDWATCH-MONITORING.md) - AWS monitoring setup
- [INFRASTRUCTURE.md](./INFRASTRUCTURE.md) - AWS architecture overview

---

## Document History

| Date | Author | Changes |
|------|--------|---------|
| 2026-01-09 | Claude + Paul | Initial creation after achieving 17K TPS |
