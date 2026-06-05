"""Generate V2 transaction documents for seeding.

Transactions are generated with rolling-state-aware fraud scoring.
Each transaction reads the customer's in-memory rolling state, computes
a realistic fraud score using actual rule logic, and returns the document
ready for insert_many.
"""

import logging
import math
import random
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from seed.data.fraud_scenarios import (
    random_service, random_service_name, random_purpose,
    random_channel, random_bank,
)
from seed.data.devices import DEVICE_MODELS

logger = logging.getLogger(__name__)


def compute_shard_key_month(z1: datetime) -> str:
    return z1.strftime("%Y-%m")


def generate_transaction(
    customer_id: str,
    b1: str,
    rolling: dict,
    z1: datetime,
    caches,
    settings,
) -> dict:
    """Generate a single transaction document with realistic fraud scoring.

    Args:
        customer_id: Customer ID
        b1: Customer's primary account number (from rolling state)
        rolling: In-memory rolling state dict for this customer
        z1: Transaction timestamp
        caches: SeedCaches with blacklist + service config
        settings: App settings

    Returns:
        Transaction document ready for insert_many
    """
    at3 = random.randint(10_000, 5_000_000)
    tp = random_purpose()
    service = random_service()

    # Occasionally pick from blacklisted accounts/merchants so blacklist
    # rules (var_1, var_5, var_6, var_23) trigger during seed scoring.
    # Hit rates are realistic: ~1% for account lists, ~0.5% for merchants.
    bl = caches.blacklist if caches else None

    r = random.random()
    if bl and bl.dest_accounts_list and r < 0.005:
        b2 = random.choice(bl.dest_accounts_list)  # var_1 hit
    elif bl and bl.gambling_accounts_list and r < 0.01:
        b2 = random.choice(bl.gambling_accounts_list)  # var_6 hit
    elif bl and bl.watchlist_accounts_list and r < 0.015:
        b2 = random.choice(bl.watchlist_accounts_list)  # var_23 hit
    else:
        b2 = f"{random.randint(1000000000, 9999999999)}"

    if bl and bl.suspicious_merchants_list and random.random() < 0.005:
        n2 = random.choice(bl.suspicious_merchants_list)  # var_5 hit (already lowercased)
    else:
        n2 = f"Merchant-{secrets.token_hex(3).upper()}"

    txn_fields = {
        "customer_id": customer_id,
        "at3": at3,
        "tp": tp,
        "service": service,
        "b2": b2,
        "n2": n2,
        "z1": z1,
    }

    # Compute realistic fraud score using actual rule logic
    if settings.seed_compute_fraud_scores:
        from seed.scoring import score_transaction_for_seed
        fraud_score = score_transaction_for_seed(txn_fields, rolling, caches, settings)
    else:
        fraud_score = {
            "final_score": 0,
            "risk_level": "low",
            "rule_scores": {},
            "triggered_count": 0,
        }

    doc = {
        "customer_id": customer_id,
        "shard_key_month": compute_shard_key_month(z1),
        "z1": z1,
        "at3": at3,
        "at7": random.choice([0, 1000, 2500]),
        "tp": tp,
        "b1": b1,
        "service": service,
        "service_name": random_service_name(),
        "is_financial": 1,
        "status": "SUCCESS",
        "pot_dataset_dest": {
            "b2": b2,
            "c2": f"BENEFICIARY-{secrets.token_hex(4).upper()}",
            "d2": random_bank(),
            "n2": n2,
        },
        "pot_master_id_dp": {
            "h1": random.choice(DEVICE_MODELS),
            "channel": random_channel(),
        },
        "location": None,
        "fraud_score": fraud_score,
    }

    return doc


def update_rolling_state(rolling: dict, txn: dict, settings) -> None:
    """Update in-memory rolling state after a transaction.

    Mirrors the update logic in app.services.fraud._build_customer_update()
    but operates on a plain dict instead of MongoDB $set/$push.

    Args:
        rolling: In-memory rolling state dict (mutated in place)
        txn: Transaction document (from generate_transaction)
        settings: App settings for window sizes and limits
    """
    z1 = txn["z1"]
    at3 = txn["at3"]
    tp = txn["tp"]
    service = txn["service"]
    b2 = txn["pot_dataset_dest"]["b2"]

    # Update previous amounts
    rolling["at3_prev2"] = rolling["at3_prev"]
    rolling["at3_prev"] = at3

    # Update z1_prev
    rolling["z1_prev"] = z1

    # Append to at3_recent (trim to limit)
    limit = settings.recent_amounts_limit
    at3_recent = rolling.get("at3_recent", [])
    at3_recent.append(at3)
    if len(at3_recent) > limit:
        at3_recent = at3_recent[-limit:]
    rolling["at3_recent"] = at3_recent

    # Append to tp_recent (trim to limit)
    tp_limit = settings.recent_purposes_limit
    tp_recent = rolling.get("tp_recent", [])
    tp_recent.append(tp)
    if len(tp_recent) > tp_limit:
        tp_recent = tp_recent[-tp_limit:]
    rolling["tp_recent"] = tp_recent

    # Update at3_sum with window reset check
    window_start = rolling.get("window_start")
    window_reset = False
    if window_start is not None:
        w_start = window_start.replace(tzinfo=None) if hasattr(window_start, 'tzinfo') and window_start.tzinfo else window_start
        z1_n = z1.replace(tzinfo=None) if z1.tzinfo else z1
        hours_elapsed = (z1_n - w_start).total_seconds() / 3600
        if hours_elapsed > settings.cumulative_window_hours:
            window_reset = True
    else:
        window_reset = True  # first transaction

    if window_reset:
        rolling["at3_sum"] = at3
        rolling["window_start"] = z1
        rolling["bl_window_start"] = rolling.get("bl")
    else:
        rolling["at3_sum"] = rolling.get("at3_sum", 0) + at3

    # Recalculate at6 (std dev) from at3_recent
    if len(at3_recent) >= 2:
        mean = sum(at3_recent) / len(at3_recent)
        variance = sum((x - mean) ** 2 for x in at3_recent) / len(at3_recent)
        rolling["at6"] = math.sqrt(variance)
    else:
        rolling["at6"] = 0

    # Add service to service_ever if new
    if service not in rolling.get("service_ever", []):
        rolling.setdefault("service_ever", []).append(service)

    # Add beneficiary to b24_list if new (cap at embed limit)
    b24_list = rolling.get("b24_list", [])
    if b2 not in b24_list:
        if len(b24_list) < settings.beneficiary_embed_limit:
            b24_list.append(b2)
            rolling["b24_list"] = b24_list
        rolling["b24_count"] = rolling.get("b24_count", 0) + 1


def random_datetime(start: datetime, end: datetime) -> datetime:
    """Generate a random datetime between start and end."""
    delta = (end - start).total_seconds()
    random_seconds = random.uniform(0, delta)
    return start + timedelta(seconds=random_seconds)
