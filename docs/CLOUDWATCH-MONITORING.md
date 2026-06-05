# CloudWatch Monitoring Guide

This document covers the CloudWatch monitoring setup for the RegionalBank Fraud Detection POC, including dashboards, alarms, and observability best practices.

## Overview

The monitoring infrastructure provides:
- **Dashboard**: Single-pane view of system health and performance
- **Alarms**: Proactive alerting for latency spikes, errors, and capacity issues
- **Log Groups**: Centralized application logs

## Quick Access

After deploying with Terraform, access the dashboard:

```bash
# Get dashboard URL
terraform output cloudwatch_dashboard_url

# Or navigate directly:
# https://ap-southeast-1.console.aws.amazon.com/cloudwatch/home?region=ap-southeast-1#dashboards:name=Regional Bank-fraud-dashboard
```

## Dashboard Layout

The dashboard is organized into sections:

### Row 1: Request Metrics
| Widget | Metric | Purpose |
|--------|--------|---------|
| **Request Count** | RequestCount/min | Monitor throughput (target: 600k/min = 10k TPS) |
| **Response Time** | TargetResponseTime Avg/P95/P99 | Latency monitoring (target: <50ms P99) |
| **HTTP Codes** | 2XX/4XX/5XX counts | Error rate tracking |

### Row 2: EC2 Performance
| Widget | Metric | Purpose |
|--------|--------|---------|
| **CPU Utilization** | CPUUtilization Avg/Max | Instance load (scale trigger at 70%) |
| **Network I/O** | NetworkIn/NetworkOut | Bandwidth utilization |

### Row 3: Infrastructure Health
| Widget | Metric | Purpose |
|--------|--------|---------|
| **Target Health** | HealthyHostCount | ALB target availability |
| **Connections** | ActiveConnectionCount | Connection pool monitoring |
| **Request Distribution** | RequestCountPerTarget | Load balancing verification |

### Row 4: Auto Scaling
| Widget | Metric | Purpose |
|--------|--------|---------|
| **ASG Status** | GroupDesiredCapacity | Current instance count |
| **Data Processed** | ProcessedBytes | Traffic volume |

## CloudWatch Alarms

### Critical Alarms (Require Action)

| Alarm | Threshold | Description |
|-------|-----------|-------------|
| `RegionalBank-fraud-alb-high-latency-p99` | P99 > 100ms for 3 min | Latency degradation |
| `RegionalBank-fraud-alb-high-latency-avg` | Avg > 50ms for 2 min | Sustained latency issues |
| `RegionalBank-fraud-alb-5xx-errors` | >100 errors/min | Server errors |
| `RegionalBank-fraud-alb-unhealthy-hosts` | Any unhealthy target | Instance health issues |
| `RegionalBank-fraud-ec2-high-memory` | >85% for 3 min | Memory pressure |

### Informational Alarms

| Alarm | Threshold | Description |
|-------|-----------|-------------|
| `RegionalBank-fraud-high-throughput` | >500k req/min | High TPS achieved (8.3k+ TPS) |

### Existing Auto-Scaling Alarms

| Alarm | Threshold | Action |
|-------|-----------|--------|
| `RegionalBank-fraud-high-cpu` | >70% for 2 min | Scale up (+1 instance) |
| `RegionalBank-fraud-low-cpu` | <30% for 2 min | Scale down (-1 instance) |

## Setting Up Email Alerts

To receive email notifications for alarms:

```hcl
# Uncomment in terraform/cloudwatch.tf:
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "your-email@example.com"
}
```

Then apply:
```bash
terraform apply -var-file="prod.tfvars"
# Confirm the email subscription when you receive the verification email
```

## Viewing Metrics via AWS CLI

```bash
# Get current request count (last 5 minutes)
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name RequestCount \
  --dimensions Name=LoadBalancer,Value=app/RegionalBank-fraud-alb/... \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Sum \
  --region ap-southeast-1

# Get P99 latency
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name TargetResponseTime \
  --dimensions Name=LoadBalancer,Value=app/RegionalBank-fraud-alb/... \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --extended-statistics p99 \
  --region ap-southeast-1

# List all alarms and their states
aws cloudwatch describe-alarms \
  --alarm-name-prefix RegionalBank-fraud \
  --query 'MetricAlarms[*].[AlarmName,StateValue]' \
  --output table \
  --region ap-southeast-1
```

## Memory Metrics (CloudWatch Agent)

The EC2 instances have CloudWatch Agent policy attached. To enable memory metrics:

1. SSH to each EC2 instance
2. Install and configure CloudWatch Agent:

```bash
# Install agent
sudo yum install -y amazon-cloudwatch-agent

# Create config
sudo tee /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << 'EOF'
{
  "agent": {
    "metrics_collection_interval": 60,
    "run_as_user": "root"
  },
  "metrics": {
    "namespace": "CWAgent",
    "append_dimensions": {
      "AutoScalingGroupName": "${aws:AutoScalingGroupName}",
      "InstanceId": "${aws:InstanceId}"
    },
    "metrics_collected": {
      "mem": {
        "measurement": ["mem_used_percent"],
        "metrics_collection_interval": 60
      },
      "disk": {
        "measurement": ["disk_used_percent"],
        "resources": ["/"],
        "metrics_collection_interval": 60
      }
    }
  }
}
EOF

# Start agent
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json \
  -s
```

## Performance Targets

| Metric | Target | Alarm Threshold |
|--------|--------|-----------------|
| **TPS** | 10,000 | - (informational at 8.3k) |
| **P99 Latency** | <50ms | 100ms |
| **Avg Latency** | <30ms | 50ms |
| **Error Rate** | <0.1% | 100 errors/min |
| **CPU** | <70% | 70% (auto-scale) |
| **Memory** | <85% | 85% |

## Troubleshooting

### Latency Spike

1. Check EC2 CPU utilization
2. Check MongoDB Atlas metrics (Performance Advisor)
3. Verify target group health
4. Check for 5XX errors

```bash
# Quick health check
curl -s http://ALB-DNS/api/health | jq .
```

### High Error Rate

1. Check application logs:
```bash
aws logs tail /RegionalBank-fraud/api --since 5m --region ap-southeast-1
```

2. Check unhealthy targets:
```bash
aws elbv2 describe-target-health \
  --target-group-arn arn:aws:elasticloadbalancing:ap-southeast-1:...:targetgroup/RegionalBank-fraud-api-tg/... \
  --region ap-southeast-1
```

### Dashboard Not Updating

- Metrics have 1-minute granularity
- Dashboard auto-refreshes every 60 seconds
- For real-time during load tests, use the Svelte UI

## Related Documentation

- [LOAD-TESTING.md](./LOAD-TESTING.md) - Load testing guide
- [INFRASTRUCTURE.md](./INFRASTRUCTURE.md) - AWS architecture
- DEPLOYMENT-RUNBOOK.md - Deployment commands
