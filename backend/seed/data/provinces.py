# Indonesian province and city data with detailed coordinates
# Based on actual Indonesian geography and population distribution

import random
import math
from typing import Tuple, List, Dict

# Province distribution for realistic Indonesian banking (based on GDP/banking penetration)
PROVINCE_DISTRIBUTION = {
    "DKI Jakarta": 0.22,        # Financial capital, highest banking activity
    "Jawa Barat": 0.16,         # Most populous province
    "Jawa Timur": 0.12,         # Second most populous
    "Jawa Tengah": 0.10,
    "Banten": 0.07,             # Industrial/commuter belt
    "Sumatera Utara": 0.06,
    "Sulawesi Selatan": 0.04,
    "Bali": 0.04,               # Tourism economy, high digital penetration
    "Kalimantan Timur": 0.03,   # Oil/mining wealth
    "Sumatera Selatan": 0.03,
    "Riau": 0.03,               # Oil wealth
    "Lampung": 0.02,
    "Sumatera Barat": 0.02,
    "Kalimantan Selatan": 0.02,
    "Yogyakarta": 0.02,         # Student population, high digital adoption
    "Nusa Tenggara Barat": 0.01,
    "Papua": 0.01,
}

# Detailed city data with actual coordinates and relative population weights
# Format: city_name: (longitude, latitude, population_weight, is_capital)
PROVINCE_CITIES: Dict[str, Dict[str, Tuple[float, float, float, bool]]] = {
    "DKI Jakarta": {
        "Jakarta Pusat": (106.8451, -6.1862, 0.15, True),
        "Jakarta Selatan": (106.8228, -6.2615, 0.25, False),
        "Jakarta Barat": (106.7656, -6.1680, 0.20, False),
        "Jakarta Timur": (106.9004, -6.2250, 0.20, False),
        "Jakarta Utara": (106.9027, -6.1384, 0.15, False),
        "Kepulauan Seribu": (106.5758, -5.7598, 0.05, False),
    },
    "Jawa Barat": {
        "Bandung": (107.6191, -6.9175, 0.25, True),
        "Bekasi": (107.0006, -6.2349, 0.20, False),
        "Depok": (106.8316, -6.4025, 0.15, False),
        "Bogor": (106.7967, -6.5971, 0.15, False),
        "Cimahi": (107.5423, -6.8841, 0.08, False),
        "Karawang": (107.2975, -6.3227, 0.07, False),
        "Sukabumi": (106.9242, -6.9277, 0.05, False),
        "Tasikmalaya": (108.2022, -7.3506, 0.05, False),
    },
    "Jawa Timur": {
        "Surabaya": (112.7521, -7.2575, 0.35, True),
        "Malang": (112.6326, -7.9666, 0.20, False),
        "Sidoarjo": (112.7183, -7.4478, 0.15, False),
        "Gresik": (112.6508, -7.1622, 0.10, False),
        "Kediri": (112.0178, -7.8480, 0.08, False),
        "Mojokerto": (112.4340, -7.4721, 0.06, False),
        "Madiun": (111.5236, -7.6298, 0.06, False),
    },
    "Jawa Tengah": {
        "Semarang": (110.4203, -6.9666, 0.30, True),
        "Solo": (110.8249, -7.5755, 0.20, False),
        "Kudus": (110.8405, -6.8048, 0.10, False),
        "Pekalongan": (109.6753, -6.8885, 0.10, False),
        "Magelang": (110.2177, -7.4798, 0.08, False),
        "Salatiga": (110.4923, -7.3305, 0.07, False),
        "Purwokerto": (109.2340, -7.4314, 0.08, False),
        "Tegal": (109.1439, -6.8797, 0.07, False),
    },
    "Sumatera Utara": {
        "Medan": (98.6722, 3.5952, 0.45, True),
        "Binjai": (98.4853, 3.6001, 0.12, False),
        "Pematangsiantar": (99.0687, 2.9595, 0.12, False),
        "Tebing Tinggi": (99.1545, 3.3285, 0.08, False),
        "Tanjungbalai": (99.8008, 2.9661, 0.08, False),
        "Sibolga": (98.7891, 1.7427, 0.08, False),
        "Padang Sidempuan": (99.2718, 1.3790, 0.07, False),
    },
    "Banten": {
        "Tangerang": (106.6297, -6.1702, 0.30, False),
        "Tangerang Selatan": (106.7109, -6.2894, 0.25, False),
        "Serang": (106.1503, -6.1103, 0.20, True),
        "Cilegon": (106.0422, -6.0165, 0.15, False),
        "Pandeglang": (106.1062, -6.3089, 0.10, False),
    },
    "Sulawesi Selatan": {
        "Makassar": (119.4327, -5.1477, 0.50, True),
        "Parepare": (119.6256, -4.0135, 0.15, False),
        "Palopo": (120.1967, -2.9926, 0.12, False),
        "Maros": (119.5747, -5.0089, 0.10, False),
        "Gowa": (119.4318, -5.1945, 0.13, False),
    },
    "Bali": {
        "Denpasar": (115.2126, -8.6705, 0.35, True),
        "Badung": (115.1762, -8.5819, 0.25, False),  # Kuta, Seminyak area
        "Gianyar": (115.3226, -8.5445, 0.15, False),  # Ubud area
        "Tabanan": (115.1253, -8.5406, 0.10, False),
        "Buleleng": (115.0920, -8.1120, 0.10, False),  # Singaraja
        "Karangasem": (115.6083, -8.4519, 0.05, False),
    },
    "Kalimantan Timur": {
        "Balikpapan": (116.8529, -1.2654, 0.35, False),
        "Samarinda": (117.1536, -0.4948, 0.35, True),
        "Bontang": (117.4997, 0.1236, 0.15, False),
        "Kutai Kartanegara": (116.9867, -0.3378, 0.10, False),
        "Berau": (117.4902, 2.1547, 0.05, False),
    },
    "Sumatera Selatan": {
        "Palembang": (104.7458, -2.9909, 0.50, True),
        "Lubuklinggau": (102.8614, -3.2971, 0.15, False),
        "Prabumulih": (104.2346, -3.4285, 0.12, False),
        "Pagar Alam": (103.2504, -4.0239, 0.08, False),
        "Banyuasin": (104.6789, -2.8123, 0.15, False),
    },
    "Riau": {
        "Pekanbaru": (101.4500, 0.5071, 0.50, True),
        "Dumai": (101.4478, 1.6668, 0.20, False),
        "Bengkalis": (102.0801, 1.4809, 0.12, False),
        "Kampar": (101.1455, 0.4157, 0.10, False),
        "Siak": (102.1502, 1.1018, 0.08, False),
    },
    "Lampung": {
        "Bandar Lampung": (105.2667, -5.4292, 0.45, True),
        "Metro": (105.3062, -5.1134, 0.20, False),
        "Pringsewu": (104.9743, -5.3582, 0.15, False),
        "Lampung Tengah": (105.2750, -4.7993, 0.12, False),
        "Way Kanan": (104.4344, -4.4333, 0.08, False),
    },
    "Sumatera Barat": {
        "Padang": (100.3543, -0.9471, 0.50, True),
        "Bukittinggi": (100.3695, -0.3055, 0.18, False),
        "Payakumbuh": (100.6310, -0.2172, 0.12, False),
        "Solok": (100.6543, -0.7992, 0.10, False),
        "Pariaman": (100.1179, -0.6265, 0.10, False),
    },
    "Kalimantan Selatan": {
        "Banjarmasin": (114.5943, -3.3186, 0.50, True),
        "Banjarbaru": (114.8413, -3.4575, 0.25, False),
        "Martapura": (114.8430, -3.4167, 0.15, False),
        "Kotabaru": (116.2168, -3.2929, 0.10, False),
    },
    "Yogyakarta": {
        "Yogyakarta": (110.3695, -7.7956, 0.50, True),
        "Sleman": (110.3518, -7.7166, 0.25, False),
        "Bantul": (110.3275, -7.8881, 0.15, False),
        "Kulonprogo": (110.1616, -7.8284, 0.10, False),
    },
    "Nusa Tenggara Barat": {
        "Mataram": (116.1167, -8.5833, 0.45, True),
        "Lombok Timur": (116.5167, -8.4833, 0.25, False),
        "Sumbawa Besar": (117.4197, -8.4895, 0.15, False),
        "Bima": (118.7272, -8.4608, 0.15, False),
    },
    "Papua": {
        "Jayapura": (140.7178, -2.5916, 0.40, True),
        "Merauke": (140.4017, -8.4932, 0.15, False),
        "Timika": (136.8833, -4.5500, 0.20, False),
        "Sorong": (131.2558, -0.8761, 0.15, False),
        "Manokwari": (134.0819, -0.8615, 0.10, False),
    },
}

# Major business districts and shopping areas with precise coordinates
# These are high-transaction areas
BUSINESS_DISTRICTS: Dict[str, List[Tuple[str, float, float]]] = {
    "DKI Jakarta": [
        ("SCBD", 106.8096, -6.2245),
        ("Sudirman", 106.8227, -6.2089),
        ("Thamrin", 106.8236, -6.1954),
        ("Kuningan", 106.8282, -6.2289),
        ("Kemang", 106.8174, -6.2608),
        ("Kelapa Gading", 106.9059, -6.1589),
        ("PIK", 106.7432, -6.1094),
        ("Senayan", 106.8014, -6.2273),
        ("Menteng", 106.8434, -6.1961),
        ("Blok M", 106.7981, -6.2441),
        ("Mangga Dua", 106.8297, -6.1387),
        ("Glodok", 106.8178, -6.1456),
        ("Tanah Abang", 106.8124, -6.1862),
        ("Senen", 106.8445, -6.1757),
    ],
    "Jawa Barat": [
        ("Dago", 107.6165, -6.8728),
        ("Braga", 107.6093, -6.9175),
        ("Summarecon Bekasi", 107.0033, -6.2256),
        ("Lippo Cikarang", 107.1475, -6.3157),
        ("Grand Indonesia Bekasi", 107.0015, -6.2489),
    ],
    "Jawa Timur": [
        ("Tunjungan", 112.7374, -7.2621),
        ("Pakuwon City", 112.7833, -7.2767),
        ("Citraland", 112.6517, -7.2894),
        ("Galaxy Mall", 112.7611, -7.2858),
        ("Town Square Malang", 112.6367, -7.9722),
    ],
    "Bali": [
        ("Kuta", 115.1667, -8.7180),
        ("Seminyak", 115.1601, -8.6867),
        ("Ubud Center", 115.2625, -8.5069),
        ("Sanur", 115.2615, -8.7068),
        ("Nusa Dua", 115.2295, -8.8003),
        ("Canggu", 115.1325, -8.6478),
    ],
}

# Mall/shopping center coordinates (high transaction density)
SHOPPING_CENTERS: Dict[str, List[Tuple[str, float, float]]] = {
    "DKI Jakarta": [
        ("Grand Indonesia", 106.8219, -6.1954),
        ("Plaza Indonesia", 106.8227, -6.1935),
        ("Pacific Place", 106.8096, -6.2245),
        ("Senayan City", 106.7973, -6.2273),
        ("Central Park", 106.7898, -6.1774),
        ("Gandaria City", 106.7841, -6.2442),
        ("Mall Kelapa Gading", 106.9051, -6.1591),
        ("Pondok Indah Mall", 106.7852, -6.2656),
        ("Lippo Mall Kemang", 106.8185, -6.2614),
        ("Kota Kasablanka", 106.8467, -6.2236),
    ],
    "Jawa Barat": [
        ("Paris Van Java", 107.5955, -6.8867),
        ("Trans Studio Bandung", 107.6353, -6.9269),
        ("23 Paskal", 107.5903, -6.9093),
        ("Summarecon Mall Bekasi", 107.0033, -6.2256),
        ("Grand Galaxy Park", 107.0167, -6.2989),
    ],
    "Jawa Timur": [
        ("Tunjungan Plaza", 112.7374, -7.2621),
        ("Pakuwon Mall", 112.6867, -7.2894),
        ("Galaxy Mall", 112.7611, -7.2858),
        ("Grand City Surabaya", 112.7506, -7.2708),
        ("Malang Town Square", 112.6367, -7.9722),
    ],
    "Bali": [
        ("Beachwalk Kuta", 115.1667, -8.7180),
        ("Mall Bali Galeria", 115.1792, -8.7067),
        ("Discovery Mall", 115.1728, -8.7247),
        ("Living World Denpasar", 115.2194, -8.6608),
    ],
}


def weighted_choice_province() -> str:
    """Select a province based on distribution weights."""
    provinces = list(PROVINCE_DISTRIBUTION.keys())
    weights = list(PROVINCE_DISTRIBUTION.values())
    return random.choices(provinces, weights=weights, k=1)[0]


def get_city_for_province(province: str) -> Tuple[str, float, float]:
    """
    Get a weighted random city for the given province.

    Returns:
        Tuple of (city_name, longitude, latitude)
    """
    cities_data = PROVINCE_CITIES.get(province)
    if not cities_data:
        # Fallback to Jakarta
        cities_data = PROVINCE_CITIES["DKI Jakarta"]

    cities = list(cities_data.keys())
    weights = [data[2] for data in cities_data.values()]
    city = random.choices(cities, weights=weights, k=1)[0]

    lon, lat, _, _ = cities_data[city]
    return city, lon, lat


def generate_province_coords(province: str, precision: str = "city") -> List[float]:
    """
    Generate realistic coordinates within a province.

    Args:
        province: Province name
        precision: 'city' (anywhere in city), 'district' (business area),
                  'precise' (specific locations like malls)

    Returns:
        [longitude, latitude]
    """
    city, base_lon, base_lat = get_city_for_province(province)

    if precision == "precise" and province in SHOPPING_CENTERS:
        # Pick a specific shopping center
        if random.random() < 0.3:  # 30% chance of being at a mall
            centers = SHOPPING_CENTERS[province]
            name, lon, lat = random.choice(centers)
            # Tiny jitter (within ~50m)
            lon += random.uniform(-0.0005, 0.0005)
            lat += random.uniform(-0.0005, 0.0005)
            return [lon, lat]

    if precision in ["district", "precise"] and province in BUSINESS_DISTRICTS:
        # Pick a business district with some probability
        if random.random() < 0.4:  # 40% chance of being in business district
            districts = BUSINESS_DISTRICTS[province]
            name, lon, lat = random.choice(districts)
            # Small jitter (within ~200m)
            lon += random.uniform(-0.002, 0.002)
            lat += random.uniform(-0.002, 0.002)
            return [lon, lat]

    # Default: anywhere in the city area
    # Jitter: ±0.03 degrees (~3km) - typical city spread
    lon = base_lon + random.gauss(0, 0.015)  # Gaussian for more central clustering
    lat = base_lat + random.gauss(0, 0.015)

    return [lon, lat]


def generate_home_location(province: str, city: str = None) -> List[float]:
    """
    Generate a realistic home location (residential area).
    Residential areas tend to be further from city centers.
    """
    if city:
        cities_data = PROVINCE_CITIES.get(province, PROVINCE_CITIES["DKI Jakarta"])
        if city in cities_data:
            base_lon, base_lat = cities_data[city][0], cities_data[city][1]
        else:
            _, base_lon, base_lat = get_city_for_province(province)
    else:
        _, base_lon, base_lat = get_city_for_province(province)

    # Residential areas: wider spread, offset from center
    # Use polar coordinates for more natural distribution
    angle = random.uniform(0, 2 * math.pi)
    # Distance: typically 2-10km from center, log-normal distribution
    distance_deg = random.lognormvariate(-4.5, 0.6)  # ~0.01-0.1 degrees
    distance_deg = max(0.005, min(0.15, distance_deg))  # Clamp to 0.5-15km

    lon = base_lon + distance_deg * math.cos(angle)
    lat = base_lat + distance_deg * math.sin(angle)

    return [lon, lat]


def get_province_capital(province: str) -> Tuple[str, float, float]:
    """Get the capital city of a province."""
    cities_data = PROVINCE_CITIES.get(province)
    if not cities_data:
        return "Unknown", 106.8456, -6.2088

    for city, data in cities_data.items():
        if data[3]:  # is_capital
            return city, data[0], data[1]

    # Return first city if no capital marked
    first_city = list(cities_data.keys())[0]
    data = cities_data[first_city]
    return first_city, data[0], data[1]


def calculate_distance_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Calculate distance between two points using Haversine formula."""
    R = 6371  # Earth's radius in km

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c
