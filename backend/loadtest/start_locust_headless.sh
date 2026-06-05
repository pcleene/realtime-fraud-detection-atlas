#!/bin/bash
# Start Locust in headless mode (API-controllable, no manual UI interaction needed)
# Usage: ./start_locust_headless.sh [users] [spawn_rate] [duration] [num_workers]

USERS=${1:-2000}
SPAWN_RATE=${2:-200}
DURATION=${3:-60}
NUM_WORKERS=${4:-16}
HOST="http://<load-balancer-endpoint>"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCUST_FILE="$SCRIPT_DIR/locustfile.py"

echo "================================================"
echo "Locust Headless Load Test"
echo "================================================"
echo "Users:      $USERS"
echo "Spawn Rate: $SPAWN_RATE/sec"
echo "Duration:   ${DURATION}s"
echo "Workers:    $NUM_WORKERS"
echo "Target:     $HOST"
echo "================================================"

# Kill any existing Locust processes
pkill -f "locust" 2>/dev/null
sleep 1

# Start workers in background
echo "Starting $NUM_WORKERS workers..."
for i in $(seq 1 $NUM_WORKERS); do
    locust -f "$LOCUST_FILE" --worker --master-host=127.0.0.1 &
done

sleep 3

# Start master in headless mode
echo "Starting master (headless)..."
echo ""
locust -f "$LOCUST_FILE" --master --headless \
    --host="$HOST" \
    --users "$USERS" \
    --spawn-rate "$SPAWN_RATE" \
    --run-time "${DURATION}s" \
    --expect-workers "$NUM_WORKERS"

# Cleanup
pkill -f "locust" 2>/dev/null
echo "Done."
