#!/bin/bash
# EC2 Setup Script for RegionalBank Fraud Detection API
#
# Recommended instance: c6i.2xlarge (8 vCPU, 16GB) or c6i.4xlarge (16 vCPU, 32GB)
# AMI: Amazon Linux 2023 or Ubuntu 22.04
#
# Usage:
#   1. Launch EC2 instance with appropriate security group (ports 80, 8000, 3000)
#   2. SSH into instance
#   3. Run: curl -sSL https://raw.githubusercontent.com/.../ec2-setup.sh | bash
#   Or copy this script and run it

set -e

echo "=========================================="
echo "RegionalBank Fraud Detection - EC2 Setup"
echo "=========================================="

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo "Cannot detect OS"
    exit 1
fi

echo "Detected OS: $OS"

# Install Docker
echo ""
echo "Installing Docker..."
if [ "$OS" = "amzn" ]; then
    # Amazon Linux 2023
    sudo dnf update -y
    sudo dnf install -y docker git
    sudo systemctl start docker
    sudo systemctl enable docker
    sudo usermod -aG docker $USER

    # Install Docker Compose v2
    sudo mkdir -p /usr/local/lib/docker/cli-plugins
    sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
    sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

elif [ "$OS" = "ubuntu" ]; then
    # Ubuntu
    sudo apt-get update
    sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo usermod -aG docker $USER
fi

# Verify Docker
docker --version
docker compose version

# System tuning for high performance
echo ""
echo "Applying system performance tuning..."

# Increase file descriptor limits
sudo tee /etc/security/limits.d/99-fraud-api.conf > /dev/null <<EOF
* soft nofile 65535
* hard nofile 65535
* soft nproc 65535
* hard nproc 65535
EOF

# Kernel tuning for high network throughput
sudo tee /etc/sysctl.d/99-fraud-api.conf > /dev/null <<EOF
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

sudo sysctl -p /etc/sysctl.d/99-fraud-api.conf

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Log out and back in (for docker group)"
echo "2. Clone your repo or copy files"
echo "3. Create .env file with MONGODB_URI"
echo "4. Run: make docker-up (single instance)"
echo "   Or:  make prod-up (with nginx load balancer)"
echo ""
echo "Recommended worker count based on instance:"
echo "  c6i.xlarge  (4 vCPU):  WORKERS=4"
echo "  c6i.2xlarge (8 vCPU):  WORKERS=8"
echo "  c6i.4xlarge (16 vCPU): WORKERS=16"
echo ""
