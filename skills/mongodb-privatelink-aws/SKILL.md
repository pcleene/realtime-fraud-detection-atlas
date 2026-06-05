---
name: mongodb-privatelink-aws
description: Connect AWS applications to MongoDB Atlas using PrivateLink for secure, low-latency database connections. Includes ALB, Route 53, VPC configuration, and sharded cluster support. Use this skill when deploying applications that connect to MongoDB Atlas from AWS, when asked about secure MongoDB connections, when setting up private database connectivity, when troubleshooting PrivateLink DNS issues, or when configuring sharded cluster connections.
---

# MongoDB Atlas PrivateLink with AWS

PrivateLink creates a private network path from your AWS VPC to MongoDB Atlas, bypassing the public internet.

## Critical Discovery: loadBalanced=true for Sharded Clusters

**This is the #1 issue encountered.** For sharded clusters via PrivateLink, you MUST use `loadBalanced=true`:

| Connection Mode | Behavior | Result |
|-----------------|----------|--------|
| `directConnection=true` | Bypasses mongos, connects directly to one shard | **BROKEN**: Only sees data on that shard |
| No special flag | Driver tries replica set discovery on port 27017 | **BROKEN**: Fails (PrivateLink uses 1024-1026) |
| `loadBalanced=true` | Uses load balancer mode, mongos routes queries | **WORKS**: Proper sharding, all data visible |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           AWS VPC                                   │
│                                                                     │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐│
│  │  Public      │     │  Private     │     │  VPC Endpoint        ││
│  │  Subnets     │     │  Subnets     │     │  (Interface)         ││
│  │              │     │              │     │                      ││
│  │ ┌──────────┐ │     │ ┌──────────┐ │     │  ┌────────────────┐  ││
│  │ │   ALB    │ │────▶│ │   EC2    │ │────▶│  │ MongoDB        │  ││
│  │ └──────────┘ │     │ │ Docker   │ │     │  │ PrivateLink    │  ││
│  │              │     │ └──────────┘ │     │  └────────┬───────┘  ││
│  └──────────────┘     └──────────────┘     └───────────┼──────────┘│
│                                                        │           │
│  ┌───────────────────────────────────────────────────┐ │           │
│  │  Route 53 Private Hosted Zone                     │ │           │
│  │  *.mongodb.net → VPC Endpoint IPs                 │ │           │
│  └───────────────────────────────────────────────────┘ │           │
└────────────────────────────────────────────────────────┼───────────┘
                                                         │
                                               AWS PrivateLink
                                                         │
                                            ┌─────────────────────┐
                                            │  MongoDB Atlas      │
                                            │  Sharded Cluster    │
                                            │  (M10+ required)    │
                                            └─────────────────────┘
```

## Prerequisites

1. MongoDB Atlas cluster **M10 or higher** (PrivateLink not available on M0-M5)
2. Atlas project with PrivateLink enabled
3. Atlas API keys with Project Owner permissions
4. AWS VPC in the same region as Atlas cluster

## Terraform Configuration

### privatelink.tf

```hcl
# Step 1: Create Atlas PrivateLink Endpoint Service
resource "mongodbatlas_privatelink_endpoint" "main" {
  project_id    = var.mongodb_atlas_project_id
  provider_name = "AWS"
  region        = var.aws_region
}

# Step 2: Create AWS VPC Endpoint
resource "aws_vpc_endpoint" "mongodb" {
  vpc_id              = aws_vpc.main.id
  service_name        = mongodbatlas_privatelink_endpoint.main.endpoint_service_name
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.mongodb.id]
  private_dns_enabled = false  # Atlas manages DNS

  tags = {
    Name = "${var.project_name}-mongodb-endpoint"
  }
}

# Step 3: Connect AWS Endpoint to Atlas
resource "mongodbatlas_privatelink_endpoint_service" "main" {
  project_id          = var.mongodb_atlas_project_id
  private_link_id     = mongodbatlas_privatelink_endpoint.main.private_link_id
  endpoint_service_id = aws_vpc_endpoint.mongodb.id
  provider_name       = "AWS"
}

# Step 4: Create Route 53 Private Hosted Zone
resource "aws_route53_zone" "mongodb" {
  name = "mongodb.net"  # Match your Atlas domain suffix

  vpc {
    vpc_id = aws_vpc.main.id
  }
}

# Step 5: DNS Records - YOU NEED ALL THREE FOR SHARDED CLUSTERS

# Record 1: SRV Record (Service Discovery) - CRITICAL
resource "aws_route53_record" "mongodb_srv" {
  zone_id = aws_route53_zone.mongodb.zone_id
  name    = "_mongodb._tcp.cluster0-pl-0-lb.${var.mongodb_domain}"
  type    = "SRV"
  ttl     = 300
  records = ["0 0 1025 pl-0-${var.aws_region}.${var.mongodb_domain}"]
}

# Record 2: A Record for SRV Target
resource "aws_route53_record" "mongodb_pl" {
  zone_id = aws_route53_zone.mongodb.zone_id
  name    = "pl-0-${var.aws_region}.${var.mongodb_domain}"
  type    = "A"
  ttl     = 300
  records = [for ip in aws_vpc_endpoint.mongodb.dns_entry[*].dns_name : ip]
}

# Record 3: A Record for Load Balancer Hostname
resource "aws_route53_record" "mongodb_lb" {
  zone_id = aws_route53_zone.mongodb.zone_id
  name    = "cluster0-pl-0-lb.${var.mongodb_domain}"
  type    = "A"
  ttl     = 300
  records = [for ip in aws_vpc_endpoint.mongodb.dns_entry[*].dns_name : ip]
}

# Security Group - MUST allow ports 1024-65535, NOT just 27017
resource "aws_security_group" "mongodb" {
  name        = "${var.project_name}-mongodb-sg"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "MongoDB PrivateLink ports"
    from_port   = 1024
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
```

## Connection String for Sharded Clusters

```bash
# CORRECT - for sharded clusters via PrivateLink
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>

# WRONG - bypasses mongos, only sees one shard
MONGODB_URI=...&directConnection=true
```

**Note the `-pl-0-lb` suffix** - this indicates PrivateLink load balancer mode.

## Docker Configuration - CRITICAL DNS SETTING

Docker containers MUST use VPC DNS to resolve Route 53 Private Hosted Zone:

```yaml
# docker-compose.yml
services:
  api:
    build: ./backend
    ports:
      - "8000:8000"
    dns:
      - <private-ip>    # VPC DNS - CRITICAL! Always x.x.0.2 for your VPC
    environment:
      - MONGODB_URI=${MONGODB_URI}
    volumes:
      - ./certs:/app/certs:ro
```

**Without `dns: - <private-ip>`, containers use Docker's internal DNS which cannot resolve Route 53 Private Zones!**

## Troubleshooting Guide

### Issue 1: DNS Not Resolving Inside Container

**Symptom:** `socket.gaierror: [Errno -2] Name or service not known`

**Cause:** Docker container not using VPC DNS.

**Solution:** Add DNS configuration to docker-compose.yml:
```yaml
services:
  api:
    dns:
      - <private-ip>   # VPC DNS (always x.x.0.2 for your VPC CIDR)
```

**Verify from inside container:**
```bash
docker compose exec api python -c "import socket; print(socket.gethostbyname('cluster0-pl-0-lb.xxxxx.mongodb.net'))"
# Should return private IP like <private-ip>
```

### Issue 2: SRV Record Not Found

**Symptom:** `ConfigurationError: The DNS query name does not exist: _mongodb._tcp.cluster0-pl-0-lb.xxxxx.mongodb.net`

**Cause:** Private Hosted Zone intercepts ALL queries for that domain but missing SRV record.

**Solution:** Create SRV record in Route 53:
```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id Z05235881BYZXF1NIMZFQ \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "_mongodb._tcp.cluster0-pl-0-lb.xxxxx.mongodb.net",
        "Type": "SRV",
        "TTL": 300,
        "ResourceRecords": [{"Value": "0 0 1025 pl-0-ap-southeast-1.xxxxx.mongodb.net"}]
      }
    }]
  }'
```

### Issue 3: Only Seeing Data from One Shard

**Symptom:** Health check shows 0 customers, but data exists in Atlas. Or queries return partial data.

**Cause:** Using `directConnection=true` which bypasses mongos router.

**Solution:** Use `loadBalanced=true` instead:
```bash
# WRONG
MONGODB_URI=...&directConnection=true

# CORRECT
MONGODB_URI=...&loadBalanced=true
```

### Issue 4: Connection Timeout on Port 27017

**Symptom:** `ServerSelectionTimeoutError: ... :27017`

**Cause:** Driver trying to connect on port 27017, but Atlas PrivateLink uses ports 1024-1026.

**Solution:**
1. Use `loadBalanced=true` to prevent replica set discovery
2. Ensure security group allows ports 1024-65535

### Issue 5: Security Group Blocking Traffic

**Symptom:** Connection timeout even with correct DNS resolution.

**Cause:** Security group only allows port 27017.

**Solution:** PrivateLink uses ports 1024-1026, allow full range:
```bash
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 1024-65535 \
  --cidr <private-ip>/16
```

### Issue 6: Private Hosted Zone Overriding Public DNS

**Symptom:** DNS works from EC2 host but not from container, or vice versa.

**Cause:** Route 53 Private Hosted Zones intercept ALL queries for that domain from within VPC. You must create records for EVERY hostname the driver needs.

**Required records for sharded cluster:**

| Name | Type | Value |
|------|------|-------|
| `_mongodb._tcp.cluster0-pl-0-lb.xxxxx.mongodb.net` | SRV | `0 0 1025 pl-0-ap-southeast-1.xxxxx.mongodb.net` |
| `pl-0-ap-southeast-1.xxxxx.mongodb.net` | A | VPC Endpoint IPs |
| `cluster0-pl-0-lb.xxxxx.mongodb.net` | A | VPC Endpoint IPs |

## Verification Commands

```bash
# Test DNS from EC2 host
nslookup -type=SRV _mongodb._tcp.cluster0-pl-0-lb.xxxxx.mongodb.net
nslookup cluster0-pl-0-lb.xxxxx.mongodb.net

# Should resolve to private IPs (172.x.x.x), NOT public IPs

# Test port connectivity (PrivateLink uses 1024-1026)
for port in 1024 1025 1026; do
  timeout 2 bash -c "cat < /dev/null > /dev/tcp/<private-ip>/$port" 2>/dev/null && \
    echo "Port $port open" || echo "Port $port closed"
done

# Verify sharding is working
curl http://localhost:8000/health | jq '.sharding'
# Expected: {"enabled": true, "shards": 3}
```

## PyMongo Configuration for PrivateLink

```python
CLIENT_OPTIONS = {
    # PrivateLink-optimized settings
    "readPreference": "nearest",  # Use closest node via PrivateLink
    "compressors": ["zstd", "snappy", "zlib"],
    "retryWrites": True,
    "retryReads": True,
    "w": "majority",

    # Pool sizing for high throughput
    "maxPoolSize": 15,
    "minPoolSize": 3,
    "maxIdleTimeMS": 45000,
}

# Connection string MUST include loadBalanced=true for sharded clusters
client = AsyncMongoClient(MONGODB_URI, **CLIENT_OPTIONS)
```

## Key Lessons Learned

1. **Atlas PrivateLink uses non-standard ports** - 1024-1026, not 27017
2. **loadBalanced=true is ESSENTIAL for sharded clusters** - directConnection=true breaks sharding
3. **Private Hosted Zones override public DNS** - ALL queries for that domain go to Route 53 first
4. **Docker containers need explicit DNS** - Add `dns: - <private-ip>` or container can't resolve Private Zone
5. **You need THREE DNS records** - SRV, A for SRV target, A for load balancer hostname
6. **PrivateLink takes 5-10 minutes to provision** - Wait until status is "AVAILABLE"
