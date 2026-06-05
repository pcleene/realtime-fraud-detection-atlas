---
name: ec2-container-workers
description: Deploy containerized Python applications on EC2 with optimized multi-worker configuration. Includes Docker troubleshooting, disk management, SSM deployment, and recovery procedures. Use this skill when deploying Docker containers to EC2 instances, troubleshooting container issues, setting up Auto Scaling Groups, configuring resource limits, or recovering from EC2/Docker failures.
---

# EC2 Container Deployment with Multi-Workers

Deploy Docker containers on EC2 with Gunicorn multi-worker setup for production workloads.

## Critical Issues We've Encountered

These are real production issues that caused significant debugging time:

### Issue 1: Root Disk 100% Full (CRITICAL)

**Symptom:** Docker won't start, `docker.service failed`

**Diagnosis:**
```bash
df -h /
# Shows: /dev/nvme0n1p1  8.0G  8.0G   20K 100% /
```

**Root Cause:** Default 8GB EBS volumes fill up quickly with Docker images.

**Fix - Resize EBS volumes:**
```bash
# Get volume IDs
aws ec2 describe-volumes --filters "Name=attachment.instance-id,Values=i-xxxxx" \
  --query 'Volumes[*].VolumeId' --output text

# Resize to 50GB
aws ec2 modify-volume --volume-id vol-xxxxx --size 50

# SSH to instance and extend filesystem
sudo growpart /dev/nvme0n1 1
sudo xfs_growfs /
```

**Prevention:** ALWAYS use 50GB+ disk for Docker deployments.

### Issue 2: SSM Agent Not Responding After Crash

**Symptom:** SSM commands return "Undeliverable", instance shows as "running"

**Root Cause:** Instance in bad state (running but kernel/services unresponsive)

**Fix - Stop/Start (NOT reboot):**
```bash
# Reboot does NOT fix this - you must stop/start
aws ec2 stop-instances --instance-ids i-xxxxx
aws ec2 wait instance-stopped --instance-ids i-xxxxx
aws ec2 start-instances --instance-ids i-xxxxx
```

### Issue 3: Containerd Not Responding

**Symptom:** Docker commands hang or timeout, containerd socket errors

**Cause:** Corrupted state after disk full or crash

**Fix:**
```bash
sudo rm -rf /var/lib/docker/tmp-old
sudo systemctl restart containerd
sleep 3
sudo systemctl restart docker
```

### Issue 4: LOG_LEVEL=info Returns Function Object

**Symptom:** `TypeError: Level not an integer or a valid string: <function info at 0x...>`

**Root Cause:** Python's logging module: `logging.info` (lowercase) is a function, `logging.INFO` (uppercase) is the constant.

**Fix:** Always use uppercase:
```bash
LOG_LEVEL=INFO  # Correct
LOG_LEVEL=info  # WRONG - returns function
```

### Issue 5: Docker Compose Not Reading .env File

**Symptom:** Environment variables not being loaded

**Root Cause:** `.env` must be in project root with `docker-compose.yml`, not in subdirectory.

**Fix:**
```
~/project/.env              # Correct - same dir as docker-compose.yml
~/project/backend/.env      # Wrong - subdirectory
```

### Issue 6: ModuleNotFoundError for Data Files

**Symptom:** `ModuleNotFoundError: No module named 'seed.data'`

**Root Cause:** Folder was in `.gitignore`

**Fix:**
```bash
git add -f backend/seed/data/
git commit -m "Add seed data folder"
git push
```

## SSM Deployment Commands

### Common SSM Issues

| Error | Cause | Fix |
|-------|-------|-----|
| "Directory not found" | SSM runs as root, `~` = `/root` | Use absolute paths |
| "Dubious ownership" git error | Root accessing another user's repo | `git config --global --add safe.directory /path` |
| "$HOME not set" | SSM doesn't set HOME | `export HOME=/root` |
| "docker-compose: command not found" | Docker Compose V2 uses space | Use `docker compose` (space) |
| GitHub SSH auth failed | Root has no SSH keys | Use HTTPS with PAT |

### Deploy to EC2 via SSM

```bash
aws ssm send-command \
  --instance-ids "i-xxxxx" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "export HOME=/root",
    "git config --global --add safe.directory /home/ssm-user/myapp",
    "cd /home/ssm-user/myapp",
    "git remote set-url origin https://YOUR_PAT@github.com/org/repo.git",
    "git pull",
    "docker compose build api",
    "docker compose up -d api"
  ]' \
  --region ap-southeast-1
```

### Check Command Result

```bash
aws ssm get-command-invocation \
  --command-id "<command-id>" \
  --instance-id "i-xxxxx" \
  --region ap-southeast-1 \
  --query 'StandardOutputContent' --output text
```

## Dockerfile for Production

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

COPY . .

# Create non-root user
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Environment variables - USE UPPERCASE for LOG_LEVEL
ENV WORKERS=4
ENV WORKER_CONNECTIONS=1000
ENV TIMEOUT=120
ENV LOG_LEVEL=INFO

# Health check for ALB integration
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
```

## docker-compose.yml with Resource Limits

```yaml
version: '3.8'

services:
  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    dns:
      - <private-ip>    # VPC DNS for Route 53 Private Zones
    environment:
      - MONGODB_URI=${MONGODB_URI}
      - DB_NAME=${DB_NAME:-mydb}
      - WORKERS=${WORKERS:-17}
      - WORKER_CONNECTIONS=${WORKER_CONNECTIONS:-1000}
      - TIMEOUT=${TIMEOUT:-120}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}  # UPPERCASE!
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        limits:
          cpus: '7'        # Leave 1 CPU for system
          memory: 14G      # Leave 2GB for system
        reservations:
          cpus: '4'
          memory: 8G
```

## Disk Space Management

### Check Disk Usage

```bash
df -h /
du -sh /var/lib/docker/*
```

### Prune Docker Data

```bash
# Safe cleanup
docker system prune -f

# Aggressive cleanup (removes unused images)
docker system prune -a -f
```

### Truncate Container Logs (Without Restart)

```bash
# Empties logs while containers keep running
sudo sh -c 'truncate -s 0 /var/lib/docker/containers/*/*-json.log'
```

### Configure Log Rotation (Production)

```bash
# /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  }
}
# Requires Docker restart
```

## Auto Scaling Group Configuration

```hcl
resource "aws_autoscaling_group" "api" {
  name                = "${var.project_name}-api-asg"
  vpc_zone_identifier = aws_subnet.private[*].id
  target_group_arns   = [aws_lb_target_group.api.arn]
  health_check_type   = "ELB"

  min_size         = var.min_instances
  max_size         = var.max_instances
  desired_capacity = var.desired_instances

  launch_template {
    id      = aws_launch_template.api.id
    version = "$Latest"
  }

  # Rolling updates without downtime
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
    }
  }
}

# Scale up on high CPU
resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "${var.project_name}-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Average"
  threshold           = 70
  alarm_actions       = [aws_autoscaling_policy.scale_up.arn]

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.api.name
  }
}
```

## EC2 Launch Template

```hcl
resource "aws_launch_template" "api" {
  name_prefix   = "${var.project_name}-api-"
  image_id      = data.aws_ami.amazon_linux_2023.id
  instance_type = var.instance_type

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 50  # ALWAYS 50GB+ for Docker
      volume_type           = "gp3"
      iops                  = 3000
      throughput            = 125
      delete_on_termination = true
      encrypted             = true
    }
  }

  monitoring {
    enabled = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"  # IMDSv2
    http_put_response_hop_limit = 1
  }
}
```

## Instance Type Recommendations

| Throughput Target | Instance Type | vCPUs | Memory | Workers | Disk |
|-------------------|---------------|-------|--------|---------|------|
| 1K TPS            | c6i.xlarge    | 4     | 8GB    | 9       | 50GB |
| 5K TPS            | c6i.2xlarge   | 8     | 16GB   | 17      | 50GB |
| 10K TPS           | c6i.2xlarge ×2| 16    | 32GB   | 34      | 50GB |
| 20K TPS           | c6i.16xlarge  | 64    | 128GB  | 129     | 100GB |

## Recovery Procedures

### Instance Unresponsive (SSM "Undeliverable")

```bash
# Stop/Start - NOT reboot
aws ec2 stop-instances --instance-ids i-xxxxx
aws ec2 wait instance-stopped --instance-ids i-xxxxx
aws ec2 start-instances --instance-ids i-xxxxx
aws ec2 wait instance-running --instance-ids i-xxxxx
```

### Docker Won't Start After Crash

```bash
# Check disk
df -h /

# If disk full, resize EBS (see Issue 1)

# Clear corrupted state
sudo rm -rf /var/lib/docker/tmp-old
sudo systemctl restart containerd
sleep 3
sudo systemctl restart docker
```

### Fresh Container Restart (Improves Performance)

Under sustained high load, periodic restarts help:
```bash
sudo systemctl restart docker
# Wait 30s for containers to stabilize before load testing
```

**Why:** Clears memory fragmentation, connection pool issues, Docker overlay state.

## Key Lessons Learned

1. **ALWAYS use 50GB+ disk** - 8GB fills up quickly with Docker
2. **Stop/Start, not reboot** - Reboot doesn't fix hung instances
3. **LOG_LEVEL=INFO (uppercase)** - lowercase returns function object
4. **Place .env in project root** - Must be with docker-compose.yml
5. **Use absolute paths in SSM** - SSM runs as root, ~ = /root
6. **Docker Compose V2 uses space** - `docker compose`, not `docker-compose`
7. **Fresh containers = better performance** - Restart Docker periodically under high load
8. **Add `dns: <private-ip>`** - Required for Route 53 Private Zone resolution
9. **Leave 1 CPU for system** - Don't allocate all CPUs to containers
10. **After any crash, clear Docker state** - rm tmp-old, restart containerd
