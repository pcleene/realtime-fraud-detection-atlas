# Device fingerprinting and IP generation for realistic transaction data
# Based on Indonesian mobile/internet market statistics

import random
import hashlib
import uuid
from typing import Dict, Tuple, List, Optional
from datetime import datetime

# Indonesian ISP ASN ranges (realistic IP allocation)
# Format: (base_ip_parts, weight, isp_name)
INDONESIAN_ISPS = [
    # Telkomsel (largest mobile operator)
    (("114.4.", "114.5.", "114.6.", "114.7."), 0.25, "Telkomsel"),
    (("103.3.", "103.4.", "103.28."), 0.10, "Telkomsel"),

    # Indosat Ooredoo
    (("114.120.", "114.121.", "114.122.", "114.125."), 0.15, "Indosat"),
    (("182.0.", "182.1.", "182.2."), 0.08, "Indosat"),

    # XL Axiata
    (("112.215.", "112.216.", "114.79."), 0.12, "XL"),

    # Telkom Indonesia (fixed broadband)
    (("180.244.", "180.245.", "180.246.", "180.247."), 0.10, "Telkom"),
    (("36.64.", "36.65.", "36.66.", "36.67.", "36.68.", "36.69."), 0.08, "Telkom"),
    (("125.160.", "125.161.", "125.162.", "125.163.", "125.164."), 0.05, "Telkom"),

    # Smartfren
    (("10.133.", "10.134.", "10.135."), 0.04, "Smartfren"),

    # Biznet (fiber ISP)
    (("103.150.", "103.151.", "203.142."), 0.02, "Biznet"),

    # First Media
    (("125.163.", "125.164."), 0.01, "First Media"),
]

# Device models with market share in Indonesia (2024 data)
ANDROID_DEVICES = {
    # Samsung (30% market share)
    "Samsung": [
        ("Galaxy A54", "SM-A546B", 0.15),
        ("Galaxy A34", "SM-A346B", 0.12),
        ("Galaxy A14", "SM-A145F", 0.15),
        ("Galaxy A04s", "SM-A047F", 0.10),
        ("Galaxy S23", "SM-S911B", 0.05),
        ("Galaxy S23 Ultra", "SM-S918B", 0.03),
        ("Galaxy M34", "SM-M346B", 0.08),
        ("Galaxy A24", "SM-A245F", 0.10),
        ("Galaxy Z Flip5", "SM-F731B", 0.02),
    ],
    # Xiaomi/Redmi (25% market share)
    "Xiaomi": [
        ("Redmi Note 12", "2209116AG", 0.20),
        ("Redmi Note 12 Pro", "22101316G", 0.15),
        ("Redmi 12C", "22120RN86G", 0.18),
        ("POCO M5", "22071219CG", 0.12),
        ("Redmi A2", "23028RN4DG", 0.15),
        ("Xiaomi 13", "2211133G", 0.05),
        ("Redmi Note 11", "2201117TG", 0.10),
        ("POCO X5 Pro", "22101320G", 0.05),
    ],
    # OPPO (15% market share)
    "OPPO": [
        ("OPPO A78", "CPH2565", 0.25),
        ("OPPO A58", "CPH2577", 0.20),
        ("OPPO Reno8", "CPH2359", 0.15),
        ("OPPO A17", "CPH2477", 0.20),
        ("OPPO Reno10", "CPH2531", 0.10),
        ("OPPO Find X6 Pro", "CPH2519", 0.05),
        ("OPPO A98", "CPH2529", 0.05),
    ],
    # Vivo (12% market share)
    "Vivo": [
        ("Vivo Y36", "V2248", 0.25),
        ("Vivo Y17s", "V2310", 0.20),
        ("Vivo Y02", "V2217", 0.18),
        ("Vivo V27", "V2231", 0.12),
        ("Vivo Y35", "V2205", 0.15),
        ("Vivo X90 Pro", "V2219", 0.05),
        ("Vivo T1", "V2154", 0.05),
    ],
    # Realme (8% market share)
    "Realme": [
        ("Realme C55", "RMX3710", 0.25),
        ("Realme 11", "RMX3636", 0.20),
        ("Realme C33", "RMX3624", 0.20),
        ("Realme 10", "RMX3630", 0.15),
        ("Realme GT Neo 5", "RMX3708", 0.10),
        ("Realme Narzo 60", "RMX3760", 0.10),
    ],
    # Infinix (5% market share)
    "Infinix": [
        ("Infinix Hot 30", "X6831", 0.30),
        ("Infinix Note 30", "X6833B", 0.25),
        ("Infinix Smart 7", "X6515", 0.25),
        ("Infinix Zero 30", "X6731", 0.10),
        ("Infinix Hot 20", "X6826", 0.10),
    ],
}

# iOS devices (less common in Indonesia ~8%)
IOS_DEVICES = [
    ("iPhone 15 Pro Max", "iPhone16,2", 0.05),
    ("iPhone 15 Pro", "iPhone16,1", 0.05),
    ("iPhone 15", "iPhone15,4", 0.08),
    ("iPhone 14 Pro Max", "iPhone15,3", 0.08),
    ("iPhone 14 Pro", "iPhone15,2", 0.08),
    ("iPhone 14", "iPhone14,7", 0.10),
    ("iPhone 13", "iPhone14,5", 0.15),
    ("iPhone 12", "iPhone13,2", 0.12),
    ("iPhone 11", "iPhone12,1", 0.15),
    ("iPhone SE (3rd)", "iPhone14,6", 0.08),
    ("iPhone XR", "iPhone11,8", 0.06),
]

# Android versions distribution
ANDROID_VERSIONS = [
    ("14", 0.15),
    ("13", 0.35),
    ("12", 0.25),
    ("11", 0.15),
    ("10", 0.08),
    ("9", 0.02),
]

# iOS versions distribution
IOS_VERSIONS = [
    ("17.2", 0.30),
    ("17.1", 0.25),
    ("17.0", 0.15),
    ("16.7", 0.15),
    ("16.6", 0.10),
    ("15.8", 0.05),
]

# Browser/app user agents
USER_AGENTS = {
    "livin": {
        "android": "Livin/{version} (Android {os_version}; {model})",
        "ios": "Livin/{version} (iOS {os_version}; {model})",
    },
    "kopra": {
        "web": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/{chrome_version} Safari/537.36",
    },
}


def generate_indonesian_ip(isp: str = None) -> str:
    """
    Generate a realistic Indonesian IP address.

    Args:
        isp: Specific ISP name, or None for weighted random.

    Returns:
        IP address string
    """
    if isp:
        # Find matching ISP
        for prefixes, weight, isp_name in INDONESIAN_ISPS:
            if isp_name.lower() == isp.lower():
                prefix = random.choice(prefixes)
                break
        else:
            # Fallback to random
            prefix = random.choice(INDONESIAN_ISPS[0][0])
    else:
        # Weighted random selection
        isps = [(prefixes, weight) for prefixes, weight, _ in INDONESIAN_ISPS]
        weights = [w for _, w in isps]
        selected = random.choices(isps, weights=weights, k=1)[0]
        prefix = random.choice(selected[0])

    # Generate last two octets
    if prefix.count('.') == 2:
        # Need 2 more octets
        return f"{prefix}{random.randint(0, 255)}.{random.randint(1, 254)}"
    else:
        # Need 1 more octet
        return f"{prefix}{random.randint(1, 254)}"


def generate_device_fingerprint(
    device_type: str = None,
    sticky_for_customer: bool = False,
    customer_seed: str = None
) -> Dict:
    """
    Generate a realistic device fingerprint.

    Args:
        device_type: 'ios', 'android', or 'web'. None for weighted random.
        sticky_for_customer: If True, generate consistent fingerprint for customer_seed.
        customer_seed: Customer ID for consistent fingerprint generation.

    Returns:
        Dict with device_id, device_type, model, os_version, app_version, etc.
    """
    if sticky_for_customer and customer_seed:
        # Use customer_id as seed for consistent device
        random.seed(hashlib.md5(customer_seed.encode()).hexdigest())

    # Determine device type if not specified
    if device_type is None:
        device_type = random.choices(
            ["android", "ios", "web"],
            weights=[0.85, 0.10, 0.05],  # Indonesian market share
            k=1
        )[0]

    if device_type == "android":
        # Select brand based on market share
        brands = list(ANDROID_DEVICES.keys())
        brand_weights = [0.30, 0.25, 0.15, 0.12, 0.08, 0.10]  # Samsung, Xiaomi, OPPO, Vivo, Realme, Infinix
        brand = random.choices(brands, weights=brand_weights, k=1)[0]

        # Select model
        models = ANDROID_DEVICES[brand]
        model_weights = [m[2] for m in models]
        selected = random.choices(models, weights=model_weights, k=1)[0]
        model_name, model_code, _ = selected

        # OS version
        os_versions, os_weights = zip(*ANDROID_VERSIONS)
        os_version = random.choices(os_versions, weights=os_weights, k=1)[0]

        device_id = f"android_{uuid.uuid4().hex[:16]}"
        fingerprint = {
            "device_id": device_id,
            "device_type": "android",
            "brand": brand,
            "model": model_name,
            "model_code": model_code,
            "os_version": os_version,
            "app_version": f"5.{random.randint(0, 9)}.{random.randint(0, 20)}",
            "screen_resolution": random.choice([
                "1080x2400", "1080x2340", "720x1600", "1080x2376", "1440x3200"
            ]),
        }

    elif device_type == "ios":
        # Select iPhone model
        model_weights = [m[2] for m in IOS_DEVICES]
        selected = random.choices(IOS_DEVICES, weights=model_weights, k=1)[0]
        model_name, model_code, _ = selected

        # iOS version
        os_versions, os_weights = zip(*IOS_VERSIONS)
        os_version = random.choices(os_versions, weights=os_weights, k=1)[0]

        device_id = f"ios_{uuid.uuid4().hex[:16]}"
        fingerprint = {
            "device_id": device_id,
            "device_type": "ios",
            "brand": "Apple",
            "model": model_name,
            "model_code": model_code,
            "os_version": os_version,
            "app_version": f"5.{random.randint(0, 9)}.{random.randint(0, 20)}",
            "screen_resolution": random.choice([
                "1179x2556", "1284x2778", "1170x2532", "1125x2436", "828x1792"
            ]),
        }

    else:  # web
        chrome_version = random.randint(110, 120)
        device_id = f"web_{uuid.uuid4().hex[:16]}"
        fingerprint = {
            "device_id": device_id,
            "device_type": "web",
            "brand": "Browser",
            "model": random.choice(["Chrome", "Safari", "Edge", "Firefox"]),
            "model_code": f"Chrome/{chrome_version}",
            "os_version": "Windows 10" if random.random() < 0.7 else "macOS",
            "app_version": None,
            "screen_resolution": random.choice([
                "1920x1080", "1366x768", "1536x864", "2560x1440", "1440x900"
            ]),
        }

    if sticky_for_customer:
        random.seed()  # Reset seed

    return fingerprint


def generate_device_history(
    customer_id: str,
    num_devices: int = None,
    primary_type: str = None
) -> List[Dict]:
    """
    Generate realistic device history for a customer.
    Most customers use 1-2 devices, with a primary and occasional secondary.

    Args:
        customer_id: Customer ID for consistent generation
        num_devices: Number of devices. None for realistic distribution.
        primary_type: Primary device type preference.

    Returns:
        List of device fingerprints with usage weights
    """
    if num_devices is None:
        # Most users have 1-2 devices
        num_devices = random.choices([1, 2, 3], weights=[0.60, 0.35, 0.05], k=1)[0]

    devices = []

    # Generate primary device
    primary_device = generate_device_fingerprint(
        device_type=primary_type,
        sticky_for_customer=True,
        customer_seed=customer_id
    )
    primary_device["is_primary"] = True
    primary_device["usage_weight"] = 0.85 if num_devices > 1 else 1.0
    primary_device["first_seen"] = datetime.utcnow()
    devices.append(primary_device)

    # Generate secondary devices if needed
    for i in range(1, num_devices):
        secondary_device = generate_device_fingerprint(
            sticky_for_customer=True,
            customer_seed=f"{customer_id}_device_{i}"
        )
        secondary_device["is_primary"] = False
        secondary_device["usage_weight"] = 0.15 / (num_devices - 1)
        secondary_device["first_seen"] = datetime.utcnow()
        devices.append(secondary_device)

    return devices


def generate_session_metadata(
    device: Dict,
    ip: str = None,
    channel: str = "Livin"
) -> Dict:
    """
    Generate session metadata for a transaction.

    Args:
        device: Device fingerprint dict
        ip: IP address, or None to generate
        channel: Transaction channel

    Returns:
        Session metadata dict
    """
    if ip is None:
        ip = generate_indonesian_ip()

    session_id = uuid.uuid4().hex

    metadata = {
        "session_id": session_id,
        "device_id": device["device_id"],
        "device_type": device["device_type"],
        "ip": ip,
        "channel": channel,
    }

    if device["device_type"] in ["android", "ios"]:
        metadata["app_version"] = device.get("app_version", "5.0.0")

    return metadata


# Quick access functions for backward compatibility
def generate_device_id() -> str:
    """Generate a random device ID (backward compat)."""
    fp = generate_device_fingerprint()
    return fp["device_id"]


def generate_ip() -> str:
    """Generate a random Indonesian IP (backward compat)."""
    return generate_indonesian_ip()
