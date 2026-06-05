"""
Load Testing API - Full HTTP Stack Testing

This module provides load testing that makes real HTTP calls to /score-transaction,
testing the complete request path including HTTP overhead, serialization, and routing.

Works locally (localhost:8000) and in production (via ALB to multiple instances).

State is stored in MongoDB for multi-worker support.

NOTE: For high-TPS testing (1000+), use the external CLI tool instead:
    python -m loadtest.cli --target http://alb.amazonaws.com --tps 1000 --duration 60

The embedded load test (this module) is best for quick demos at lower TPS,
as it shares CPU with the scoring API.
"""

import asyncio
import logging
import os
import random
import secrets
import time
from datetime import datetime
from typing import List, Optional, Dict, Any

import httpx
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Request
from pydantic import BaseModel, Field

from app.db import get_db

# Import shared utilities from loadtest package
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from loadtest.common import (
    SYNC_INTERVAL_MS,
    SYNC_BATCH_SIZE,
    MAX_LATENCY_SAMPLES,
    MAX_RECENT_TRANSACTIONS,
    generate_transaction_payload,
    calculate_percentile,
    build_histogram,
    get_customer_pool_async as get_customer_pool_random,  # Fallback random sampling
)
from app.services.customer_sampling import (
    get_sampled_customers,
    get_customer_cache_stats,
    invalidate_customer_cache,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/loadtest", tags=["loadtest"])


# =============================================================================
# Models
# =============================================================================

class RecentTransaction(BaseModel):
    """A recent transaction from the load test for UI display."""
    customer_id: str
    amount: float
    channel: str
    risk_level: str
    latency_ms: float
    scoring_ms: float = 0.0  # Time for reads + rule evaluation (before writes)
    persist_ms: float = 0.0  # Time for customer update + transaction insert (writes)
    timestamp: str


class LoadTestConfig(BaseModel):
    """Configuration for a load test run."""
    target_tps: int = Field(100, ge=1, le=10000, description="Target transactions per second")
    duration_seconds: int = Field(10, ge=1, le=300, description="Test duration in seconds")
    concurrency: int = Field(50, ge=1, le=500, description="Number of concurrent connections")
    fraud_rate: float = Field(0.12, ge=0, le=1, description="Fraction of fraudulent transactions")
    target_url: Optional[str] = Field(None, description="Target URL (defaults to self)")
    customer_pool_size: Optional[int] = Field(
        None,
        ge=100,
        le=50000,
        description="Customer pool size. Default: auto-calculated as min(TPS*10, 10000) to target ~1 write/sec/customer at high TPS"
    )
    sampling_method: str = Field(
        "chunk_based",
        description="Customer sampling method: 'chunk_based' (shard-aware) or 'random' (fallback)"
    )
    force_refresh_customers: bool = Field(
        False,
        description="Force refresh customer cache (default: use cached customers)"
    )


class LoadTestProgress(BaseModel):
    """Real-time progress of a load test."""
    test_id: str
    status: str  # "running", "completed", "failed", "stopped"
    elapsed_seconds: float
    total_transactions: int
    successful: int
    failed: int
    current_tps: float
    avg_latency_ms: float
    avg_scoring_ms: float = 0.0  # Avg time for reads + rule evaluation (before writes)
    avg_persist_ms: float = 0.0  # Avg time for customer update + transaction insert (writes)
    p95_latency_ms: float
    p99_latency_ms: float
    risk_distribution: Dict[str, int]
    recent_transactions: List[RecentTransaction] = []
    error_message: Optional[str] = None


class LoadTestResult(BaseModel):
    """Final result of a load test."""
    test_id: str
    config: LoadTestConfig
    status: str
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    total_transactions: int
    successful: int
    failed: int
    error_rate: float
    throughput_tps: float
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    risk_distribution: Dict[str, int]
    latency_histogram: List[Dict[str, Any]]


# =============================================================================
# MongoDB Operations for Load Test State
# =============================================================================

async def create_load_test(db, test_id: str, config: LoadTestConfig) -> None:
    """Create a new load test document in MongoDB."""
    doc = {
        "test_id": test_id,
        "config": config.model_dump(),
        "status": "running",
        "start_time": datetime.utcnow(),
        "end_time": None,
        "total_transactions": 0,
        "successful": 0,
        "failed": 0,
        "current_tps": 0.0,
        "risk_distribution": {"low": 0, "medium": 0, "high": 0},
        "latency_stats": {
            "sum": 0.0,
            "count": 0,
            "min": None,
            "max": None,
            "samples": []
        },
        "stop_requested": False,
        "error_message": None,
        "final_result": None
    }
    await db.load_tests.insert_one(doc)


async def get_load_test(db, test_id: str) -> Optional[Dict[str, Any]]:
    """Get a load test document from MongoDB."""
    return await db.load_tests.find_one({"test_id": test_id})


async def update_load_test_progress(
    db,
    test_id: str,
    successful_delta: int,
    failed_delta: int,
    latency_sum_delta: float,
    latency_count_delta: int,
    latency_min: Optional[float],
    latency_max: Optional[float],
    latency_samples: List[float],
    risk_distribution_delta: Dict[str, int],
    current_tps: float,
    recent_transactions: Optional[List[Dict[str, Any]]] = None
) -> None:
    """Update load test progress in MongoDB using atomic operations."""
    update_ops: Dict[str, Any] = {
        "$inc": {
            "total_transactions": successful_delta + failed_delta,
            "successful": successful_delta,
            "failed": failed_delta,
            "latency_stats.sum": latency_sum_delta,
            "latency_stats.count": latency_count_delta,
        },
        "$set": {
            "current_tps": current_tps
        }
    }
    
    # Include recent transactions for UI feed (replaced, not appended)
    if recent_transactions is not None:
        update_ops["$set"]["recent_transactions"] = recent_transactions
    
    # Update risk distribution
    for risk_level, count in risk_distribution_delta.items():
        if count > 0:
            update_ops["$inc"][f"risk_distribution.{risk_level}"] = count
    
    await db.load_tests.update_one({"test_id": test_id}, update_ops)
    
    # Update min/max and samples separately (can't mix $min/$max with $inc on same field path)
    sample_update: Dict[str, Any] = {}
    if latency_min is not None:
        sample_update["$min"] = {"latency_stats.min": latency_min}
    if latency_max is not None:
        if "$max" not in sample_update:
            sample_update["$max"] = {}
        sample_update["$max"]["latency_stats.max"] = latency_max
    
    if sample_update:
        await db.load_tests.update_one({"test_id": test_id}, sample_update)
    
    # Push samples (keep last MAX_LATENCY_SAMPLES)
    if latency_samples:
        await db.load_tests.update_one(
            {"test_id": test_id},
            {
                "$push": {
                    "latency_stats.samples": {
                        "$each": latency_samples,
                        "$slice": -MAX_LATENCY_SAMPLES
                    }
                }
            }
        )


async def complete_load_test(db, test_id: str, final_result: Dict[str, Any], status: str) -> None:
    """Mark a load test as completed with final results."""
    await db.load_tests.update_one(
        {"test_id": test_id},
        {
            "$set": {
                "status": status,
                "end_time": datetime.utcnow(),
                "final_result": final_result
            }
        }
    )


async def fail_load_test(db, test_id: str, error_message: str) -> None:
    """Mark a load test as failed."""
    await db.load_tests.update_one(
        {"test_id": test_id},
        {
            "$set": {
                "status": "failed",
                "end_time": datetime.utcnow(),
                "error_message": error_message
            }
        }
    )


async def request_stop_load_test(db, test_id: str) -> bool:
    """Request a load test to stop. Returns True if test was found and updated."""
    result = await db.load_tests.update_one(
        {"test_id": test_id, "status": "running"},
        {"$set": {"stop_requested": True}}
    )
    return result.modified_count > 0


async def check_stop_requested(db, test_id: str) -> bool:
    """Check if stop has been requested for a load test."""
    doc = await db.load_tests.find_one(
        {"test_id": test_id},
        {"stop_requested": 1}
    )
    return doc.get("stop_requested", False) if doc else False


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/start", response_model=LoadTestProgress)
async def start_load_test(
    config: LoadTestConfig,
    background_tasks: BackgroundTasks,
    request: Request
):
    """
    Start a load test that makes real HTTP calls to /score-transaction.

    This tests the complete HTTP stack including network, serialization, and routing.
    When deployed behind ALB, requests are distributed across all API instances.

    Args:
        config: Load test configuration
        - target_tps: Target transactions per second (1-10000)
        - duration_seconds: How long to run (1-300)
        - concurrency: Number of concurrent HTTP connections (1-500)
        - fraud_rate: Fraction of transactions near fraud hotspots (0-1)
        - target_url: Optional URL override (defaults to self)
    """
    test_id = f"test-{secrets.token_hex(4)}"

    # Determine target URL
    if config.target_url:
        base_url = config.target_url.rstrip("/")
    else:
        # Default to calling ourselves
        base_url = str(request.base_url).rstrip("/")

    # Store config with resolved URL
    config_with_url = config.model_copy()
    config_with_url.target_url = base_url

    # Create test document in MongoDB
    db = await get_db()
    await create_load_test(db, test_id, config_with_url)

    # Start background task
    background_tasks.add_task(run_load_test_http, test_id, config_with_url, base_url)

    return LoadTestProgress(
        test_id=test_id,
        status="running",
        elapsed_seconds=0,
        total_transactions=0,
        successful=0,
        failed=0,
        current_tps=0,
        avg_latency_ms=0,
        p95_latency_ms=0,
        p99_latency_ms=0,
        risk_distribution={},
    )


async def run_load_test_http(test_id: str, config: LoadTestConfig, base_url: str):
    """
    Background task that executes the load test using HTTP calls.

    Uses httpx with connection pooling for high-performance HTTP requests.
    State is synced to MongoDB periodically for multi-worker visibility.
    """
    db = await get_db()
    score_url = f"{base_url}/score-transaction"

    logger.info(
        f"[LOADTEST:{test_id}] Started: target_tps={config.target_tps}, "
        f"duration={config.duration_seconds}s, concurrency={config.concurrency}, "
        f"fraud_rate={config.fraud_rate}, score_url={score_url}"
    )

    # Local state for batching (kept in memory during test)
    local_state = {
        "successful": 0,
        "failed": 0,
        "latencies": [],
        "risk_distribution": {"low": 0, "medium": 0, "high": 0},
        "recent_transactions": [],  # Last N transactions for UI feed
        "last_sync_successful": 0,
        "last_sync_failed": 0,
        "last_sync_latency_sum": 0.0,
        "last_sync_latency_count": 0,
        "last_sync_risk": {"low": 0, "medium": 0, "high": 0},
    }

    try:
        # Get customer pool using configured sampling method
        # Default: chunk_based for even shard distribution, random as fallback
        #
        # Pool size calculation (when not explicitly set):
        # - Formula: min(TPS * 10, 10000)
        # - At 100 TPS: 1000 customers → 0.1 writes/sec/customer (very low contention)
        # - At 1000 TPS: 10000 customers → 0.1 writes/sec/customer (very low contention)
        # - At 10000 TPS: 10000 customers → 1 write/sec/customer (optimal for benchmarks)
        #
        # Write contention math:
        # - Each transaction updates 1 customer document (features.latest_*)
        # - MongoDB uses document-level locking (~5ms per update)
        # - At 10 writes/sec/customer: 50ms lock time/sec = 5% contention (marginal)
        # - At 1 write/sec/customer: 5ms lock time/sec = 0.5% contention (ideal)
        if config.customer_pool_size:
            pool_size = config.customer_pool_size
        else:
            pool_size = min(config.target_tps * 10, 10000)  # Auto-calculate, cap at 10K

        sampling_method = config.sampling_method if hasattr(config, 'sampling_method') else "chunk_based"
        force_refresh = config.force_refresh_customers if hasattr(config, 'force_refresh_customers') else False

        # Calculate expected write contention
        writes_per_sec_per_customer = config.target_tps / pool_size if pool_size > 0 else 0
        expected_lock_time_pct = writes_per_sec_per_customer * 5 / 1000 * 100  # 5ms per update

        logger.info(
            f"[LOADTEST:{test_id}] Loading customer pool: size={pool_size}, "
            f"method={sampling_method}, force_refresh={force_refresh}"
        )
        logger.info(
            f"[LOADTEST:{test_id}] Write contention: {writes_per_sec_per_customer:.2f} writes/sec/customer, "
            f"~{expected_lock_time_pct:.1f}% expected lock time"
        )

        customer_pool = await get_sampled_customers(
            db,
            size=pool_size,
            method=sampling_method,
            force_refresh=force_refresh,
        )

        if not customer_pool:
            await fail_load_test(db, test_id, "No customers in database. Run 'make seed-test' first.")
            logger.error(f"[LOADTEST:{test_id}] Failed: No customers in database")
            return

        # Log cache stats for debugging
        cache_stats = get_customer_cache_stats()
        logger.info(
            f"[LOADTEST:{test_id}] Customer pool loaded: {len(customer_pool)} customers "
            f"(method: {cache_stats.get('method')}, cached: {cache_stats.get('loaded')})"
        )

        # Create HTTP client with connection pooling
        limits = httpx.Limits(
            max_connections=config.concurrency,
            max_keepalive_connections=config.concurrency
        )
        timeout = httpx.Timeout(30.0, connect=10.0)

        async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
            start_time = time.perf_counter()
            end_time = start_time + config.duration_seconds
            start_datetime = datetime.utcnow()

            # Semaphore for concurrency control
            semaphore = asyncio.Semaphore(config.concurrency)
            
            # Track sync timing
            last_sync_time = start_time
            transactions_since_sync = 0

            async def make_request():
                """Make a single HTTP request to score-transaction."""
                nonlocal transactions_since_sync
                async with semaphore:
                    # Check stop requested from MongoDB periodically
                    customer = random.choice(customer_pool)
                    fraud_type = "blacklist" if random.random() < config.fraud_rate else None
                    payload = generate_transaction_payload(customer, fraud_type)

                    req_start = time.perf_counter()
                    try:
                        response = await client.post(score_url, json=payload)
                        latency_ms = (time.perf_counter() - req_start) * 1000

                        if response.status_code == 200:
                            data = response.json()
                            local_state["successful"] += 1
                            local_state["latencies"].append(latency_ms)
                            risk_level = data.get("risk_level", "unknown")
                            if risk_level in local_state["risk_distribution"]:
                                local_state["risk_distribution"][risk_level] += 1
                            
                            # Capture transaction for UI feed
                            local_state["recent_transactions"].append({
                                "customer_id": customer["customer_id"],
                                "amount": payload["amount"],
                                "channel": payload["channel"],
                                "risk_level": risk_level,
                                "latency_ms": round(latency_ms, 2),
                                "timestamp": datetime.utcnow().isoformat()
                            })
                            # Keep only last N transactions
                            if len(local_state["recent_transactions"]) > MAX_RECENT_TRANSACTIONS:
                                local_state["recent_transactions"] = local_state["recent_transactions"][-MAX_RECENT_TRANSACTIONS:]
                        else:
                            local_state["failed"] += 1
                            response_text = response.text[:200] if response.text else "(empty)"
                            logger.warning(
                                f"[LOADTEST:{test_id}] HTTP Error: status={response.status_code}, "
                                f"response={response_text}"
                            )
                    except httpx.TimeoutException as e:
                        local_state["failed"] += 1
                        logger.warning(f"[LOADTEST:{test_id}] Timeout: {e}")
                    except httpx.ConnectError as e:
                        local_state["failed"] += 1
                        logger.warning(f"[LOADTEST:{test_id}] Connection Error: {e}")
                    except Exception as e:
                        local_state["failed"] += 1
                        logger.warning(f"[LOADTEST:{test_id}] Request Exception: {type(e).__name__}: {e}")
                    finally:
                        transactions_since_sync += 1

            async def sync_to_mongodb(current_tps: float):
                """Sync local state to MongoDB."""
                nonlocal last_sync_time, transactions_since_sync
                
                # Calculate deltas since last sync
                successful_delta = local_state["successful"] - local_state["last_sync_successful"]
                failed_delta = local_state["failed"] - local_state["last_sync_failed"]
                
                # Get new latencies since last sync
                new_latencies = local_state["latencies"][local_state["last_sync_latency_count"]:]
                latency_sum_delta = sum(new_latencies)
                latency_count_delta = len(new_latencies)
                latency_min = min(new_latencies) if new_latencies else None
                latency_max = max(new_latencies) if new_latencies else None
                
                # Risk distribution delta
                risk_delta = {}
                for k in ["low", "medium", "high"]:
                    delta = local_state["risk_distribution"][k] - local_state["last_sync_risk"][k]
                    if delta > 0:
                        risk_delta[k] = delta
                
                # Update MongoDB
                if successful_delta > 0 or failed_delta > 0:
                    await update_load_test_progress(
                        db, test_id,
                        successful_delta, failed_delta,
                        latency_sum_delta, latency_count_delta,
                        latency_min, latency_max,
                        new_latencies[-100:] if new_latencies else [],  # Only push last 100 per sync
                        risk_delta,
                        current_tps,
                        local_state["recent_transactions"][-MAX_RECENT_TRANSACTIONS:]  # Last 50 transactions for UI
                    )
                
                # Update sync tracking
                local_state["last_sync_successful"] = local_state["successful"]
                local_state["last_sync_failed"] = local_state["failed"]
                local_state["last_sync_latency_count"] = len(local_state["latencies"])
                local_state["last_sync_risk"] = local_state["risk_distribution"].copy()
                last_sync_time = time.perf_counter()
                transactions_since_sync = 0

            tasks = []
            transactions_sent = 0
            last_log_time = start_time
            stop_check_time = start_time

            # Main load generation loop
            while time.perf_counter() < end_time:
                current_time = time.perf_counter()
                elapsed = current_time - start_time

                # Check stop requested every second
                if current_time - stop_check_time >= 1.0:
                    if await check_stop_requested(db, test_id):
                        logger.info(f"[LOADTEST:{test_id}] Stop requested, terminating...")
                        break
                    stop_check_time = current_time

                # Calculate how many transactions should have been sent by now
                target_transactions = int(config.target_tps * elapsed)
                transactions_to_send = target_transactions - transactions_sent

                # Generate and send transactions
                for _ in range(max(0, transactions_to_send)):
                    tasks.append(asyncio.create_task(make_request()))
                    transactions_sent += 1

                # Calculate current TPS
                total_completed = local_state["successful"] + local_state["failed"]
                current_tps = total_completed / elapsed if elapsed > 0 else 0

                # Sync to MongoDB every SYNC_INTERVAL_MS or SYNC_BATCH_SIZE transactions
                time_since_sync = (current_time - last_sync_time) * 1000
                if time_since_sync >= SYNC_INTERVAL_MS or transactions_since_sync >= SYNC_BATCH_SIZE:
                    await sync_to_mongodb(current_tps)

                # Log progress every second
                if current_time - last_log_time >= 1.0:
                    latencies = local_state["latencies"]
                    avg_latency = sum(latencies) / len(latencies) if latencies else 0
                    logger.info(
                        f"[LOADTEST:{test_id}] Progress: {elapsed:.1f}s | "
                        f"TPS: {current_tps:.0f} | "
                        f"OK: {local_state['successful']} | ERR: {local_state['failed']} | "
                        f"Avg Latency: {avg_latency:.1f}ms"
                    )
                    last_log_time = current_time

                # Small sleep to prevent tight loop
                await asyncio.sleep(0.005)

            # Wait for remaining tasks to complete
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        # Calculate final statistics
        end_time_actual = time.perf_counter()
        duration = end_time_actual - start_time
        latencies = local_state["latencies"]
        
        # Check if stopped
        was_stopped = await check_stop_requested(db, test_id)
        final_status = "stopped" if was_stopped else "completed"

        # Build final result
        final_result = {
            "test_id": test_id,
            "config": config.model_dump(),
            "status": final_status,
            "start_time": start_datetime.isoformat(),
            "end_time": datetime.utcnow().isoformat(),
            "duration_seconds": round(duration, 2),
            "total_transactions": local_state["successful"] + local_state["failed"],
            "successful": local_state["successful"],
            "failed": local_state["failed"],
            "error_rate": round(local_state["failed"] / max(local_state["successful"] + local_state["failed"], 1) * 100, 2),
            "throughput_tps": round(local_state["successful"] / duration if duration > 0 else 0, 2),
            "avg_latency_ms": round(sum(latencies) / len(latencies) if latencies else 0, 2),
            "min_latency_ms": round(min(latencies) if latencies else 0, 2),
            "max_latency_ms": round(max(latencies) if latencies else 0, 2),
            "p50_latency_ms": round(calculate_percentile(latencies, 50), 2),
            "p95_latency_ms": round(calculate_percentile(latencies, 95), 2),
            "p99_latency_ms": round(calculate_percentile(latencies, 99), 2),
            "risk_distribution": local_state["risk_distribution"],
            "latency_histogram": build_histogram(latencies),
        }

        # Final sync and complete
        await complete_load_test(db, test_id, final_result, final_status)

        # Log comprehensive completion stats
        risk_dist_str = ", ".join(f"{k}={v}" for k, v in local_state["risk_distribution"].items())
        logger.info(
            f"[LOADTEST:{test_id}] Completed: status={final_status}, "
            f"duration={duration:.1f}s"
        )
        logger.info(
            f"[LOADTEST:{test_id}] Results: total={final_result['total_transactions']}, "
            f"successful={final_result['successful']}, failed={final_result['failed']}, "
            f"error_rate={final_result['error_rate']:.1f}%"
        )
        logger.info(
            f"[LOADTEST:{test_id}] Performance: throughput={final_result['throughput_tps']:.1f} TPS, "
            f"avg={final_result['avg_latency_ms']:.1f}ms, p50={final_result['p50_latency_ms']:.1f}ms, "
            f"p95={final_result['p95_latency_ms']:.1f}ms, p99={final_result['p99_latency_ms']:.1f}ms"
        )
        logger.info(f"[LOADTEST:{test_id}] Risk Distribution: {risk_dist_str or 'none'}")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(f"[LOADTEST:{test_id}] Failed with error: {error_msg}")
        await fail_load_test(db, test_id, error_msg)


@router.get("/progress/{test_id}", response_model=LoadTestProgress)
async def get_load_test_progress(test_id: str):
    """Get the current progress of a running load test."""
    db = await get_db()
    doc = await get_load_test(db, test_id)
    
    if not doc:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "Test not found"})

    # Calculate elapsed time
    start_time = doc["start_time"]
    if isinstance(start_time, str):
        start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    elapsed = (datetime.utcnow() - start_time).total_seconds()

    # Calculate latency stats from stored data
    latency_stats = doc.get("latency_stats", {})
    latency_sum = latency_stats.get("sum", 0)
    latency_count = latency_stats.get("count", 0)
    avg_latency = latency_sum / latency_count if latency_count > 0 else 0

    # Calculate scoring vs persist breakdown (from Locust sampler data)
    scoring_sum = latency_stats.get("scoring_sum", 0)
    persist_sum = latency_stats.get("persist_sum", 0)
    avg_scoring = scoring_sum / latency_count if latency_count > 0 else 0
    avg_persist = persist_sum / latency_count if latency_count > 0 else 0

    # Get samples for percentile calculation
    samples = latency_stats.get("samples", [])
    p95 = calculate_percentile(samples, 95)
    p99 = calculate_percentile(samples, 99)

    # Get recent transactions for UI feed
    raw_transactions = doc.get("recent_transactions", [])
    recent_transactions = [
        RecentTransaction(**txn) for txn in raw_transactions
    ]

    return LoadTestProgress(
        test_id=test_id,
        status=doc["status"],
        elapsed_seconds=round(elapsed, 2),
        total_transactions=doc["total_transactions"],
        successful=doc["successful"],
        failed=doc["failed"],
        current_tps=round(doc.get("current_tps", 0), 2),
        avg_latency_ms=round(avg_latency, 2),
        avg_scoring_ms=round(avg_scoring, 2),
        avg_persist_ms=round(avg_persist, 2),
        p95_latency_ms=round(p95, 2),
        p99_latency_ms=round(p99, 2),
        risk_distribution=doc.get("risk_distribution", {}),
        recent_transactions=recent_transactions,
        error_message=doc.get("error_message"),
    )


@router.get("/result/{test_id}", response_model=LoadTestResult)
async def get_load_test_result(test_id: str):
    """Get the final result of a completed load test."""
    db = await get_db()
    doc = await get_load_test(db, test_id)
    
    if not doc:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "Test result not found"})

    if doc["status"] == "running":
        raise HTTPException(
            status_code=400,
            detail={"error": "test_running", "message": "Test is still running. Use /progress endpoint."}
        )
    
    if doc["status"] == "failed" and not doc.get("final_result"):
        raise HTTPException(
            status_code=400,
            detail={"error": "test_failed", "message": doc.get("error_message", "Test failed")}
        )

    # Get final result from document
    final_result = doc.get("final_result")
    if not final_result:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "Test result not found"})

    # Parse dates if they're strings
    start_time = final_result["start_time"]
    end_time = final_result["end_time"]
    if isinstance(start_time, str):
        start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    if isinstance(end_time, str):
        end_time = datetime.fromisoformat(end_time.replace("Z", "+00:00"))

    return LoadTestResult(
        test_id=final_result["test_id"],
        config=LoadTestConfig(**final_result["config"]),
        status=final_result["status"],
        start_time=start_time,
        end_time=end_time,
        duration_seconds=final_result["duration_seconds"],
        total_transactions=final_result["total_transactions"],
        successful=final_result["successful"],
        failed=final_result["failed"],
        error_rate=final_result["error_rate"],
        throughput_tps=final_result["throughput_tps"],
        avg_latency_ms=final_result["avg_latency_ms"],
        min_latency_ms=final_result["min_latency_ms"],
        max_latency_ms=final_result["max_latency_ms"],
        p50_latency_ms=final_result["p50_latency_ms"],
        p95_latency_ms=final_result["p95_latency_ms"],
        p99_latency_ms=final_result["p99_latency_ms"],
        risk_distribution=final_result["risk_distribution"],
        latency_histogram=final_result["latency_histogram"],
    )


@router.post("/stop/{test_id}")
async def stop_load_test(test_id: str):
    """Stop a running load test."""
    db = await get_db()
    doc = await get_load_test(db, test_id)
    
    if not doc:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "Test not found"})

    if doc["status"] != "running":
        raise HTTPException(
            status_code=400,
            detail={"error": "not_running", "message": f"Test is not running (status: {doc['status']})"}
        )

    success = await request_stop_load_test(db, test_id)
    if success:
        logger.info(f"Stop requested for load test {test_id}")
        return {"message": "Stop requested", "test_id": test_id}
    else:
        raise HTTPException(
            status_code=400,
            detail={"error": "stop_failed", "message": "Failed to request stop"}
        )


@router.get("/customer-pool")
async def get_customer_pool_info(
    size: int = Query(10000, ge=1, le=50000),
    method: str = Query("chunk_based", description="Sampling method: 'chunk_based' or 'random'"),
    force_refresh: bool = Query(False, description="Force refresh cache"),
):
    """
    Get sampled customers for load testing.

    - **chunk_based** (default): Samples proportionally from each MongoDB chunk
      for even shard distribution. Cached for 1 hour.
    - **random**: Uses MongoDB $sample. Simple but can concentrate on one shard.

    The same customers are reused across tests (cached) unless force_refresh=true.
    """
    db = await get_db()
    pool = await get_sampled_customers(
        db,
        size=size,
        method=method,
        force_refresh=force_refresh,
    )
    cache_stats = get_customer_cache_stats()

    return {
        "count": len(pool),
        "customers_sample": pool[:10],  # Only return first 10 for display
        "cache": cache_stats,
        "message": f"Pool contains {len(pool)} customers (method: {method})"
    }


@router.get("/customer-pool/stats")
async def get_customer_pool_stats():
    """Get customer pool cache statistics."""
    return get_customer_cache_stats()


@router.post("/customer-pool/invalidate")
async def invalidate_customer_pool():
    """
    Invalidate the customer pool cache.

    Next load test will re-sample customers from the database.
    """
    invalidate_customer_cache()
    return {"message": "Customer cache invalidated", "cache": get_customer_cache_stats()}
