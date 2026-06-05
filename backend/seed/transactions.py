# Transaction seed data generator with realistic patterns and fraud injection

import random
import secrets
from datetime import datetime, timedelta
from typing import Dict, Generator, List, Optional

from seed.data.provinces import (
    generate_province_coords,
    get_city_for_province,
    calculate_distance_km,
)
from seed.data.merchants import (
    get_random_merchant,
    get_merchant_for_channel,
    weighted_choice_channel,
    generate_amount,
)
from seed.data.devices import (
    generate_device_fingerprint,
    generate_indonesian_ip,
)
from seed.data.fraud_scenarios import FRAUD_HOTSPOTS


def compute_shard_key_month(timestamp: datetime) -> str:
    """Compute coarse-grained month for shard key."""
    return timestamp.strftime("%Y-%m")


def generate_device_id() -> str:
    """Generate a random device ID."""
    return f"DEV-{secrets.token_hex(4).upper()}"


def generate_random_timestamp_last_12_months() -> datetime:
    """
    Generate a realistic timestamp within the last 12 months.

    Patterns modeled:
    - Time of day: peaks at lunch (12-13h) and evening (19-21h), dead 2-5am
    - Day of week: slightly higher on weekends
    - Day of month: spike on payday (25th-1st)
    """
    now = datetime.utcnow()

    # Random day in last 12 months
    days_ago = random.randint(0, 365)
    base_date = now - timedelta(days=days_ago)

    # Realistic hour distribution (Indonesian banking patterns)
    # Index = hour (0-23), value = relative weight
    HOUR_WEIGHTS = [
        0.01, 0.01, 0.005, 0.005, 0.01, 0.02,  # 0-5am (very low, dead 2-4am)
        0.04, 0.06, 0.07, 0.08, 0.09, 0.10,    # 6-11am (morning rise)
        0.11, 0.09, 0.07, 0.06, 0.06, 0.07,    # 12-5pm (lunch peak at 12, afternoon lull)
        0.08, 0.10, 0.11, 0.09, 0.06, 0.03,    # 6-11pm (evening peak 19-20h)
    ]
    hour = random.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]

    # Random minute
    minute = random.randint(0, 59)
    second = random.randint(0, 59)

    # Day of month adjustment: boost transactions around payday (25th-1st)
    day_of_month = base_date.day
    if day_of_month >= 25 or day_of_month <= 3:
        # 30% chance to shift to payday cluster if not already there
        if random.random() < 0.3:
            # Pick a day in the payday window
            if random.random() < 0.5:
                day_of_month = random.randint(25, 28)  # End of month
            else:
                day_of_month = random.randint(1, 3)    # Start of month
            try:
                base_date = base_date.replace(day=day_of_month)
            except ValueError:
                pass  # Keep original if invalid (e.g., Feb 30)

    return base_date.replace(hour=hour, minute=minute, second=second, microsecond=0)


def _get_expected_rules(fraud_type: str) -> List[str]:
    """Map fraud type to expected triggering rules."""
    rule_mapping = {
        "velocity": ["velocity"],
        "impossible_travel": ["impossible_travel"],
        "blacklist": ["blacklist_proximity"],
        "ato": ["velocity", "impossible_travel"],
        "card_testing": [],
        "unusual_amount": [],
        "new_device": [],
        "midnight_burst": [],
        "geo_anomaly": ["impossible_travel"],
    }
    return rule_mapping.get(fraud_type, [])


def generate_transaction(
    customer: Dict,
    timestamp: Optional[datetime] = None,
    inject_fraud: Optional[str] = None,
    prev_txn: Optional[Dict] = None,
) -> Dict:
    """
    Generate a single transaction document.

    Args:
        customer: Customer document
        timestamp: Transaction timestamp. If None, randomly generated.
        inject_fraud: Type of fraud to inject (velocity, impossible_travel, blacklist, etc.)
        prev_txn: Previous transaction for fraud pattern injection

    Returns:
        Transaction document dict ready for MongoDB insertion.
    """
    if timestamp is None:
        timestamp = generate_random_timestamp_last_12_months()

    channel = weighted_choice_channel()
    province = customer["province"]
    coords = generate_province_coords(province)
    merchant = get_random_merchant()

    # Handle fraud injection
    if inject_fraud == "velocity" and prev_txn:
        # Make transaction within 5 seconds of previous
        timestamp = prev_txn["timestamp"] + timedelta(seconds=random.uniform(1, 5))
        coords = prev_txn["location"]["coordinates"]  # Same location

    elif inject_fraud == "impossible_travel" and prev_txn:
        # Make transaction from very different location but short time
        timestamp = prev_txn["timestamp"] + timedelta(minutes=random.uniform(5, 30))
        # Generate coords far away (different province)
        other_provinces = ["Papua", "Sumatera Utara", "Sulawesi Selatan", "Bali"]
        far_province = random.choice([p for p in other_provinces if p != province])
        coords = generate_province_coords(far_province)

    elif inject_fraud == "blacklist":
        # Use coordinates near a known fraud hotspot
        hotspot = random.choice(FRAUD_HOTSPOTS)
        coords = [
            hotspot["coords"][0] + random.uniform(-0.002, 0.002),
            hotspot["coords"][1] + random.uniform(-0.002, 0.002)
        ]

    # Generate realistic device fingerprint
    device_fingerprint = generate_device_fingerprint(
        sticky_for_customer=True,
        customer_seed=customer["customer_id"]
    )

    # Get city info
    city_info = get_city_for_province(province)
    city_name = city_info[0] if isinstance(city_info, tuple) else city_info

    # Build fraud metadata if fraud was injected
    fraud_metadata = None
    if inject_fraud:
        fraud_metadata = {
            "injected_type": inject_fraud,
            "expected_rules": _get_expected_rules(inject_fraud),
        }

    return {
        "customer_id": customer["customer_id"],
        "shard_key_month": compute_shard_key_month(timestamp),
        "customer": {
            "_id": customer.get("_id"),
            "customer_id": customer["customer_id"],
            "name": customer["name"],
        },
        "account_id": customer["account_ids"][0],  # Use first account ID
        "type": "debit",
        "channel": channel,
        "amount": generate_amount(channel),
        "currency": "IDR",
        "status": "authorized",
        "timestamp": timestamp,
        "location": {
            "type": "Point",
            "coordinates": coords,
        },
        "city": city_name,
        "province": province,
        "merchant": merchant,
        "device": {
            "device_id": device_fingerprint.get("device_id", generate_device_id()),
            "device_type": device_fingerprint.get("os_type", "android"),
            "device_model": device_fingerprint.get("model"),
            "os_version": device_fingerprint.get("os_version"),
            "ip": generate_indonesian_ip(),
        },
        "fraud_score": None,  # Will be filled during scoring
        "fraud_metadata": fraud_metadata,  # For testing/debugging
        "attrs": {},
    }


def generate_transactions_for_customer(
    customer: Dict,
    num_transactions: int,
) -> List[Dict]:
    """
    Generate transactions for a single customer.

    Args:
        customer: Customer document
        num_transactions: Number of transactions to generate

    Returns:
        List of transaction documents
    """
    transactions = []

    for i in range(num_transactions):
        # Determine if we should inject fraud (12% total fraud rate)
        fraud_type = None
        prev_txn = transactions[-1] if transactions else None

        roll = random.random()
        if roll < 0.05 and prev_txn:
            fraud_type = "impossible_travel"
        elif roll < 0.07 and prev_txn:
            fraud_type = "velocity"
        elif roll < 0.10:
            fraud_type = "blacklist"

        txn = generate_transaction(
            customer,
            inject_fraud=fraud_type,
            prev_txn=prev_txn,
        )
        transactions.append(txn)

    # Sort by timestamp
    transactions.sort(key=lambda x: x["timestamp"])
    return transactions


def transaction_generator(
    customers: List[Dict],
    total_transactions: int,
    batch_size: int = 10000,
) -> Generator[List[Dict], None, None]:
    """
    Generator that yields batches of transactions.

    Args:
        customers: List of customer documents
        total_transactions: Total number of transactions to generate
        batch_size: Number of transactions per batch

    Yields:
        Batches of transaction documents
    """
    # Calculate average transactions per customer
    avg_txns_per_customer = total_transactions / len(customers) if customers else 2

    batch = []
    generated = 0

    for customer in customers:
        if generated >= total_transactions:
            break

        # Use Poisson distribution for realistic transaction count per customer
        num_txns = max(1, int(random.expovariate(1 / avg_txns_per_customer)))
        num_txns = min(num_txns, total_transactions - generated)

        txns = generate_transactions_for_customer(customer, num_txns)
        batch.extend(txns)
        generated += len(txns)

        while len(batch) >= batch_size:
            yield batch[:batch_size]
            batch = batch[batch_size:]

    if batch:
        yield batch
