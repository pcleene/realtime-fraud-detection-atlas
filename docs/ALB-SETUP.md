# Application Load Balancer Setup Guide

This document covers setting up an Application Load Balancer (ALB) to distribute traffic across EC2 instances running the RegionalBank Fraud Detection API.

## Architecture Overview

```
                           Internet
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS VPC (ap-southeast-1)                        │
│                                                                              │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                    Application Load Balancer                           │ │
│   │    <load-balancer-endpoint>      │ │
│   │                                                                        │ │
│   │    ┌────────────┐              ┌────────────┐                         │ │
│   │    │ Listener   │              │ Listener   │                         │ │
│   │    │ HTTP:80    │              │ HTTP:3000  │                         │ │
│   │    └─────┬──────┘              └──────┬─────┘                         │ │
│   │          │                            │                                │ │
│   │          ▼                            ▼                                │ │
│   │    ┌────────────┐              ┌────────────┐                         │ │
│   │    │ Target     │              │ Target     │                         │ │
│   │    │ Group:8000 │              │ Group:3000 │                         │ │
│   │    └─────┬──────┘              └──────┬─────┘                         │ │
│   │          │                            │                                │ │
│   └──────────┼────────────────────────────┼────────────────────────────────┘ │
│              │                            │                                   │
│              ▼                            ▼                                   │
│   ┌──────────────────────┐     ┌──────────────────────┐                      │
│   │   EC2 #1             │     │   EC2 #2             │                      │
│   │   <instance-id>│     │   <instance-id>│                      │
│   │   <private-ip>       │     │   <private-ip>      │                      │
│   │                      │     │                      │                      │
│   │   FastAPI :8000      │     │   FastAPI :8000      │                      │
│   │   Frontend :3000     │     │   Frontend :3000     │                      │
│   └──────────────────────┘     └──────────────────────┘                      │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Resource Summary

| Resource | ID / Value |
|----------|------------|
| **ALB Name** | RegionalBank-fraud-alb |
| **ALB DNS** | <load-balancer-endpoint> |
| **ALB ARN** | arn:aws:elasticloadbalancing:ap-southeast-1:...:loadbalancer/app/RegionalBank-fraud-alb/... |
| **ALB Security Group** | <sg-id> |
| **Target Group (API)** | RegionalBank-fraud-tg-8000 (port 8000) |
| **Target Group (Frontend)** | RegionalBank-fraud-tg-3000 (port 3000) |
| **Subnets** | <subnet-id> (1a), <subnet-id> (1b) |
| **Region** | ap-southeast-1 (Singapore) |

---

## Part 1: ALB Concepts

### What is an Application Load Balancer?

An ALB operates at Layer 7 (HTTP/HTTPS) and provides:

| Feature | Description |
|---------|-------------|
| **Path-based routing** | Route /api/* to backend, /* to frontend |
| **Health checks** | Automatically removes unhealthy targets |
| **Cross-zone load balancing** | Distributes across AZs evenly |
| **Connection draining** | Graceful shutdown of instances |
| **Sticky sessions** | Optional session affinity |

### Key Components

| Component | Purpose |
|-----------|---------|
| **Load Balancer** | Entry point with public DNS name |
| **Listener** | Checks for connection requests (port + protocol) |
| **Target Group** | Routes requests to registered targets |
| **Target** | EC2 instance or IP address |
| **Health Check** | Validates target availability |

---

## Part 2: Creating the ALB

### 2.1 Create ALB Security Group

The ALB security group allows inbound HTTP traffic from the internet:

```bash
# Create security group for ALB
aws ec2 create-security-group \
  --group-name RegionalBank-alb-sg \
  --description "Security group for RegionalBank Fraud ALB" \
  --vpc-id <vpc-id> \
  --region ap-southeast-1

# Allow HTTP (port 80) from anywhere
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp \
  --port 80 \
  --cidr 0.0.0.0/0 \
  --region ap-southeast-1

# Allow port 3000 from anywhere (for frontend)
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp \
  --port 3000 \
  --cidr 0.0.0.0/0 \
  --region ap-southeast-1
```

### 2.2 Create Target Groups

Target groups define where traffic is routed:

```bash
# Create target group for API (port 8000)
aws elbv2 create-target-group \
  --name RegionalBank-fraud-tg-8000 \
  --protocol HTTP \
  --port 8000 \
  --vpc-id <vpc-id> \
  --target-type instance \
  --health-check-protocol HTTP \
  --health-check-path /health \
  --health-check-interval-seconds 30 \
  --health-check-timeout-seconds 5 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --region ap-southeast-1

# Create target group for Frontend (port 3000)
aws elbv2 create-target-group \
  --name RegionalBank-fraud-tg-3000 \
  --protocol HTTP \
  --port 3000 \
  --vpc-id <vpc-id> \
  --target-type instance \
  --health-check-protocol HTTP \
  --health-check-path / \
  --health-check-interval-seconds 30 \
  --health-check-timeout-seconds 5 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --region ap-southeast-1
```

### 2.3 Create the Application Load Balancer

```bash
# Create ALB (must span at least 2 AZs)
aws elbv2 create-load-balancer \
  --name RegionalBank-fraud-alb \
  --type application \
  --scheme internet-facing \
  --subnets <subnet-id> <subnet-id> \
  --security-groups <sg-id> \
  --region ap-southeast-1
```

### 2.4 Create Listeners

Listeners check for incoming connections and forward to target groups:

```bash
# Get target group ARNs first
API_TG_ARN=$(aws elbv2 describe-target-groups \
  --names RegionalBank-fraud-tg-8000 \
  --query 'TargetGroups[0].TargetGroupArn' \
  --output text \
  --region ap-southeast-1)

FRONTEND_TG_ARN=$(aws elbv2 describe-target-groups \
  --names RegionalBank-fraud-tg-3000 \
  --query 'TargetGroups[0].TargetGroupArn' \
  --output text \
  --region ap-southeast-1)

ALB_ARN=$(aws elbv2 describe-load-balancers \
  --names RegionalBank-fraud-alb \
  --query 'LoadBalancers[0].LoadBalancerArn' \
  --output text \
  --region ap-southeast-1)

# Create listener for API (port 80 → port 8000)
aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=forward,TargetGroupArn=$API_TG_ARN \
  --region ap-southeast-1

# Create listener for Frontend (port 3000 → port 3000)
aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTP \
  --port 3000 \
  --default-actions Type=forward,TargetGroupArn=$FRONTEND_TG_ARN \
  --region ap-southeast-1
```

### 2.5 Register EC2 Instances as Targets

```bash
# Register EC2 instances with API target group
aws elbv2 register-targets \
  --target-group-arn $API_TG_ARN \
  --targets Id=<instance-id> Id=<instance-id> \
  --region ap-southeast-1

# Register EC2 instances with Frontend target group
aws elbv2 register-targets \
  --target-group-arn $FRONTEND_TG_ARN \
  --targets Id=<instance-id> Id=<instance-id> \
  --region ap-southeast-1
```

---

## Part 3: EC2 Security Group Configuration

EC2 instances must only accept traffic from the ALB:

```bash
# Allow port 8000 from ALB security group only
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp \
  --port 8000 \
  --source-group <sg-id> \
  --region ap-southeast-1

# Allow port 3000 from ALB security group only
aws ec2 authorize-security-group-ingress \
  --group-id <sg-id> \
  --protocol tcp \
  --port 3000 \
  --source-group <sg-id> \
  --region ap-southeast-1
```

### Security Group Summary

| Security Group | Inbound Rules |
|----------------|---------------|
| **ALB SG** (<sg-id>) | 80 from 0.0.0.0/0, 3000 from 0.0.0.0/0 |
| **EC2 SG** (<sg-id>) | 8000 from ALB SG, 3000 from ALB SG, 22 from bastion/your IP |

---

## Part 4: Health Checks

### 4.1 Health Check Configuration

| Setting | API Target Group | Frontend Target Group |
|---------|------------------|----------------------|
| **Protocol** | HTTP | HTTP |
| **Path** | /health | / |
| **Port** | 8000 | 3000 |
| **Interval** | 30 seconds | 30 seconds |
| **Timeout** | 5 seconds | 5 seconds |
| **Healthy threshold** | 2 | 2 |
| **Unhealthy threshold** | 3 | 3 |

### 4.2 Verify Health Status

```bash
# Check API target group health
aws elbv2 describe-target-health \
  --target-group-arn $API_TG_ARN \
  --region ap-southeast-1

# Expected output for healthy targets:
# {
#   "TargetHealthDescriptions": [
#     {
#       "Target": {"Id": "<instance-id>", "Port": 8000},
#       "HealthCheckPort": "8000",
#       "TargetHealth": {"State": "healthy"}
#     },
#     {
#       "Target": {"Id": "<instance-id>", "Port": 8000},
#       "HealthCheckPort": "8000",
#       "TargetHealth": {"State": "healthy"}
#     }
#   ]
# }
```

---

## Part 5: Testing the ALB

### 5.1 Test API Endpoints

```bash
# Health check
curl http://<load-balancer-endpoint>/health

# Score a transaction
curl -X POST http://<load-balancer-endpoint>/score-transaction \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "CUST-001",
    "account_id": "ACC-12345678",
    "amount": 500000,
    "lat": -6.2088,
    "lon": 106.8456,
    "timestamp": "2026-01-07T10:00:00Z",
    "channel": "Livin",
    "merchant_id": "M-1234",
    "merchant_name": "Test Merchant",
    "mcc": "5411",
    "device_id": "DEV-123456",
    "device_type": "ios",
    "ip": "<private-ip>"
  }'

# API docs
curl http://<load-balancer-endpoint>/docs
```

### 5.2 Test Frontend

```bash
# Frontend (port 3000)
curl http://<load-balancer-endpoint>:3000

# Or open in browser
open http://<load-balancer-endpoint>:3000
```

---

## Part 6: Load Balancer Behavior

### 6.1 Load Balancing Algorithm

By default, ALB uses **round robin** algorithm:

| Request | Target |
|---------|--------|
| 1 | EC2 #1 (<private-ip>) |
| 2 | EC2 #2 (<private-ip>) |
| 3 | EC2 #1 |
| 4 | EC2 #2 |
| ... | ... |

### 6.2 Cross-Zone Load Balancing

With cross-zone load balancing enabled (default), requests are distributed evenly across all registered instances regardless of AZ:

```
                           ALB
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
        ┌─────────┐   ┌─────────┐   ┌─────────┐
        │ EC2 #1  │   │ EC2 #2  │   │ EC2 #3  │
        │ AZ 1a   │   │ AZ 1b   │   │ AZ 1a   │
        └─────────┘   └─────────┘   └─────────┘
            33%           33%           34%
```

### 6.3 Connection Draining

When a target is deregistered or fails health checks, ALB allows in-flight requests to complete:

| Setting | Value |
|---------|-------|
| **Deregistration delay** | 300 seconds (default) |

```bash
# Modify deregistration delay
aws elbv2 modify-target-group-attributes \
  --target-group-arn $API_TG_ARN \
  --attributes Key=deregistration_delay.timeout_seconds,Value=60 \
  --region ap-southeast-1
```

---

## Part 7: Monitoring

### 7.1 CloudWatch Metrics

Key ALB metrics to monitor:

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| **RequestCount** | Total requests | N/A (baseline) |
| **TargetResponseTime** | Latency to targets | > 1 second |
| **HTTPCode_Target_5XX_Count** | Server errors | > 10/minute |
| **UnHealthyHostCount** | Unhealthy targets | > 0 |
| **ActiveConnectionCount** | Active connections | > 10,000 |

### 7.2 View Metrics

```bash
# Get ALB metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name RequestCount \
  --dimensions Name=LoadBalancer,Value=app/RegionalBank-fraud-alb/... \
  --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics Sum \
  --region ap-southeast-1
```

### 7.3 Access Logs

Enable access logs for detailed request analysis:

```bash
# Create S3 bucket for logs
aws s3api create-bucket \
  --bucket RegionalBank-fraud-alb-logs \
  --region ap-southeast-1 \
  --create-bucket-configuration LocationConstraint=ap-southeast-1

# Enable access logs
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn $ALB_ARN \
  --attributes \
    Key=access_logs.s3.enabled,Value=true \
    Key=access_logs.s3.bucket,Value=RegionalBank-fraud-alb-logs \
    Key=access_logs.s3.prefix,Value=alb \
  --region ap-southeast-1
```

---

## Troubleshooting

### Issue: 502 Bad Gateway

**Cause:** Target not responding or security group misconfigured.

```bash
# 1. Check target health
aws elbv2 describe-target-health --target-group-arn $API_TG_ARN

# 2. Verify EC2 security group allows ALB
aws ec2 describe-security-groups --group-ids <sg-id>

# 3. Test direct connection from bastion
ssh ec2-user@203.0.113.10
curl http://<private-ip>:8000/health
```

### Issue: 504 Gateway Timeout

**Cause:** Target taking too long to respond.

```bash
# 1. Check target response time
curl -w "@curl-format.txt" -o /dev/null -s \
  http://<load-balancer-endpoint>/health

# 2. Increase idle timeout (default 60s)
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn $ALB_ARN \
  --attributes Key=idle_timeout.timeout_seconds,Value=120 \
  --region ap-southeast-1
```

### Issue: Uneven Load Distribution

**Cause:** One instance handling more requests than another.

```bash
# Check request count per target
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name RequestCountPerTarget \
  --dimensions Name=TargetGroup,Value=targetgroup/RegionalBank-fraud-tg-8000/... \
  --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics Sum
```

---

## Related Documentation

- [EC2-DOCKER-SETUP.md](./EC2-DOCKER-SETUP.md) - EC2 and Docker configuration
- [PRIVATELINK-SETUP.md](./PRIVATELINK-SETUP.md) - MongoDB Atlas PrivateLink
- [LOCUST-SETUP.md](./LOCUST-SETUP.md) - Load testing with Locust
- DEPLOYMENT-RUNBOOK.md - Quick reference commands

---

## Document History

| Date | Author | Changes |
|------|--------|---------|
| 2026-01-07 | Claude + Paul | Initial creation with current resource IDs |
