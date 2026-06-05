"""V2 device data for seeding."""

import random
import secrets

DEVICE_MODELS = [
    "samsung SM-A546B", "samsung SM-S918B", "samsung SM-A145F",
    "OPPO CPH2565", "OPPO A78", "Xiaomi 2209116AG", "Xiaomi 22101316G",
    "vivo V2217", "vivo V29", "iPhone 15 Pro", "iPhone 14",
    "Huawei P60", "Realme C55",
]

# Devices that would trigger var_4 (risky device type)
RISKY_DEVICE_MODELS = [
    "rooted-android", "jailbroken-iphone", "emulator-x86",
    "bluestacks", "nox-player",
]

# Devices that would trigger var_25 (high-risk device)
HIGH_RISK_DEVICE_MODELS = [
    "STOLEN-samsung SM-A546B", "STOLEN-OPPO CPH2565",
    "CLONED-xiaomi-2209116AG", "FRAUD-vivo-V2217",
]


def random_device_model(risky_pct: float = 0.02, high_risk_pct: float = 0.01) -> str:
    r = random.random()
    if r < high_risk_pct:
        return random.choice(HIGH_RISK_DEVICE_MODELS)
    if r < high_risk_pct + risky_pct:
        return random.choice(RISKY_DEVICE_MODELS)
    return random.choice(DEVICE_MODELS)
