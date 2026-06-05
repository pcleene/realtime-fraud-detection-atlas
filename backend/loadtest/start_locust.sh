#!/bin/bash
# Start Locust master + workers for distributed load testing
# Usage: ./start_locust.sh [num_workers] [host]

NUM_WORKERS=${1:-16}  # Default 16 workers for c6i.8xlarge (32 vCPU)
HOST=${2:-"http://<load-balancer-endpoint>"}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCUST_FILE="$SCRIPT_DIR/locustfile.py"

echo "================================================"
echo "Locust Distributed Load Test"
echo "================================================"
echo "Workers:    $NUM_WORKERS"
echo "Target:     $HOST"
echo "Web UI:     http://localhost:8089"
echo "================================================"

# Kill any existing Locust processes
pkill -f "locust" 2>/dev/null
sleep 1

# Start workers in background
echo "Starting $NUM_WORKERS workers..."
for i in $(seq 1 $NUM_WORKERS); do
    locust -f "$LOCUST_FILE" --worker --master-host=127.0.0.1 &
    echo "  Worker $i started (PID: $!)"
done

sleep 2

# Start master with web UI (foreground)
echo ""
echo "Starting master with Web UI on port 8089..."
echo "Access: http://localhost:8089 (use SSM port forwarding)"
echo ""
echo "To port forward from your local machine:"
echo "  aws ssm start-session --target <instance-id> --region ap-southeast-1 \\"
echo "    --document-name AWS-StartPortForwardingSession \\"
echo "    --parameters '{\"portNumber\":[\"8089\"],\"localPortNumber\":[\"8089\"]}'"
echo ""
echo "Press Ctrl+C to stop all Locust processes"
echo "================================================"

locust -f "$LOCUST_FILE" --master --host="$HOST" --web-host=0.0.0.0

# Cleanup on exit
trap "pkill -f 'locust'; echo 'All Locust processes stopped.'" EXIT
