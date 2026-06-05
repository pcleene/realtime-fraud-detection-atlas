# Customer behavioral profiles for realistic transaction generation
# Based on actual Indonesian banking user patterns

import random
import math
from datetime import datetime, timedelta, time
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum


class CustomerSegment(Enum):
    """Customer segments based on banking behavior."""
    MASS_MARKET = "mass_market"           # Low-value, high-frequency (majority)
    MASS_AFFLUENT = "mass_affluent"       # Medium-value, regular users
    AFFLUENT = "affluent"                 # High-value, diverse transactions
    HIGH_NET_WORTH = "hnw"                # Very high-value, varied patterns
    STUDENT = "student"                   # Low-value, irregular
    SENIOR = "senior"                     # Traditional, branch-heavy
    MERCHANT = "merchant"                 # High-frequency inflows
    GIG_WORKER = "gig_worker"             # Irregular income, regular small expenses


class TransactionHabit(Enum):
    """Transaction timing habits."""
    MORNING_PERSON = "morning"            # 6am-10am peak
    LUNCH_BREAK = "lunch"                 # 11am-2pm peak
    EVENING_SHOPPER = "evening"           # 6pm-10pm peak
    NIGHT_OWL = "night"                   # 10pm-2am active
    RANDOM = "random"                     # No clear pattern


class SpendingCategory(Enum):
    """Primary spending categories."""
    FOOD_DELIVERY = "food_delivery"
    MARKETPLACE = "marketplace"
    RIDE_HAILING = "ride_hailing"
    BILLS = "bills"
    RETAIL = "retail"
    ENTERTAINMENT = "entertainment"


# Segment distribution in Indonesian banking
SEGMENT_DISTRIBUTION = {
    CustomerSegment.MASS_MARKET: 0.55,
    CustomerSegment.MASS_AFFLUENT: 0.20,
    CustomerSegment.STUDENT: 0.10,
    CustomerSegment.GIG_WORKER: 0.06,
    CustomerSegment.AFFLUENT: 0.05,
    CustomerSegment.SENIOR: 0.03,
    CustomerSegment.HIGH_NET_WORTH: 0.01,
}

# Segment characteristics
SEGMENT_PROFILES = {
    CustomerSegment.MASS_MARKET: {
        "age_range": (25, 45),
        "monthly_income_idr": (3_000_000, 10_000_000),
        "avg_balance_idr": (500_000, 5_000_000),
        "monthly_txn_count": (15, 40),
        "avg_txn_amount_idr": (25_000, 150_000),
        "max_txn_amount_idr": 2_000_000,
        "primary_channels": ["Livin", "QRIS"],
        "channel_weights": {"Livin": 0.50, "QRIS": 0.35, "ATM": 0.10, "Branch": 0.03, "KOPRA": 0.02},
        "primary_merchants": ["food_delivery", "marketplace", "ride_hailing", "retail"],
        "device_preference": {"android": 0.92, "ios": 0.05, "web": 0.03},
        "habits": [TransactionHabit.LUNCH_BREAK, TransactionHabit.EVENING_SHOPPER],
        "weekend_multiplier": 1.3,
        "fraud_risk": "low",
    },
    CustomerSegment.MASS_AFFLUENT: {
        "age_range": (30, 50),
        "monthly_income_idr": (10_000_000, 30_000_000),
        "avg_balance_idr": (5_000_000, 30_000_000),
        "monthly_txn_count": (25, 60),
        "avg_txn_amount_idr": (100_000, 500_000),
        "max_txn_amount_idr": 10_000_000,
        "primary_channels": ["Livin", "QRIS", "ATM"],
        "channel_weights": {"Livin": 0.55, "QRIS": 0.25, "ATM": 0.12, "KOPRA": 0.05, "Branch": 0.03},
        "primary_merchants": ["marketplace", "food_delivery", "retail", "utilities"],
        "device_preference": {"android": 0.80, "ios": 0.15, "web": 0.05},
        "habits": [TransactionHabit.EVENING_SHOPPER, TransactionHabit.LUNCH_BREAK],
        "weekend_multiplier": 1.5,
        "fraud_risk": "medium",
    },
    CustomerSegment.AFFLUENT: {
        "age_range": (35, 55),
        "monthly_income_idr": (30_000_000, 100_000_000),
        "avg_balance_idr": (30_000_000, 200_000_000),
        "monthly_txn_count": (30, 80),
        "avg_txn_amount_idr": (300_000, 2_000_000),
        "max_txn_amount_idr": 50_000_000,
        "primary_channels": ["Livin", "KOPRA", "ATM"],
        "channel_weights": {"Livin": 0.45, "KOPRA": 0.25, "QRIS": 0.15, "ATM": 0.10, "Branch": 0.05},
        "primary_merchants": ["marketplace", "retail", "utilities", "telco"],
        "device_preference": {"android": 0.60, "ios": 0.35, "web": 0.05},
        "habits": [TransactionHabit.MORNING_PERSON, TransactionHabit.EVENING_SHOPPER],
        "weekend_multiplier": 1.2,
        "fraud_risk": "high",  # More attractive target
    },
    CustomerSegment.HIGH_NET_WORTH: {
        "age_range": (40, 65),
        "monthly_income_idr": (100_000_000, 1_000_000_000),
        "avg_balance_idr": (200_000_000, 2_000_000_000),
        "monthly_txn_count": (20, 50),
        "avg_txn_amount_idr": (1_000_000, 20_000_000),
        "max_txn_amount_idr": 500_000_000,
        "primary_channels": ["KOPRA", "Livin", "Branch"],
        "channel_weights": {"KOPRA": 0.40, "Livin": 0.30, "Branch": 0.20, "ATM": 0.08, "QRIS": 0.02},
        "primary_merchants": ["utilities", "retail", "marketplace"],
        "device_preference": {"android": 0.40, "ios": 0.55, "web": 0.05},
        "habits": [TransactionHabit.MORNING_PERSON],
        "weekend_multiplier": 0.8,
        "fraud_risk": "very_high",  # Prime target
    },
    CustomerSegment.STUDENT: {
        "age_range": (18, 25),
        "monthly_income_idr": (500_000, 3_000_000),
        "avg_balance_idr": (100_000, 1_000_000),
        "monthly_txn_count": (20, 50),
        "avg_txn_amount_idr": (10_000, 75_000),
        "max_txn_amount_idr": 500_000,
        "primary_channels": ["QRIS", "Livin"],
        "channel_weights": {"QRIS": 0.50, "Livin": 0.40, "ATM": 0.08, "Branch": 0.02},
        "primary_merchants": ["food_delivery", "ride_hailing", "marketplace"],
        "device_preference": {"android": 0.93, "ios": 0.05, "web": 0.02},
        "habits": [TransactionHabit.NIGHT_OWL, TransactionHabit.RANDOM],
        "weekend_multiplier": 1.4,
        "fraud_risk": "low",
    },
    CustomerSegment.SENIOR: {
        "age_range": (55, 75),
        "monthly_income_idr": (5_000_000, 20_000_000),
        "avg_balance_idr": (10_000_000, 100_000_000),
        "monthly_txn_count": (5, 15),
        "avg_txn_amount_idr": (200_000, 1_000_000),
        "max_txn_amount_idr": 20_000_000,
        "primary_channels": ["ATM", "Branch", "Livin"],
        "channel_weights": {"ATM": 0.40, "Branch": 0.30, "Livin": 0.25, "QRIS": 0.05},
        "primary_merchants": ["utilities", "retail", "telco"],
        "device_preference": {"android": 0.85, "ios": 0.10, "web": 0.05},
        "habits": [TransactionHabit.MORNING_PERSON],
        "weekend_multiplier": 0.7,
        "fraud_risk": "medium",  # Vulnerable to scams
    },
    CustomerSegment.GIG_WORKER: {
        "age_range": (22, 40),
        "monthly_income_idr": (2_000_000, 8_000_000),
        "avg_balance_idr": (200_000, 2_000_000),
        "monthly_txn_count": (30, 80),
        "avg_txn_amount_idr": (15_000, 100_000),
        "max_txn_amount_idr": 1_000_000,
        "primary_channels": ["QRIS", "Livin"],
        "channel_weights": {"QRIS": 0.55, "Livin": 0.35, "ATM": 0.08, "Branch": 0.02},
        "primary_merchants": ["food_delivery", "ride_hailing", "telco", "retail"],
        "device_preference": {"android": 0.95, "ios": 0.03, "web": 0.02},
        "habits": [TransactionHabit.RANDOM, TransactionHabit.EVENING_SHOPPER],
        "weekend_multiplier": 1.6,
        "fraud_risk": "low",
    },
}

# Time-of-day distributions for each habit
HABIT_TIME_DISTRIBUTIONS = {
    TransactionHabit.MORNING_PERSON: {
        # Hour: weight
        6: 0.08, 7: 0.15, 8: 0.20, 9: 0.18, 10: 0.12,
        11: 0.08, 12: 0.06, 13: 0.04, 14: 0.03, 15: 0.02,
        16: 0.01, 17: 0.01, 18: 0.01, 19: 0.01,
    },
    TransactionHabit.LUNCH_BREAK: {
        10: 0.05, 11: 0.12, 12: 0.25, 13: 0.22, 14: 0.15,
        15: 0.08, 16: 0.05, 17: 0.03, 18: 0.02, 19: 0.02, 20: 0.01,
    },
    TransactionHabit.EVENING_SHOPPER: {
        10: 0.02, 11: 0.03, 12: 0.05, 13: 0.05, 14: 0.05,
        15: 0.05, 16: 0.08, 17: 0.10, 18: 0.15, 19: 0.18,
        20: 0.12, 21: 0.08, 22: 0.04,
    },
    TransactionHabit.NIGHT_OWL: {
        14: 0.02, 15: 0.03, 16: 0.05, 17: 0.05, 18: 0.08,
        19: 0.10, 20: 0.15, 21: 0.18, 22: 0.15, 23: 0.10,
        0: 0.05, 1: 0.03, 2: 0.01,
    },
    TransactionHabit.RANDOM: {
        h: 1.0 / 24 for h in range(24)  # Uniform distribution
    },
}


@dataclass
class CustomerProfile:
    """Complete customer behavioral profile."""
    customer_id: str
    segment: CustomerSegment
    province: str
    city: str
    home_location: List[float]

    # Demographics
    name: str
    gender: str
    age: int
    monthly_income: float
    avg_balance: float

    # Behavior
    primary_habit: TransactionHabit
    secondary_habit: Optional[TransactionHabit]
    monthly_txn_count: int
    avg_txn_amount: float
    max_txn_amount: float

    # Preferences
    channel_weights: Dict[str, float]
    merchant_preferences: List[str]
    device_type: str

    # Risk factors
    fraud_risk: str
    password_change_frequency_days: float  # Average days between password changes

    # State (for transaction generation)
    last_txn_time: Optional[datetime] = None
    last_txn_location: Optional[List[float]] = None
    devices: List[Dict] = field(default_factory=list)


def select_segment() -> CustomerSegment:
    """Select a customer segment based on distribution."""
    segments = list(SEGMENT_DISTRIBUTION.keys())
    weights = list(SEGMENT_DISTRIBUTION.values())
    return random.choices(segments, weights=weights, k=1)[0]


def generate_customer_profile(
    customer_id: str,
    province: str,
    city: str,
    home_location: List[float],
    name: str,
    gender: str,
    segment: CustomerSegment = None
) -> CustomerProfile:
    """
    Generate a complete customer behavioral profile.

    Args:
        customer_id: Unique customer ID
        province: Customer's province
        city: Customer's city
        home_location: [lon, lat] of residence
        name: Customer name
        gender: 'male' or 'female'
        segment: Customer segment, or None for random weighted selection

    Returns:
        CustomerProfile with all behavioral attributes
    """
    if segment is None:
        segment = select_segment()

    profile_data = SEGMENT_PROFILES[segment]

    # Generate demographics
    age = random.randint(*profile_data["age_range"])
    monthly_income = random.uniform(*profile_data["monthly_income_idr"])
    avg_balance = random.uniform(*profile_data["avg_balance_idr"])

    # Generate transaction behavior
    monthly_txn_count = random.randint(*profile_data["monthly_txn_count"])
    avg_txn_amount = random.uniform(*profile_data["avg_txn_amount_idr"])
    max_txn_amount = profile_data["max_txn_amount_idr"]

    # Select habits
    habits = profile_data["habits"]
    primary_habit = random.choice(habits)
    secondary_habit = random.choice(habits) if len(habits) > 1 and random.random() < 0.5 else None

    # Select device type
    device_types = list(profile_data["device_preference"].keys())
    device_weights = list(profile_data["device_preference"].values())
    device_type = random.choices(device_types, weights=device_weights, k=1)[0]

    # Password change frequency (risky vs normal)
    if random.random() < 0.20:  # 20% have risky password patterns
        password_freq = random.uniform(3, 10)  # Too frequent
    else:
        password_freq = random.gauss(90, 30)  # Normal: ~3 months
        password_freq = max(30, password_freq)  # At least monthly

    return CustomerProfile(
        customer_id=customer_id,
        segment=segment,
        province=province,
        city=city,
        home_location=home_location,
        name=name,
        gender=gender,
        age=age,
        monthly_income=monthly_income,
        avg_balance=avg_balance,
        primary_habit=primary_habit,
        secondary_habit=secondary_habit,
        monthly_txn_count=monthly_txn_count,
        avg_txn_amount=avg_txn_amount,
        max_txn_amount=max_txn_amount,
        channel_weights=profile_data["channel_weights"].copy(),
        merchant_preferences=profile_data["primary_merchants"].copy(),
        device_type=device_type,
        fraud_risk=profile_data["fraud_risk"],
        password_change_frequency_days=password_freq,
    )


def generate_transaction_time(
    profile: CustomerProfile,
    base_date: datetime = None,
    is_weekend: bool = None
) -> datetime:
    """
    Generate a realistic transaction timestamp based on customer habits.

    Args:
        profile: Customer profile
        base_date: Base date for transaction. None for today.
        is_weekend: Override weekend detection.

    Returns:
        datetime for transaction
    """
    if base_date is None:
        base_date = datetime.utcnow()

    if is_weekend is None:
        is_weekend = base_date.weekday() >= 5

    # Select habit to use (80% primary, 20% secondary if exists)
    if profile.secondary_habit and random.random() < 0.2:
        habit = profile.secondary_habit
    else:
        habit = profile.primary_habit

    # Get time distribution
    time_dist = HABIT_TIME_DISTRIBUTIONS[habit]
    hours = list(time_dist.keys())
    weights = list(time_dist.values())

    # Select hour
    hour = random.choices(hours, weights=weights, k=1)[0]

    # Add some variance
    minute = random.randint(0, 59)
    second = random.randint(0, 59)

    # Apply weekend modifier (more spread out on weekends)
    if is_weekend and random.random() < 0.3:
        # Shift later on weekends
        hour = (hour + random.randint(1, 3)) % 24

    return base_date.replace(hour=hour, minute=minute, second=second, microsecond=0)


def generate_transaction_amount(
    profile: CustomerProfile,
    channel: str = None,
    merchant_category: str = None
) -> float:
    """
    Generate a realistic transaction amount based on profile and context.

    Args:
        profile: Customer profile
        channel: Transaction channel
        merchant_category: Merchant category

    Returns:
        Transaction amount in IDR
    """
    base_amount = profile.avg_txn_amount

    # Channel modifier
    channel_modifiers = {
        "QRIS": 0.5,      # QRIS typically smaller transactions
        "Livin": 1.0,
        "ATM": 2.5,       # ATM withdrawals tend to be larger
        "Branch": 5.0,    # Branch transactions are often larger
        "KOPRA": 3.0,     # Corporate banking, larger amounts
        "Ecom": 1.5,      # E-commerce moderate
    }
    modifier = channel_modifiers.get(channel, 1.0)

    # Merchant category modifier
    merchant_modifiers = {
        "food_delivery": 0.4,
        "ride_hailing": 0.3,
        "marketplace": 1.2,
        "retail": 0.8,
        "utilities": 1.5,
        "telco": 0.6,
    }
    if merchant_category:
        modifier *= merchant_modifiers.get(merchant_category, 1.0)

    # Generate with log-normal distribution
    mu = math.log(base_amount * modifier)
    sigma = 0.6

    amount = random.lognormvariate(mu, sigma)

    # Clamp to reasonable bounds
    amount = max(5_000, min(profile.max_txn_amount, amount))

    # Round to common denomination
    if amount < 100_000:
        amount = round(amount / 1_000) * 1_000
    elif amount < 1_000_000:
        amount = round(amount / 10_000) * 10_000
    else:
        amount = round(amount / 100_000) * 100_000

    return amount


def select_channel(profile: CustomerProfile) -> str:
    """Select a transaction channel based on profile preferences."""
    channels = list(profile.channel_weights.keys())
    weights = list(profile.channel_weights.values())
    return random.choices(channels, weights=weights, k=1)[0]


def select_merchant_category(profile: CustomerProfile) -> str:
    """Select a merchant category based on profile preferences."""
    # Weight preferred categories more heavily
    all_categories = ["food_delivery", "marketplace", "ride_hailing", "retail", "utilities", "telco"]
    weights = []
    for cat in all_categories:
        if cat in profile.merchant_preferences[:2]:
            weights.append(3.0)
        elif cat in profile.merchant_preferences:
            weights.append(1.5)
        else:
            weights.append(0.3)

    return random.choices(all_categories, weights=weights, k=1)[0]
