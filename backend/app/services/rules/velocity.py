from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings
from app.models.transaction import RuleAnalysis


def ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def check_velocity(
    latest_time_transaction: Optional[datetime],
    current_timestamp: datetime,
) -> RuleAnalysis:
    """
    Velocity check - detects rapid sequential transactions (potential automated fraud).

    Args:
        latest_time_transaction: Customer's last transaction timestamp
        current_timestamp: Current transaction timestamp

    Returns:
        RuleAnalysis with velocity check results
    """
    settings = get_settings()
    threshold_seconds = settings.min_txn_gap_seconds

    if latest_time_transaction is None:
        return RuleAnalysis(
            rule="velocity",
            score=0,
            triggered=False,
            details={
                "delta_seconds": None,
                "threshold_seconds": threshold_seconds,
            },
        )

    delta_seconds = (ensure_utc(current_timestamp) - ensure_utc(latest_time_transaction)).total_seconds()

    if delta_seconds < threshold_seconds:
        return RuleAnalysis(
            rule="velocity",
            score=settings.weight_velocity,
            triggered=True,
            details={
                "delta_seconds": round(delta_seconds, 2),
                "threshold_seconds": threshold_seconds,
            },
        )

    return RuleAnalysis(
        rule="velocity",
        score=0,
        triggered=False,
        details={
            "delta_seconds": round(delta_seconds, 2),
            "threshold_seconds": threshold_seconds,
        },
    )
