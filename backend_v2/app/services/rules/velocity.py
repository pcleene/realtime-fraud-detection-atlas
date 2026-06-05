"""
Velocity rules: var_8, var_10, var_13, var_24, var_26.

Time-based checks using rolling fields from customer document.
"""

from datetime import datetime
from typing import Optional

from app.models.transaction import RuleResult


def check_var_8(z1: datetime, z1_prev: Optional[datetime], threshold_seconds: int, weight: int) -> RuleResult:
    """Transaction velocity in seconds -- rapid transactions."""
    if z1_prev is None:
        return RuleResult(rule="var_8", triggered=False, weight=weight, score=0,
                          details={"gap_seconds": None, "threshold": threshold_seconds})

    z1_n = z1.replace(tzinfo=None) if z1.tzinfo else z1
    prev_n = z1_prev.replace(tzinfo=None) if z1_prev.tzinfo else z1_prev
    gap = (z1_n - prev_n).total_seconds()
    triggered = gap < threshold_seconds and gap >= 0
    return RuleResult(
        rule="var_8", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"gap_seconds": round(gap, 2), "threshold": threshold_seconds},
    )


def check_var_10(z1: datetime, z1_prev: Optional[datetime], threshold_days: int, weight: int) -> RuleResult:
    """Transaction velocity in days -- same-day transactions."""
    if z1_prev is None:
        return RuleResult(rule="var_10", triggered=False, weight=weight, score=0,
                          details={"gap_days": None, "threshold": threshold_days})

    z1_n = z1.replace(tzinfo=None) if z1.tzinfo else z1
    prev_n = z1_prev.replace(tzinfo=None) if z1_prev.tzinfo else z1_prev
    gap_days = (z1_n.date() - prev_n.date()).days
    triggered = gap_days <= threshold_days
    return RuleResult(
        rule="var_10", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"gap_days": gap_days, "threshold": threshold_days},
    )


def check_var_13(z1: datetime, z3: Optional[int], z4: Optional[int], weight: int) -> RuleResult:
    """Transaction outside customer's usual hours."""
    if z3 is None or z4 is None:
        return RuleResult(rule="var_13", triggered=False, weight=weight, score=0,
                          details={"hour": z1.hour, "typical_range": None})

    hour = z1.hour
    # Handle wrap-around (e.g., z3=22, z4=6 means 22:00-06:00 is normal)
    if z3 <= z4:
        in_range = z3 <= hour <= z4
    else:
        in_range = hour >= z3 or hour <= z4

    triggered = not in_range
    return RuleResult(
        rule="var_13", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"hour": hour, "typical_lower": z3, "typical_upper": z4},
    )


def check_var_24(z1: datetime, w2_latest: Optional[datetime], window_hours: int, weight: int) -> RuleResult:
    """Transaction within window of card change event."""
    if w2_latest is None:
        return RuleResult(rule="var_24", triggered=False, weight=weight, score=0,
                          details={"hours_since_change": None, "window_hours": window_hours})

    z1_n = z1.replace(tzinfo=None) if z1.tzinfo else z1
    w2_n = w2_latest.replace(tzinfo=None) if w2_latest.tzinfo else w2_latest
    hours_since = (z1_n - w2_n).total_seconds() / 3600
    triggered = 0 <= hours_since < window_hours
    return RuleResult(
        rule="var_24", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"hours_since_change": round(hours_since, 2), "window_hours": window_hours},
    )


def check_var_26(z1: datetime, pt_latest: Optional[datetime], window_hours: int, weight: int) -> RuleResult:
    """Transaction within window of device provisioning."""
    if pt_latest is None:
        return RuleResult(rule="var_26", triggered=False, weight=weight, score=0,
                          details={"hours_since_prov": None, "window_hours": window_hours})

    z1_n = z1.replace(tzinfo=None) if z1.tzinfo else z1
    pt_n = pt_latest.replace(tzinfo=None) if pt_latest.tzinfo else pt_latest
    hours_since = (z1_n - pt_n).total_seconds() / 3600
    triggered = 0 <= hours_since < window_hours
    return RuleResult(
        rule="var_26", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"hours_since_prov": round(hours_since, 2), "window_hours": window_hours},
    )
