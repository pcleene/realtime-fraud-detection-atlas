"""Generate V2 customer documents for seeding.

Rolling fields derived from transactions (z1_prev, at3_prev, at3_recent, etc.)
are initialized to None/empty. Phase 3 populates them from actual generated
transactions via the chunked pagination loop.
"""

import logging
import random
import secrets
from datetime import datetime, timedelta
from typing import Dict, List

from seed.data.devices import random_device_model, RISKY_DEVICE_MODELS, HIGH_RISK_DEVICE_MODELS
from seed.data.fraud_scenarios import SERVICE_CODES
from seed.data.loan_providers import LOAN_PROVIDERS

logger = logging.getLogger(__name__)


def generate_customer_id() -> str:
    return f"CUST-{secrets.token_hex(6).upper()}"


def generate_customer_doc(
    customer_id: str = None,
    blacklist_accounts: Dict[str, set] = None,
) -> dict:
    """Generate a single V2 customer document with empty rolling state.

    Transaction-derived rolling fields (z1_prev, at3_prev, at3_recent, etc.)
    are set to None/empty and will be populated during Phase 3 chunked
    transaction generation.
    """
    if customer_id is None:
        customer_id = generate_customer_id()

    now = datetime.utcnow()
    reg_date = now - timedelta(days=random.randint(30, 3650))

    # Device profile
    device_model = random_device_model()
    devices = [{"h1": device_model, "r": reg_date}]

    # Flags (pre-computed blacklist membership)
    flags = {
        "var_3": random.random() < 0.02,   # 2% email blacklisted
        "var_4": device_model in RISKY_DEVICE_MODELS,
        "var_7": random.random() < 0.02,   # 2% phone blacklisted
        "var_25": device_model in HIGH_RISK_DEVICE_MODELS,
    }

    # Service history
    num_services = random.randint(1, 6)
    service_ever = random.sample(SERVICE_CODES, min(num_services, len(SERVICE_CODES)))

    # Beneficiary list (b24) — realistic Indonesian consumer banking distribution.
    # Most consumers transfer to 5-20 people. 500+ is money mule territory.
    # Only 0.5% overflow to pot_nb_overflow (4th DB op in hot path).
    b24_count = random.choices(
        [random.randint(0, 20), random.randint(20, 100), random.randint(100, 300), random.randint(300, 500), random.randint(500, 800)],
        weights=[60, 30, 8, 1.5, 0.5],
    )[0]
    b24_list = [f"{random.randint(1000000000, 9999999999)}" for _ in range(min(b24_count, 500))]

    balance = random.uniform(100_000, 50_000_000)

    # Rolling fields — transaction-derived fields default to None/empty.
    # Customer attributes (z3, z4, bl, b1, pt_latest, w2_latest, etc.) are
    # initialized here since they're intrinsic to the customer.
    rolling = {
        # Transaction-derived (populated by Phase 3 chunked pagination)
        "z1_prev": None,
        "at3_prev": None,
        "at3_prev2": None,
        "at3_recent": [],
        "tp_recent": [],
        "at3_sum": 0,
        "at6": 0,
        "bl_window_start": None,
        "window_start": None,
        # Customer attributes (intrinsic, not derived from transactions)
        "pt_latest": now - timedelta(days=random.randint(30, 365)) if random.random() < 0.3 else None,
        "w2_latest": now - timedelta(days=random.randint(7, 365)) if random.random() < 0.2 else None,
        "w1_latest": random.choice([1, 2, 3]) if random.random() < 0.2 else None,
        "z3": random.randint(6, 10),    # typical hour lower
        "z4": random.randint(18, 22),   # typical hour upper
        "bl": balance,
        "b1": f"{random.randint(1000000000, 9999999999)}",
        "pot_i_recent": [],
    }

    # Add loan incoming for some customers (for var_9)
    if random.random() < 0.1:
        num_loans = random.randint(1, 3)
        rolling["pot_i_recent"] = [
            {
                "at3": random.randint(1_000_000, 10_000_000),
                "z1": now - timedelta(hours=random.randint(1, 48)),
                "q2": random.choice(LOAN_PROVIDERS),
            }
            for _ in range(num_loans)
        ]

    doc = {
        "customer_id": customer_id,
        "e1": f"user_{secrets.token_hex(4)}@email.com",
        "f1": f"+62{random.randint(8000000000, 8999999999)}",
        "r": reg_date,
        "y": random.choice(["PB", "PL", "PR"]),
        "pot_master_id_dp": devices,
        "flags": flags,
        "av1": random.uniform(100_000, 1_000_000),   # volatility threshold
        "av2": random.uniform(5_000_000, 50_000_000), # cumulative sum threshold
        "service_ever": service_ever,
        "b24_count": b24_count,
        "b24_list": b24_list,
        "rolling": rolling,
    }

    return doc


def generate_customer_batch(
    count: int,
    blacklist_accounts: Dict[str, set] = None,
) -> List[dict]:
    """Generate a batch of customer documents with empty rolling state."""
    docs = []
    for _ in range(count):
        doc = generate_customer_doc(blacklist_accounts=blacklist_accounts)
        docs.append(doc)
    return docs
