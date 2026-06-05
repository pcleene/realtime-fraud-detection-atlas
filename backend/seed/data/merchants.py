# Indonesian merchant data for realistic transaction generation
# Based on actual Indonesian e-commerce and payment landscape

import random
from typing import Dict, List, Tuple

# MCC (Merchant Category Code) mapping
MCC_CATEGORIES = {
    "5311": "marketplace",
    "5812": "food_delivery",
    "4121": "ride_hailing",
    "5411": "retail",
    "4814": "telco",
    "4900": "utilities",
    "5814": "fast_food",
    "5912": "pharmacy",
    "5942": "bookstore",
    "7832": "entertainment",
    "5732": "electronics",
    "5651": "fashion",
    "5541": "fuel",
    "8011": "healthcare",
    "8211": "education",
}

# Detailed merchant list by category with realistic data
MERCHANTS_BY_CATEGORY: Dict[str, List[Dict]] = {
    "marketplace": [
        # Major e-commerce platforms
        {"id": "M-TOKO001", "name": "Tokopedia", "mcc": "5311", "popularity": 0.30},
        {"id": "M-SHPE001", "name": "Shopee", "mcc": "5311", "popularity": 0.35},
        {"id": "M-BUBL001", "name": "Bukalapak", "mcc": "5311", "popularity": 0.12},
        {"id": "M-LZDA001", "name": "Lazada", "mcc": "5311", "popularity": 0.10},
        {"id": "M-BLBL001", "name": "Blibli", "mcc": "5311", "popularity": 0.08},
        {"id": "M-TKTX001", "name": "TikTok Shop", "mcc": "5311", "popularity": 0.05},
    ],
    "food_delivery": [
        {"id": "M-GFOD001", "name": "GoFood", "mcc": "5812", "popularity": 0.35},
        {"id": "M-GRFD001", "name": "GrabFood", "mcc": "5812", "popularity": 0.30},
        {"id": "M-SHFD001", "name": "ShopeeFood", "mcc": "5812", "popularity": 0.25},
        {"id": "M-MCDO001", "name": "McDonald's Delivery", "mcc": "5814", "popularity": 0.05},
        {"id": "M-KFCD001", "name": "KFC Delivery", "mcc": "5814", "popularity": 0.05},
    ],
    "ride_hailing": [
        {"id": "M-GJEK001", "name": "Gojek", "mcc": "4121", "popularity": 0.45},
        {"id": "M-GRAB001", "name": "Grab", "mcc": "4121", "popularity": 0.40},
        {"id": "M-MXIM001", "name": "Maxim", "mcc": "4121", "popularity": 0.10},
        {"id": "M-INDR001", "name": "InDriver", "mcc": "4121", "popularity": 0.05},
    ],
    "retail": [
        # Convenience stores
        {"id": "M-INDN001", "name": "Indomaret", "mcc": "5411", "popularity": 0.25},
        {"id": "M-ALFA001", "name": "Alfamart", "mcc": "5411", "popularity": 0.25},
        {"id": "M-ALFM001", "name": "Alfamidi", "mcc": "5411", "popularity": 0.08},
        # Supermarkets
        {"id": "M-HRMT001", "name": "Hypermart", "mcc": "5411", "popularity": 0.10},
        {"id": "M-CRFR001", "name": "Transmart Carrefour", "mcc": "5411", "popularity": 0.08},
        {"id": "M-GRNT001", "name": "Giant", "mcc": "5411", "popularity": 0.06},
        {"id": "M-SUPR001", "name": "Superindo", "mcc": "5411", "popularity": 0.06},
        {"id": "M-HERO001", "name": "Hero", "mcc": "5411", "popularity": 0.04},
        # Department stores
        {"id": "M-MTHR001", "name": "Matahari", "mcc": "5311", "popularity": 0.04},
        {"id": "M-RAML001", "name": "Ramayana", "mcc": "5311", "popularity": 0.04},
    ],
    "telco": [
        {"id": "M-TLKM001", "name": "Telkomsel", "mcc": "4814", "popularity": 0.40},
        {"id": "M-ISAT001", "name": "Indosat Ooredoo", "mcc": "4814", "popularity": 0.20},
        {"id": "M-XL01001", "name": "XL Axiata", "mcc": "4814", "popularity": 0.18},
        {"id": "M-3TRI001", "name": "Tri (3)", "mcc": "4814", "popularity": 0.12},
        {"id": "M-SMRT001", "name": "Smartfren", "mcc": "4814", "popularity": 0.10},
    ],
    "utilities": [
        {"id": "M-PLN0001", "name": "PLN", "mcc": "4900", "popularity": 0.50},
        {"id": "M-PDAM001", "name": "PDAM", "mcc": "4900", "popularity": 0.25},
        {"id": "M-PGNS001", "name": "PGN (Gas)", "mcc": "4900", "popularity": 0.15},
        {"id": "M-BPJS001", "name": "BPJS Kesehatan", "mcc": "4900", "popularity": 0.10},
    ],
    "fast_food": [
        {"id": "M-MCDO002", "name": "McDonald's", "mcc": "5814", "popularity": 0.25},
        {"id": "M-KFCS001", "name": "KFC", "mcc": "5814", "popularity": 0.20},
        {"id": "M-BRGK001", "name": "Burger King", "mcc": "5814", "popularity": 0.12},
        {"id": "M-JCOB001", "name": "J.CO", "mcc": "5814", "popularity": 0.10},
        {"id": "M-SBUX001", "name": "Starbucks", "mcc": "5814", "popularity": 0.10},
        {"id": "M-KKDD001", "name": "Kopi Kenangan", "mcc": "5814", "popularity": 0.08},
        {"id": "M-FORS001", "name": "Fore Coffee", "mcc": "5814", "popularity": 0.05},
        {"id": "M-HOKA001", "name": "HokBen", "mcc": "5814", "popularity": 0.05},
        {"id": "M-PIZZ001", "name": "Pizza Hut", "mcc": "5814", "popularity": 0.05},
    ],
    "pharmacy": [
        {"id": "M-KIMT001", "name": "Kimia Farma", "mcc": "5912", "popularity": 0.35},
        {"id": "M-CENT001", "name": "Century", "mcc": "5912", "popularity": 0.25},
        {"id": "M-WTSN001", "name": "Watsons", "mcc": "5912", "popularity": 0.20},
        {"id": "M-GRDN001", "name": "Guardian", "mcc": "5912", "popularity": 0.15},
        {"id": "M-KTWA001", "name": "K-24", "mcc": "5912", "popularity": 0.05},
    ],
    "electronics": [
        {"id": "M-ERAF001", "name": "Erafone", "mcc": "5732", "popularity": 0.30},
        {"id": "M-ELEC001", "name": "Electronic City", "mcc": "5732", "popularity": 0.20},
        {"id": "M-BEST001", "name": "Best Denki", "mcc": "5732", "popularity": 0.15},
        {"id": "M-DJKT001", "name": "Digimap", "mcc": "5732", "popularity": 0.15},
        {"id": "M-IXBX001", "name": "iBox", "mcc": "5732", "popularity": 0.20},
    ],
    "fashion": [
        {"id": "M-UNQL001", "name": "Uniqlo", "mcc": "5651", "popularity": 0.20},
        {"id": "M-ZARA001", "name": "Zara", "mcc": "5651", "popularity": 0.15},
        {"id": "M-HNM0001", "name": "H&M", "mcc": "5651", "popularity": 0.15},
        {"id": "M-MAPS001", "name": "MAP (Multi-brand)", "mcc": "5651", "popularity": 0.20},
        {"id": "M-SOCK001", "name": "Sogo", "mcc": "5651", "popularity": 0.10},
        {"id": "M-TRBL001", "name": "The Body Shop", "mcc": "5651", "popularity": 0.10},
        {"id": "M-SPRT001", "name": "Sports Station", "mcc": "5651", "popularity": 0.10},
    ],
    "fuel": [
        {"id": "M-PERT001", "name": "Pertamina", "mcc": "5541", "popularity": 0.70},
        {"id": "M-SHEL001", "name": "Shell", "mcc": "5541", "popularity": 0.15},
        {"id": "M-VIVO001", "name": "Vivo", "mcc": "5541", "popularity": 0.10},
        {"id": "M-BPGS001", "name": "BP", "mcc": "5541", "popularity": 0.05},
    ],
    "entertainment": [
        {"id": "M-CGVS001", "name": "CGV Cinemas", "mcc": "7832", "popularity": 0.30},
        {"id": "M-XXI0001", "name": "Cinema XXI", "mcc": "7832", "popularity": 0.35},
        {"id": "M-CINP001", "name": "Cinepolis", "mcc": "7832", "popularity": 0.15},
        {"id": "M-SPOT001", "name": "Spotify", "mcc": "7832", "popularity": 0.10},
        {"id": "M-NFLX001", "name": "Netflix", "mcc": "7832", "popularity": 0.10},
    ],
    "healthcare": [
        {"id": "M-SILO001", "name": "RS Siloam", "mcc": "8011", "popularity": 0.25},
        {"id": "M-MRDK001", "name": "RS Mitra Keluarga", "mcc": "8011", "popularity": 0.20},
        {"id": "M-MDKA001", "name": "RS Medika", "mcc": "8011", "popularity": 0.15},
        {"id": "M-PRLD001", "name": "Prodia", "mcc": "8011", "popularity": 0.20},
        {"id": "M-HLDZ001", "name": "Halodoc", "mcc": "8011", "popularity": 0.10},
        {"id": "M-ALDO001", "name": "Alodokter", "mcc": "8011", "popularity": 0.10},
    ],
    "education": [
        {"id": "M-RUMA001", "name": "Ruangguru", "mcc": "8211", "popularity": 0.35},
        {"id": "M-ZENI001", "name": "Zenius", "mcc": "8211", "popularity": 0.25},
        {"id": "M-SKOL001", "name": "Skill Academy", "mcc": "8211", "popularity": 0.20},
        {"id": "M-HACK001", "name": "Hacktiv8", "mcc": "8211", "popularity": 0.10},
        {"id": "M-PURC001", "name": "Purwadhika", "mcc": "8211", "popularity": 0.10},
    ],
}

# Channel to typical merchant category mapping
CHANNEL_MERCHANT_AFFINITY = {
    "Livin": {
        "marketplace": 0.25,
        "food_delivery": 0.20,
        "utilities": 0.15,
        "telco": 0.12,
        "ride_hailing": 0.10,
        "retail": 0.08,
        "fast_food": 0.05,
        "entertainment": 0.05,
    },
    "QRIS": {
        "food_delivery": 0.25,
        "fast_food": 0.20,
        "retail": 0.20,
        "ride_hailing": 0.15,
        "pharmacy": 0.08,
        "fuel": 0.07,
        "fashion": 0.05,
    },
    "ATM": {
        "retail": 0.40,  # ATM withdrawals often at retail
        "fuel": 0.20,
        "pharmacy": 0.15,
        "utilities": 0.15,
        "entertainment": 0.10,
    },
    "Branch": {
        "utilities": 0.40,
        "telco": 0.20,
        "healthcare": 0.15,
        "education": 0.15,
        "retail": 0.10,
    },
    "KOPRA": {
        "utilities": 0.35,
        "marketplace": 0.25,
        "telco": 0.15,
        "healthcare": 0.10,
        "education": 0.10,
        "electronics": 0.05,
    },
    "Ecom": {
        "marketplace": 0.50,
        "fashion": 0.15,
        "electronics": 0.15,
        "entertainment": 0.10,
        "education": 0.10,
    },
}

# Amount ranges by category (min, typical, max in IDR)
CATEGORY_AMOUNT_RANGES = {
    "marketplace": (25_000, 250_000, 10_000_000),
    "food_delivery": (15_000, 50_000, 500_000),
    "ride_hailing": (8_000, 25_000, 200_000),
    "retail": (10_000, 75_000, 2_000_000),
    "telco": (10_000, 50_000, 500_000),
    "utilities": (50_000, 300_000, 5_000_000),
    "fast_food": (20_000, 75_000, 500_000),
    "pharmacy": (20_000, 100_000, 1_000_000),
    "electronics": (100_000, 2_000_000, 50_000_000),
    "fashion": (50_000, 300_000, 5_000_000),
    "fuel": (50_000, 150_000, 500_000),
    "entertainment": (30_000, 100_000, 500_000),
    "healthcare": (100_000, 500_000, 50_000_000),
    "education": (50_000, 500_000, 20_000_000),
}


def get_random_merchant(category: str = None) -> Dict:
    """
    Get a random merchant, optionally from a specific category.

    Args:
        category: Merchant category, or None for weighted random

    Returns:
        Merchant dict with id, name, mcc, category
    """
    if category and category in MERCHANTS_BY_CATEGORY:
        merchants = MERCHANTS_BY_CATEGORY[category]
    else:
        # Select category first based on overall transaction volume
        category_weights = {
            "marketplace": 0.25,
            "food_delivery": 0.18,
            "retail": 0.15,
            "ride_hailing": 0.12,
            "telco": 0.10,
            "utilities": 0.08,
            "fast_food": 0.05,
            "fuel": 0.03,
            "entertainment": 0.02,
            "pharmacy": 0.02,
        }
        categories = list(category_weights.keys())
        weights = list(category_weights.values())
        category = random.choices(categories, weights=weights, k=1)[0]
        merchants = MERCHANTS_BY_CATEGORY.get(category, MERCHANTS_BY_CATEGORY["retail"])

    # Select merchant based on popularity
    popularities = [m["popularity"] for m in merchants]
    selected = random.choices(merchants, weights=popularities, k=1)[0]

    return {
        "id": selected["id"],
        "name": selected["name"],
        "mcc": selected["mcc"],
        "category": category,
    }


def get_merchant_for_channel(channel: str) -> Tuple[Dict, str]:
    """
    Get a merchant appropriate for the transaction channel.

    Args:
        channel: Transaction channel

    Returns:
        Tuple of (merchant_dict, category)
    """
    affinity = CHANNEL_MERCHANT_AFFINITY.get(channel, CHANNEL_MERCHANT_AFFINITY["Livin"])
    categories = list(affinity.keys())
    weights = list(affinity.values())
    category = random.choices(categories, weights=weights, k=1)[0]

    merchant = get_random_merchant(category)
    return merchant, category


def weighted_choice_channel() -> str:
    """Select a channel based on Indonesian market distribution."""
    channels = ["Livin", "QRIS", "ATM", "KOPRA", "Branch", "Ecom"]
    weights = [0.40, 0.25, 0.15, 0.10, 0.07, 0.03]
    return random.choices(channels, weights=weights, k=1)[0]


def generate_amount(channel: str = None, category: str = None) -> float:
    """
    Generate a realistic transaction amount.

    Args:
        channel: Transaction channel
        category: Merchant category

    Returns:
        Amount in IDR
    """
    if category and category in CATEGORY_AMOUNT_RANGES:
        min_amt, typical_amt, max_amt = CATEGORY_AMOUNT_RANGES[category]
    else:
        min_amt, typical_amt, max_amt = 10_000, 100_000, 1_000_000

    # Use log-normal for realistic distribution
    import math
    mu = math.log(typical_amt)
    sigma = 0.7

    amount = random.lognormvariate(mu, sigma)
    amount = max(min_amt, min(max_amt, amount))

    # Round to common denominations
    if amount < 50_000:
        amount = round(amount / 1_000) * 1_000
    elif amount < 500_000:
        amount = round(amount / 5_000) * 5_000
    elif amount < 5_000_000:
        amount = round(amount / 10_000) * 10_000
    else:
        amount = round(amount / 100_000) * 100_000

    return amount
