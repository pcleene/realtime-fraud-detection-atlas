"""
Pattern rules: var_30, var_31.

Transaction pattern detection using purpose codes and amounts.
"""

from typing import List

from app.models.transaction import RuleResult


def check_var_30(tp: int, tp_recent: List[int], weight: int) -> RuleResult:
    """Repetitive purpose code pattern."""
    if len(tp_recent) < 2:
        return RuleResult(rule="var_30", triggered=False, weight=weight, score=0,
                          details={"pattern": None, "recent_count": len(tp_recent)})
    all_values = tp_recent + [tp]
    # Check if all same purpose code
    if len(set(all_values)) == 1:
        return RuleResult(
            rule="var_30", triggered=True, weight=weight, score=weight,
            details={"pattern": "repetitive", "tp": tp, "count": len(all_values)},
        )
    # Check sequential pattern (constant difference)
    diffs = [all_values[i + 1] - all_values[i] for i in range(len(all_values) - 1)]
    if len(set(diffs)) == 1 and diffs[0] != 0:
        return RuleResult(
            rule="var_30", triggered=True, weight=weight, score=weight,
            details={"pattern": "sequential", "step": diffs[0], "count": len(all_values)},
        )
    return RuleResult(rule="var_30", triggered=False, weight=weight, score=0,
                      details={"pattern": None, "recent_count": len(all_values)})


def check_var_31(tp: int, at3: float, ratio_threshold: float, weight: int) -> RuleResult:
    """Purpose-to-amount ratio anomaly.

    Flags transactions where the purpose code suggests a small payment
    but the amount is disproportionately large, or vice versa.

    TUNING NOTE: With the default threshold of 0.01, this rule fires when
    tp/at3 > 0.01 (e.g. purpose code 55555 on a 1M IDR transaction gives
    ratio ~0.056, triggering the rule). If this over-fires in production,
    raise PURPOSE_AMOUNT_RATIO_THRESHOLD (e.g. to 0.05 or 0.10).
    """
    if at3 <= 0 or tp <= 0:
        return RuleResult(rule="var_31", triggered=False, weight=weight, score=0,
                          details={"tp": tp, "at3": at3, "ratio": None})
    ratio = tp / at3
    triggered = ratio > ratio_threshold
    return RuleResult(
        rule="var_31", triggered=triggered, weight=weight,
        score=weight if triggered else 0,
        details={"tp": tp, "at3": at3, "ratio": round(ratio, 6), "threshold": ratio_threshold},
    )
