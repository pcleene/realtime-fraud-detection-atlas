#!/bin/bash
# =============================================================================
# Start Locust Optimized for 10K+ TPS
# =============================================================================
#
# This script is optimized for achieving 10,000+ TPS by:
# 1. Using 16 workers (for bastion with 32 vCPU like c6i.8xlarge)
# 2. Using HighThroughputUser class (no wait time between requests)
# 3. Pre-warming connections before starting the swarm
#
# Performance math:
# - Each worker can handle ~800 TPS at ~30ms latency
# - 16 workers = ~12,800 TPS theoretical max
# - 10K TPS target is achievable with headroom
#
# Usage:
#   ./start_locust_10k.sh              # Default: 16 workers
#   ./start_locust_10k.sh 24           # Custom: 24 workers for higher TPS
#
# =============================================================================

set -e

NUM_WORKERS=${1:-16}  # Default 16 workers for 10K+ TPS
HOST="${LOCUST_TARGET_HOST:-http://<load-balancer-endpoint>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCUST_FILE="$SCRIPT_DIR/locustfile.py"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$SCRIPT_DIR/locust.pid"

# Detect virtual environment
if [ -f "$SCRIPT_DIR/../.venv/bin/locust" ]; then
    LOCUST_BIN="$SCRIPT_DIR/../.venv/bin/locust"
elif [ -f "$SCRIPT_DIR/venv/bin/locust" ]; then
    LOCUST_BIN="$SCRIPT_DIR/venv/bin/locust"
elif command -v locust &> /dev/null; then
    LOCUST_BIN="locust"
else
    echo "ERROR: Locust not found"
    echo "Install with: pip install locust"
    exit 1
fi

# Create log directory
mkdir -p "$LOG_DIR"

echo "=================================================================="
echo "  Locust 10K TPS Configuration"
echo "=================================================================="
echo "  Workers:         $NUM_WORKERS"
echo "  Target Host:     $HOST"
echo "  Locust API:      http://0.0.0.0:8089"
echo "  User Class:      HighThroughputUser (zero wait time)"
echo ""
echo "  Expected TPS:    ~$((NUM_WORKERS * 800)) (800 TPS per worker)"
echo "=================================================================="

# Kill any existing Locust processes
echo ""
echo "Cleaning up existing Locust processes..."
if [ -f "$PID_FILE" ]; then
    while read pid; do
        kill "$pid" 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
fi
pkill -f "bin/locust" 2>/dev/null || true
sleep 2

# System tuning (if running as root or with sudo)
if [ "$(id -u)" = "0" ] || sudo -n true 2>/dev/null; then
    echo "Applying system tuning for high throughput..."
    sudo sysctl -w net.core.somaxconn=65535 2>/dev/null || true
    sudo sysctl -w net.ipv4.tcp_max_syn_backlog=65535 2>/dev/null || true
    sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535" 2>/dev/null || true
    ulimit -n 65535 2>/dev/null || true
fi

# Start workers in background
echo ""
echo "Starting $NUM_WORKERS workers..."
for i in $(seq 1 $NUM_WORKERS); do
    "$LOCUST_BIN" -f "$LOCUST_FILE" --worker --master-host=127.0.0.1 \
        >> "$LOG_DIR/worker_$i.log" 2>&1 &
    echo $! >> "$PID_FILE"
    printf "  Worker %2d started (PID: %s)\n" "$i" "$!"
done

# Wait for workers to initialize
echo ""
echo "Waiting for workers to initialize..."
sleep 5

# Start master with web UI
echo "Starting master with web UI..."
nohup "$LOCUST_BIN" -f "$LOCUST_FILE" \
    --master \
    --expect-workers "$NUM_WORKERS" \
    --host="$HOST" \
    --web-host=0.0.0.0 \
    >> "$LOG_DIR/master.log" 2>&1 &
echo $! >> "$PID_FILE"
MASTER_PID=$!

# Wait for master to start
sleep 3

# Verify Locust is running and workers connected
echo ""
if curl -s http://localhost:8089/stats/requests > /dev/null 2>&1; then
    # Get worker count
    CONNECTED_WORKERS=$(curl -s http://localhost:8089/stats/requests | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('workers', [])))" 2>/dev/null || echo "?")

    echo "=================================================================="
    echo "  Locust Ready for 10K TPS!"
    echo "=================================================================="
    echo "  Master PID:      $MASTER_PID"
    echo "  Workers:         $CONNECTED_WORKERS / $NUM_WORKERS connected"
    echo ""
    echo "  Quick Test (via API):"
    echo "    curl -X POST http://localhost:8089/swarm \\"
    echo "      -d 'user_count=1000&spawn_rate=100&host=$HOST'"
    echo ""
    echo "  For 10K TPS, recommended settings:"
    echo "    - Users: 1000-1500 (HighThroughputUser has zero wait)"
    echo "    - Spawn Rate: 100/s"
    echo ""
    echo "  Monitor via UI:"
    echo "    http://<bastion-public-ip>:8089"
    echo "    or via FastAPI proxy: /loadtest/external/stats"
    echo ""
    echo "  Stop: ./stop_locust_service.sh or pkill -f locust"
    echo "=================================================================="
else
    echo ""
    echo "WARNING: Locust may not have started correctly."
    echo "Check logs: tail -f $LOG_DIR/master.log"
    exit 1
fi
