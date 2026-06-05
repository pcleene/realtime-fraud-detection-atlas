import time
import functools
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a datetime is timezone-aware (UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class TimingBreakdown:
    """V2 timing breakdown for 31-rule scoring.

    Phase breakdown:
      Phase 1 (DB read):  db_customer_fetch_ms (+ db_overflow_check_ms if applicable)
      Phase 2 (CPU):      rules_eval_ms
      Phase 3 (DB write): db_customer_update_ms + db_transaction_insert_ms (run in parallel)

    Aggregates:
      db_read_ms:          Total DB read time (Phase 1)
      db_write_ms:         Wall-clock for parallel writes (Phase 3)
      app_processing_ms:   Phase 1 + Phase 2 (everything before writes)
      total_db_ms:         Sum of all individual DB op times
      total_ms:            End-to-end wall-clock
    """

    # Phase 1: DB read
    db_customer_fetch_ms: float = 0.0
    db_overflow_check_ms: float = 0.0  # rare 4th op for b24_count > 500
    db_txn_lookups_ms: float = 0.0     # consolidated lookup query (LOOKUP_MODE=db only)

    # Phase 2: CPU-only rule evaluation
    rules_eval_ms: float = 0.0

    # Phase 3: DB writes (individual times measured inside asyncio.gather)
    db_customer_update_ms: float = 0.0
    db_transaction_insert_ms: float = 0.0
    parallel_writes_ms: float = 0.0   # wall-clock for the gather

    # Aggregates (computed by calculate_aggregates)
    db_read_ms: float = 0.0           # Phase 1 total
    db_write_ms: float = 0.0          # Phase 3 wall-clock
    app_processing_ms: float = 0.0    # Phase 1 + Phase 2 (before writes)
    total_db_ms: float = 0.0          # sum of all individual DB ops
    total_ms: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary for API response."""
        d = {
            # Individual DB ops
            "db_customer_fetch_ms": round(self.db_customer_fetch_ms, 2),
            "db_customer_update_ms": round(self.db_customer_update_ms, 2),
            "db_transaction_insert_ms": round(self.db_transaction_insert_ms, 2),
            "db_overflow_check_ms": round(self.db_overflow_check_ms, 2),
            # CPU
            "rules_eval_ms": round(self.rules_eval_ms, 2),
            # Phase aggregates
            "db_read_ms": round(self.db_read_ms, 2),
            "db_write_ms": round(self.db_write_ms, 2),
            "app_processing_ms": round(self.app_processing_ms, 2),
            # Totals
            "total_db_ms": round(self.total_db_ms, 2),
            "total_ms": round(self.total_ms, 2),
        }
        # Only include txn_lookups timing when in DB lookup mode
        if self.db_txn_lookups_ms > 0:
            d["db_txn_lookups_ms"] = round(self.db_txn_lookups_ms, 2)
        return d

    def calculate_aggregates(self):
        """Calculate aggregate timings from individual measurements."""
        self.db_read_ms = self.db_customer_fetch_ms + self.db_overflow_check_ms + self.db_txn_lookups_ms
        self.db_write_ms = self.parallel_writes_ms
        self.total_db_ms = (
            self.db_customer_fetch_ms
            + self.db_customer_update_ms
            + self.db_transaction_insert_ms
            + self.db_overflow_check_ms
            + self.db_txn_lookups_ms
        )


def compute_shard_key_month(timestamp: datetime) -> str:
    """Compute coarse-grained month for shard key."""
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
