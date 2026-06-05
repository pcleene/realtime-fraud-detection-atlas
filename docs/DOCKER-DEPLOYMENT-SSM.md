# Docker Deployment via AWS SSM

This document describes how to deploy the RegionalBank Fraud Detection backend API to EC2 instances using AWS Systems Manager (SSM) and Docker Compose.

## Prerequisites

1. **AWS CLI** configured with appropriate credentials
2. **SSM Agent** installed and running on target EC2 instances
3. **IAM Role** on EC2 instances with `AmazonSSMManagedInstanceCore` policy
4. **Docker and Docker Compose V2** installed on EC2 instances
5. **Git** installed on EC2 instances
6. **GitHub Personal Access Token (PAT)** for repository authentication

## Environment Summary

| Component | Resource ID / Value |
|-----------|---------------------|
| **Region** | ap-southeast-1 (Singapore) |
| **Bastion Instance** | <instance-id> |
| **Bastion EIP** | 203.0.113.10 |
| **Bastion Private IP** | <private-ip> |
| **EC2 #1 Instance** | <instance-id> |
| **EC2 #1 Private IP** | <private-ip> |
| **EC2 #2 Instance** | <instance-id> |
| **EC2 #2 Private IP** | <private-ip> |
| **ALB DNS** | <load-balancer-endpoint> |

---

## Step-by-Step Deployment

### Step 1: Prepare GitHub Authentication

Generate a Personal Access Token (PAT) from GitHub:
1. Go to: https://github.com/settings/tokens
2. Click "Generate new token (classic)"
3. Select scopes: `repo` (full control of private repositories)
4. Copy the generated token

### Step 2: Deploy to EC2 Instances

Run the following AWS SSM command to deploy to both EC2 instances:

```bash
aws ssm send-command \
  --instance-ids "<instance-id>" "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "export HOME=/root",
    "git config --global --add safe.directory /home/ssm-user/RegionalBank_fraud_detection",
    "cd /home/ssm-user/RegionalBank_fraud_detection",
    "git remote set-url origin https://YOUR_PAT@github.com/pcleene/RegionalBank_fraud_detection.git",
    "git pull",
    "docker compose build api",
    "docker compose up -d api",
    "docker compose ps"
  ]' \
  --region ap-southeast-1 \
  --output json
```

Replace `YOUR_PAT` with your GitHub Personal Access Token.

### Step 3: Check Command Status

```bash
aws ssm get-command-invocation \
  --command-id "<command-id-from-step-2>" \
  --instance-id "<instance-id>" \
  --region ap-southeast-1
```

### Step 4: Verify Deployment

Check the API health via ALB:

```bash
curl -s http://<load-balancer-endpoint>/health | jq .
```

Expected response:
```json
{
  "status": "healthy",
  "database": "connected",
  "sharding": {"enabled": true, "shards": 3}
}
```

---

## Important Notes

### Why SSM Instead of SSH?

- **No SSH Keys Required**: SSM uses IAM for authentication
- **Audit Trail**: All commands are logged in CloudTrail
- **No Bastion Needed**: Direct access to private instances
- **Secure**: No open ports required (uses HTTPS outbound)

### Common Issues and Fixes

#### 1. "Directory not found" Error

SSM runs as root, so `~` expands to `/root`. Always use absolute paths:
```bash
# Wrong
cd ~/RegionalBank_fraud_detection

# Correct
cd /home/ssm-user/RegionalBank_fraud_detection
```

#### 2. "Dubious ownership" Git Error

Root user accessing another user's repository:
```bash
git config --global --add safe.directory /home/ssm-user/RegionalBank_fraud_detection
```

#### 3. "$HOME not set" Error

SSM doesn't set HOME by default:
```bash
export HOME=/root
```

#### 4. "docker-compose: command not found"

Docker Compose V2 uses space instead of hyphen:
```bash
# Wrong (V1 syntax)
docker-compose up -d

# Correct (V2 syntax)
docker compose up -d
```

#### 5. GitHub SSH Authentication Failed

Root doesn't have SSH keys configured. Use HTTPS with PAT:
```bash
git remote set-url origin https://YOUR_PAT@github.com/pcleene/RegionalBank_fraud_detection.git
```

---

## Locust Setup on Bastion

### Step 1: Create Virtual Environment and Install Locust

```bash
aws ssm send-command \
  --instance-ids "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend",
    "python3 -m venv .venv",
    "chown -R ssm-user:ssm-user .venv",
    ". .venv/bin/activate && pip install --upgrade pip && pip install locust"
  ]' \
  --region ap-southeast-1
```

### Step 2: Start Locust Master

```bash
aws ssm send-command \
  --instance-ids "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "pkill -f locust || true",
    "sleep 2",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --master --expect-workers 16 --host=http://<load-balancer-endpoint> > /tmp/locust-master.log 2>&1 &"
  ]' \
  --region ap-southeast-1
```

### Step 3: Start 16 Locust Workers (recommended for 10K TPS)

```bash
# Run this command twice - SSM has a 10-command limit per invocation
# First batch: workers 1-10
aws ssm send-command \
  --instance-ids "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-1.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-2.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-3.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-4.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-5.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-6.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-7.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-8.log 2>&1 &"
  ]' \
  --region ap-southeast-1

# Second batch: workers 9-16
aws ssm send-command \
  --instance-ids "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-9.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-10.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-11.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-12.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-13.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-14.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-15.log 2>&1 &",
    "cd /home/ssm-user/RegionalBank_fraud_detection/backend && nohup /home/ssm-user/RegionalBank_fraud_detection/backend/.venv/bin/locust -f loadtest/locustfile.py --worker --master-host=127.0.0.1 > /tmp/locust-worker-16.log 2>&1 &"
  ]' \
  --region ap-southeast-1
```

### Step 4: Verify Locust

```bash
aws ssm send-command \
  --instance-ids "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["curl -s http://localhost:8089/stats/requests | jq .state,.worker_count"]' \
  --region ap-southeast-1
```

Expected output:
```
"ready"
16
```

---

## Quick Reference Commands

### Deploy to Both EC2s
```bash
aws ssm send-command \
  --instance-ids "<instance-id>" "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["export HOME=/root && git config --global --add safe.directory /home/ssm-user/RegionalBank_fraud_detection && cd /home/ssm-user/RegionalBank_fraud_detection && git remote set-url origin https://YOUR_PAT@github.com/pcleene/RegionalBank_fraud_detection.git && git pull && docker compose build api && docker compose up -d api"]' \
  --region ap-southeast-1
```

### Check Container Status
```bash
aws ssm send-command \
  --instance-ids "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd /home/ssm-user/RegionalBank_fraud_detection && docker compose ps"]' \
  --region ap-southeast-1
```

### View Container Logs
```bash
aws ssm send-command \
  --instance-ids "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd /home/ssm-user/RegionalBank_fraud_detection && docker compose logs --tail 50 api"]' \
  --region ap-southeast-1
```

### Restart API Container
```bash
aws ssm send-command \
  --instance-ids "<instance-id>" "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd /home/ssm-user/RegionalBank_fraud_detection && docker compose restart api"]' \
  --region ap-southeast-1
```

### Configure Docker Log Rotation

Apply log rotation to prevent disk exhaustion from API container logs during load tests:

```bash
# Apply to both EC2 instances (rolling - one at a time for zero downtime)
aws ssm send-command \
  --instance-ids "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters '{"commands":["printf \"{\\n  \\\"log-driver\\\": \\\"json-file\\\",\\n  \\\"log-opts\\\": {\\n    \\\"max-size\\\": \\\"100m\\\",\\n    \\\"max-file\\\": \\\"3\\\"\\n  }\\n}\\n\" > /etc/docker/daemon.json","systemctl restart docker","sleep 15","docker ps","curl -sf http://localhost:8000/health || echo HEALTH CHECK FAILED"]}' \
  --region ap-southeast-1

# Wait for API-1 to be healthy in ALB, then repeat for API-2
aws ssm send-command \
  --instance-ids "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters '{"commands":["printf \"{\\n  \\\"log-driver\\\": \\\"json-file\\\",\\n  \\\"log-opts\\\": {\\n    \\\"max-size\\\": \\\"100m\\\",\\n    \\\"max-file\\\": \\\"3\\\"\\n  }\\n}\\n\" > /etc/docker/daemon.json","systemctl restart docker","sleep 15","docker ps","curl -sf http://localhost:8000/health || echo HEALTH CHECK FAILED"]}' \
  --region ap-southeast-1
```

**Note:** Docker daemon restart briefly stops containers. The `restart: unless-stopped` policy brings them back automatically. Apply one instance at a time so the ALB always has a healthy target.

### Check Docker Log Sizes
```bash
aws ssm send-command \
  --instance-ids "<instance-id>" "<instance-id>" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["echo $(hostname) && find /var/lib/docker/containers/ -name *-json.log -exec ls -lh {} \;"]' \
  --region ap-southeast-1
```

---

## Health Check Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/health` | API and MongoDB connectivity |
| `/api/health` | Detailed database health |
| `/loadtest/external/status` | Locust status via proxy |

---

## Bastion Mode Architecture

The load testing UI supports two modes: **Local** and **Bastion (External)**.

### How Bastion Mode Works

When running from a local browser, the frontend routes bastion mode requests through the ALB:

```
Local Browser
     │
     │ (1) GET /loadtest/external/status?target=bastion
     ▼
   ALB (<load-balancer-endpoint>)
     │
     │ (2) Routes to EC2 backend
     ▼
   EC2 Backend (:8000)
     │
     │ (3) HTTP to bastion private IP
     ▼
   Bastion (<private-ip>:8089)
     │
     ▼
   Locust Master + 16 Workers
```

### Key Configuration

| Component | Setting | Value |
|-----------|---------|-------|
| **Frontend** | `ALB_URL` | `http://<load-balancer-endpoint>` |
| **EC2 .env** | `LOCUST_BASTION_HOST` | `<private-ip>` (bastion private IP) |
| **EC2 .env** | `LOCUST_PORT` | `8089` |

### Why This Design?

1. **Bastion has no public port 8089**: Security group only allows VPC traffic on 8089
2. **VPC internal routing**: EC2 backends reach bastion via private IP
3. **ALB as entry point**: Browser calls ALB which routes to EC2

### Testing Bastion Mode

```bash
# From local machine - via ALB proxy
curl -s "http://<load-balancer-endpoint>/loadtest/external/status?target=bastion" | jq .

# Expected response:
{
  "available": true,
  "state": "stopped",
  "user_count": 0,
  "workers": 16,
  "message": "Locust is running at http://<private-ip>:8089"
}
```

---

## Document History

| Date | Author | Changes |
|------|--------|---------|
| 2026-01-09 | Claude | Added bastion mode architecture documentation |
| 2026-01-09 | Claude | Initial SSM deployment documentation |
| 2026-02-10 | Claude + Paul | Added Docker log rotation via SSM commands |
