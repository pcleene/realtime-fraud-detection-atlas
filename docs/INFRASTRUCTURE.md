# AWS Infrastructure Provisioning Guide

This document covers the complete AWS infrastructure for deploying the RegionalBank Fraud Detection API at production scale (10K+ TPS).

## Architecture Overview

```
                              ┌─────────────────────────────────────────────────────────────┐
                              │                        AWS VPC                               │
                              │                     <private-ip>/16                              │
                              │                                                              │
    Internet ─────────────────┤  ┌─────────────────────────────────────────────────────┐    │
                              │  │              Public Subnets (2 AZs)                  │    │
                              │  │           <private-ip>/24  │  <private-ip>/24               │    │
                              │  │                        │                             │    │
                              │  │   ┌────────────────────┴────────────────────┐       │    │
                              │  │   │        Application Load Balancer         │       │    │
                              │  │   │           (internet-facing)              │       │    │
                              │  │   └────────────────────┬────────────────────┘       │    │
                              │  │                        │                             │    │
                              │  │              ┌─────────┴─────────┐                   │    │
                              │  │              │    NAT Gateway    │                   │    │
                              │  └──────────────┴───────────────────┴───────────────────┘    │
                              │                           │                                   │
                              │  ┌────────────────────────┴────────────────────────────┐    │
                              │  │              Private Subnets (2 AZs)                 │    │
                              │  │           <private-ip>/24  │  <private-ip>/24              │    │
                              │  │                         │                            │    │
                              │  │   ┌─────────────┐  ┌────┴──────┐  ┌─────────────┐   │    │
                              │  │   │   EC2-1     │  │   EC2-2   │  │   EC2-N     │   │    │
                              │  │   │ c6i.2xlarge │  │c6i.2xlarge│  │ c6i.2xlarge │   │    │
                              │  │   │ 16 workers  │  │ 16 workers│  │ 16 workers  │   │    │
                              │  │   └──────┬──────┘  └─────┬─────┘  └──────┬──────┘   │    │
                              │  │          │               │               │          │    │
                              │  │          └───────────────┼───────────────┘          │    │
                              │  │                          │                          │    │
                              │  │               ┌──────────┴──────────┐               │    │
                              │  │               │    VPC Endpoint     │               │    │
                              │  │               │    (PrivateLink)    │               │    │
                              │  └───────────────┴─────────────────────┴───────────────┘    │
                              │                           │                                   │
                              └───────────────────────────┼───────────────────────────────────┘
                                                          │
                                            ┌─────────────┴─────────────┐
                                            │     MongoDB Atlas         │
                                            │   (M10+ / 3 shards)       │
                                            │     PrivateLink           │
                                            └───────────────────────────┘
```

## Components

### 1. VPC and Networking

| Component | CIDR / Details |
|-----------|----------------|
| VPC | <private-ip>/16 |
| Public Subnet AZ-a | <private-ip>/24 |
| Public Subnet AZ-b | <private-ip>/24 |
| Private Subnet AZ-a | <private-ip>/24 |
| Private Subnet AZ-b | <private-ip>/24 |
| NAT Gateway | 1x in public subnet (egress for private) |

**Why 2 AZs?** High availability - if one AZ fails, traffic routes to the other.

### 2. Application Load Balancer (ALB)

- **Type:** Internet-facing, application layer (Layer 7)
- **Health Check:** `GET /api/health` every 30s
- **Listeners:** HTTP:80 → Target Group
- **Target Group:** EC2 instances on port 8000

**Why ALB over nginx?**
- Native AWS integration (auto-scaling, CloudWatch)
- No additional EC2 instances to manage
- Built-in health checks and connection draining
- Pay per use, scales automatically

### 3. EC2 Auto Scaling Group

| Setting | Value |
|---------|-------|
| Instance Type | c6i.2xlarge (8 vCPU, 16GB RAM) |
| AMI | Amazon Linux 2023 |
| Min Instances | 2 |
| Max Instances | 6 |
| Desired | 2 |
| Scale Up | CPU > 70% for 2 minutes |
| Scale Down | CPU < 30% for 2 minutes |

**Why c6i.2xlarge?**
- Compute-optimized (Intel Ice Lake)
- 8 vCPU = 16 Gunicorn workers (2x vCPU)
- Each instance handles ~6-8K TPS
- 2 instances = 12-16K TPS capacity

### 4. MongoDB Atlas PrivateLink

PrivateLink provides private connectivity between AWS VPC and MongoDB Atlas:

- **No public internet:** Traffic stays on AWS backbone
- **Lower latency:** ~1-2ms vs ~5-10ms over public internet
- **Better security:** No public IP exposure for MongoDB

**Components:**
- AWS VPC Endpoint (Interface type)
- Atlas PrivateLink Endpoint
- Route53 Private Hosted Zone (DNS resolution)

### 5. Security Groups

| Security Group | Inbound | Outbound |
|----------------|---------|----------|
| ALB | 80 from 0.0.0.0/0 | All to VPC |
| API (EC2) | 8000 from ALB SG | 443 to MongoDB Endpoint |
| MongoDB Endpoint | 27017 from API SG | N/A |

## Prerequisites

1. **AWS CLI** configured with credentials
2. **Terraform** >= 1.0
3. **MongoDB Atlas** M10+ cluster with:
   - API Key (Organization Access Manager)
   - Project ID
   - Connection string
4. **EC2 Key Pair** for SSH access (optional)

## Deployment Steps

### Step 1: Configure Variables

```bash
cd terraform
cp prod.tfvars.example prod.tfvars
```

Edit `prod.tfvars`:

```hcl
# AWS
aws_region = "ap-southeast-1"  # Singapore

# MongoDB Atlas (from Atlas Console > Access Manager > API Keys)
mongodb_atlas_public_key  = "xxxxxxxx"
mongodb_atlas_private_key = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
mongodb_atlas_project_id  = "xxxxxxxxxxxxxxxxxxxxxxxx"
mongodb_connection_string = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"

# EC2
instance_type            = "c6i.2xlarge"
api_instance_count       = 2
api_workers_per_instance = 16
key_pair_name            = "your-key-pair"

# Auto Scaling
min_instances            = 2
max_instances            = 6
scale_up_cpu_threshold   = 70
scale_down_cpu_threshold = 30
```

### Step 2: Initialize Terraform

```bash
make tf-init
# or
cd terraform && terraform init
```

### Step 3: Preview Changes

```bash
make tf-plan
```

Review the plan output. Expect ~25-30 resources to be created.

### Step 4: Deploy

```bash
make tf-apply
```

Deployment takes ~5-10 minutes. Resources created:
- VPC, subnets, route tables, NAT gateway
- ALB, target group, listeners
- Launch template, auto scaling group
- CloudWatch alarms, log groups
- PrivateLink endpoint (if Atlas configured)
- IAM roles and instance profile

### Step 5: Verify Deployment

```bash
# Get outputs
make tf-output

# Health check
curl http://<alb-dns-name>/api/health

# Check instances
make tf-status
```

## Scaling

### Manual Scaling

```bash
# Scale to 4 instances
make tf-scale N=4

# Check status
make tf-status
```

### Auto Scaling Behavior

The ASG automatically scales based on CPU:

| Condition | Action |
|-----------|--------|
| CPU > 70% for 2 min | Add 1 instance |
| CPU < 30% for 2 min | Remove 1 instance |

Modify thresholds in `prod.tfvars`:
```hcl
scale_up_cpu_threshold   = 60  # More aggressive
scale_down_cpu_threshold = 40
```

### Capacity Planning

| Instance Count | Est. TPS | Workers |
|----------------|----------|---------|
| 2 × c6i.2xlarge | 12-16K | 32 |
| 3 × c6i.2xlarge | 18-24K | 48 |
| 4 × c6i.2xlarge | 24-32K | 64 |

## Load Testing

The load testing system is built into the API and triggered from the UI. It makes real HTTP calls to `/score-transaction`, testing the complete stack including HTTP overhead, serialization, and (when deployed) ALB routing across multiple instances.

See [LOAD-TESTING.md](./LOAD-TESTING.md) for complete documentation on how the load testing system works.

## Monitoring

### CloudWatch Logs

```bash
# Tail API logs
aws logs tail /RegionalBank-fraud/api --follow

# Filter errors
aws logs filter-log-events \
    --log-group-name /RegionalBank-fraud/api \
    --filter-pattern "ERROR"
```

### Key Metrics

| Metric | Namespace | Description |
|--------|-----------|-------------|
| RequestCount | AWS/ApplicationELB | Requests per minute |
| TargetResponseTime | AWS/ApplicationELB | P50/P99 latency |
| CPUUtilization | AWS/EC2 | Instance CPU % |
| UnHealthyHostCount | AWS/ApplicationELB | Failed health checks |

### Dashboards

Create a CloudWatch dashboard with:
- ALB request count and latency
- Target group healthy/unhealthy hosts
- EC2 CPU across all instances
- ASG desired vs actual capacity

## Troubleshooting

### Instances Not Becoming Healthy

```bash
# SSH to instance (if key pair configured)
aws ssm start-session --target <instance-id>

# Check user-data log
sudo cat /var/log/user-data.log

# Check Docker
sudo docker ps
sudo docker logs <container-id>
```

Common issues:
- MongoDB connection string incorrect
- Security group blocking traffic
- Docker image build failed

### High Latency

1. Check MongoDB Atlas metrics (Collections > Performance Advisor)
2. Verify PrivateLink is active (not falling back to public)
3. Check EC2 CPU - scale up if > 70%
4. Review slow queries in CloudWatch Logs

### Connection Errors

1. Verify security groups allow traffic:
   - ALB → EC2:8000
   - EC2 → MongoDB Endpoint:27017
2. Check MongoDB Atlas network access (PrivateLink should bypass IP whitelist)
3. Validate connection string format

## Cost Estimate

| Component | Monthly Cost (est.) |
|-----------|---------------------|
| 2× c6i.2xlarge EC2 | $500 |
| Application Load Balancer | $20 + $0.008/LCU-hour |
| NAT Gateway | $35 + $0.045/GB |
| PrivateLink Endpoint | $10 + $0.01/GB |
| CloudWatch Logs | $0.50/GB ingested |
| **Total (baseline)** | **~$600/month** |

**Cost Optimization:**
- Use Spot Instances for load testing (60-70% savings)
- Scale down after hours if not 24/7
- Use Reserved Instances for production (30-40% savings)

## Teardown

### Standard Teardown

```bash
make tf-destroy
```

### Complete Teardown with Verification

```bash
make tf-teardown
```

This will:
1. Prompt for confirmation (type `DESTROY`)
2. Run `terraform destroy`
3. Verify all resources are deleted:
   - EC2 instances
   - Load balancers
   - VPC endpoints
   - NAT gateways
   - VPC

### Verify Teardown Manually

```bash
make tf-verify-teardown
```

Checks for remaining resources tagged with `RegionalBank-fraud`.

## Terraform Files Reference

```
terraform/
├── main.tf              # VPC, ALB, EC2, ASG, CloudWatch
├── privatelink.tf       # MongoDB Atlas PrivateLink setup
├── variables.tf         # All input variables with defaults
├── outputs.tf           # API URL, VPC IDs, connection info
├── user_data.sh         # EC2 bootstrap script (Docker, tuning)
└── prod.tfvars.example  # Example configuration
```

### Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `aws_region` | ap-southeast-1 | AWS region |
| `instance_type` | c6i.2xlarge | EC2 instance type |
| `api_instance_count` | 2 | Initial instance count |
| `api_workers_per_instance` | 16 | Gunicorn workers per instance |
| `min_instances` | 2 | ASG minimum |
| `max_instances` | 6 | ASG maximum |
| `scale_up_cpu_threshold` | 70 | CPU % to trigger scale up |
| `scale_down_cpu_threshold` | 30 | CPU % to trigger scale down |

## Next Steps

After deployment:

1. **Run load tests** to validate performance
2. **Set up alerts** for high latency or errors
3. **Configure HTTPS** with ACM certificate (add HTTPS listener)
4. **Add WAF** for DDoS protection (optional)
5. **Enable access logs** to S3 for compliance
