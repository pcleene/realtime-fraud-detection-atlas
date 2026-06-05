#!/bin/bash
# EC2 Deployment Script
# Run this after ec2-setup.sh to deploy the application
#
# Usage:
#   ./ec2-deploy.sh <mongodb_uri>
#
# Example:
#   ./ec2-deploy.sh "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"

set -e

MONGODB_URI=${1:-$MONGODB_URI}

if [ -z "$MONGODB_URI" ]; then
    echo "Error: MONGODB_URI is required"
    echo "Usage: ./ec2-deploy.sh <mongodb_uri>"
    echo "   Or: export MONGODB_URI=... && ./ec2-deploy.sh"
    exit 1
fi

# Detect CPU count for worker configuration
CPU_COUNT=$(nproc)
RECOMMENDED_WORKERS=$((CPU_COUNT * 2))

echo "=========================================="
echo "RegionalBank Fraud Detection - Deployment"
echo "=========================================="
echo "CPUs detected: $CPU_COUNT"
echo "Recommended workers: $RECOMMENDED_WORKERS"
echo ""

# Create .env file
cat > .env <<EOF
MONGODB_URI=${MONGODB_URI}
DB_NAME=RegionalBank_fraud
LOG_LEVEL=info
WORKERS=${RECOMMENDED_WORKERS}
WORKER_CONNECTIONS=1000
TIMEOUT=120
EOF

echo "Created .env file"

# Build and start
echo ""
echo "Building Docker images..."
docker compose build

echo ""
echo "Starting services..."
docker compose up -d

echo ""
echo "Waiting for services to be healthy..."
sleep 10

# Health check
echo ""
echo "Checking API health..."
for i in {1..30}; do
    if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "API is healthy!"
        break
    fi
    echo "Waiting for API... ($i/30)"
    sleep 2
done

# Show status
echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
docker compose ps

echo ""
echo "Services:"
echo "  API:      http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo 'localhost'):8000"
echo "  Frontend: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo 'localhost'):3000"
echo "  Docs:     http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo 'localhost'):8000/docs"
echo ""
echo "Logs: docker compose logs -f"
echo ""
