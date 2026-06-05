"""
Shared utilities for load testing.

This module contains functions and constants shared between:
- The embedded load test API (backend/app/routes/loadtest.py)
- The external CLI load test tool (backend/loadtest/cli.py)

Extracted to avoid code duplication and ensure consistency.
"""

import random
from datetime import datetime
from typing import List, Dict, Any, Optional

# =============================================================================
# Constants
# =============================================================================

SYNC_INTERVAL_MS = 300  # Sync to MongoDB every 300ms
SYNC_BATCH_SIZE = 500   # Or every 500 transactions
MAX_LATENCY_SAMPLES = 1000  # Keep last N samples for percentile calculation
MAX_RECENT_TRANSACTIONS = 50  # Keep last N transactions for UI feed


# =============================================================================
# Transaction Payload Generation
# =============================================================================

def generate_transaction_payload(
    customer: Dict[str, str],
    fraud_type: Optional[str] = None,
    *,
    # These are imported lazily to avoid circular imports
    weighted_choice_province=None,
    weighted_choice_channel=None,
    get_merchant_for_channel=None,
    generate_device_fingerprint=None,
    generate_indonesian_ip=None,
    generate_province_coords=None,
    FRAUD_HOTSPOTS=None,
) -> Dict[str, Any]:
    """
    Generate a realistic transaction payload for HTTP request.
    
    Args:
        customer: Dict with customer_id and account_id
        fraud_type: Optional fraud type ("blacklist" to generate near fraud hotspot)
        
    Returns:
        Dict payload ready for /score-transaction endpoint
    """
    # Lazy imports if not provided (for backwards compatibility)
    if weighted_choice_province is None:
        from seed.data.provinces import weighted_choice_province, generate_province_coords as _gen_coords
        generate_province_coords = _gen_coords
    if weighted_choice_channel is None:
        from seed.data.merchants import get_merchant_for_channel as _get_merchant, weighted_choice_channel as _choice_channel
        weighted_choice_channel = _choice_channel
        get_merchant_for_channel = _get_merchant
    if generate_device_fingerprint is None:
        from seed.data.devices import generate_device_fingerprint, generate_indonesian_ip as _gen_ip
        generate_indonesian_ip = _gen_ip
    if FRAUD_HOTSPOTS is None:
        from seed.data.fraud_scenarios import FRAUD_HOTSPOTS

    province = weighted_choice_province()
    channel = weighted_choice_channel()
    merchant, _ = get_merchant_for_channel(channel)
    device = generate_device_fingerprint()

    # Handle fraud injection
    if fraud_type == "blacklist":
        hotspot = random.choice(FRAUD_HOTSPOTS)
        lat = hotspot["coords"][1] + random.uniform(-0.002, 0.002)
        lon = hotspot["coords"][0] + random.uniform(-0.002, 0.002)
    else:
        coords = generate_province_coords(province, precision="district")
        lat = coords[1]
        lon = coords[0]

    return {
        "customer_id": customer["customer_id"],
        "account_id": customer["account_id"],
        "amount": random.randint(10_000, 5_000_000),
        "lat": lat,
        "lon": lon,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "channel": channel,
        "merchant_id": merchant["id"],
        "merchant_name": merchant["name"],
        "mcc": merchant["mcc"],
        "device_id": device["device_id"],
        "device_type": device["device_type"],
        "ip": generate_indonesian_ip(),
    }


# =============================================================================
# Statistics Calculation
# =============================================================================

def calculate_percentile(latencies: List[float], percentile: float) -> float:
    """
    Calculate percentile from a list of latencies.
    
    Args:
        latencies: List of latency values in ms
        percentile: Percentile to calculate (0-100)
        
    Returns:
        Percentile value in ms
    """
    if not latencies:
        return 0.0
    sorted_latencies = sorted(latencies)
    index = int(len(sorted_latencies) * percentile / 100)
    return sorted_latencies[min(index, len(sorted_latencies) - 1)]


def build_histogram(latencies: List[float], buckets: int = 20) -> List[Dict[str, Any]]:
    """
    Build a latency histogram.
    
    Args:
        latencies: List of latency values in ms
        buckets: Number of histogram buckets
        
    Returns:
        List of bucket dicts with bucket_ms, count, percentage
    """
    if not latencies:
        return []

    min_val = min(latencies)
    max_val = max(latencies)
    bucket_size = (max_val - min_val) / buckets if max_val > min_val else 1

    histogram = []
    for i in range(buckets):
        lower = min_val + i * bucket_size
        upper = lower + bucket_size
        count = sum(1 for l in latencies if lower <= l < upper)
        histogram.append({
            "bucket_ms": f"{lower:.1f}-{upper:.1f}",
            "count": count,
            "percentage": count / len(latencies) * 100 if latencies else 0
        })

    return histogram


# =============================================================================
# Customer Pool
# =============================================================================

async def get_customer_pool_async(db, size: int = 1000) -> List[Dict[str, str]]:
    """
    Get a pool of customer IDs for load testing (async version).
    
    Args:
        db: AsyncDatabase instance
        size: Number of customers to fetch
        
    Returns:
        List of dicts with customer_id and account_id
    """
    # In pymongo async, aggregate() returns a coroutine, await it first to get cursor
    cursor = await db.customers.aggregate([
        {"$sample": {"size": size}},
        {"$project": {"customer_id": 1, "account_ids": 1}}
    ])
    docs = await cursor.to_list(length=size)
    
    customer_ids = []
    for doc in docs:
        customer_ids.append({
            "customer_id": doc["customer_id"],
            "account_id": doc.get("account_ids", ["ACC-00000000"])[0] if doc.get("account_ids") else "ACC-00000000"
        })
    return customer_ids


def get_customer_pool_sync(db, size: int = 1000) -> List[Dict[str, str]]:
    """
    Get a pool of customer IDs for load testing (sync version for CLI).
    
    Args:
        db: Database instance (synchronous)
        size: Number of customers to fetch
        
    Returns:
        List of dicts with customer_id and account_id
    """
    cursor = db.customers.aggregate([
        {"$sample": {"size": size}},
        {"$project": {"customer_id": 1, "account_ids": 1}}
    ])
    
    customer_ids = []
    for doc in cursor:
        customer_ids.append({
            "customer_id": doc["customer_id"],
            "account_id": doc.get("account_ids", ["ACC-00000000"])[0] if doc.get("account_ids") else "ACC-00000000"
        })
    return customer_ids


# =============================================================================
# Local State Management
# =============================================================================

def create_local_state() -> Dict[str, Any]:
    """
    Create initial local state for tracking load test progress.
    
    This state is kept in memory during the test and periodically synced to MongoDB.
    """
    return {
        "successful": 0,
        "failed": 0,
        "latencies": [],
        "risk_distribution": {"low": 0, "medium": 0, "high": 0},
        "recent_transactions": [],  # Last N transactions for UI feed
        "last_sync_successful": 0,
        "last_sync_failed": 0,
        "last_sync_latency_sum": 0.0,
        "last_sync_latency_count": 0,
        "last_sync_risk": {"low": 0, "medium": 0, "high": 0},
    }


def calculate_sync_deltas(local_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate deltas since last sync for MongoDB update.
    
    Args:
        local_state: Current local state dict
        
    Returns:
        Dict with deltas for successful, failed, latencies, risk distribution
    """
    # Calculate deltas since last sync
    successful_delta = local_state["successful"] - local_state["last_sync_successful"]
    failed_delta = local_state["failed"] - local_state["last_sync_failed"]
    
    # Get new latencies since last sync
    new_latencies = local_state["latencies"][local_state["last_sync_latency_count"]:]
    latency_sum_delta = sum(new_latencies)
    latency_count_delta = len(new_latencies)
    latency_min = min(new_latencies) if new_latencies else None
    latency_max = max(new_latencies) if new_latencies else None
    
    # Risk distribution delta
    risk_delta = {}
    for k in ["low", "medium", "high"]:
        delta = local_state["risk_distribution"][k] - local_state["last_sync_risk"][k]
        if delta > 0:
            risk_delta[k] = delta
    
    return {
        "successful_delta": successful_delta,
        "failed_delta": failed_delta,
        "new_latencies": new_latencies,
        "latency_sum_delta": latency_sum_delta,
        "latency_count_delta": latency_count_delta,
        "latency_min": latency_min,
        "latency_max": latency_max,
        "risk_delta": risk_delta,
    }


def update_sync_tracking(local_state: Dict[str, Any]) -> None:
    """
    Update sync tracking after a successful MongoDB sync.
    
    Args:
        local_state: Local state dict to update (modified in place)
    """
    local_state["last_sync_successful"] = local_state["successful"]
    local_state["last_sync_failed"] = local_state["failed"]
    local_state["last_sync_latency_count"] = len(local_state["latencies"])
    local_state["last_sync_risk"] = local_state["risk_distribution"].copy()



