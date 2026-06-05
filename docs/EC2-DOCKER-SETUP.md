# EC2 and Docker Setup Guide

This document covers deploying the RegionalBank Fraud Detection API to AWS EC2 with Docker, including Docker fundamentals explained along the way.

## Executive Summary

We built production-grade infrastructure including private networking, MongoDB Atlas PrivateLink, and containerized services—all designed for a high-throughput load test demonstrating MongoDB's capabilities for real-time fraud scoring.

**Final Result:** Successfully deployed Docker containers on EC2 instances connected to a sharded MongoDB Atlas M30 cluster (3 shards) via PrivateLink, achieving 9,867 RPS with 43ms average latency.

---

## Part 1: Architecture Overview

### What We Built

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS VPC (ap-southeast-1)                        │
│                              CIDR: <private-ip>/16                             │
│                                                                              │
│  ┌─────────────────┐     ┌─────────────────────────────────────────────┐   │
│  │   Your Laptop   │     │            Private Subnets                   │   │
│  │  (Load Test     │     │  ┌─────────────┐    ┌─────────────┐         │   │
│  │   via Bastion)  │     │  │   EC2 #1    │    │   EC2 #2    │         │   │
│  └────────┬────────┘     │  │  (Docker)   │    │  (Docker)   │         │   │
│           │              │  │  - API x16  │    │  - API x16  │         │   │
│           │              │  │  workers    │    │  workers    │         │   │
│           ▼              │  └──────┬──────┘    └──────┬──────┘         │   │
│  ┌─────────────────┐     │         │                  │                │   │
│  │ Application     │     │         └────────┬─────────┘                │   │
│  │ Load Balancer   │◄────┼──────────────────┤                          │   │
│  │ (Public)        │     │                  │                          │   │
│  └─────────────────┘     │                  ▼                          │   │
│                          │         ┌─────────────────┐                 │   │
│                          │         │  VPC Endpoint   │                 │   │
│                          │         │  (PrivateLink)  │                 │   │
│                          │         └────────┬────────┘                 │   │
│                          └──────────────────┼──────────────────────────┘   │
│                                             │                              │
└─────────────────────────────────────────────┼──────────────────────────────┘
                                              │
                                              ▼
                                    ┌─────────────────┐
                                    │  MongoDB Atlas  │
                                    │   M60 Cluster   │
                                    │   (3 shards)    │
                                    └─────────────────┘
```

### Why This Architecture?

| Component | Purpose |
|-----------|---------|
| **Private Subnets** | EC2 instances have no public IP. Can't be accessed from internet. |
| **NAT Gateway** | Allows private instances to reach internet (pull Docker images) without being reachable FROM internet. |
| **PrivateLink** | Traffic to MongoDB stays on AWS private backbone. Lower latency, better security. |
| **Application Load Balancer** | Distributes requests across EC2 instances. Only public-facing component. |

---

## Part 2: Docker Fundamentals

### What Problem Does Docker Solve?

Docker packages your application along with everything it needs to run: OS libraries, runtime, dependencies, and configuration. This package is called a **container**.

### Key Concepts

#### Images vs Containers

| Concept | Analogy | Description |
|---------|---------|-------------|
| **Image** | Recipe / Class | Read-only template with code, libraries, config |
| **Container** | Cake / Instance | Live, running instance of an image |

#### Dockerfile: The Recipe

```dockerfile
# Start from Python 3.11 on slim Debian
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Container listens on port 8000
EXPOSE 8000

# Command to run on container start
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
```

**Layer Caching:** Each instruction creates a layer. Unchanged layers are cached and reused, speeding up builds.

#### Docker Compose: Orchestrating Multiple Containers

```yaml
# docker-compose.yml
services:
  api:
    build: ./backend
    ports:
      - "8000:8000"
    volumes:
      - ./certs:/app/certs:ro    # Mount certs read-only
    env_file:
      - .env
    dns:
      - <private-ip>               # VPC DNS for Route 53 Private Zone
    deploy:
      resources:
        limits:
          cpus: '7'
          memory: 14G

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - api
```

### Essential Docker Commands

```bash
# Build and start in background
docker compose up -d --build

# View running containers
docker compose ps

# View logs
docker compose logs api --tail 50

# Shell into container
docker compose exec api bash

# Stop and remove
docker compose down

# Rebuild specific service
docker compose up -d --build api
```

### Volumes and Environment Variables

**Volumes** mount host folders into containers:
```yaml
volumes:
  - ./certs:/app/certs:ro   # Host → Container (read-only)
```

**Environment Variables** passed via `.env` file:
```bash
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>
DB_NAME=RegionalBank_fraud
LOG_LEVEL=INFO
WORKERS=16
```

### Log Rotation

Docker container logs grow unbounded by default. During load tests, API logs can grow by hundreds of MB in minutes. To prevent disk exhaustion, configure Docker daemon-level log rotation in `/etc/docker/daemon.json`:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  }
}
```

This caps each container's logs at **300MB total** (3 x 100MB files). When a log file reaches 100MB, Docker automatically rotates it.

**Applying the config:**
```bash
# Write config (requires root / SSM)
printf '{\n  "log-driver": "json-file",\n  "log-opts": {\n    "max-size": "100m",\n    "max-file": "3"\n  }\n}\n' > /etc/docker/daemon.json

# Restart Docker daemon (containers restart automatically via restart policy)
systemctl restart docker
```

**Note:** Changing `daemon.json` requires a Docker daemon restart, which briefly stops all containers. With 2 instances behind the ALB, apply this as a rolling update (one instance at a time) for zero downtime. The config applies to newly created containers; existing containers pick it up after being recreated (`docker compose down && docker compose up -d`).

### Networking in Docker Compose

- Services communicate using service names: `http://api:8000`
- Port mapping `8000:8000` exposes container port to host
- Add `dns: - <private-ip>` to use VPC DNS (required for Route 53 Private Zones)

---

## Part 3: AWS Infrastructure Setup

### VPC and Networking Concepts

#### What is a VPC?

A Virtual Private Cloud (VPC) is your isolated network within AWS. You control:
- IP address ranges (CIDR blocks)
- Subnets (network subdivisions)
- Route tables (traffic rules)
- Security groups (firewalls)

#### CIDR Notation

| CIDR | # of IPs | Use Case |
|------|----------|----------|
| /16 | 65,536 | VPC level |
| /20 | 4,096 | Large subnets |
| /24 | 256 | Standard subnets |

Our VPC `<private-ip>/16` gives us 65,536 IP addresses.

#### Public vs Private Subnets

| Type | Route | Access |
|------|-------|--------|
| **Public** | Has route to Internet Gateway | Instances can have public IPs |
| **Private** | No direct internet route | Reaches internet via NAT Gateway (outbound only) |

### What We Built

#### Step 1: Created Private Subnets

```bash
# Subnet in AZ 1a
aws ec2 create-subnet \
  --vpc-id <vpc-id> \
  --cidr-block <private-ip>/20 \
  --availability-zone ap-southeast-1a \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=RegionalBank-fraud-1}]'

# Subnet in AZ 1b (ALB requires 2 AZs)
aws ec2 create-subnet \
  --vpc-id <vpc-id> \
  --cidr-block <private-ip>/20 \
  --availability-zone ap-southeast-1b \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=RegionalBank-fraud-2}]'
```

#### Step 2: Configured Route Tables

```bash
# Create route table for private subnets
aws ec2 create-route-table --vpc-id <vpc-id>

# Route internet traffic through NAT Gateway
aws ec2 create-route \
  --route-table-id rtb-xxxxx \
  --destination-cidr-block 0.0.0.0/0 \
  --nat-gateway-id nat-xxxxx

# Associate with private subnets
aws ec2 associate-route-table \
  --route-table-id rtb-xxxxx \
  --subnet-id <subnet-id>
```

#### Step 3: Created Security Groups

```bash
# EC2 Security Group - only allows traffic from ALB
aws ec2 create-security-group \
  --group-name RegionalBank-ec2-sg \
  --description "EC2 security group" \
  --vpc-id <vpc-id>

aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp \
  --port 8000 \
  --source-group <sg-id>  # From ALB only
```

---

## Part 4: EC2 and Docker Deployment

### IAM Role for EC2

EC2 instances need permissions to access AWS services:

```bash
# Create role
aws iam create-role \
  --role-name RegionalBank-ec2-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ec2.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach policies
aws iam attach-role-policy --role-name RegionalBank-ec2-role \
  --policy-arn arn:aws:iam::aws:policy/SecretsManagerReadWrite
aws iam attach-role-policy --role-name RegionalBank-ec2-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

# Create instance profile
aws iam create-instance-profile --instance-profile-name RegionalBank-ec2-profile
aws iam add-role-to-instance-profile \
  --instance-profile-name RegionalBank-ec2-profile \
  --role-name RegionalBank-ec2-role
```

### Launching EC2 Instances

```bash
aws ec2 run-instances \
  --image-id ami-0c3d4e5f607182930 \
  --instance-type c6i.2xlarge \
  --subnet-id <subnet-id> \
  --security-group-ids <sg-id> \
  --iam-instance-profile Name=RegionalBank-ec2-profile \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=RegionalBank-fraud-1}]'
```

**Why c6i.2xlarge?**
- 8 vCPUs for 16 Gunicorn workers (2 per core)
- 16GB RAM for concurrent connections
- Intel Ice Lake processors

### Accessing Private Instances

Use AWS Systems Manager Session Manager (no SSH keys needed):

```bash
aws ssm start-session --target <instance-id> --region ap-southeast-1
```

### Installing Docker on Amazon Linux 2023

```bash
# Install Docker
sudo dnf install -y docker
sudo systemctl enable docker
sudo systemctl start docker

# Add user to docker group
sudo usermod -aG docker ssm-user

# Install Docker Compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
```

### Deploying the Application

#### 1. Clone Repository

```bash
cd /home/ssm-user
git clone git@github.com:YOUR_ORG/RegionalBank_fraud_detection.git
cd RegionalBank_fraud_detection
```

#### 2. Retrieve Secrets

```bash
# Get MongoDB X509 certificate
mkdir -p certs
aws secretsmanager get-secret-value \
  --secret-id RegionalBank/mongodb-x509-cert \
  --query SecretString \
  --output text > certs/mongodb-cert.pem
```

#### 3. Create Environment File

```bash
cat > .env << 'EOF'
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>
DB_NAME=RegionalBank_fraud
LOG_LEVEL=INFO
WORKERS=16
LOCUST_HOST=<private-ip>
LOCUST_PORT=8089
EOF
```

**Important:** `LOG_LEVEL=INFO` (uppercase). Python's logging module:
- `logging.INFO` = 20 (level constant)
- `logging.info` = function

#### 4. Build and Start

```bash
docker compose up -d --build
```

#### 5. Verify

```bash
docker compose ps
docker compose logs api --tail 50
curl http://localhost:8000/health
```

---

## Part 5: Troubleshooting

### Issue 1: ModuleNotFoundError for seed.data

**Symptom:** `ModuleNotFoundError: No module named 'seed.data'`

**Cause:** The `backend/seed/data/` folder was in `.gitignore`.

**Solution:**
```bash
git add -f backend/seed/data/
git commit -m "Add seed data folder"
git push
```

### Issue 2: TypeError with LOG_LEVEL

**Symptom:** `TypeError: Level not an integer or a valid string: <function info at 0x...>`

**Cause:** `LOG_LEVEL=info` (lowercase) returns `logging.info` function, not `logging.INFO` constant.

**Solution:** Use uppercase: `LOG_LEVEL=INFO`

### Issue 3: Docker Compose Not Reading .env

**Cause:** Docker Compose reads `.env` from project root, not `backend/.env`.

**Solution:** Place `.env` in same directory as `docker-compose.yml`:
```
~/RegionalBank_fraud_detection/.env          # Correct
~/RegionalBank_fraud_detection/backend/.env  # Wrong
```

---

## Part 6: Resource Reference

### Current AWS Resources

| Resource | ID/Value |
|----------|----------|
| **Region** | ap-southeast-1 (Singapore) |
| **VPC** | <vpc-id> |
| **VPC CIDR** | <private-ip>/16 |
| **Private Subnet 1a** | <subnet-id> |
| **Private Subnet 1b** | <subnet-id> |
| **EC2 #1 (Instance ID)** | <instance-id> |
| **EC2 #1 (Private IP)** | <private-ip> |
| **EC2 #2 (Instance ID)** | <instance-id> |
| **EC2 #2 (Private IP)** | <private-ip> |
| **EC2 Security Group** | <sg-id> |
| **IAM Role** | RegionalBank-ec2-role |
| **IAM Instance Profile** | RegionalBank-ec2-profile |

### Docker Compose Services

| Service | Port | Workers | Resources |
|---------|------|---------|-----------|
| api | 8000 | 16 Gunicorn | 7 CPU, 14GB RAM |
| frontend | 3000 | 1 Node.js | 0.5 CPU, 512MB |

---

## Related Documentation

- [PRIVATELINK-SETUP.md](./PRIVATELINK-SETUP.md) - MongoDB Atlas PrivateLink configuration
- [ALB-SETUP.md](./ALB-SETUP.md) - Application Load Balancer setup
- [LOCUST-SETUP.md](./LOCUST-SETUP.md) - Locust load testing architecture
- DEPLOYMENT-RUNBOOK.md - Quick reference commands

---

## Document History

| Date | Author | Changes |
|------|--------|---------|
| 2025-12-31 | Claude + Paul | Initial creation |
| 2026-01-07 | Claude + Paul | Updated with current resource IDs |
| 2026-02-10 | Claude + Paul | Added Docker log rotation configuration |
