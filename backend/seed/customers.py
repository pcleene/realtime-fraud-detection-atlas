# Customer seed data generator with realistic profiles

import random
import secrets
from datetime import datetime, timedelta
from typing import Dict, Generator, List

from seed.data.indonesian_names import generate_indonesian_name
from seed.data.provinces import (
    weighted_choice_province,
    get_city_for_province,
    generate_home_location,
)
from seed.data.devices import generate_device_fingerprint
from seed.data.profiles import (
    generate_customer_profile,
    select_segment,
    CustomerProfile,
)


def generate_customer_id() -> str:
    """Generate a random, non-monotonic customer ID."""
    return f"CUST-{secrets.token_hex(6).upper()}"


def generate_account_id() -> str:
    """Generate a random account ID."""
    return f"ACC-{secrets.token_hex(4).upper()}"


def generate_customer(province: str = None, with_profile: bool = False) -> Dict:
    """
    Generate a single customer document with realistic data.

    Args:
        province: Province for the customer. If None, randomly selected.
        with_profile: Include full behavioral profile data.

    Returns:
        Customer document dict ready for MongoDB insertion.
    """
    if province is None:
        province = weighted_choice_province()

    now = datetime.utcnow()

    # Generate name with province-appropriate ethnicity
    name, gender = generate_indonesian_name(province=province)

    # Get city and home location
    city, _, _ = get_city_for_province(province)
    home_location = generate_home_location(province, city)

    # Generate customer ID and accounts
    customer_id = generate_customer_id()

    # Generate 1-3 account IDs
    num_accounts = random.choices([1, 2, 3], weights=[0.7, 0.25, 0.05])[0]
    account_ids = [generate_account_id() for _ in range(num_accounts)]

    # Generate behavioral profile
    profile = generate_customer_profile(
        customer_id=customer_id,
        province=province,
        city=city,
        home_location=home_location,
        name=name,
        gender=gender,
    )

    # 70% have no transaction history yet, 30% have some
    has_history = random.random() < 0.30

    # Generate features based on profile
    features = {
        "latest_time_transaction": None,
        "latest_location": None,
        "avg_gap_change_password": profile.password_change_frequency_days,
    }

    if has_history:
        # Set last transaction time (1-30 days ago)
        features["latest_time_transaction"] = now - timedelta(
            days=random.randint(1, 30),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )
        # Use home location with some variance for last transaction
        last_loc = home_location.copy()
        last_loc[0] += random.gauss(0, 0.01)  # ~1km variance
        last_loc[1] += random.gauss(0, 0.01)
        features["latest_location"] = {
            "type": "Point",
            "coordinates": last_loc,
        }

    # Build customer document
    customer = {
        "customer_id": customer_id,
        "name": name,
        "account_ids": account_ids,
        "province": province,
        "features": features,
        "created_at": now - timedelta(days=random.randint(30, 1800)),
        "updated_at": now,
    }

    # Optionally include extended profile data (for analytics)
    if with_profile:
        customer["_profile"] = {
            "gender": gender,
            "city": city,
            "segment": profile.segment.value,
            "age": profile.age,
            "device_type": profile.device_type,
            "fraud_risk": profile.fraud_risk,
        }

    return customer


def generate_customers_batch(batch_size: int, with_profile: bool = False) -> List[Dict]:
    """Generate a batch of customers."""
    return [generate_customer(with_profile=with_profile) for _ in range(batch_size)]


def customer_generator(
    total: int,
    batch_size: int = 10000,
    with_profile: bool = False
) -> Generator[List[Dict], None, None]:
    """
    Generator that yields batches of customers.

    Args:
        total: Total number of customers to generate
        batch_size: Number of customers per batch
        with_profile: Include behavioral profile data

    Yields:
        Batches of customer documents
    """
    generated = 0
    while generated < total:
        current_batch = min(batch_size, total - generated)
        yield generate_customers_batch(current_batch, with_profile=with_profile)
        generated += current_batch
