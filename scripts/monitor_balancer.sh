#!/bin/bash
# MongoDB Balancer Monitor
# Run: ./monitor_balancer.sh [interval_seconds]
# Default interval: 300 seconds (5 minutes)

INTERVAL=${1:-300}
API_INSTANCE="<instance-id>"
REGION="ap-southeast-1"

check_balancer() {
    echo "=========================================="
    echo "Balancer Check: $(date)"
    echo "=========================================="

    COMMAND_ID=$(aws ssm send-command \
        --instance-ids $API_INSTANCE \
        --document-name "AWS-RunShellScript" \
        --parameters 'commands=["sudo docker exec RegionalBank_fraud_detection-api-1 python3 -c '\''from pymongo import MongoClient; import os; from datetime import datetime, timedelta; client = MongoClient(os.environ[\"MONGODB_URI\"]); admin = client.admin; config = client.config; status = admin.command(\"balancerStatus\"); print(\"Balancer Mode:\", status.get(\"mode\")); print(\"Currently Running:\", status.get(\"inBalancerRound\")); db = client.RegionalBank_fraud; for coll in [\"customers\", \"transactions\"]: stats = db.command(\"collStats\", coll); shards = stats.get(\"shards\", {}); print(f\"\\n{coll}:\"); [print(f\"  {s}: {shards[s].get('count', 0):,} docs\") for s in sorted(shards.keys()) if s != \"config\"]; recent = list(config.changelog.find({\"what\": \"moveChunk.commit\", \"time\": {\"$gte\": datetime.utcnow() - timedelta(minutes=10)}}).sort(\"time\", -1).limit(3)); print(f\"\\nRecent chunk moves (last 10 min): {len(recent)}\"); [print(f\"  {m['time']}: {m['ns'].split('.')[1]}\") for m in recent]'\'' 2>&1"]' \
        --region $REGION \
        --output text \
        --query 'Command.CommandId')

    sleep 12

    aws ssm get-command-invocation \
        --command-id "$COMMAND_ID" \
        --instance-id $API_INSTANCE \
        --region $REGION \
        --query 'StandardOutputContent' \
        --output text

    echo ""
}

# Single run or continuous mode
if [ "$2" == "--once" ]; then
    check_balancer
else
    echo "Starting balancer monitor (interval: ${INTERVAL}s)"
    echo "Press Ctrl+C to stop"
    echo ""

    while true; do
        check_balancer
        echo "Next check in ${INTERVAL} seconds..."
        sleep $INTERVAL
    done
fi
