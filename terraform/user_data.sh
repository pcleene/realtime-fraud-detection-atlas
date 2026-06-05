#!/bin/bash
# =============================================================================
# EC2 User Data Script - RegionalBank Fraud Detection API
# =============================================================================
# This script runs on first boot to configure the instance and start the API.
# Variables are injected by Terraform templatefile().
# =============================================================================

set -ex

# Log everything
exec > >(tee /var/log/user-data.log) 2>&1
echo "Starting user data script at $(date)"

# =============================================================================
# System Setup
# =============================================================================

# Update system
dnf update -y

# Install Docker
dnf install -y docker git

# Start and enable Docker
systemctl start docker
systemctl enable docker

# Add ec2-user to docker group
usermod -aG docker ec2-user

# =============================================================================
# System Tuning for High Performance
# =============================================================================

# Increase file descriptor limits
cat > /etc/security/limits.d/99-fraud-api.conf <<EOF
* soft nofile 65535
* hard nofile 65535
* soft nproc 65535
* hard nproc 65535
EOF

# Kernel tuning for high network throughput
cat > /etc/sysctl.d/99-fraud-api.conf <<EOF
# Network performance
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_fin_timeout = 10
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535

# TCP keepalive
net.ipv4.tcp_keepalive_time = 60
net.ipv4.tcp_keepalive_intvl = 10
net.ipv4.tcp_keepalive_probes = 6

# Memory
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# File handles
fs.file-max = 2097152
EOF

sysctl -p /etc/sysctl.d/99-fraud-api.conf

# =============================================================================
# Application Setup
# =============================================================================

# Create application directory
mkdir -p /opt/fraud-api
cd /opt/fraud-api

# Create environment file
cat > /opt/fraud-api/.env <<EOF
MONGODB_URI=${mongodb_uri}
DB_NAME=RegionalBank_fraud
LOG_LEVEL=warning
WORKERS=${workers}
WORKER_CONNECTIONS=1000
TIMEOUT=120
LOCUST_HOST=${locust_host}
LOCUST_PORT=8089
%{ if enable_v2 ~}
DB_NAME_V2=RegionalBank_fraud_v2
DOCKER_TAG_V2=${docker_image_tag_v2}
BIND_PORT_V2=${api_port_v2}
%{ endif ~}
EOF

chmod 600 /opt/fraud-api/.env

# Create docker-compose.yml
cat > /opt/fraud-api/docker-compose.yml <<EOF
version: '3.8'

services:
  api:
    image: ghcr.io/your-org/RegionalBank-fraud-api:${docker_image_tag}
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: always
    ulimits:
      nofile:
        soft: 65535
        hard: 65535
    logging:
      driver: awslogs
      options:
        awslogs-region: ${aws_region}
        awslogs-group: /RegionalBank-fraud/api
        awslogs-stream-prefix: api
    deploy:
      resources:
        limits:
%{ if enable_v2 ~}
          cpus: '28'
          memory: 50G
%{ else ~}
          cpus: '60'
          memory: 120G
%{ endif ~}
%{ if enable_v2 ~}

  api-v2:
    image: ghcr.io/your-org/RegionalBank-fraud-api-v2:${docker_image_tag_v2}
    ports:
      - "${api_port_v2}:${api_port_v2}"
    env_file:
      - .env
    environment:
      - DB_NAME=RegionalBank_fraud_v2
      - BIND_PORT=${api_port_v2}
    restart: unless-stopped
    ulimits:
      nofile:
        soft: 65535
        hard: 65535
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:${api_port_v2}/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    logging:
      driver: awslogs
      options:
        awslogs-region: ${aws_region}
        awslogs-group: /RegionalBank-fraud/api-v2
        awslogs-stream-prefix: api-v2
    deploy:
      resources:
        limits:
          cpus: '28'
          memory: 65G
%{ endif ~}
EOF

# =============================================================================
# CloudWatch Logs Setup
# =============================================================================

# Create CloudWatch log group (if not exists)
aws logs create-log-group --log-group-name /RegionalBank-fraud/api --region ${aws_region} || true
%{ if enable_v2 ~}
aws logs create-log-group --log-group-name /RegionalBank-fraud/api-v2 --region ${aws_region} || true
%{ endif ~}

# =============================================================================
# Build and Run (if no pre-built image)
# =============================================================================

# For now, clone and build locally (replace with ECR pull in production)
# This is a fallback - ideally you push to ECR and pull here

# Check if image exists, otherwise build from source
if ! docker pull ghcr.io/your-org/RegionalBank-fraud-api:${docker_image_tag} 2>/dev/null; then
    echo "Pre-built image not found, building from source..."

    # Clone repository (replace with your repo)
    cd /tmp
    git clone https://github.com/your-org/RegionalBank_fraud_detection.git
    cd RegionalBank_fraud_detection/backend

    # Build Docker image
    docker build -t RegionalBank-fraud-api:latest .

    # Update docker-compose to use local image
    sed -i 's|ghcr.io/your-org/RegionalBank-fraud-api:${docker_image_tag}|RegionalBank-fraud-api:latest|' /opt/fraud-api/docker-compose.yml
fi

%{ if enable_v2 ~}
# Pull or build V2 image
if ! docker pull ghcr.io/your-org/RegionalBank-fraud-api-v2:${docker_image_tag_v2} 2>/dev/null; then
    echo "Pre-built V2 image not found, building from source..."

    if [ ! -d /tmp/RegionalBank_fraud_detection ]; then
        cd /tmp
        git clone https://github.com/your-org/RegionalBank_fraud_detection.git
    fi
    cd /tmp/RegionalBank_fraud_detection/backend_v2

    docker build -t RegionalBank-fraud-api-v2:latest .

    sed -i 's|ghcr.io/your-org/RegionalBank-fraud-api-v2:${docker_image_tag_v2}|RegionalBank-fraud-api-v2:latest|' /opt/fraud-api/docker-compose.yml
fi
%{ endif ~}

# =============================================================================
# Start Application
# =============================================================================

cd /opt/fraud-api
docker compose up -d

# Wait for V1 health check
echo "Waiting for V1 API to be healthy..."
for i in {1..30}; do
    if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "V1 API is healthy!"
        break
    fi
    echo "Waiting... ($i/30)"
    sleep 5
done

%{ if enable_v2 ~}
# Wait for V2 health check
echo "Waiting for V2 API to be healthy..."
for i in {1..30}; do
    if curl -sf http://localhost:${api_port_v2}/health > /dev/null 2>&1; then
        echo "V2 API is healthy!"
        break
    fi
    echo "Waiting... ($i/30)"
    sleep 5
done
%{ endif ~}

# =============================================================================
# Setup Auto-restart on Boot
# =============================================================================

cat > /etc/systemd/system/fraud-api.service <<EOF
[Unit]
Description=RegionalBank Fraud Detection API
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/fraud-api
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable fraud-api.service

echo "User data script completed at $(date)"
