"""
V2 Shared utilities for load testing.

Adapted from V1 for V2 transaction payload format.
"""

import random
import secrets
from datetime import datetime
from typing import List, Dict, Any, Optional

# =============================================================================
# Constants
# =============================================================================

SYNC_INTERVAL_MS = 300
SYNC_BATCH_SIZE = 500
MAX_LATENCY_SAMPLES = 1000
MAX_RECENT_TRANSACTIONS = 50

# V2 transaction constants
SERVICE_CODES = [5, 12, 16, 17, 30, 31, 32, 33, 34, 35, 36, 37, 38, 46]
SERVICE_NAMES = ["Y", "X", "N", "A", "B", "C", "D", "E"]
PURPOSE_CODES = [0, 300, 55555]
DESTINATION_BANKS = ["BRI", "BTN", "RegionalBank", "Bank BCA", "BNI", "CIMB"]
CHANNELS = ["Livin", "KOPRA", "ATM", "QRIS"]
DEVICES = ["samsung SM-A546B", "OPPO CPH2565", "Xiaomi 2209116AG", "iPhone 15", "vivo V29"]


# =============================================================================
# V2 Transaction Payload Generation (Realistic)
# =============================================================================

# Hit-rate constants (same as locustfile.py)
KNOWN_BENEFICIARY_RATE = 0.90
BLACKLIST_BF_RATE = 0.015
BLACKLIST_ANJ_RATE = 0.009
BLACKLIST_CB_RATE = 0.015
SUSPICIOUS_MERCHANT_RATE = 0.05


def _generate_realistic_b2(
    customer: Dict[str, Any],
    blacklist_sample: Optional[Dict[str, list]] = None,
) -> str:
    """Generate a destination account with realistic hit rates."""
    b24_sample = customer.get("b24_sample", [])

    if b24_sample and random.random() < KNOWN_BENEFICIARY_RATE:
        return random.choice(b24_sample)

    bl = blacklist_sample or {}
    roll = random.random()
    if bl.get("pot_bf") and roll < BLACKLIST_BF_RATE:
        return random.choice(bl["pot_bf"])
    elif bl.get("pot_anj") and roll < BLACKLIST_BF_RATE + BLACKLIST_ANJ_RATE:
        return random.choice(bl["pot_anj"])
    elif bl.get("pot_cb") and roll < BLACKLIST_BF_RATE + BLACKLIST_ANJ_RATE + BLACKLIST_CB_RATE:
        return random.choice(bl["pot_cb"])

    return f"{random.randint(1000000000, 9999999999)}"


def _generate_realistic_n2(
    blacklist_sample: Optional[Dict[str, list]] = None,
) -> str:
    """Generate a merchant name, occasionally from suspicious merchant list."""
    bl = blacklist_sample or {}
    if bl.get("pot_sm") and random.random() < SUSPICIOUS_MERCHANT_RATE:
        return random.choice(bl["pot_sm"])
    return f"Merchant-{secrets.token_hex(3).upper()}"


def generate_v2_transaction_payload(
    customer: Dict[str, Any],
    blacklist_sample: Optional[Dict[str, list]] = None,
) -> Dict[str, Any]:
    """Generate a V2 transaction payload with realistic hit rates.

    Args:
        customer: Enriched dict with customer_id, b1, b24_sample.
        blacklist_sample: Optional dict with pot_bf, pot_anj, pot_cb, pot_sm lists.
    """
    return {
        "customer_id": customer["customer_id"],
        "b1": customer.get("b1") or f"{random.randint(1000000000, 9999999999)}",
        "b2": _generate_realistic_b2(customer, blacklist_sample),
        "c2": f"BENEFICIARY-{secrets.token_hex(4).upper()}",
        "d2": random.choice(DESTINATION_BANKS),
        "n2": _generate_realistic_n2(blacklist_sample),
        "at3": random.randint(10000, 5000000),
        "tp": random.choice(PURPOSE_CODES),
        "at7": random.choice([0, 1000, 2500]),
        "service": random.choice(SERVICE_CODES),
        "service_name": random.choice(SERVICE_NAMES),
        "z1": datetime.utcnow().isoformat() + "Z",
        "h1": random.choice(DEVICES),
        "is_financial": 1,
        "channel": random.choice(CHANNELS),
    }


# =============================================================================
# Statistics Calculation
# =============================================================================

def calculate_percentile(latencies: List[float], percentile: float) -> float:
    if not latencies:
        return 0.0
    sorted_latencies = sorted(latencies)
    index = int(len(sorted_latencies) * percentile / 100)
    return sorted_latencies[min(index, len(sorted_latencies) - 1)]


def build_histogram(latencies: List[float], buckets: int = 20) -> List[Dict[str, Any]]:
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
            "percentage": count / len(latencies) * 100 if latencies else 0,
        })
    return histogram


async def get_customer_pool_async(db, size: int = 1000) -> List[Dict[str, str]]:
    """Get customer pool for load testing (V2: customer_id is separate field)."""
    cursor = await db.customers.aggregate([
        {"$sample": {"size": size}},
        {"$project": {"_id": 0, "customer_id": 1}},
    ])
    docs = await cursor.to_list(length=size)
    return [{"customer_id": doc["customer_id"]} for doc in docs]
