from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ScoreTransactionRequest(BaseModel):
    """Request model for POST /score-transaction."""

    customer_id: str
    account_id: str
    amount: float
    lat: Optional[float] = None
    lon: Optional[float] = None
    timestamp: datetime
    channel: Literal["Livin", "KOPRA", "ATM", "QRIS", "Branch", "Ecom"]
    merchant_id: str
    merchant_name: str
    mcc: str
    device_id: str
    device_type: Literal["ios", "android", "web"]
    ip: str


class RuleAnalysisResponse(BaseModel):
    """Rule analysis result in response."""

    rule: str
    score: int
    triggered: bool
    details: Optional[Dict[str, Any]] = None


class TimingBreakdownResponse(BaseModel):
    """Detailed timing breakdown for performance analysis."""
    
    # Database reads (individual times)
    db_customer_fetch_ms: float
    db_blacklist_query_ms: float
    db_holiday_query_ms: float
    
    # Database writes (individual times)
    db_customer_update_ms: float
    db_transaction_insert_ms: float
    
    # Rule processing (CPU-bound)
    rule_velocity_ms: float
    rule_travel_ms: float
    rule_blacklist_ms: float
    rule_password_ms: float
    rule_holiday_ms: float
    
    # Aggregates (sum of individual times)
    total_db_read_ms: float
    total_db_write_ms: float
    total_rules_ms: float
    scoring_ms: float
    persistence_ms: float
    total_ms: float


class ScoreTransactionResponse(BaseModel):
    """Response model for POST /score-transaction."""

    transaction_id: str
    risk_score: int
    risk_level: Literal["low", "medium", "high"]
    analysis: List[RuleAnalysisResponse]
    scoring_time_ms: float  # Time to compute score (before DB writes)
    total_time_ms: float  # Total time including DB persistence
    timing: TimingBreakdownResponse  # Detailed timing breakdown
    recorded_at: datetime


class CollectionStatus(BaseModel):
    """Collection status for health check."""

    exists: bool
    sharded: bool


class ShardingStatus(BaseModel):
    """Sharding status for health check."""

    enabled: bool
    shards: int


class HealthResponse(BaseModel):
    """Response model for GET /health."""

    status: Literal["healthy", "unhealthy"]
    database: Literal["connected", "disconnected"]
    sharding: ShardingStatus
    collections: Dict[str, CollectionStatus]
    indexes: Literal["verified", "missing"]


class PoolStats(BaseModel):
    """MongoDB connection pool statistics."""

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
    """In-memory cache statistics."""

    holidays_cached: int
    blacklist_cached: int
    cache_ttl_seconds: int


class DetailedHealthResponse(BaseModel):
    """Response model for GET /health/detailed with pool stats and cache info."""

    status: Literal["healthy", "unhealthy"]
    database: Literal["connected", "disconnected"]
    sharding: ShardingStatus
    collections: Dict[str, CollectionStatus]
    indexes: Literal["verified", "missing"]
    pool_stats: Optional[PoolStats] = None
    cache_stats: Optional[CacheStats] = None


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    message: str
