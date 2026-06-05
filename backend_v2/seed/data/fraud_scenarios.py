"""V2 fraud scenario data for seeding transactions that trigger specific rules."""

import random

# Service codes and their descriptions
SERVICE_CODES = [5, 12, 16, 17, 30, 31, 32, 33, 34, 35, 36, 37, 38, 46]
SERVICE_NAMES = ["Y", "X", "N", "A", "B", "C", "D", "E"]
PURPOSE_CODES = [0, 300, 55555]
DESTINATION_BANKS = ["BRI", "BTN", "RegionalBank", "Bank BCA", "BNI", "CIMB"]
CHANNELS = ["Livin", "KOPRA", "ATM", "QRIS"]


def random_service() -> int:
    return random.choice(SERVICE_CODES)


def random_service_name() -> str:
    return random.choice(SERVICE_NAMES)


def random_purpose() -> int:
    return random.choice(PURPOSE_CODES)


def random_channel() -> str:
    return random.choice(CHANNELS)


def random_bank() -> str:
    return random.choice(DESTINATION_BANKS)
