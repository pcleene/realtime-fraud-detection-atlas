import time
import functools
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# =============================================================================
# Datetime Utilities
# =============================================================================

def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Ensure a datetime is timezone-aware (UTC).
    
    MongoDB stores timezone-aware datetimes, but API requests often use naive
    datetimes. This normalizes both to UTC for safe comparisons.
    
    Args:
        dt: A datetime that may be naive or timezone-aware
        
    Returns:
        Timezone-aware datetime in UTC, or None if input is None
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# =============================================================================
# Timing Breakdown
# =============================================================================

@dataclass
class TimingBreakdown:
    """
    Detailed timing breakdown for fraud scoring operations.
    
    Tracks individual operation times and calculates aggregates for
    observability and performance monitoring.
    """
    
    # Database reads (run in parallel)
    db_customer_fetch_ms: float = 0.0
    db_blacklist_query_ms: float = 0.0
    db_holiday_query_ms: float = 0.0
    
    # Database writes (run in parallel)
    db_customer_update_ms: float = 0.0
    db_transaction_insert_ms: float = 0.0
    
    # Rule processing (CPU-bound, runs after customer fetch)
    rule_velocity_ms: float = 0.0
    rule_travel_ms: float = 0.0
    rule_blacklist_ms: float = 0.0
    rule_password_ms: float = 0.0
    rule_holiday_ms: float = 0.0
    
    # Parallel execution wall-clock times
    parallel_reads_ms: float = 0.0
    parallel_writes_ms: float = 0.0
    
    # Aggregates
    total_db_read_ms: float = 0.0
    total_db_write_ms: float = 0.0
    total_rules_ms: float = 0.0
    scoring_ms: float = 0.0
    persistence_ms: float = 0.0
    total_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary for API response."""
        return {
            "db_customer_fetch_ms": round(self.db_customer_fetch_ms, 2),
            "db_blacklist_query_ms": round(self.db_blacklist_query_ms, 2),
            "db_holiday_query_ms": round(self.db_holiday_query_ms, 2),
            "db_customer_update_ms": round(self.db_customer_update_ms, 2),
            "db_transaction_insert_ms": round(self.db_transaction_insert_ms, 2),
            "rule_velocity_ms": round(self.rule_velocity_ms, 2),
            "rule_travel_ms": round(self.rule_travel_ms, 2),
            "rule_blacklist_ms": round(self.rule_blacklist_ms, 2),
            "rule_password_ms": round(self.rule_password_ms, 2),
            "rule_holiday_ms": round(self.rule_holiday_ms, 2),
            "total_db_read_ms": round(self.total_db_read_ms, 2),
            "total_db_write_ms": round(self.total_db_write_ms, 2),
            "total_rules_ms": round(self.total_rules_ms, 2),
            "scoring_ms": round(self.scoring_ms, 2),
            "persistence_ms": round(self.persistence_ms, 2),
            "total_ms": round(self.total_ms, 2),
            "parallel_reads_ms": round(self.parallel_reads_ms, 2),
            "parallel_writes_ms": round(self.parallel_writes_ms, 2),
        }
    
    def calculate_aggregates(self):
        """Calculate aggregate timings from individual measurements."""
        self.total_db_read_ms = (
            self.db_customer_fetch_ms + 
            self.db_blacklist_query_ms + 
            self.db_holiday_query_ms
        )
        self.total_db_write_ms = (
            self.db_customer_update_ms + 
            self.db_transaction_insert_ms
        )
        self.total_rules_ms = (
            self.rule_velocity_ms +
            self.rule_travel_ms +
            self.rule_blacklist_ms +
            self.rule_password_ms +
            self.rule_holiday_ms
        )
        self.persistence_ms = self.parallel_writes_ms


def timed(func: F) -> F:
    """
    Decorator to measure and log execution time of a function.
    Works with both sync and async functions.
    """

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            return result
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(f"{func.__name__} executed in {elapsed_ms:.2f}ms")

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug(f"{func.__name__} executed in {elapsed_ms:.2f}ms")

    import asyncio

    if asyncio.iscoroutinefunction(func):
        return async_wrapper  # type: ignore
    return sync_wrapper  # type: ignore


def compute_shard_key_month(timestamp: datetime) -> str:
    """
    Compute coarse-grained month for shard key.

    Args:
        timestamp: Transaction timestamp

    Returns:
        String in format "YYYY-MM"
    """
    return timestamp.strftime("%Y-%m")


class Timer:
    """Context manager for timing code blocks."""

    def __init__(self, name: str = "operation"):
        self.name = name
        self.elapsed_ms: float = 0

    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        self.elapsed_ms = (time.perf_counter() - self.start) * 1000
        logger.debug(f"{self.name} executed in {self.elapsed_ms:.2f}ms")
