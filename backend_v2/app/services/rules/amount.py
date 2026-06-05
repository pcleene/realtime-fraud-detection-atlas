"""
Amount rules: var_12, var_14, var_15, var_16, var_17, var_18, var_19, var_20, var_21, var_28, var_29.

Amount-based anomaly detection using rolling fields and service config.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.models.transaction import RuleResult


def check_var_12(at3: float, service: int, service_limits: Dict[int, float],
                 ratio_threshold: float, weight: int) -> RuleResult:
    """Amount vs service transaction limit (pot_sl)."""
    limit = service_limits.get(service)
    if limit is None or limit <= 0:
        return RuleResult(rule="var_12", triggered=False, weight=weight, score=0,
                          details={"at3": at3, "service": service, "limit": None})
    ratio = at3 / limit
    triggered = ratio >= ratio_threshold
    return RuleResult(
        rule="var_12", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"at3": at3, "service": service, "limit": limit, "ratio": round(ratio, 4)},
    )


def check_var_14(at3: float, service: int, avg_bounds: Dict[int, Tuple[float, float]],
                 weight: int) -> RuleResult:
    """Amount above historical avg for service (pot_va)."""
    bounds = avg_bounds.get(service)
    if bounds is None:
        return RuleResult(rule="var_14", triggered=False, weight=weight, score=0,
                          details={"at3": at3, "service": service, "bounds": None})
    at1_lower, at2_upper = bounds
    triggered = at3 > at2_upper or at3 < at1_lower
    return RuleResult(
        rule="var_14", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"at3": at3, "lower": at1_lower, "upper": at2_upper},
    )


def check_var_15(at3: float, bl: Optional[float], threshold: float, weight: int) -> RuleResult:
    """Amount to balance ratio."""
    if bl is None or bl <= 0:
        return RuleResult(rule="var_15", triggered=False, weight=weight, score=0,
                          details={"ratio": None, "bl": bl})
    ratio = at3 / bl
    triggered = ratio > threshold
    return RuleResult(
        rule="var_15", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"ratio": round(ratio, 4), "at3": at3, "bl": bl, "threshold": threshold},
    )


def check_var_16(at3: float, at3_recent: List[float], weight: int) -> RuleResult:
    """Repetitive/sequential amount pattern detection."""
    if len(at3_recent) < 2:
        return RuleResult(rule="var_16", triggered=False, weight=weight, score=0,
                          details={"pattern": None, "recent_count": len(at3_recent)})
    amounts = at3_recent + [at3]
    # Check repetitive: all same amount
    if len(set(amounts)) == 1:
        return RuleResult(
            rule="var_16", triggered=True, weight=weight, score=weight,
            details={"pattern": "repetitive", "amount": at3, "count": len(amounts)},
        )
    # Check sequential: constant difference
    diffs = [amounts[i + 1] - amounts[i] for i in range(len(amounts) - 1)]
    if len(set(round(d, 2) for d in diffs)) == 1 and diffs[0] != 0:
        return RuleResult(
            rule="var_16", triggered=True, weight=weight, score=weight,
            details={"pattern": "sequential", "step": round(diffs[0], 2), "count": len(amounts)},
        )
    return RuleResult(rule="var_16", triggered=False, weight=weight, score=0,
                      details={"pattern": None, "recent_count": len(amounts)})


def check_var_17(at3: float, at3_prev: Optional[float], spike_ratio: float, weight: int) -> RuleResult:
    """Sudden amount spike (at3/at4 ratio)."""
    if at3_prev is None or at3_prev <= 0:
        return RuleResult(rule="var_17", triggered=False, weight=weight, score=0,
                          details={"ratio": None})
    ratio = at3 / at3_prev
    triggered = ratio >= spike_ratio
    return RuleResult(
        rule="var_17", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"ratio": round(ratio, 4), "at3": at3, "at3_prev": at3_prev, "threshold": spike_ratio},
    )


def check_var_18(at3: float, at3_sum: float, bl: Optional[float],
                 balance_ratio: float, weight: int) -> RuleResult:
    """Cumulative amount in window vs balance."""
    if bl is None or bl <= 0:
        return RuleResult(rule="var_18", triggered=False, weight=weight, score=0,
                          details={"cumulative": at3_sum + at3, "bl": bl})
    cumulative = at3_sum + at3
    ratio = cumulative / bl
    triggered = ratio > balance_ratio
    return RuleResult(
        rule="var_18", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"cumulative": round(cumulative, 2), "bl": bl, "ratio": round(ratio, 4)},
    )


def check_var_19(at3: float, at3_sum: float, bl: Optional[float],
                 pt_latest: Optional[datetime], z1: datetime,
                 prov_hours: int, balance_ratio: float, weight: int) -> RuleResult:
    """Post-provisioning cumulative amount vs balance."""
    if pt_latest is None or bl is None or bl <= 0:
        return RuleResult(rule="var_19", triggered=False, weight=weight, score=0,
                          details={"post_prov": False})
    z1_n = z1.replace(tzinfo=None) if z1.tzinfo else z1
    pt_n = pt_latest.replace(tzinfo=None) if pt_latest.tzinfo else pt_latest
    hours_since = (z1_n - pt_n).total_seconds() / 3600
    if hours_since < 0 or hours_since > prov_hours:
        return RuleResult(rule="var_19", triggered=False, weight=weight, score=0,
                          details={"hours_since_prov": round(hours_since, 2), "window": prov_hours})
    cumulative = at3_sum + at3
    ratio = cumulative / bl
    triggered = ratio > balance_ratio
    return RuleResult(
        rule="var_19", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"cumulative": round(cumulative, 2), "bl": bl, "ratio": round(ratio, 4),
                 "hours_since_prov": round(hours_since, 2)},
    )


def check_var_20(at3: float, at3_recent: List[float], repeat_count: int, weight: int) -> RuleResult:
    """Exact amount repetition N times (including current transaction)."""
    historical = sum(1 for a in at3_recent if a == at3)
    total = historical + 1  # include current transaction
    triggered = total >= repeat_count
    return RuleResult(
        rule="var_20", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"at3": at3, "repeat_count": total, "threshold": repeat_count},
    )


def check_var_21(at3: float, at3_prev: Optional[float], drop_ratio: float, weight: int) -> RuleResult:
    """Sudden amount drop (at3/at4 ratio < threshold)."""
    if at3_prev is None or at3_prev <= 0:
        return RuleResult(rule="var_21", triggered=False, weight=weight, score=0,
                          details={"ratio": None})
    ratio = at3 / at3_prev
    triggered = ratio < drop_ratio
    return RuleResult(
        rule="var_21", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"ratio": round(ratio, 4), "at3": at3, "at3_prev": at3_prev, "threshold": drop_ratio},
    )


def check_var_28(at6: float, av1: Optional[float], weight: int) -> RuleResult:
    """Amount std dev exceeds customer-specific volatility threshold."""
    if av1 is None or av1 <= 0:
        return RuleResult(rule="var_28", triggered=False, weight=weight, score=0,
                          details={"at6": at6, "av1": av1})
    triggered = at6 > av1
    return RuleResult(
        rule="var_28", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"at6": round(at6, 4), "av1": av1},
    )


def check_var_29(at3_sum: float, av2: Optional[float], weight: int) -> RuleResult:
    """Cumulative sum exceeds customer-specific threshold."""
    if av2 is None or av2 <= 0:
        return RuleResult(rule="var_29", triggered=False, weight=weight, score=0,
                          details={"at3_sum": at3_sum, "av2": av2})
    triggered = at3_sum > av2
    return RuleResult(
        rule="var_29", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"at3_sum": round(at3_sum, 2), "av2": av2},
    )
