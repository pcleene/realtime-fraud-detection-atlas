# Locust Distributed Load Testing Setup

This document covers the complete setup for distributed load testing using Locust, including the bastion host configuration, FastAPI proxy integration, and Svelte UI integration.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    AWS VPC                                           │
│                              <private-ip>/16                                           │
│                                                                                      │
│  ┌─────────────────────┐                                                             │
│  │   Bastion Host      │                                                             │
│  │   <private-ip>      │                                                             │
│  │                     │                                                             │
│  │  ┌───────────────┐  │       ┌─────────────────────────────────────────────────┐  │
│  │  │ Locust Master │  │       │              Application Load Balancer           │  │
│  │  │   :8089       │◀─┼───────│     RegionalBank-fraud-alb-1390886417.ap-southeast-1  │  │
│  │  └───────┬───────┘  │       │                    .elb.amazonaws.com            │  │
│  │          │          │       └────────────────────────┬────────────────────────┘  │
│  │  ┌───────┴───────┐  │                                │                           │
│  │  │ 16× Workers   │──┼────────────────────────────────┤                           │
│  │  │ (scoring)     │  │                                │                           │
│  │  └───────────────┘  │                                │                           │
│  └─────────────────────┘                                │                           │
│                                                         │                           │
│  ┌────────────────────────┐    ┌────────────────────────┴────────────────────────┐  │
│  │   EC2 #1               │    │   EC2 #2                                         │  │
│  │   <instance-id>  │    │   <instance-id>                            │  │
│  │   <private-ip>         │    │   <private-ip>                                  │  │
│  │                        │    │                                                  │  │
│  │   FastAPI :8000        │    │   FastAPI :8000                                  │  │
│  │   └─ /loadtest/external│    │   └─ /loadtest/external                         │  │
│  │      (Locust proxy)    │    │      (Locust proxy)                             │  │
│  │   └─ /score-transaction│    │   └─ /score-transaction                         │  │
│  │      (fraud scoring)   │    │      (fraud scoring)                            │  │
│  └────────────────────────┘    └──────────────────────────────────────────────────┘  │
│                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                               ┌──────────────────────┐
                               │   MongoDB Atlas M60  │
                               │   3 Shards           │
                               │   (via PrivateLink)  │
                               └──────────────────────┘
```

## Data Flow

1. **User** opens Svelte UI and selects "Bastion (External)" mode
2. **Svelte UI** calls FastAPI endpoint: `POST /loadtest/external/start`
3. **FastAPI** proxies the request to Locust Master on bastion: `POST http://<private-ip>:8089/swarm`
4. **Locust Master** distributes work to 16 workers
5. **Locust Workers** make HTTP requests to ALB: `POST /score-transaction`
6. **ALB** distributes requests across EC2 instances
7. **FastAPI** scores transactions against MongoDB Atlas
8. **Svelte UI** polls `GET /loadtest/external/stats` for real-time metrics

## Environment Details

### Your Specific AWS Resources

| Resource | ID / Value |
|----------|------------|
| **VPC CIDR** | <private-ip>/16 |
| **ALB DNS** | <load-balancer-endpoint> |
| **Bastion Host** | <private-ip> (private), 203.0.113.10 (public), <instance-id> |
| **EC2 #1 (API)** | <instance-id> / <private-ip> (c6i.16xlarge) |
| **EC2 #2 (API)** | <instance-id> / <private-ip> (c6i.16xlarge) |
| **Bastion Security Group** | <sg-id> |
| **MongoDB Atlas** | M60 cluster with 3 shards |
| **Region** | ap-southeast-1 (Singapore) |
| **EBS Volumes** | 50GB (upgraded from 8GB) |

---

## Part 1: Bastion Host Setup

### 1.1 SSH to Bastion

```bash
# From your laptop
ssh -i ~/.ssh/RegionalBank-fraud-key.pem ec2-user@203.0.113.10
```

### 1.2 Clone Repository and Set Up Python Environment

```bash
# Clone the repository (or pull if already exists)
cd ~
git clone git@github.com:YOUR_ORG/RegionalBank_fraud_detection.git
# OR if already cloned:
cd ~/RegionalBank_fraud_detection && git pull

# Create Python virtual environment
cd ~/RegionalBank_fraud_detection/backend
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install locust
```

### 1.3 GitHub SSH Authentication

GitHub no longer supports password authentication. You must use SSH keys.

#### Generate SSH Key on Bastion

```bash
# Generate ED25519 key (recommended)
ssh-keygen -t ed25519 -C "bastion-RegionalBank-fraud"

# Or RSA if ED25519 not supported
ssh-keygen -t rsa -b 4096 -C "bastion-RegionalBank-fraud"

# View the public key
cat ~/.ssh/id_ed25519.pub
# Example output:
# ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG... bastion-Regional Bank-fraud
```

#### Add Key to GitHub

1. Go to [GitHub SSH Keys](https://github.com/settings/keys)
2. Click **"New SSH key"**
3. Title: `SSH RegionalBank bastion`
4. Key type: **Authentication Key** (NOT signing key)
5. Paste the public key from `cat ~/.ssh/id_ed25519.pub`
6. Click **"Add SSH key"**

#### Test GitHub Connection

```bash
ssh -T git@github.com
# Expected: "Hi username! You've successfully authenticated..."
```

#### Configure Git Remote (if needed)

```bash
cd ~/RegionalBank_fraud_detection

# Check current remote
git remote -v
# If it shows https://, change to SSH:
git remote set-url origin git@github.com:YOUR_ORG/RegionalBank_fraud_detection.git

# Verify
git remote -v
# Should show: git@github.com:YOUR_ORG/Regional Bank_fraud_detection.git
```

### 1.4 Start Locust Master + Workers

```bash
# Activate virtual environment
cd ~/RegionalBank_fraud_detection/backend
source .venv/bin/activate

# Start Locust in distributed mode with 16 workers (recommended for 10K TPS)
# Master binds to 0.0.0.0 so EC2s can reach it
locust -f loadtest/locustfile.py \
  --master \
  --expect-workers 16 \
  --host=http://<load-balancer-endpoint> &

# Start 16 workers (each in background)
for i in {1..16}; do
  locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 &
done

# Verify workers connected
curl -s http://localhost:8089/stats/requests | jq '.state, .workers | length'
# Expected: "ready" and 16
```

### 1.5 Run Locust as a Systemd Service (Recommended)

For production, create a systemd service so Locust survives reboots.

**Worker Scaling Guide:**
| Bastion Instance | vCPUs | Recommended Workers | Max TPS |
|------------------|-------|---------------------|---------|
| c6i.xlarge | 4 | 4 | ~3,200 |
| c6i.2xlarge | 8 | 8 | ~6,400 |
| c6i.4xlarge | 16 | 16 | ~12,800 |
| c6i.8xlarge | 32 | 24-32 | ~20,000+ |

**Rule of thumb:** Each Locust worker can generate ~800 TPS at 30ms latency.

```bash
# Create service file (using 16 workers for 10K TPS)
sudo tee /etc/systemd/system/locust-master.service << 'EOF'
[Unit]
Description=Locust Master
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/RegionalBank_fraud_detection/backend
Environment="PATH=/home/ec2-user/RegionalBank_fraud_detection/backend/.venv/bin:/usr/local/bin:/usr/bin"
ExecStart=/home/ec2-user/RegionalBank_fraud_detection/backend/.venv/bin/locust \
  -f loadtest/locustfile.py \
  --master \
  --expect-workers 16 \
  --host=http://<load-balancer-endpoint>
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Create worker service (spawns 16 workers for 10K TPS)
# Adjust the loop range based on your bastion instance size
sudo tee /etc/systemd/system/locust-workers.service << 'EOF'
[Unit]
Description=Locust Workers
After=locust-master.service
Requires=locust-master.service

[Service]
Type=forking
User=ec2-user
WorkingDirectory=/home/ec2-user/RegionalBank_fraud_detection/backend
Environment="PATH=/home/ec2-user/RegionalBank_fraud_detection/backend/.venv/bin:/usr/local/bin:/usr/bin"
ExecStart=/bin/bash -c 'for i in {1..16}; do /home/ec2-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 & done'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Enable and start services
sudo systemctl daemon-reload
sudo systemctl enable locust-master locust-workers
sudo systemctl start locust-master
sleep 3
sudo systemctl start locust-workers

# Check status
sudo systemctl status locust-master
sudo systemctl status locust-workers
```

---

## Part 2: Security Group Configuration

EC2 instances need to reach the Locust master on port 8089.

### 2.1 Add Inbound Rule to Bastion Security Group

```bash
# Allow TCP 8089 from VPC CIDR
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp \
  --port 8089 \
  --cidr <private-ip>/16 \
  --region ap-southeast-1

# Verify the rule was added
aws ec2 describe-security-groups \
  --group-ids <sg-id> \
  --query 'SecurityGroups[0].IpPermissions' \
  --region ap-southeast-1
```

### 2.2 Security Group Rules Summary

| Security Group | Port | Source | Purpose |
|----------------|------|--------|---------|
| Bastion (<sg-id>) | 22 | Your IP | SSH access |
| Bastion (<sg-id>) | 8089 | <private-ip>/16 | Locust API from VPC |
| ALB | 80 | 0.0.0.0/0 | Public HTTP access |
| EC2 API | 8000 | ALB SG | API traffic from ALB |

---

## Part 3: EC2 API Configuration

### 3.1 GitHub SSH Authentication on EC2s

Each EC2 instance needs SSH access to GitHub to pull code.

```bash
# SSH to EC2 via bastion
ssh -i ~/.ssh/RegionalBank-fraud-key.pem ec2-user@203.0.113.10
ssh <private-ip>  # EC2 #1

# Generate SSH key
ssh-keygen -t ed25519 -C "ec2-RegionalBank-fraud"
cat ~/.ssh/id_ed25519.pub
# Add this key to GitHub (same process as bastion)

# Test connection
ssh -T git@github.com

# Repeat for EC2 #2 (<private-ip>)
```

### 3.2 Configure Locust Proxy Settings

The FastAPI application needs to know where Locust is running.

#### Update docker-compose.yml

The following environment variables must be set in `docker-compose.yml`:

```yaml
services:
  api:
    environment:
      # ... other variables ...
      # Locust proxy configuration
      - LOCUST_HOST=${LOCUST_HOST:-localhost}
      - LOCUST_PORT=${LOCUST_PORT:-8089}
```

#### Create .env File on EC2s

```bash
# SSH to each EC2 and create .env file
ssh <private-ip>  # EC2 #1
cd ~/RegionalBank_fraud_detection

# Create .env file with Locust bastion address
cat > .env << 'EOF'
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>
DB_NAME=RegionalBank_fraud
LOG_LEVEL=info
LOCUST_HOST=<private-ip>
LOCUST_PORT=8089
EOF

# Repeat for EC2 #2
ssh <private-ip>
# Same .env creation
```

### 3.3 Deploy Updated Code to EC2s

```bash
# SSH to each EC2 and pull + rebuild
ssh <private-ip>
cd ~/RegionalBank_fraud_detection
git pull
docker-compose build api
docker-compose up -d api

# Verify container is running
docker-compose ps
docker-compose logs --tail 50 api

# Repeat for EC2 #2
```

---

## Part 4: FastAPI Locust Proxy

The proxy is implemented in `backend/app/routes/locust_proxy.py`.

### 4.1 Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/loadtest/external/status` | GET | Check if Locust is available |
| `/loadtest/external/start` | POST | Start a load test (swarm) |
| `/loadtest/external/stop` | GET | Stop the current test |
| `/loadtest/external/reset` | GET | Reset statistics |
| `/loadtest/external/stats` | GET | Get aggregated statistics |
| `/loadtest/external/stats/endpoints` | GET | Get per-endpoint breakdown |
| `/loadtest/external/config` | GET | View Locust configuration |

### 4.2 Configuration

Settings are loaded from environment variables via `app/config.py`:

```python
class Settings(BaseSettings):
    # ... other settings ...

    # Locust load testing proxy
    locust_host: str = "localhost"
    locust_port: int = 8089
```

### 4.3 Proxy Implementation Details

The proxy uses `httpx.AsyncClient` to forward requests to Locust:

```python
LOCUST_BASE_URL = f"http://{LOCUST_HOST}:{LOCUST_PORT}"

async def locust_request(method: str, endpoint: str, **kwargs):
    url = f"{LOCUST_BASE_URL}{endpoint}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.request(method, url, **kwargs)
        return response.json()
```

### 4.4 Error Handling

The proxy handles Locust unavailability gracefully:

| Error | HTTP Status | Response |
|-------|-------------|----------|
| Connection refused | 503 | `{"error": "locust_unavailable", "message": "Cannot connect..."}` |
| Timeout | 504 | `{"error": "locust_timeout", "message": "Timeout..."}` |
| Locust error | varies | `{"error": "locust_error", "message": "..."}` |

---

## Part 5: Locust Test Script

The load test script is at `backend/loadtest/locustfile.py`.

### 5.1 User Classes

| Class | Wait Time | Tasks | Use Case |
|-------|-----------|-------|----------|
| `FraudAPIUser` | 1-10ms | 95% scoring, 5% health | Realistic production mix |
| `HighThroughputUser` | 0ms | 100% scoring | Maximum throughput testing |

### 5.2 Task Breakdown

```python
@task(20)  # Weight: 20 (95% of requests)
def score_transaction(self):
    """Score a transaction for fraud."""
    payload = generate_transaction_payload()
    self.client.post("/score-transaction", json=payload)

@task(1)   # Weight: 1 (5% of requests)
def health_check(self):
    """Occasional health check."""
    self.client.get("/health")
```

### 5.3 Customer Pool Loading

On startup, workers fetch real customer IDs from the database:

```python
def on_start(self):
    response = self.client.get("/mock/customers?limit=100000")  # 100K customers
    if response.status_code == 200:
        CUSTOMER_POOL.extend([c["customer_id"] for c in response.json()["customers"]])
```

**Important:** The customer pool is loaded ONCE at Locust startup and cached in memory. After crashes or restarts, you must restart Locust to reload the pool.

**Pool Size Limits:**

| Size | Status | Notes |
|------|--------|-------|
| 100K | ✅ Safe | Recommended for production |
| 200K | ⚠️ Risky | Near ALB timeout |
| 1M | ❌ CRASH | Exceeds 60s timeout, crashes instances |

See LOAD-TEST-SESSION-2026-01-12.md for scaling options.

### 5.4 Transaction Payload Generation

```python
def generate_transaction_payload(customer_id: str = None):
    return {
        "customer_id": customer_id or random.choice(CUSTOMER_POOL),
        "account_id": f"ACC-{random.randint(10000000, 99999999)}",
        "amount": random.randint(10000, 10000000),
        "lat": -6.2 + random.uniform(-0.5, 0.5),  # Jakarta area
        "lon": 106.8 + random.uniform(-0.5, 0.5),
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "channel": random.choice(["Livin", "KOPRA", "ATM", "QRIS", "Branch", "Ecom"]),
        # ... additional fields ...
    }
```

---

## Part 6: Running Load Tests

### 6.1 Via Svelte UI

1. Open the frontend: `http://<load-balancer-endpoint>:3000`
2. Go to **Load Testing** tab
3. Select **"Bastion (External)"** mode
4. Configure: 500 users, 50 spawn rate
5. Click **Start**
6. Watch real-time metrics

### 6.2 Via curl

```bash
# Check Locust status
curl http://<load-balancer-endpoint>/loadtest/external/status | jq .

# Start a test
curl -X POST http://<load-balancer-endpoint>/loadtest/external/start \
  -H "Content-Type: application/json" \
  -d '{"user_count": 500, "spawn_rate": 50}' | jq .

# Get stats
curl http://<load-balancer-endpoint>/loadtest/external/stats | jq .

# Get per-endpoint stats
curl http://<load-balancer-endpoint>/loadtest/external/stats/endpoints | jq .

# Stop the test
curl http://<load-balancer-endpoint>/loadtest/external/stop | jq .

# Reset stats
curl http://<load-balancer-endpoint>/loadtest/external/reset | jq .
```

### 6.3 Directly on Bastion (Locust Web UI)

If you have SSH access to bastion with port forwarding:

```bash
# Forward Locust UI to your laptop
ssh -L 8089:localhost:8089 -i ~/.ssh/RegionalBank-fraud-key.pem ec2-user@203.0.113.10

# Open in browser
open http://localhost:8089
```

---

## Part 7: Performance Results

### 7.1 Test Configuration (Optimized - January 2026)

| Parameter | Value |
|-----------|-------|
| Users | 200-600 |
| Spawn Rate | 40-50/sec |
| Locust Workers | 16-17 |
| EC2 Instances | 2× c6i.16xlarge (64 vCPU each) |
| Gunicorn Workers | 129 per instance (258 total) |
| MongoDB | Atlas M60, 3 shards (PrivateLink) |

### 7.2 Results Achieved

| Metric | Achieved | Target | Status |
|--------|----------|--------|--------|
| **Peak TPS** | **17,263** | 10,000 | **173% of target** |
| **Sustainable TPS** | **10,673** | 10,000 | **PASS** |
| **Avg Latency** | **17ms** | <50ms | **PASS** |
| **P50 Latency** | **15ms** | - | Excellent |
| **P95 Latency** | **22ms** | - | Excellent |
| **P99 Latency** | **45ms** | <100ms | **PASS** |
| **Total Requests** | 3,221,987 | - | - |
| **Failure Rate** | **0.1%** | <0.1% | **PASS** |
| **EC2 CPU** | **18-21%** | <70% | Significant headroom |

### 7.3 Scaling Results

| Users | TPS | Avg Latency | P95 | Notes |
|-------|-----|-------------|-----|-------|
| 200 | 10,617 | 16.5ms | 21ms | Optimal efficiency |
| 400 | 15,585 | 17.5ms | 40ms | Good scaling |
| 600 | 17,263 | 20.6ms | 68ms | Near peak |

### 7.4 Latency Breakdown

| Component | Time | % of Total |
|-----------|------|------------|
| **Scoring** (MongoDB reads + rules) | 4ms | 30% |
| **Persist** (customer update + txn insert) | 9ms | 70% |
| **Network** (bastion ↔ ALB) | ~3ms | - |
| **Total App Processing** | 13ms | - |
| **End-to-End (Locust)** | 17ms | 100% |

---

## Troubleshooting

### Issue: "Cannot connect to Locust"

```bash
# 1. Check if Locust is running on bastion
ssh ec2-user@203.0.113.10
curl http://localhost:8089/stats/requests

# 2. Check security group allows 8089 from VPC
aws ec2 describe-security-groups --group-ids <sg-id>

# 3. Check EC2 can reach bastion
ssh <private-ip>
curl http://<private-ip>:8089/stats/requests
```

### Issue: Workers not connecting

```bash
# Check master is listening on 0.0.0.0
netstat -tlnp | grep 5557  # Locust master port

# Check worker logs
journalctl -u locust-workers -f
```

### Issue: Pydantic validation error for 'locust_host'

The Settings class must include Locust configuration:

```python
# app/config.py
class Settings(BaseSettings):
    locust_host: str = "localhost"
    locust_port: int = 8089
```

### Issue: 404 on /mock/customers

Ensure the endpoint exists in `backend/app/routes/mock.py`:

```python
@router.get("/customers")
async def get_customers(limit: int = Query(1000), db=Depends(get_db)):
    cursor = db.customers.find({}, {"customer_id": 1, "_id": 0}).limit(limit)
    customers = await cursor.to_list(length=limit)
    return {"customers": customers, "count": len(customers)}
```

### Issue: Git authentication failed

```bash
# Check SSH key is loaded
ssh-add -l

# Test GitHub connection
ssh -T git@github.com

# Ensure remote uses SSH URL
git remote set-url origin git@github.com:YOUR_ORG/repo.git
```

---

## File Reference

| File | Purpose |
|------|---------|
| `backend/loadtest/locustfile.py` | Locust user classes and task definitions |
| `backend/app/routes/locust_proxy.py` | FastAPI proxy to Locust API |
| `backend/app/routes/mock.py` | Mock data endpoints (incl. /customers) |
| `backend/app/config.py` | Settings including locust_host, locust_port |
| `docker-compose.yml` | LOCUST_HOST/LOCUST_PORT env vars |
| `.env` | Environment-specific configuration |

---

## Next Steps

1. **Monitor Atlas metrics** during load tests (Performance Advisor)
2. **Use CloudWatch dashboard** - See [CLOUDWATCH-MONITORING.md](./CLOUDWATCH-MONITORING.md)
3. **Scale EC2 instances** if CPU > 70% (auto-scaling configured)
4. **Increase Locust workers** for higher TPS:
   - 8 workers = ~6.4k TPS
   - 16 workers = ~12.8k TPS (recommended for 10K target)
   - 24 workers = ~19k TPS
5. **For 10K+ TPS**, use `start_locust_10k.sh` script

---

## Related Documentation

- [EC2-DOCKER-SETUP.md](./EC2-DOCKER-SETUP.md) - EC2 and Docker configuration
- [ALB-SETUP.md](./ALB-SETUP.md) - Application Load Balancer setup
- [PRIVATELINK-SETUP.md](./PRIVATELINK-SETUP.md) - MongoDB Atlas PrivateLink
- DEPLOYMENT-RUNBOOK.md - Quick reference commands
- [LOAD-TESTING.md](./LOAD-TESTING.md) - Complete load testing guide

---

## Document History

| Date | Author | Changes |
|------|--------|---------|
| 2026-01-07 | Claude + Paul | Initial creation with Locust distributed setup |
| 2026-01-12 | Claude + Paul | Updated AWS resources, added customer pool limits, disk size upgrade |
