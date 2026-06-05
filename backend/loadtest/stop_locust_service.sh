#!/bin/bash
# Stop the Locust service
# Usage: ./stop_locust_service.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/locust.pid"

echo "Stopping Locust service..."

# Kill processes from PID file
if [ -f "$PID_FILE" ]; then
    while read pid; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            echo "  Killed PID $pid"
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
fi

# Kill any remaining Locust processes
pkill -f "locust" 2>/dev/null

echo "Locust service stopped."
