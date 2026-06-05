import secrets


def generate_customer_id() -> str:
    """
    Generate customer_id that is:
    - Unique (12 hex chars = 16^12 = ~281 trillion combinations)
    - Not monotonically increasing (random)
    - Human readable
    """
    return f"CUST-{secrets.token_hex(6).upper()}"


def generate_account_id() -> str:
    """Generate a random account ID."""
    return f"ACC-{secrets.token_hex(4).upper()}"
