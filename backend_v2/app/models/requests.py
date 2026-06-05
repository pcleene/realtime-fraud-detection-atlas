"""
V2 API Request/Response models.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from app.models.transaction import FraudScore, RuleAnalysis


class ScoreTransactionRequest(BaseModel):
    """Request model for POST /score-transaction."""
    customer_id: str
    b1: Optional[str] = None       # source account
    b2: str                        # destination account
    c2: Optional[str] = None       # destination name
    d2: Optional[str] = None       # destination bank
    n2: Optional[str] = None       # merchant/beneficiary description
    at3: float                     # transaction amount
    tp: int = 0                    # purpose code
    at7: float = 0.0               # fee
    service: int = 0               # service code
    service_name: str = "Y"        # service category
    z1: datetime                   # transaction timestamp
    h1: Optional[str] = None       # device model
    is_financial: int = 1
    status: str = "SUCCESS"
    channel: str = "Livin"
    lat: Optional[float] = None
    lon: Optional[float] = None


class ScoreTransactionResponse(BaseModel):
    """Response model for POST /score-transaction."""
    transaction_id: str
    customer_id: str
    fraud_score: FraudScore
    analysis: List[RuleAnalysis]
    app_processing_ms: float     # Phase 1 (DB read) + Phase 2 (rules) -- before writes
    total_time_ms: float         # End-to-end including writes
    timing: Optional[Dict[str, float]] = None  # Full breakdown when requested
    recorded_at: datetime


class TimingBreakdownResponse(BaseModel):
    """Detailed timing breakdown."""
    # Individual DB ops
    db_customer_fetch_ms: float
    db_customer_update_ms: float
    db_transaction_insert_ms: float
    db_overflow_check_ms: float = 0.0
    # CPU
    rules_eval_ms: float
    # Phase aggregates
    db_read_ms: float            # Phase 1: customer fetch + overflow
    db_write_ms: float           # Phase 3: parallel writes wall-clock
    app_processing_ms: float     # Phase 1 + Phase 2 (before writes)
    # Totals
    total_db_ms: float           # Sum of all individual DB op times
    total_ms: float


class CollectionStatus(BaseModel):
    exists: bool
    sharded: bool


class ShardingStatus(BaseModel):
    enabled: bool
    shards: int


class HealthResponse(BaseModel):
    status: Literal["healthy", "unhealthy"]
    database: Literal["connected", "disconnected"]
    sharding: ShardingStatus
    collections: Dict[str, CollectionStatus]
    indexes: Literal["verified", "missing"]


class PoolStats(BaseModel):
    topology_type: str
    nodes: int
    max_pool_size: int
    min_pool_size: int
    max_idle_time_ms: int
    wait_queue_timeout_ms: int
    compression: str
    read_preference: str
    retry_writes: bool


class CacheStats(BaseModel):
    blacklist_entries: int
    service_config_entries: int
    cache_ttl_seconds: int


class DetailedHealthResponse(BaseModel):
    status: Literal["healthy", "unhealthy"]
    database: Literal["connected", "disconnected"]
    sharding: ShardingStatus
    collections: Dict[str, CollectionStatus]
    indexes: Literal["verified", "missing"]
    pool_stats: Optional[PoolStats] = None
    cache_stats: Optional[CacheStats] = None


class ErrorResponse(BaseModel):
    error: str
    message: str
