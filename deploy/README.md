# AWS Deployment Guide

## Architecture

```
                         ┌─────────────────┐
                         │    Internet     │
                         └────────┬────────┘
                                  │
                         ┌────────┴────────┐
                         │    AWS ALB      │
                         │  (managed LB)   │
                         └────────┬────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
        ┌─────┴─────┐       ┌─────┴─────┐       ┌─────┴─────┐
        │   EC2-1   │       │   EC2-2   │       │   EC2-N   │
        │c6i.2xlarge│       │c6i.2xlarge│       │c6i.2xlarge│
        │ 16 workers│       │ 16 workers│       │ 16 workers│
        └─────┬─────┘       └─────┬─────┘       └─────┬─────┘
              │                   │                   │
              └───────────────────┴───────────────────┘
                                  │
                         ┌────────┴────────┐
                         │  VPC Endpoint   │
                         │  (PrivateLink)  │
                         └────────┬────────┘
                                  │
                         ┌────────┴────────┐
                         │ MongoDB Atlas   │
                         │  (3 shards)     │
                         └─────────────────┘
```

## Prerequisites

1. **AWS CLI** configured with appropriate credentials
2. **Terraform** >= 1.0 installed
3. **MongoDB Atlas** cluster (M10+) with API keys
4. **EC2 Key Pair** for SSH access

## Quick Start

### 1. Configure Variables

```bash
cd terraform
cp prod.tfvars.example prod.tfvars
```

Edit `prod.tfvars` with your values:

```hcl
# MongoDB Atlas (get from Atlas > Access Manager > API Keys)
mongodb_atlas_public_key  = "your-public-key"
mongodb_atlas_private_key = "your-private-key"
mongodb_atlas_project_id  = "your-project-id"
mongodb_connection_string = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"

# EC2
key_pair_name = "your-key-pair"
```

### 2. Deploy

```bash
# Initialize Terraform
make tf-init

# Preview changes
make tf-plan

# Deploy (takes ~5-10 minutes)
make tf-apply
```

### 3. Get API URL

```bash
make tf-output
```

Output will show:
```
api_url = "http://<load-balancer-endpoint>"
```

### 4. Test

```bash
# Health check
curl http://<alb-url>/api/health

# Run load test
python backend/scripts/loadtest_distributed.py \
    --url http://<alb-url> \
    --tps 5000 \
    --duration 60
```

## Scaling

### Manual Scaling

```bash
# Scale to 4 instances
make tf-scale N=4

# Check status
make tf-status
```

### Auto Scaling

Auto scaling is configured by default:
- **Scale up**: When CPU > 70% for 2 minutes
- **Scale down**: When CPU < 30% for 2 minutes
- **Min instances**: 2
- **Max instances**: 6

Modify in `terraform/variables.tf` or `prod.tfvars`:
```hcl
min_instances            = 2
max_instances            = 10
scale_up_cpu_threshold   = 70
scale_down_cpu_threshold = 30
```

## Instance Sizing Guide

| Instance | vCPU | RAM | Workers | Est. TPS | Monthly Cost |
|----------|------|-----|---------|----------|--------------|
| c6i.xlarge | 4 | 8GB | 8 | 3-4K | ~$125 |
| c6i.2xlarge | 8 | 16GB | 16 | 6-8K | ~$250 |
| c6i.4xlarge | 16 | 32GB | 32 | 12-15K | ~$500 |

**For 10K TPS target**: 2× c6i.2xlarge or 1× c6i.4xlarge

## MongoDB Atlas PrivateLink

PrivateLink provides:
- Private connectivity (no public internet)
- Lower latency (~1-2ms vs ~5-10ms)
- Better security

### Setup Steps (handled by Terraform)

1. Creates VPC Endpoint in AWS
2. Creates PrivateLink endpoint in Atlas
3. Connects them together
4. Sets up Route53 for DNS resolution

### Verify PrivateLink

```bash
# Check endpoint status
aws ec2 describe-vpc-endpoints \
    --filters "Name=tag:Name,Values=RegionalBank-fraud-mongodb-endpoint" \
    --query 'VpcEndpoints[*].[VpcEndpointId,State]'
```

Should show `available` state.

## Cost Estimate

| Component | Monthly Cost (est.) |
|-----------|---------------------|
| 2× c6i.2xlarge EC2 | $500 |
| ALB | $20 + data |
| NAT Gateway | $35 + data |
| PrivateLink | $10 + data |
| **Total** | **~$600/month** |

For load testing only, use spot instances to reduce cost by 60-70%.

## Monitoring

### CloudWatch Logs

```bash
# View API logs
aws logs tail /RegionalBank-fraud/api --follow

# Filter errors
aws logs filter-log-events \
    --log-group-name /RegionalBank-fraud/api \
    --filter-pattern "ERROR"
```

### CloudWatch Metrics

Key metrics to watch:
- `AWS/ApplicationELB/RequestCount`
- `AWS/ApplicationELB/TargetResponseTime`
- `AWS/EC2/CPUUtilization`

### Health Check

```bash
# ALB health
curl http://<alb-url>/api/health

# Check target health
aws elbv2 describe-target-health \
    --target-group-arn <target-group-arn>
```

## Troubleshooting

### Instances Not Healthy

```bash
# Check instance logs
aws ssm start-session --target <instance-id>
# Then: sudo cat /var/log/user-data.log
```

### High Latency

1. Check MongoDB Atlas metrics
2. Verify PrivateLink is working (not falling back to public)
3. Check EC2 CPU utilization

### Connection Errors

1. Verify security groups allow traffic
2. Check MongoDB Atlas IP whitelist (not needed with PrivateLink)
3. Verify MongoDB connection string

## Cleanup

```bash
# Destroy all infrastructure
make tf-destroy
```

⚠️ This will delete all resources including ALB, EC2 instances, and VPC endpoints.

## Files

```
terraform/
├── main.tf              # VPC, ALB, EC2, ASG
├── privatelink.tf       # MongoDB Atlas PrivateLink
├── variables.tf         # Input variables
├── outputs.tf           # Output values
├── user_data.sh         # EC2 bootstrap script
└── prod.tfvars.example  # Example configuration
```
