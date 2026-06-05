# MongoDB Atlas PrivateLink Setup Guide

This document covers the complete setup of MongoDB Atlas PrivateLink for the RegionalBank Fraud Detection API, including all configuration steps, debugging challenges, and solutions.

## Why PrivateLink?

When connecting to MongoDB Atlas from AWS, you have three options:

| Connection Method | Traffic Path | Security | Latency | Cost |
|-------------------|--------------|----------|---------|------|
| **Public Internet** | EC2 → Internet Gateway → Atlas | Encrypted but traverses public internet | Higher, variable | Free |
| **VPC Peering** | EC2 → Peered VPC → Atlas | Private, but requires CIDR management | Low | Free |
| **PrivateLink** | EC2 → VPC Endpoint → AWS Backbone → Atlas | Private, no CIDR overlap concerns | Lowest, consistent | ~$0.01/GB |

**We chose PrivateLink because:**

1. **Security:** Traffic never leaves AWS's private backbone network. Even though public connections are encrypted, some compliance requirements mandate private-only connectivity.

2. **Latency:** PrivateLink provides the lowest and most consistent latency because traffic stays on AWS's internal network rather than routing through the public internet.

3. **No CIDR Management:** Unlike VPC Peering, PrivateLink doesn't require coordinating IP address ranges between your VPC and Atlas. This avoids conflicts if your VPC CIDR overlaps with Atlas's internal ranges.

4. **Simplified Security Groups:** You control access via security groups attached to the VPC Endpoint, rather than managing complex network ACLs.

5. **Production-Grade:** For a fraud detection system handling 10K+ TPS with sub-50ms latency requirements, we need the most reliable and fastest connection possible.

## Executive Summary

**Final Result:** Successfully connected Docker containers on EC2 instances to a sharded MongoDB Atlas M60 cluster (3 shards) via PrivateLink with X509 certificate authentication, achieving sub-15ms latency with proper load distribution across all shards.

**Key Discovery:** For sharded clusters, use `loadBalanced=true` instead of `directConnection=true` to enable proper mongos routing.

---

## Part 1: Architecture Overview

### Understanding the Components

Before diving into the diagram, let's understand what each component does and why it's necessary:

**VPC Endpoint (AWS PrivateLink):** This is the core of the setup. A VPC Endpoint creates an Elastic Network Interface (ENI) inside your VPC subnets. This ENI has a private IP address that your EC2 instances can reach. When traffic goes to this ENI, AWS internally routes it over its private backbone to MongoDB Atlas - never touching the public internet.

**Route 53 Private Hosted Zone:** MongoDB drivers use DNS to discover cluster members. When you use a connection string like `mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db> the driver first does a DNS lookup. Normally, this would resolve to Atlas's public IPs. But we need it to resolve to our VPC Endpoint's private IPs instead. A Private Hosted Zone lets us "override" the public DNS - any query for `*.mongodb.net` from within our VPC goes to our private zone first.

**Security Groups:** These act as virtual firewalls. The VPC Endpoint has its own security group that controls which resources in your VPC can send traffic through the endpoint to Atlas.

**X509 Certificates:** Instead of username/password authentication, we use client certificates. The certificate contains the identity that MongoDB uses for authorization. This is more secure (no passwords to leak) and works seamlessly with PrivateLink.

### What We Built

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              AWS VPC (<vpc-id>)                               │
│                              CIDR: <private-ip>/16                                  │
│                                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────────┐    │
│  │                           Private Subnets                                 │    │
│  │                                                                           │    │
│  │   ┌─────────────────────┐              ┌─────────────────────┐           │    │
│  │   │  ap-southeast-1a    │              │  ap-southeast-1b    │           │    │
│  │   │  <private-ip>/20     │              │  <private-ip>/20     │           │    │
│  │   │                     │              │                     │           │    │
│  │   │  ┌───────────────┐  │              │  ┌───────────────┐  │           │    │
│  │   │  │    EC2 #1     │  │              │  │    EC2 #2     │  │           │    │
│  │   │  │    Docker     │  │              │  │    Docker     │  │           │    │
│  │   │  │  API x16      │  │              │  │  API x16      │  │           │    │
│  │   │  │  workers      │  │              │  │  workers      │  │           │    │
│  │   │  └───────┬───────┘  │              │  └───────┬───────┘  │           │    │
│  │   │          │          │              │          │          │           │    │
│  │   │  ┌───────▼───────┐  │              │  ┌───────▼───────┐  │           │    │
│  │   │  │ VPC Endpoint  │  │              │  │ VPC Endpoint  │  │           │    │
│  │   │  │     ENI       │  │              │  │     ENI       │  │           │    │
│  │   │  │ <private-ip> │  │              │  │ <private-ip> │  │           │    │
│  │   │  └───────┬───────┘  │              │  └───────┬───────┘  │           │    │
│  │   └──────────┼──────────┘              └──────────┼──────────┘           │    │
│  │              │                                    │                      │    │
│  │              └─────────────┬──────────────────────┘                      │    │
│  │                            │                                             │    │
│  └────────────────────────────┼─────────────────────────────────────────────┘    │
│                               │                                                   │
│                      ┌────────▼────────┐                                         │
│                      │  VPC Endpoint   │                                         │
│                      │  (PrivateLink)  │                                         │
│                      │ vpce-076064...  │                                         │
│                      └────────┬────────┘                                         │
│                               │                                                   │
│  ┌────────────────────────────┼────────────────────────────────────────────┐     │
│  │ Route 53 Private Hosted Zone: <atlas-cluster>.mongodb.net                         │     │
│  │                                                                         │     │
│  │  _mongodb._tcp.cluster0-pl-0-lb  → SRV 0 0 1025 pl-0-ap-southeast-1    │     │
│  │  pl-0-ap-southeast-1             → A   <private-ip>, <private-ip>    │     │
│  │  cluster0-pl-0-lb                → A   <private-ip>, <private-ip>    │     │
│  └─────────────────────────────────────────────────────────────────────────┘     │
│                                                                                   │
└───────────────────────────────────┬───────────────────────────────────────────────┘
                                    │
                                    │ AWS PrivateLink
                                    │ (Private AWS Backbone)
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │      MongoDB Atlas M60        │
                    │    Sharded Cluster (3 shards) │
                    │      ap-southeast-1           │
                    │                               │
                    │  ┌─────────────────────────┐  │
                    │  │        mongos           │  │
                    │  │    (Load Balancer)      │  │
                    │  └───────────┬─────────────┘  │
                    │              │                │
                    │    ┌─────────┼─────────┐      │
                    │    ▼         ▼         ▼      │
                    │ ┌─────┐  ┌─────┐  ┌─────┐    │
                    │ │Shard│  │Shard│  │Shard│    │
                    │ │  0  │  │  1  │  │  2  │    │
                    │ └─────┘  └─────┘  └─────┘    │
                    └───────────────────────────────┘
```

### Key Components

| Component | Purpose |
|-----------|---------|
| **VPC Endpoint** | Creates private network interface (ENI) that connects to Atlas |
| **Route 53 Private Hosted Zone** | Resolves MongoDB hostnames to VPC Endpoint private IPs |
| **Security Groups** | Controls traffic flow to/from the VPC Endpoint |
| **X509 Certificate** | Authenticates the application to MongoDB (no password) |
| **loadBalanced=true** | Tells PyMongo to use load balancer mode for proper sharding |

### Why loadBalanced=true is Critical

| Connection Mode | Behavior | Result |
|-----------------|----------|--------|
| `directConnection=true` | Bypasses mongos, connects directly to one shard | ❌ Only sees data on that shard |
| No special flag | Driver tries replica set discovery on port 27017 | ❌ Fails (PrivateLink uses 1024-1026) |
| `loadBalanced=true` | Uses load balancer mode, mongos routes queries | ✅ Proper sharding, all data visible |

---

## Part 2: Prerequisites

### Atlas Configuration

1. **Cluster Type:** M30 or higher (PrivateLink requires dedicated clusters)
   - *Why:* Shared clusters (M0/M2/M5) run on multi-tenant infrastructure that doesn't support PrivateLink. You need a dedicated cluster to get a unique PrivateLink endpoint.

2. **Region:** ap-southeast-1 (Singapore)
   - *Why:* PrivateLink is region-specific. Your Atlas cluster and AWS VPC must be in the same region. Cross-region PrivateLink is not supported.

3. **Sharding:** Enabled with 3 shards
   - *Why:* For 10K+ TPS, we need horizontal scaling. Each shard handles a portion of the data, and mongos routes queries to the appropriate shard(s).

4. **Authentication:** X509 certificate
   - *Why:* More secure than username/password (no credentials to leak), works seamlessly with PrivateLink, and provides cryptographic identity verification.

### AWS Requirements

1. **VPC:** With private subnets in multiple AZs
   - *Why:* Private subnets ensure your EC2 instances aren't directly accessible from the internet. Multiple AZs provide fault tolerance - if one AZ goes down, the other continues serving traffic.

2. **IAM:** Permissions to create VPC Endpoints, Route 53 zones
   - *Why:* You'll need to create resources in both EC2 (VPC Endpoints) and Route 53 (Private Hosted Zones). Ensure your IAM user/role has these permissions before starting.

3. **EC2:** Instances in private subnets with Docker installed
   - *Why:* The application runs in Docker containers. Being in private subnets means all outbound traffic to MongoDB goes through the VPC Endpoint.

---

## Part 3: Step-by-Step Setup

### Step 1: Create VPC Endpoint

**Why this step:** The VPC Endpoint is the bridge between your VPC and MongoDB Atlas. It creates private network interfaces (ENIs) inside your subnets that act as entry points to Atlas's PrivateLink service. Without this, your EC2 instances would have no private path to reach Atlas.

**Why multiple subnets:** We specify two subnets in different Availability Zones (ap-southeast-1a and 1b) for high availability. If one AZ has issues, traffic automatically routes through the other. Each subnet gets its own ENI with its own private IP.

**Why the service name matters:** MongoDB Atlas exposes a specific PrivateLink service endpoint for each region. This service name (`com.amazonaws.vpce...`) is unique to your Atlas project and region - it tells AWS which PrivateLink service to connect to.

Get the endpoint service name from Atlas UI → Network Access → Private Endpoint.

```bash
# Atlas provides the service name
SERVICE_NAME="com.amazonaws.vpce.ap-southeast-1.vpce-svc-0865f8b449c5ce646"

# Create VPC Endpoint in BOTH availability zones
aws ec2 create-vpc-endpoint \
  --vpc-id <vpc-id> \
  --service-name $SERVICE_NAME \
  --vpc-endpoint-type Interface \
  --subnet-ids <subnet-id> <subnet-id> \
  --security-group-ids <sg-id> \
  --region ap-southeast-1
```

**Result:** VPC Endpoint `vpce-076064803f85fe072` created

### Step 2: Verify Endpoint Status

```bash
aws ec2 describe-vpc-endpoints \
  --vpc-endpoint-ids vpce-076064803f85fe072 \
  --query 'VpcEndpoints[0].State' \
  --region ap-southeast-1
```

Wait until status is `available`.

### Step 3: Get Endpoint Private IPs

**Why this step:** We need the private IP addresses of the ENIs that AWS created. These IPs are what we'll put in our Route 53 DNS records. When your application resolves MongoDB hostnames, they need to point to these private IPs - not Atlas's public IPs.

**Why two IPs:** One for each Availability Zone. Having IPs in both AZs provides redundancy and allows traffic to stay within the same AZ as your EC2 instance (reducing cross-AZ data transfer costs and latency).

```bash
# Get ENI IDs
aws ec2 describe-vpc-endpoints \
  --vpc-endpoint-ids vpce-076064803f85fe072 \
  --query 'VpcEndpoints[0].NetworkInterfaceIds' \
  --region ap-southeast-1
# Result: ["eni-0b2c3d4e5f6071829", "eni-0a1b2c3d4e5f60718"]

# Get private IPs for each ENI
aws ec2 describe-network-interfaces \
  --network-interface-ids eni-0b2c3d4e5f6071829 eni-0a1b2c3d4e5f60718 \
  --query 'NetworkInterfaces[].{Subnet:SubnetId,IP:PrivateIpAddress}' \
  --region ap-southeast-1
```

**Results:**
- <private-ip> (ap-southeast-1a)
- <private-ip> (ap-southeast-1b)

### Step 4: Configure Security Group

**Why this step:** Security groups are stateful firewalls. Even though we created the VPC Endpoint, traffic won't flow unless the endpoint's security group allows it. Think of it as unlocking the door we just created.

**Why ports 1024-65535:** Atlas PrivateLink does NOT use MongoDB's standard port 27017. Instead, it uses ports in the 1024-1026 range for the load balancer mode we need for sharded clusters. We open a wider range to be safe, but only from within our VPC CIDR.

**Why source-group rule:** The second rule allows all traffic from our EC2 instances' security group. This is more secure than opening by IP range because it follows the instances even if their IPs change.

The VPC Endpoint's security group must allow inbound traffic on ports 1024-65535:

```bash
# Add rule for PrivateLink ports
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp \
  --port 1024-65535 \
  --cidr <private-ip>/16 \
  --region ap-southeast-1

# Allow all traffic from EC2 security group
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol -1 \
  --source-group <sg-id> \
  --region ap-southeast-1
```

### Step 5: Create Route 53 Private Hosted Zone

**Why this step:** This is the DNS "trick" that makes PrivateLink work. MongoDB drivers use DNS to find cluster members. Without this, when your app queries `<atlas-cluster>.mongodb.net`, it would get Atlas's public IPs.

**How Private Hosted Zones work:** When you create a Private Hosted Zone for a domain (like `<atlas-cluster>.mongodb.net`) and associate it with your VPC, ALL DNS queries from within that VPC for that domain go to your private zone first. It's like creating a private phone book that overrides the public one.

**The zone name must match Atlas's domain:** We use `<atlas-cluster>.mongodb.net` because that's the domain suffix Atlas assigned to our cluster. Any query for `*<atlas-cluster>.mongodb.net` from within our VPC will now check our private zone.

```bash
aws route53 create-hosted-zone \
  --name <atlas-cluster>.mongodb.net \
  --vpc VPCRegion=ap-southeast-1,VPCId=<vpc-id> \
  --caller-reference "RegionalBank-privatelink-$(date +%s)" \
  --hosted-zone-config PrivateZone=true
```

**Result:** Hosted Zone ID `Z05235881BYZXF1NIMZFQ`

### Step 6: Create DNS Records

**Why this step:** The Private Hosted Zone is empty by default. We need to add records that tell the MongoDB driver where to connect. Without these records, DNS lookups will fail and the driver can't establish a connection.

**Understanding mongodb+srv:// connection strings:**

When you use a connection string like `mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db> the driver does a multi-step DNS lookup:

```
Step 1: SRV Lookup
   Query: _mongodb._tcp.<atlas-cluster>.mongodb.net
   Returns: Server hostname and port (<atlas-cluster>.mongodb.net:1025)

Step 2: A Record Lookup
   Query: <atlas-cluster>.mongodb.net
   Returns: IP addresses (<private-ip>, <private-ip>)

Step 3: Connect
   Driver connects to <private-ip>:1025 via the VPC Endpoint
```

**Why three records:**
1. **SRV Record:** Tells the driver which server(s) to connect to and on what port. This is how `mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db> works - it's a service discovery mechanism.
2. **A Record for SRV target:** Resolves the hostname from the SRV record to actual IP addresses.
3. **A Record for load balancer hostname:** Some drivers also query the base hostname directly. We need this for complete compatibility.

You need three DNS records for a sharded cluster with `loadBalanced=true`:

#### Record 1: SRV Record (Service Discovery)

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id Z05235881BYZXF1NIMZFQ \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "_mongodb._tcp.<atlas-cluster>.mongodb.net",
        "Type": "SRV",
        "TTL": 300,
        "ResourceRecords": [{"Value": "0 0 1025 <atlas-cluster>.mongodb.net"}]
      }
    }]
  }' \
  --region ap-southeast-1
```

#### Record 2: A Record for SRV Target

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id Z05235881BYZXF1NIMZFQ \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "<atlas-cluster>.mongodb.net",
        "Type": "A",
        "TTL": 300,
        "ResourceRecords": [
          {"Value": "<private-ip>"},
          {"Value": "<private-ip>"}
        ]
      }
    }]
  }' \
  --region ap-southeast-1
```

#### Record 3: A Record for Load Balancer Hostname

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id Z05235881BYZXF1NIMZFQ \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "<atlas-cluster>.mongodb.net",
        "Type": "A",
        "TTL": 300,
        "ResourceRecords": [
          {"Value": "<private-ip>"},
          {"Value": "<private-ip>"}
        ]
      }
    }]
  }' \
  --region ap-southeast-1
```

### Step 7: Verify DNS Records

```bash
aws route53 list-resource-record-sets \
  --hosted-zone-id Z05235881BYZXF1NIMZFQ \
  --query 'ResourceRecordSets[?Type!=`NS` && Type!=`SOA`]' \
  --region ap-southeast-1
```

**Expected Output:**

| Name | Type | Value |
|------|------|-------|
| `_mongodb._tcp.<atlas-cluster>.mongodb.net` | SRV | `0 0 1025 <atlas-cluster>.mongodb.net` |
| `<atlas-cluster>.mongodb.net` | A | `<private-ip>, <private-ip>` |
| `<atlas-cluster>.mongodb.net` | A | `<private-ip>, <private-ip>` |

---

## Part 4: Application Configuration

### Docker Compose Configuration

**Why explicit DNS configuration is critical:**

By default, Docker containers use Docker's internal DNS resolver (127.0.0.11), which forwards queries to the host's DNS settings. However, this forwarding doesn't always work correctly with Route 53 Private Hosted Zones.

**The problem:** When a container queries `<atlas-cluster>.mongodb.net`, Docker's DNS might:
- Cache stale results
- Forward to public DNS instead of VPC DNS
- Not properly resolve private zone records

**The solution:** Explicitly configure the container to use the VPC's DNS resolver directly:

```yaml
dns:
  - <private-ip>    # VPC DNS resolver
```

**Why <private-ip>?** AWS reserves the `.2` address in every VPC CIDR for the DNS resolver. For a VPC with CIDR `<private-ip>/16`, the DNS resolver is always at `<private-ip>`. This resolver knows about your Private Hosted Zones.

```yaml
# docker-compose.yml
services:
  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    dns:
      - <private-ip>    # VPC DNS - CRITICAL for Route 53 Private Zone
    environment:
      - MONGODB_URI=${MONGODB_URI}
      - DB_NAME=${DB_NAME:-RegionalBank_fraud}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - WORKERS=${WORKERS:-16}
    volumes:
      - ./certs:/app/certs:ro
    deploy:
      resources:
        limits:
          cpus: '7'
          memory: 14G
```

### Environment File (.env)

```bash
# .env - FOR SHARDED CLUSTERS
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>
DB_NAME=RegionalBank_fraud
LOG_LEVEL=INFO
WORKERS=16
```

### Connection String Breakdown

Each parameter in the connection string serves a specific purpose:

```
mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>
  ?authSource=%24external           # Use $external for X509
  &authMechanism=MONGODB-X509       # X509 certificate auth
  &tlsCertificateKeyFile=/app/certs/mongodb-cert.pem  # Cert path
  &tls=true                         # Enable TLS
  &loadBalanced=true                # CRITICAL: Enable load balancer mode
```

**Parameter explanations:**

| Parameter | Value | Why It's Needed |
|-----------|-------|-----------------|
| `authSource` | `$external` | X509 authentication uses external identity (the certificate), not a MongoDB user database |
| `authMechanism` | `MONGODB-X509` | Tells the driver to authenticate using the client certificate, not username/password |
| `tlsCertificateKeyFile` | `/app/certs/...` | Path to the certificate file inside the container (mounted via Docker volume) |
| `tls` | `true` | Enforces TLS encryption - required for X509 and PrivateLink |
| `loadBalanced` | `true` | **Critical for sharded clusters** - tells the driver to use load balancer mode instead of replica set discovery |

**Why loadBalanced=true is critical:**

Without this flag, the MongoDB driver tries to:
1. Connect to port 27017 (PrivateLink uses 1024-1026)
2. Discover replica set members (which doesn't work through a load balancer)
3. Connect directly to individual shards (bypassing mongos)

With `loadBalanced=true`, the driver:
1. Connects to the port specified in the SRV record (1025)
2. Sends all queries through mongos (the shard router)
3. Properly utilizes all shards in the cluster

---

## Part 5: Troubleshooting Guide

Each issue below represents a real problem we encountered. Understanding the root cause helps you diagnose similar issues faster.

### Issue 1: DNS Not Resolving Inside Container

**Symptom:** `socket.gaierror: [Errno -2] Name or service not known`

**Cause:** Docker container not using VPC DNS.

**What's happening:** The container is using Docker's internal DNS (127.0.0.11), which either can't reach the VPC DNS resolver or is caching stale results. The Private Hosted Zone records exist, but the container can't see them.

**Solution:** Add DNS configuration to docker-compose.yml:
```yaml
services:
  api:
    dns:
      - <private-ip>   # VPC DNS (always x.x.0.2)
```

### Issue 2: SRV Record Not Found

**Symptom:** `ConfigurationError: The DNS query name does not exist: _mongodb._tcp.<atlas-cluster>.mongodb.net`

**Cause:** Private Hosted Zone intercepts all queries but missing SRV record.

**What's happening:** Your Private Hosted Zone for `<atlas-cluster>.mongodb.net` is working - it's intercepting DNS queries. But you only created the A record, not the SRV record. The `mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db> protocol requires an SRV record to discover servers. Since your private zone doesn't have it and won't fall through to public DNS, the lookup fails.

**Solution:** Create SRV record in Route 53 (see Step 6).

### Issue 3: Only Seeing Data from One Shard

**Symptom:** Health check shows 0 customers, but data exists in Atlas.

**Cause:** Using `directConnection=true` which bypasses mongos.

**What's happening:** With `directConnection=true`, the driver connects directly to one server and treats it as a standalone. In a sharded cluster, this means you're talking to one shard directly, bypassing mongos (the shard router). Since your data is distributed across shards, you only see data that happens to be on the shard you connected to - potentially none of what you're looking for.

**Solution:** Use `loadBalanced=true` instead:
```bash
# Wrong (bypasses mongos)
MONGODB_URI=...&directConnection=true

# Correct (uses mongos for sharding)
MONGODB_URI=...&loadBalanced=true
```

### Issue 4: Connection Timeout on Port 27017

**Symptom:** `ServerSelectionTimeoutError: ... :27017`

**Cause:** Driver trying to connect on port 27017, but PrivateLink uses 1024-1026.

**What's happening:** Without `loadBalanced=true`, the MongoDB driver uses its standard replica set discovery process. It tries to connect to port 27017 and ask for the replica set configuration. But Atlas PrivateLink only exposes ports 1024-1026 - port 27017 isn't open. The driver times out waiting for a response on a port that's not listening.

**Solution:** Use `loadBalanced=true` to prevent replica set discovery. This tells the driver to use the port specified in the SRV record (1025) and skip the discovery handshake.

### Issue 5: Security Group Blocking Traffic

**Symptom:** Connection timeout even with correct DNS.

**Solution:** Ensure VPC Endpoint security group allows ports 1024-65535:
```bash
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp \
  --port 1024-65535 \
  --cidr <private-ip>/16 \
  --region ap-southeast-1
```

---

## Part 6: Verification Commands

### Test DNS Resolution (from EC2 host)

```bash
# SRV record
nslookup -type=SRV _mongodb._tcp.<atlas-cluster>.mongodb.net

# A record for SRV target
nslookup <atlas-cluster>.mongodb.net

# Load balancer hostname
nslookup <atlas-cluster>.mongodb.net
```

### Test DNS from Inside Container

```bash
docker compose exec api python -c "import socket; print(socket.gethostbyname('<atlas-cluster>.mongodb.net'))"
```

### Test Port Connectivity

```bash
# Atlas PrivateLink uses ports 1024-1026
for port in 1024 1025 1026; do
  timeout 2 bash -c "cat < /dev/null > /dev/tcp/<private-ip>/$port" 2>/dev/null && \
    echo "Port $port open" || echo "Port $port closed"
done
```

### Test Application Health

```bash
# Local test
curl http://localhost:8000/health

# Via ALB
curl http://<load-balancer-endpoint>/health
```

### Verify Sharding is Working

```bash
curl http://localhost:8000/health | jq '.sharding'
# Expected: {"enabled": true, "shards": 3}
```

---

## Part 7: Performance Results

**Why these numbers matter:** The whole point of PrivateLink is performance and security. These metrics prove it's working correctly.

With proper PrivateLink configuration and `loadBalanced=true`:

| Metric | Value |
|--------|-------|
| Average Latency | 13.7ms |
| P95 Latency | 15.6ms |
| P99 Latency | 34ms |
| Scoring Time | 3.9ms |
| DB Persist Time | 5.4ms |
| Shards Utilized | 3/3 |

---

## Part 8: Resource Reference

### AWS Resources

| Resource | ID |
|----------|-----|
| VPC | <vpc-id> |
| Private Subnet 1a | <subnet-id> |
| Private Subnet 1b | <subnet-id> |
| VPC Endpoint | vpce-076064803f85fe072 |
| Hosted Zone | Z05235881BYZXF1NIMZFQ |
| Endpoint Security Group | <sg-id> |

### VPC Endpoint ENIs

| ENI | Subnet | AZ | Private IP |
|-----|--------|-----|------------|
| eni-0b2c3d4e5f6071829 | <subnet-id> | ap-southeast-1a | <private-ip> |
| eni-0a1b2c3d4e5f60718 | <subnet-id> | ap-southeast-1b | <private-ip> |

### Route 53 Records

| Name | Type | TTL | Value |
|------|------|-----|-------|
| `_mongodb._tcp.<atlas-cluster>.mongodb.net` | SRV | 300 | `0 0 1025 <atlas-cluster>.mongodb.net` |
| `<atlas-cluster>.mongodb.net` | A | 300 | `<private-ip>, <private-ip>` |
| `<atlas-cluster>.mongodb.net` | A | 300 | `<private-ip>, <private-ip>` |

### Security Group Rules (<sg-id>)

| Type | Protocol | Port Range | Source |
|------|----------|------------|--------|
| Inbound | TCP | 1024-65535 | <private-ip>/16 |
| Inbound | All | All | <sg-id> |

---

## Part 9: Key Lessons Learned

These lessons came from real debugging sessions. Understanding the "why" behind each will save you hours of troubleshooting.

### 1. Atlas PrivateLink Uses Non-Standard Ports

MongoDB typically uses port 27017, but Atlas PrivateLink exposes ports 1024-1026.

**Why different ports?** Atlas PrivateLink uses a load balancer architecture to handle traffic from multiple customers' VPCs. The load balancer listens on ports 1024-1026 (one per mongos router for sharded clusters). This is an Atlas implementation detail - you can't change it.

**The implication:** If you see connection timeouts on port 27017, it means your driver isn't using `loadBalanced=true` and is trying to connect the "normal" way.

### 2. loadBalanced=true is Essential for Sharded Clusters

| Flag | Use Case | Sharding Support |
|------|----------|------------------|
| `directConnection=true` | Single replica set, testing | ❌ No |
| `loadBalanced=true` | Sharded clusters via PrivateLink | ✅ Yes |

### 3. Private Hosted Zones Override Public DNS

ALL DNS queries for that domain from within your VPC go to Route 53 first. You must create records for every hostname the driver needs.

**Why this matters:** When you create a Private Hosted Zone for `<atlas-cluster>.mongodb.net`, your VPC will NEVER query public DNS for any `*<atlas-cluster>.mongodb.net` hostname. If a record doesn't exist in your private zone, the lookup fails - it doesn't "fall through" to public DNS.

**Common mistake:** Creating only the main A record but forgetting the SRV record. The driver queries both, and if either fails, the connection fails.

### 4. Docker Containers Need Explicit DNS Configuration

Docker's internal DNS doesn't automatically forward to Route 53 Private Zones:
```yaml
dns:
  - <private-ip>   # VPC DNS resolver (always x.x.0.2)
```

**Why Docker DNS is problematic:** Docker runs its own DNS resolver inside containers at 127.0.0.11. This resolver caches aggressively and doesn't always properly forward to the host's DNS. For Private Hosted Zones to work, queries must reach the VPC's DNS resolver (the `.2` address in your CIDR), which is the only resolver that knows about your private zones.

**How to find your VPC DNS:** Take your VPC CIDR (e.g., `<private-ip>/16`) and use the `.2` address: `<private-ip>`. This works for any VPC CIDR - just replace the host portion with `.2`.

### 5. DNS Resolution Chain for mongodb+srv://

```
1. SRV lookup: _mongodb._tcp.<atlas-cluster>.mongodb.net
   → Returns: <atlas-cluster>.mongodb.net:1025

2. A lookup: <atlas-cluster>.mongodb.net
   → Returns: <private-ip>, <private-ip>

3. Driver connects to <private-ip>:1025 (load balanced mode)

4. mongos routes queries to appropriate shards

5. All 3 shards accessible ✅
```

---

## Quick Reference Card

### Connection String (Sharded Cluster)

```
mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>
```

### Required Route 53 Records

1. **SRV:** `_mongodb._tcp.cluster0-pl-0-lb` → `0 0 1025 pl-0-ap-southeast-1`
2. **A:** `pl-0-ap-southeast-1` → VPC Endpoint IPs
3. **A:** `cluster0-pl-0-lb` → VPC Endpoint IPs

### Required Security Group Rules

- TCP 1024-65535 from VPC CIDR

### Docker DNS Config

```yaml
dns:
  - <private-ip>
```

---

## Related Documentation

- [EC2-DOCKER-SETUP.md](./EC2-DOCKER-SETUP.md) - EC2 and Docker configuration
- [ALB-SETUP.md](./ALB-SETUP.md) - Application Load Balancer setup
- [LOCUST-SETUP.md](./LOCUST-SETUP.md) - Load testing with Locust
- DEPLOYMENT-RUNBOOK.md - Quick reference commands

---

## Document History

| Date | Author | Changes |
|------|--------|---------|
| 2026-01-05 | Claude + Paul | Initial creation |
| 2026-01-07 | Claude + Paul | Updated with current resource IDs, added related docs |
| 2026-01-20 | Claude + Paul | Added detailed explanations for each step (the "why" behind each command) |
