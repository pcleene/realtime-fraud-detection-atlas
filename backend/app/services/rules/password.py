from typing import Optional

from app.config import get_settings
from app.models.transaction import RuleAnalysis


def check_password_frequency(
    avg_gap_change_password: Optional[float],
) -> RuleAnalysis:
    """
    Password frequency check - detects accounts with unusually frequent password changes.

    Args:
        avg_gap_change_password: Average days between password changes

    Returns:
        RuleAnalysis with password frequency check results
    """
    settings = get_settings()
    threshold_days = settings.password_threshold_days

    if avg_gap_change_password is None:
        return RuleAnalysis(
            rule="password_frequency",
            score=0,
            triggered=False,
            details={
                "avg_gap_days": None,
                "threshold_days": threshold_days,
            },
        )

    if avg_gap_change_password < threshold_days:
        return RuleAnalysis(
            rule="password_frequency",
            score=settings.weight_password,
            triggered=True,
            details={
                "avg_gap_days": round(avg_gap_change_password, 2),
                "threshold_days": threshold_days,
            },
        )

    return RuleAnalysis(
        rule="password_frequency",
        score=0,
        triggered=False,
        details={
            "avg_gap_days": round(avg_gap_change_password, 2),
            "threshold_days": threshold_days,
        },
    )
