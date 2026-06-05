"""
Scoring utilities for fraud detection.

Provides helper functions for calculating risk scores and levels.
"""

from typing import List, Tuple

from app.config import get_settings
from app.models.transaction import RuleAnalysis


def calculate_risk_level(final_score: int) -> str:
    """
    Calculate risk level from final score.
    
    Args:
        final_score: Aggregated fraud score (0-100)
        
    Returns:
        Risk level: "low", "medium", or "high"
    """
    settings = get_settings()
    if final_score >= settings.risk_threshold_high:
        return "high"
    elif final_score >= settings.risk_threshold_medium:
        return "medium"
    return "low"


def calculate_final_score(analysis: List[RuleAnalysis]) -> Tuple[int, str]:
    """
    Sum all triggered rule scores and determine risk level.
    
    Args:
        analysis: List of RuleAnalysis results from fraud rules
        
    Returns:
        Tuple of (final_score, risk_level)
        - final_score is capped at 100
        - risk_level is "low", "medium", or "high"
    """
    total = sum(rule.score for rule in analysis)
    final_score = min(100, total)
    risk_level = calculate_risk_level(final_score)
    return final_score, risk_level

