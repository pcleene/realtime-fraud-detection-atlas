# Blacklist location seed data generator

import random
from datetime import datetime
from typing import Dict, List

# City coordinates (center)
CITY_COORDINATES = {
    "Jakarta": (106.8456, -6.2088),
    "Surabaya": (112.7521, -7.2575),
    "Bandung": (107.6191, -6.9175),
    "Medan": (98.6722, 3.5952),
    "Denpasar": (115.2126, -8.6705),
}

CITY_TO_PROVINCE = {
    "Jakarta": "DKI Jakarta",
    "Surabaya": "Jawa Timur",
    "Bandung": "Jawa Barat",
    "Medan": "Sumatera Utara",
    "Denpasar": "Bali",
}

# City distribution
CITY_DISTRIBUTION = {
    "Jakarta": 0.40,
    "Surabaya": 0.20,
    "Bandung": 0.15,
    "Medan": 0.15,
    "Denpasar": 0.10,
}

# Category distribution
CATEGORY_DISTRIBUTION = {
    "fraud_hub": 0.20,
    "scammer": 0.30,
    "wifi": 0.30,
    "merchant": 0.20,
}

# Street name components for generating addresses
STREET_PREFIXES = ["Jl.", "Gang", "Komplek"]
STREET_NAMES = [
    "Mangga Dua", "Glodok", "Tanah Abang", "Senen", "Kota",
    "Blok M", "Kemang", "Sudirman", "Thamrin", "Gatot Subroto",
    "Raya", "Merdeka", "Diponegoro", "Ahmad Yani", "Veteran",
    "Pasar Baru", "Gajah Mada", "Hayam Wuruk", "Panglima Polim",
]


def generate_street_address(city: str) -> str:
    """Generate a realistic street address."""
    prefix = random.choice(STREET_PREFIXES)
    street = random.choice(STREET_NAMES)
    number = random.randint(1, 200)
    return f"{prefix} {street} No. {number}"


def generate_blacklist_location(city: str = None) -> Dict:
    """
    Generate a single blacklist location document.

    Args:
        city: City for the location. If None, randomly selected.

    Returns:
        Blacklist location document dict ready for MongoDB insertion.
    """
    if city is None:
        cities = list(CITY_DISTRIBUTION.keys())
        weights = list(CITY_DISTRIBUTION.values())
        city = random.choices(cities, weights=weights, k=1)[0]

    base_coords = CITY_COORDINATES[city]
    # Add jitter: ±0.01 degrees (~1km)
    coords = [
        base_coords[0] + random.uniform(-0.01, 0.01),
        base_coords[1] + random.uniform(-0.01, 0.01),
    ]

    # Select category
    categories = list(CATEGORY_DISTRIBUTION.keys())
    cat_weights = list(CATEGORY_DISTRIBUTION.values())
    category = random.choices(categories, weights=cat_weights, k=1)[0]

    reasons = {
        "fraud_hub": "Reported fraud cluster - multiple incidents",
        "scammer": "Known scammer operation location",
        "wifi": "Public WiFi hotspot with fraud history",
        "merchant": "Suspicious merchant activity reported",
    }

    return {
        "address": generate_street_address(city),
        "city": city,
        "province": CITY_TO_PROVINCE[city],
        "location": {
            "type": "Point",
            "coordinates": coords,
        },
        "category": category,
        "normalized": [],
        "added_at": datetime.utcnow(),
        "added_reason": reasons[category],
    }


def generate_blacklist_locations(count: int = 100) -> List[Dict]:
    """
    Generate blacklist locations.

    Args:
        count: Number of locations to generate

    Returns:
        List of blacklist location documents
    """
    return [generate_blacklist_location() for _ in range(count)]
