# Fraud scenario injection for realistic testing
# Generates various fraud patterns that the scoring system should detect

import random
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from seed.data.provinces import (
    PROVINCE_CITIES,
    calculate_distance_km,
    generate_province_coords,
)


class FraudType(Enum):
    """Types of fraud patterns to inject."""
    VELOCITY = "velocity"                    # Rapid sequential transactions
    IMPOSSIBLE_TRAVEL = "impossible_travel"  # Location inconsistency
    BLACKLIST_PROXIMITY = "blacklist"        # Near fraud hotspot
    ACCOUNT_TAKEOVER = "ato"                 # Full account compromise pattern
    CARD_TESTING = "card_testing"            # Small test transactions
    UNUSUAL_AMOUNT = "unusual_amount"        # Atypical transaction size
    NEW_DEVICE = "new_device"                # Transaction from unknown device
    MIDNIGHT_BURST = "midnight_burst"        # Suspicious late-night activity
    GEOGRAPHIC_ANOMALY = "geo_anomaly"       # Different country/region


# Fraud scenario configurations
FRAUD_SCENARIOS = {
    FraudType.VELOCITY: {
        "description": "Multiple transactions within seconds",
        "time_gap_seconds": (1, 8),  # Rapid fire
        "same_location": True,
        "risk_level": "high",
        "detection_rule": "velocity",
    },
    FraudType.IMPOSSIBLE_TRAVEL: {
        "description": "Transaction from impossible location given time",
        "time_gap_minutes": (5, 30),  # Short time
        "min_distance_km": 500,       # But far distance
        "risk_level": "high",
        "detection_rule": "impossible_travel",
    },
    FraudType.BLACKLIST_PROXIMITY: {
        "description": "Transaction near known fraud hotspot",
        "use_blacklist_coords": True,
        "risk_level": "medium",
        "detection_rule": "blacklist_proximity",
    },
    FraudType.ACCOUNT_TAKEOVER: {
        "description": "Pattern suggesting compromised account",
        "includes": ["new_device", "password_change", "velocity", "unusual_amount"],
        "risk_level": "critical",
    },
    FraudType.CARD_TESTING: {
        "description": "Small test transactions before larger fraud",
        "amounts": [1_000, 5_000, 10_000],  # Very small amounts
        "count": (3, 5),
        "risk_level": "medium",
    },
    FraudType.UNUSUAL_AMOUNT: {
        "description": "Transaction significantly larger than normal",
        "multiplier": (5, 20),  # 5-20x normal amount
        "risk_level": "medium",
    },
    FraudType.NEW_DEVICE: {
        "description": "First transaction from unknown device",
        "risk_level": "low",
    },
    FraudType.MIDNIGHT_BURST: {
        "description": "Multiple transactions between midnight and 4am",
        "hour_range": (0, 4),
        "transaction_count": (3, 7),
        "risk_level": "medium",
    },
    FraudType.GEOGRAPHIC_ANOMALY: {
        "description": "Transaction from unexpected location",
        "provinces_away": ["Papua", "Nusa Tenggara Timur", "Sulawesi Selatan"],
        "risk_level": "medium",
    },
}

# Known fraud hotspot locations (for blacklist proximity testing)
FRAUD_HOTSPOTS = [
    # Jakarta fraud clusters
    {"city": "Jakarta", "province": "DKI Jakarta", "coords": [106.8297, -6.1387], "category": "fraud_hub"},  # Mangga Dua
    {"city": "Jakarta", "province": "DKI Jakarta", "coords": [106.8178, -6.1456], "category": "fraud_hub"},  # Glodok
    {"city": "Jakarta", "province": "DKI Jakarta", "coords": [106.8124, -6.1862], "category": "scammer"},    # Tanah Abang
    # Surabaya
    {"city": "Surabaya", "province": "Jawa Timur", "coords": [112.7374, -7.2621], "category": "wifi"},
    # Bandung
    {"city": "Bandung", "province": "Jawa Barat", "coords": [107.6191, -6.9175], "category": "merchant"},
    # Medan
    {"city": "Medan", "province": "Sumatera Utara", "coords": [98.6722, 3.5952], "category": "scammer"},
]


@dataclass
class FraudScenario:
    """A configured fraud scenario for injection."""
    fraud_type: FraudType
    customer_id: str
    base_timestamp: datetime
    base_location: List[float]
    transactions: List[Dict]  # Generated fraudulent transactions


def inject_velocity_fraud(
    customer_id: str,
    base_timestamp: datetime,
    base_location: List[float],
    num_transactions: int = 3
) -> List[Dict]:
    """
    Generate velocity fraud pattern (rapid sequential transactions).

    Args:
        customer_id: Customer ID
        base_timestamp: Starting timestamp
        base_location: Starting location [lon, lat]
        num_transactions: Number of rapid transactions

    Returns:
        List of transaction modifications
    """
    transactions = []
    current_time = base_timestamp

    for i in range(num_transactions):
        # Very short time gap (1-8 seconds)
        gap_seconds = random.uniform(1, 8)
        current_time = current_time + timedelta(seconds=gap_seconds)

        txn = {
            "timestamp": current_time,
            "location": base_location.copy(),  # Same location
            "amount": random.randint(50_000, 500_000),
            "fraud_injected": FraudType.VELOCITY.value,
            "expected_rules": ["velocity"],
        }
        transactions.append(txn)

    return transactions


def inject_impossible_travel(
    customer_id: str,
    base_timestamp: datetime,
    base_location: List[float],
    base_province: str
) -> Dict:
    """
    Generate impossible travel fraud (location inconsistency).

    Args:
        customer_id: Customer ID
        base_timestamp: Previous transaction timestamp
        base_location: Previous transaction location
        base_province: Customer's home province

    Returns:
        Transaction modification dict
    """
    # Pick a far-away location
    far_provinces = ["Papua", "Sumatera Utara", "Sulawesi Selatan", "Kalimantan Timur"]
    far_provinces = [p for p in far_provinces if p != base_province]
    target_province = random.choice(far_provinces)

    # Get coordinates for the far province
    far_location = generate_province_coords(target_province, precision="city")

    # Short time gap (5-30 minutes) - impossible to travel that far
    gap_minutes = random.uniform(5, 30)
    new_timestamp = base_timestamp + timedelta(minutes=gap_minutes)

    # Calculate speed for verification
    distance = calculate_distance_km(
        base_location[0], base_location[1],
        far_location[0], far_location[1]
    )
    hours = gap_minutes / 60
    speed_kmh = distance / hours if hours > 0 else float('inf')

    return {
        "timestamp": new_timestamp,
        "location": far_location,
        "amount": random.randint(100_000, 2_000_000),
        "fraud_injected": FraudType.IMPOSSIBLE_TRAVEL.value,
        "expected_rules": ["impossible_travel"],
        "_debug": {
            "distance_km": round(distance, 2),
            "time_gap_minutes": round(gap_minutes, 2),
            "speed_kmh": round(speed_kmh, 2),
        },
    }


def inject_blacklist_proximity(
    customer_id: str,
    base_timestamp: datetime,
    hotspot: Dict = None
) -> Dict:
    """
    Generate transaction near a fraud hotspot.

    Args:
        customer_id: Customer ID
        base_timestamp: Transaction timestamp
        hotspot: Specific hotspot to use, or None for random

    Returns:
        Transaction modification dict
    """
    if hotspot is None:
        hotspot = random.choice(FRAUD_HOTSPOTS)

    # Add small jitter to be "near" but not exactly at hotspot
    # Within 200m (about 0.002 degrees)
    location = [
        hotspot["coords"][0] + random.uniform(-0.002, 0.002),
        hotspot["coords"][1] + random.uniform(-0.002, 0.002),
    ]

    return {
        "timestamp": base_timestamp,
        "location": location,
        "amount": random.randint(100_000, 1_000_000),
        "fraud_injected": FraudType.BLACKLIST_PROXIMITY.value,
        "expected_rules": ["blacklist_proximity"],
        "_debug": {
            "hotspot_category": hotspot["category"],
            "hotspot_city": hotspot["city"],
        },
    }


def inject_card_testing(
    customer_id: str,
    base_timestamp: datetime,
    base_location: List[float]
) -> List[Dict]:
    """
    Generate card testing pattern (small test transactions).

    Args:
        customer_id: Customer ID
        base_timestamp: Starting timestamp
        base_location: Transaction location

    Returns:
        List of small test transactions
    """
    transactions = []
    current_time = base_timestamp
    test_amounts = [1_000, 2_000, 5_000, 10_000, 15_000]

    # 3-5 small test transactions
    num_tests = random.randint(3, 5)

    for i in range(num_tests):
        gap_minutes = random.uniform(1, 5)
        current_time = current_time + timedelta(minutes=gap_minutes)

        txn = {
            "timestamp": current_time,
            "location": base_location.copy(),
            "amount": random.choice(test_amounts),
            "fraud_injected": FraudType.CARD_TESTING.value,
            "expected_rules": [],  # May not trigger specific rules
            "_debug": {"test_number": i + 1},
        }
        transactions.append(txn)

    # Often followed by a large transaction
    if random.random() < 0.7:
        gap_minutes = random.uniform(2, 10)
        current_time = current_time + timedelta(minutes=gap_minutes)
        large_txn = {
            "timestamp": current_time,
            "location": base_location.copy(),
            "amount": random.randint(1_000_000, 10_000_000),
            "fraud_injected": FraudType.CARD_TESTING.value,
            "expected_rules": [],
            "_debug": {"is_main_fraud_attempt": True},
        }
        transactions.append(large_txn)

    return transactions


def inject_midnight_burst(
    customer_id: str,
    base_date: datetime,
    base_location: List[float]
) -> List[Dict]:
    """
    Generate midnight burst pattern (suspicious late-night activity).

    Args:
        customer_id: Customer ID
        base_date: Base date (will set to midnight)
        base_location: Transaction location

    Returns:
        List of late-night transactions
    """
    transactions = []

    # Start between midnight and 2am
    start_hour = random.randint(0, 2)
    start_minute = random.randint(0, 59)
    current_time = base_date.replace(
        hour=start_hour, minute=start_minute, second=0, microsecond=0
    )

    # 3-7 transactions
    num_txns = random.randint(3, 7)

    for i in range(num_txns):
        gap_minutes = random.uniform(5, 30)
        current_time = current_time + timedelta(minutes=gap_minutes)

        # Keep within midnight-4am window
        if current_time.hour >= 4:
            break

        txn = {
            "timestamp": current_time,
            "location": base_location.copy(),
            "amount": random.randint(100_000, 2_000_000),
            "fraud_injected": FraudType.MIDNIGHT_BURST.value,
            "expected_rules": [],  # No specific rule, pattern-based
            "_debug": {"sequence": i + 1},
        }
        transactions.append(txn)

    return transactions


def inject_account_takeover_pattern(
    customer_id: str,
    base_timestamp: datetime,
    base_location: List[float],
    customer_province: str
) -> List[Dict]:
    """
    Generate account takeover pattern (comprehensive fraud scenario).

    This combines multiple signals:
    1. New device
    2. Password change (simulated via avg_gap_change_password)
    3. Velocity transactions
    4. Unusual amounts
    5. Possible impossible travel

    Args:
        customer_id: Customer ID
        base_timestamp: Starting timestamp
        base_location: Original customer location
        customer_province: Customer's home province

    Returns:
        List of transactions representing ATO pattern
    """
    transactions = []
    current_time = base_timestamp

    # Phase 1: Initial "test" transaction from new device
    txn1 = {
        "timestamp": current_time,
        "location": base_location.copy(),
        "amount": 50_000,  # Small test
        "fraud_injected": FraudType.ACCOUNT_TAKEOVER.value,
        "expected_rules": [],
        "new_device": True,
        "_debug": {"ato_phase": "test"},
    }
    transactions.append(txn1)

    # Phase 2: Quick succession of medium transactions
    for i in range(3):
        current_time = current_time + timedelta(seconds=random.uniform(3, 10))
        txn = {
            "timestamp": current_time,
            "location": base_location.copy(),
            "amount": random.randint(200_000, 500_000),
            "fraud_injected": FraudType.ACCOUNT_TAKEOVER.value,
            "expected_rules": ["velocity"],
            "_debug": {"ato_phase": "drain", "sequence": i + 1},
        }
        transactions.append(txn)

    # Phase 3: Large transfer attempts
    current_time = current_time + timedelta(minutes=random.uniform(1, 5))
    large_txn = {
        "timestamp": current_time,
        "location": base_location.copy(),
        "amount": random.randint(5_000_000, 20_000_000),
        "fraud_injected": FraudType.ACCOUNT_TAKEOVER.value,
        "expected_rules": [],
        "_debug": {"ato_phase": "large_transfer"},
    }
    transactions.append(large_txn)

    return transactions


def generate_fraud_scenario(
    fraud_type: FraudType,
    customer_id: str,
    base_timestamp: datetime,
    base_location: List[float],
    customer_province: str = "DKI Jakarta"
) -> FraudScenario:
    """
    Generate a complete fraud scenario.

    Args:
        fraud_type: Type of fraud to generate
        customer_id: Customer ID
        base_timestamp: Starting timestamp
        base_location: Customer's base location
        customer_province: Customer's province

    Returns:
        FraudScenario with generated transactions
    """
    if fraud_type == FraudType.VELOCITY:
        transactions = inject_velocity_fraud(
            customer_id, base_timestamp, base_location
        )
    elif fraud_type == FraudType.IMPOSSIBLE_TRAVEL:
        transactions = [inject_impossible_travel(
            customer_id, base_timestamp, base_location, customer_province
        )]
    elif fraud_type == FraudType.BLACKLIST_PROXIMITY:
        transactions = [inject_blacklist_proximity(
            customer_id, base_timestamp
        )]
    elif fraud_type == FraudType.CARD_TESTING:
        transactions = inject_card_testing(
            customer_id, base_timestamp, base_location
        )
    elif fraud_type == FraudType.MIDNIGHT_BURST:
        transactions = inject_midnight_burst(
            customer_id, base_timestamp, base_location
        )
    elif fraud_type == FraudType.ACCOUNT_TAKEOVER:
        transactions = inject_account_takeover_pattern(
            customer_id, base_timestamp, base_location, customer_province
        )
    else:
        transactions = []

    return FraudScenario(
        fraud_type=fraud_type,
        customer_id=customer_id,
        base_timestamp=base_timestamp,
        base_location=base_location,
        transactions=transactions,
    )


def select_fraud_for_injection(
    fraud_rate: float = 0.12,
    ato_rate: float = 0.01
) -> Optional[FraudType]:
    """
    Randomly select a fraud type to inject based on rates.

    Args:
        fraud_rate: Overall fraud rate (default 12%)
        ato_rate: Account takeover rate (default 1%)

    Returns:
        FraudType or None if no fraud
    """
    roll = random.random()

    if roll >= fraud_rate:
        return None

    # Among fraudulent transactions, distribution of types
    fraud_distribution = {
        FraudType.VELOCITY: 0.25,
        FraudType.IMPOSSIBLE_TRAVEL: 0.20,
        FraudType.BLACKLIST_PROXIMITY: 0.20,
        FraudType.CARD_TESTING: 0.15,
        FraudType.MIDNIGHT_BURST: 0.10,
        FraudType.ACCOUNT_TAKEOVER: ato_rate / fraud_rate,  # Proportional
        FraudType.UNUSUAL_AMOUNT: 0.05,
        FraudType.NEW_DEVICE: 0.05,
    }

    types = list(fraud_distribution.keys())
    weights = list(fraud_distribution.values())

    return random.choices(types, weights=weights, k=1)[0]
