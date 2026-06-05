"""
V2 Locust load test file with realistic payload generation.

Generates payloads with configurable hit rates for blacklist rules and
known-beneficiary checks, using enriched customer data and blacklist samples
loaded at startup.

Usage:
    locust -f loadtest/locustfile.py --host http://localhost:8001
    locust -f loadtest/locustfile.py --host http://alb.amazonaws.com --master --expect-workers 16
"""

import random
import secrets
from datetime import datetime

from locust import HttpUser, task, between

SERVICE_CODES = [5, 12, 16, 17, 30, 31, 32, 33, 34, 35, 36, 37, 38, 46]
SERVICE_NAMES = ["Y", "X", "N", "A", "B", "C", "D", "E"]
PURPOSE_CODES = [0, 300, 55555]
DESTINATION_BANKS = ["BRI", "BTN", "RegionalBank", "Bank BCA", "BNI", "CIMB"]
CHANNELS = ["Livin", "KOPRA", "ATM", "QRIS"]
DEVICES = ["samsung SM-A546B", "OPPO CPH2565", "Xiaomi 2209116AG", "iPhone 15", "vivo V29"]

# Customer pool loaded at startup
_customer_pool = []        # List of dicts: {"customer_id": str, "b1": str|None, "b24_sample": list}
_blacklist_sample = {}     # {"pot_bf": [...], "pot_anj": [...], "pot_cb": [...], "pot_sm": [...]}
_overflow_pairs = []       # List of dicts: {"customer_id": str, "b2": str}

CUSTOMER_POOL_SIZE = 100_000
CUSTOMER_POOL_ROUND_SIZE = 5_000  # Must stay within 5s MongoDB socketTimeout (~4.6s for 5K from 40M)

# Configurable hit-rate constants
KNOWN_BENEFICIARY_RATE = 0.90
BLACKLIST_BF_RATE = 0.015
BLACKLIST_ANJ_RATE = 0.009
BLACKLIST_CB_RATE = 0.015
SUSPICIOUS_MERCHANT_RATE = 0.05
OVERFLOW_HIT_RATE = 0.000005


def _generate_realistic_b2(customer: dict) -> str:
    """Generate a destination account with realistic hit rates.

    90% of the time: pick from customer's known beneficiaries (var_22 won't fire)
    10% of the time: unknown beneficiary, with small chance of hitting blacklists
    """
    b24_sample = customer.get("b24_sample", [])

    # Known beneficiary path
    if b24_sample and random.random() < KNOWN_BENEFICIARY_RATE:
        return random.choice(b24_sample)

    # Unknown beneficiary path -- occasionally use a real blacklisted value
    roll = random.random()
    if _blacklist_sample.get("pot_bf") and roll < BLACKLIST_BF_RATE:
        return random.choice(_blacklist_sample["pot_bf"])
    elif _blacklist_sample.get("pot_anj") and roll < BLACKLIST_BF_RATE + BLACKLIST_ANJ_RATE:
        return random.choice(_blacklist_sample["pot_anj"])
    elif _blacklist_sample.get("pot_cb") and roll < BLACKLIST_BF_RATE + BLACKLIST_ANJ_RATE + BLACKLIST_CB_RATE:
        return random.choice(_blacklist_sample["pot_cb"])

    # Default: truly random (unknown, not blacklisted)
    return f"{random.randint(1000000000, 9999999999)}"


def _generate_realistic_n2() -> str:
    """Generate a merchant name, occasionally from suspicious merchant list."""
    if _blacklist_sample.get("pot_sm") and random.random() < SUSPICIOUS_MERCHANT_RATE:
        return random.choice(_blacklist_sample["pot_sm"])
    return f"Merchant-{secrets.token_hex(3).upper()}"


def _load_pool(host: str):
    """Load enriched customer pool and blacklist samples from the API.

    Called at module import time so every process (master + workers)
    has the pool before any test starts.

    Uses multiple smaller $sample calls (5x20K) instead of one 100K
    call to avoid MongoDB $sample shard locality bias — each call
    hits a different random cursor start, spreading across all shards.
    """
    global _customer_pool, _blacklist_sample, _overflow_pairs
    import requests as req

    seen_ids = set()
    pool = []

    num_rounds = 25  # 25 × 5K = 125K samples, ~100K after dedup
    per_round = CUSTOMER_POOL_ROUND_SIZE
    print(f"  Loading {CUSTOMER_POOL_SIZE} customers via up to {num_rounds}x{per_round} $sample calls...", flush=True)

    for i in range(num_rounds):
        if len(pool) >= CUSTOMER_POOL_SIZE:
            break
        try:
            resp = req.get(
                f"{host}/mock/customers?limit={per_round}",
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                batch = data.get("customers", [])
                new_count = 0
                for cust in batch:
                    cid = cust["customer_id"]
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        pool.append(cust)
                        new_count += 1
                print(
                    f"  Round {i + 1}/{num_rounds}: fetched {len(batch)}, "
                    f"{new_count} new unique (total: {len(pool)})",
                    flush=True,
                )
            else:
                print(f"  Round {i + 1}: failed with status {resp.status_code}", flush=True)
        except Exception as e:
            print(f"  Round {i + 1}: failed with error {e}", flush=True)

    # Trim to exact target size
    if len(pool) > CUSTOMER_POOL_SIZE:
        pool = pool[:CUSTOMER_POOL_SIZE]

    if pool:
        _customer_pool = pool
        print(f"Loaded {len(_customer_pool)} unique customers from {host}", flush=True)
    else:
        _customer_pool = [
            {"customer_id": f"CUST-{secrets.token_hex(6).upper()}", "b1": None, "b24_sample": []}
            for _ in range(1000)
        ]
        print(f"WARNING: Using {len(_customer_pool)} random customers (fallback) -- expect 404s", flush=True)

    # --- Load blacklist + overflow samples (single call, ~41KB) ---
    try:
        resp = req.get(f"{host}/mock/blacklist-sample", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            _overflow_pairs = data.pop("overflow_pairs", [])
            _blacklist_sample = data
            counts = {k: len(v) for k, v in _blacklist_sample.items()}
            print(f"Loaded blacklist samples: {counts}", flush=True)
            print(f"Loaded overflow pairs: {len(_overflow_pairs)}", flush=True)
        else:
            print(f"WARNING: Failed to load blacklist sample (status {resp.status_code})", flush=True)
            _blacklist_sample = {}
            _overflow_pairs = []
    except Exception as e:
        print(f"WARNING: Failed to load blacklist sample: {e}", flush=True)
        _blacklist_sample = {}
        _overflow_pairs = []


# Load pool at module import time — runs in every process (master + workers)
import os
_POOL_HOST = os.environ.get("LOCUST_HOST", "http://localhost:8001")
_load_pool(_POOL_HOST)


class FraudScoringUser(HttpUser):
    wait_time = between(0.001, 0.01)

    @task
    def score_transaction(self):
        customer = random.choice(_customer_pool)
        customer_id = customer["customer_id"]
        b2 = _generate_realistic_b2(customer)

        # Overflow path: very rarely override both customer_id and b2
        # with a real pot_nb_overflow entry so the 4th DB op finds a match.
        if _overflow_pairs and random.random() < OVERFLOW_HIT_RATE:
            pair = random.choice(_overflow_pairs)
            customer_id = pair["customer_id"]
            b2 = pair["b2"]

        payload = {
            "customer_id": customer_id,
            "b1": customer.get("b1") or f"{random.randint(1000000000, 9999999999)}",
            "b2": b2,
            "c2": f"BENEFICIARY-{secrets.token_hex(4).upper()}",
            "d2": random.choice(DESTINATION_BANKS),
            "n2": _generate_realistic_n2(),
            "at3": random.randint(10000, 5000000),
            "tp": random.choice(PURPOSE_CODES),
            "at7": random.choice([0, 1000, 2500]),
            "service": random.choice(SERVICE_CODES),
            "service_name": random.choice(SERVICE_NAMES),
            "z1": datetime.utcnow().isoformat() + "Z",
            "h1": random.choice(DEVICES),
            "is_financial": 1,
            "channel": random.choice(CHANNELS),
        }
        self.client.post("/score-transaction", json=payload)
