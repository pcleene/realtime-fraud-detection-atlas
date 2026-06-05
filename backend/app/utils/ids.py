import secrets


def generate_customer_id() -> str:
    """
    Generate customer_id that is:
    - Unique (12 hex chars = 16^12 = ~281 trillion combinations)
    - Not monotonically increasing (random)
    - Human readable

    Random keys cause B-tree page splits, but customer inserts are rare (~1/sec).
    The distribution benefit far outweighs the B-tree overhead.
    """
    return f"CUST-{secrets.token_hex(6).upper()}"


def generate_account_id() -> str:
    """Generate a random account ID."""
    return f"ACC-{secrets.token_hex(4).upper()}"


def generate_device_id() -> str:
    """Generate a random device ID."""
    return f"DEV-{secrets.token_hex(4).upper()}"


def generate_merchant_id() -> str:
    """Generate a random merchant ID."""
    return f"M-{secrets.token_hex(4).upper()}"
