"""
Blacklist rules: var_1, var_2, var_3, var_4, var_5, var_6, var_7, var_23, var_25.

All use pre-computed flags on the customer document or in-memory cache lookups.
No database I/O during scoring.
"""

from datetime import datetime
from typing import Optional

from app.models.transaction import RuleResult


def check_var_1(b2: str, cache, weight: int) -> RuleResult:
    """Destination account on fraud blacklist (pot_bf)."""
    triggered = b2 in cache.dest_accounts
    return RuleResult(
        rule="var_1", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"b2": b2, "in_pot_bf": triggered},
    )


def check_var_2(customer_id: str, b2: str, z1: datetime, cache, cascade_hours: int, weight: int) -> RuleResult:
    """Customer or destination involved in confirmed fraud in last 24h (pot_bf24)."""
    triggered = False
    match_key = None
    if b2 in cache.fraud_cascade:
        entry = cache.fraud_cascade[b2]
        # If cascade entry is linked to a specific customer, only trigger for that customer
        entry_customer = entry.get("customer_id")
        if entry_customer and entry_customer != customer_id:
            pass  # Different customer - not a cascade match
        else:
            cascade_time = entry.get("z1")
            if cascade_time:
                if isinstance(cascade_time, str):
                    cascade_time = datetime.fromisoformat(cascade_time.replace("Z", "+00:00")).replace(tzinfo=None)
                if isinstance(cascade_time, datetime):
                    if cascade_time.tzinfo:
                        cascade_time = cascade_time.replace(tzinfo=None)
                    z1_naive = z1.replace(tzinfo=None) if z1.tzinfo else z1
                    if (z1_naive - cascade_time).total_seconds() < cascade_hours * 3600:
                        triggered = True
                        match_key = b2
            else:
                triggered = True
                match_key = b2

    return RuleResult(
        rule="var_2", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"match_key": match_key, "cascade_hours": cascade_hours},
    )


def check_var_3(flags_var_3: bool, weight: int) -> RuleResult:
    """Customer's email on blacklist (pre-computed flag from pot_be)."""
    return RuleResult(
        rule="var_3", triggered=flags_var_3, weight=weight,
        score=weight if flags_var_3 else 0,
        details={"email_blacklisted": flags_var_3},
    )


def check_var_4(flags_var_4: bool, weight: int) -> RuleResult:
    """Customer's device on risky device list (pre-computed flag from pot_rtd)."""
    return RuleResult(
        rule="var_4", triggered=flags_var_4, weight=weight,
        score=weight if flags_var_4 else 0,
        details={"risky_device": flags_var_4},
    )


def check_var_5(n2: Optional[str], cache, weight: int) -> RuleResult:
    """Merchant/beneficiary name is suspicious (pot_sm)."""
    if not n2:
        return RuleResult(
            rule="var_5", triggered=False, weight=weight, score=0,
            details={"n2": None},
        )
    triggered = n2.lower() in cache.suspicious_merchants
    return RuleResult(
        rule="var_5", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"n2": n2, "in_pot_sm": triggered},
    )


def check_var_6(b2: str, cache, weight: int) -> RuleResult:
    """Destination account linked to gambling (pot_anj)."""
    triggered = b2 in cache.gambling_accounts
    return RuleResult(
        rule="var_6", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"b2": b2, "in_pot_anj": triggered},
    )


def check_var_7(flags_var_7: bool, weight: int) -> RuleResult:
    """Customer's phone on blacklist (pre-computed flag from pot_bmn)."""
    return RuleResult(
        rule="var_7", triggered=flags_var_7, weight=weight,
        score=weight if flags_var_7 else 0,
        details={"phone_blacklisted": flags_var_7},
    )


def check_var_23(b2: str, cache, weight: int) -> RuleResult:
    """Destination on compliance watchlist (pot_cb)."""
    triggered = b2 in cache.watchlist_accounts
    return RuleResult(
        rule="var_23", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"b2": b2, "in_pot_cb": triggered},
    )


def check_var_25(flags_var_25: bool, weight: int) -> RuleResult:
    """Customer's device on high-risk device list (pre-computed flag from pot_rkd)."""
    return RuleResult(
        rule="var_25", triggered=flags_var_25, weight=weight,
        score=weight if flags_var_25 else 0,
        details={"high_risk_device": flags_var_25},
    )
