"""V2 scoring utilities -- weighted sum with configurable risk levels."""

from typing import List, Tuple

from app.config import get_settings


def calculate_final_score(results: list) -> Tuple[int, str]:
    """
    Calculate final fraud score from all rule results.

    Args:
        results: List of RuleResult objects

    Returns:
        Tuple of (final_score capped at 100, risk_level)
    """
    settings = get_settings()
    total = sum(r.score for r in results)
    final_score = min(total, 100)

    if final_score >= settings.risk_threshold_high:
        risk_level = "high"
    elif final_score >= settings.risk_threshold_medium:
        risk_level = "medium"
    else:
        risk_level = "low"

    return final_score, risk_level
