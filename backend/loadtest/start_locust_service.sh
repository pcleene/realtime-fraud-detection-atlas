#!/bin/bash
# Start Locust as a background service (API-controllable)
# Usage: ./start_locust_service.sh [num_workers]
#
# This script starts Locust with a web UI that can be controlled via REST API.
# The Svelte UI communicates with FastAPI, which proxies requests to Locust.

NUM_WORKERS=${1:-16}  # 16 workers for 10K+ TPS (adjust for bastion instance size)
HOST="http://<load-balancer-endpoint>"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCUST_FILE="$SCRIPT_DIR/locustfile.py"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$SCRIPT_DIR/locust.pid"
VENV_DIR="$SCRIPT_DIR/venv"

# Create log directory
mkdir -p "$LOG_DIR"

# Check virtual environment exists
LOCUST_BIN="$VENV_DIR/bin/locust"
if [ ! -f "$LOCUST_BIN" ]; then
    echo "ERROR: Locust not found at $LOCUST_BIN"
    echo "Create venv with: python3 -m venv venv && ./venv/bin/pip install locust"
    exit 1
fi

echo "================================================"
echo "Locust Service (API-Controllable)"
echo "================================================"
echo "Workers:    $NUM_WORKERS"
echo "Target:     $HOST"
echo "API:        http://0.0.0.0:8089"
echo "Logs:       $LOG_DIR/"
echo "================================================"

# Kill any existing Locust processes
if [ -f "$PID_FILE" ]; then
    echo "Stopping existing Locust processes..."
    while read pid; do
        kill "$pid" 2>/dev/null
    done < "$PID_FILE"
    rm -f "$PID_FILE"
fi
# Kill existing locust python processes (not this script)
pkill -f "bin/locust" 2>/dev/null
sleep 2

# Start workers in background
echo "Starting $NUM_WORKERS workers..."
for i in $(seq 1 $NUM_WORKERS); do
    "$LOCUST_BIN" -f "$LOCUST_FILE" --worker --master-host=127.0.0.1 \
        >> "$LOG_DIR/worker_$i.log" 2>&1 &
    echo $! >> "$PID_FILE"
    echo "  Worker $i started (PID: $!)"
done

sleep 3

# Start master with web UI (in background)
echo "Starting master..."
nohup "$LOCUST_BIN" -f "$LOCUST_FILE" --master --host="$HOST" --web-host=0.0.0.0 \
    >> "$LOG_DIR/master.log" 2>&1 &
echo $! >> "$PID_FILE"
MASTER_PID=$!

sleep 2

# Verify Locust is running
if curl -s http://localhost:8089/stats/requests > /dev/null 2>&1; then
    echo ""
    echo "================================================"
    echo "Locust is running!"
    echo "================================================"
    echo "Master PID:    $MASTER_PID"
    echo "Status API:    curl http://localhost:8089/stats/requests"
    echo ""
    echo "Control via FastAPI endpoints:"
    echo "  GET  /loadtest/external/status"
    echo "  POST /loadtest/external/start"
    echo "  GET  /loadtest/external/stop"
    echo "  GET  /loadtest/external/stats"
    echo ""
    echo "To stop: ./stop_locust_service.sh"
    echo "================================================"
else
    echo ""
    echo "WARNING: Locust may not have started correctly."
    echo "Check logs in $LOG_DIR/"
fi
