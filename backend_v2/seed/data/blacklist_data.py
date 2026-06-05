"""
V2 blacklist data generators — production-scale volumes with realistic formats.

All account-based collections use 10-digit numeric strings matching the
transaction b2 format. Merchant collections use the same "Merchant-{hex}"
format as generate_transaction(). This ensures non-zero hit rates during
seed scoring and load testing.

Production volumes (from RegionalBank documentation):
  pot_bf:   ~470K   (destination account blacklist)
  pot_bf24: ~49K    (fraud cascade 24h)
  pot_sm:   ~132K   (suspicious merchant names)
  pot_anj:  ~470K   (gambling-affiliated accounts)
  pot_pp:   ~1.7K   (online loan provider accounts)
  pot_cb:   ~1M     (compliance/watchlist accounts)

Total in-memory footprint: ~130-170 MB at production scale.
"""

import random
import secrets
from datetime import datetime, timedelta
from typing import Generator

from seed.data.loan_providers import LOAN_PROVIDERS

# ---------------------------------------------------------------------------
# Production counts (from RegionalBank docs)
# ---------------------------------------------------------------------------
PROD_COUNTS = {
    "pot_bf": 470_000,
    "pot_bf24": 49_000,
    "pot_sm": 132_000,
    "pot_anj": 470_000,
    "pot_pp": 1_700,
    "pot_cb": 1_000_000,
}

# Test-mode counts (quick validation)
TEST_COUNTS = {
    "pot_bf": 50,
    "pot_bf24": 20,
    "pot_sm": 30,
    "pot_anj": 50,
    "pot_pp": 20,
    "pot_cb": 50,
}


def _random_account() -> str:
    """Generate a 10-digit account number matching transaction b2 format."""
    return f"{random.randint(1000000000, 9999999999)}"


def _random_merchant() -> str:
    """Generate a merchant name matching transaction n2 format."""
    return f"Merchant-{secrets.token_hex(3).upper()}"


# ---------------------------------------------------------------------------
# Generators — yield individual documents
# ---------------------------------------------------------------------------

def generate_pot_bf(count: int) -> Generator[dict, None, None]:
    """pot_bf: destination account blacklist (var_1)."""
    for _ in range(count):
        yield {"b23": _random_account()}


def generate_pot_bf24(count: int) -> Generator[dict, None, None]:
    """pot_bf24: fraud cascade 24h (var_2).

    ~80% of entries have customer_id=None (applies to any customer sending to
    this destination). ~20% have a specific customer_id (cascade scoped to
    the original fraud victim only). This matches check_var_2() logic where
    `if entry_customer and entry_customer != customer_id` skips non-matching
    customers, but None falls through to the time window check.
    """
    now = datetime.utcnow()
    for _ in range(count):
        yield {
            "b23": _random_account(),
            "customer_id": f"CUST-{secrets.token_hex(6).upper()}" if random.random() < 0.2 else None,
            "a23": _random_account(),
            "b13": random.choice(["BTN", "BRI", "BCA", "BNI", "CIMB"]),
            "z1": now - timedelta(hours=random.randint(1, 48)),
        }


def generate_pot_sm(count: int) -> Generator[dict, None, None]:
    """pot_sm: suspicious merchant names (var_5).

    Uses same "Merchant-{hex}" format as transaction n2 field so the
    scoring check (n2.lower() in cache) produces natural matches.
    """
    for _ in range(count):
        yield {"n3": _random_merchant()}


def generate_pot_anj(count: int) -> Generator[dict, None, None]:
    """pot_anj: gambling-affiliated accounts (var_6)."""
    for _ in range(count):
        yield {"b23": _random_account()}


def generate_pot_pp(count: int) -> Generator[dict, None, None]:
    """pot_pp: loan provider accounts (var_9).

    ~1.7K accounts spread across ~20 known loan providers.
    Each provider has ~85 registered accounts on average.
    """
    for _ in range(count):
        yield {
            "b23": _random_account(),
            "q2": random.choice(LOAN_PROVIDERS),
        }


def generate_pot_cb(count: int) -> Generator[dict, None, None]:
    """pot_cb: compliance/watchlist accounts (var_23).

    Largest blacklist at ~1M entries. Includes flagged account name (c23).
    """
    for _ in range(count):
        yield {
            "b23": _random_account(),
            "c23": f"FLAGGED-{secrets.token_hex(4).upper()}",
        }
