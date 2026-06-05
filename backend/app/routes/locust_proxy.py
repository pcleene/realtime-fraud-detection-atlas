"""
Locust Proxy API - Control Locust load tests running on the bastion host.

This module provides API endpoints to control a Locust instance running on a separate
bastion host. It proxies requests to Locust's REST API for starting/stopping tests
and retrieving statistics.

Architecture:
    Svelte UI → FastAPI (/loadtest/external/*) → Locust (bastion:8089)

When a Locust test starts, this module also creates a load_tests document in MongoDB.
The /score-transaction endpoint samples transactions into this document, enabling
the UI to show transaction feed and risk distribution even for Locust-driven traffic.

Environment Variables:
    LOCUST_HOST: The bastion host running Locust (default: localhost)
    LOCUST_PORT: The Locust web UI port (default: 8089)
"""

import logging
import secrets
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import get_db
from app.services.locust_sampler import clear_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/loadtest/external", tags=["loadtest-external"])

# Configuration from settings
settings = get_settings()
LOCUST_HOST = settings.locust_host
LOCUST_PORT = settings.locust_port
LOCUST_BASTION_HOST = settings.locust_bastion_host

# HTTP client timeout
TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Target type for Locust connection
LocustTarget = Literal["local", "bastion"]


def get_locust_url(target: LocustTarget = "local") -> str:
    """Get the Locust base URL for the specified target."""
    host = LOCUST_BASTION_HOST if target == "bastion" else LOCUST_HOST
    return f"http://{host}:{LOCUST_PORT}"


# =============================================================================
# Models
# =============================================================================

class LocustStartRequest(BaseModel):
    """Request to start a Locust load test."""
    user_count: int = Field(500, ge=1, le=10000, description="Number of concurrent users")
    spawn_rate: int = Field(100, ge=1, le=1000, description="Users to spawn per second")
    host: Optional[str] = Field(None, description="Target host URL (uses Locust default if not set)")
    target: Literal["local", "bastion"] = Field("local", description="Where Locust is running: 'local' or 'bastion'")


class LocustStats(BaseModel):
    """Aggregated statistics from Locust."""
    state: str  # "ready", "spawning", "running", "stopped"
    user_count: int
    total_requests: int
    total_failures: int
    current_rps: float
    current_fail_rate: float
    avg_response_time: float
    min_response_time: float
    max_response_time: float
    p50_response_time: float
    p90_response_time: float
    p95_response_time: float
    p99_response_time: float
    error_messages: List[str] = []


class LocustEndpointStats(BaseModel):
    """Statistics for a specific endpoint."""
    method: str
    name: str
    num_requests: int
    num_failures: int
    avg_response_time: float
    min_response_time: float
    max_response_time: float
    current_rps: float
    current_fail_rate: float


class LocustStatus(BaseModel):
    """Current status of Locust."""
    available: bool
    state: str  # "ready", "spawning", "running", "stopped", "unavailable"
    user_count: int = 0
    workers: int = 0
    message: str = ""


# =============================================================================
# Helper Functions
# =============================================================================

async def locust_request(
    method: str,
    endpoint: str,
    target: LocustTarget = "local",
    **kwargs
) -> Dict[str, Any]:
    """Make a request to the Locust API."""
    base_url = get_locust_url(target)
    url = f"{base_url}{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            if method.upper() == "GET":
                response = await client.get(url, **kwargs)
            elif method.upper() == "POST":
                response = await client.post(url, **kwargs)
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            # Some Locust endpoints return empty or non-JSON responses
            if not response.content or len(response.content.strip()) == 0:
                return {}
            try:
                return response.json()
            except Exception:
                # Return empty dict for non-JSON responses (like /stats/reset)
                return {}
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "locust_unavailable",
                "message": f"Cannot connect to Locust at {base_url}. Is it running?"
            }
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail={
                "error": "locust_timeout",
                "message": f"Timeout connecting to Locust at {base_url}"
            }
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail={
                "error": "locust_error",
                "message": f"Locust returned error: {e.response.text}"
            }
        )


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/status", response_model=LocustStatus)
async def get_locust_status(
    target: LocustTarget = Query("local", description="Where Locust is running: 'local' or 'bastion'")
):
    """
    Check if Locust is available and get its current state.

    Returns the Locust state: ready, spawning, running, stopped, or unavailable.
    """
    base_url = get_locust_url(target)
    try:
        # Try to get stats - this tells us Locust is running
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{base_url}/stats/requests")
            if response.status_code == 200:
                data = response.json()
                workers_list = data.get("workers", [])
                return LocustStatus(
                    available=True,
                    state=data.get("state", "unknown"),
                    user_count=data.get("user_count", 0),
                    workers=len(workers_list) if isinstance(workers_list, list) else 0,
                    message=f"Locust is running at {base_url}"
                )
            else:
                return LocustStatus(
                    available=False,
                    state="error",
                    message=f"Locust returned status {response.status_code}"
                )
    except httpx.ConnectError:
        return LocustStatus(
            available=False,
            state="unavailable",
            message=f"Cannot connect to Locust at {base_url}"
        )
    except Exception as e:
        return LocustStatus(
            available=False,
            state="error",
            message=str(e)
        )


@router.post("/start")
async def start_locust_test(config: LocustStartRequest):
    """
    Start a Locust load test (swarm).

    This tells Locust to start spawning users. Locust must already be running
    with its master process on the bastion host or locally.

    Also creates a load_tests document in MongoDB for transaction sampling.
    The /score-transaction endpoint will sample transactions into this document,
    enabling the UI to show transaction feed and risk distribution.
    """
    logger.info(f"Starting Locust test: users={config.user_count}, spawn_rate={config.spawn_rate}, target={config.target}")

    # Generate test ID
    test_id = f"locust-{secrets.token_hex(4)}"

    # Create load_tests document in MongoDB
    db = await get_db()
    doc = {
        "test_id": test_id,
        "source": "locust",
        "config": {
            "user_count": config.user_count,
            "spawn_rate": config.spawn_rate,
            "host": config.host,
            "target": config.target,
        },
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
            "samples": [],
            "scoring_sum": 0.0,  # Total of scoring_ms (reads + rules)
            "persist_sum": 0.0,  # Total of persist_ms (writes)
        },
        "recent_transactions": [],
        "stop_requested": False,
        "error_message": None,
        "final_result": None,
    }
    await db.load_tests.insert_one(doc)
    logger.info(f"Created load_tests document: {test_id}")

    # Clear sampler cache so it picks up the new test immediately
    clear_cache()

    # Build request data for Locust
    data = {
        "user_count": config.user_count,
        "spawn_rate": config.spawn_rate,
    }
    if config.host:
        data["host"] = config.host

    result = await locust_request("POST", "/swarm", target=config.target, data=data)

    locust_url = get_locust_url(config.target)
    return {
        "success": True,
        "test_id": test_id,
        "message": f"Started Locust test with {config.user_count} users at {locust_url}",
        "target": config.target,
        "locust_url": locust_url,
        "details": result
    }


@router.get("/stop")
async def stop_locust_test(
    target: LocustTarget = Query("local", description="Where Locust is running: 'local' or 'bastion'")
):
    """
    Stop the current Locust load test.

    This stops spawning new users and ends the test.
    Also marks the MongoDB load_tests document as completed.
    """
    logger.info(f"Stopping Locust test (target={target})")

    # Mark the MongoDB document as completed
    db = await get_db()

    # Find the active Locust test
    active_test = await db.load_tests.find_one(
        {"source": "locust", "status": "running"}
    )

    if active_test:
        test_id = active_test["test_id"]
        start_time = active_test["start_time"]
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        # Calculate final stats
        total_txns = active_test.get("total_transactions", 0)
        successful = active_test.get("successful", 0)
        failed = active_test.get("failed", 0)
        latency_stats = active_test.get("latency_stats", {})

        throughput_tps = successful / duration if duration > 0 else 0
        avg_latency = latency_stats.get("sum", 0) / latency_stats.get("count", 1) if latency_stats.get("count", 0) > 0 else 0

        # Update the document
        await db.load_tests.update_one(
            {"test_id": test_id},
            {
                "$set": {
                    "status": "completed",
                    "end_time": end_time,
                    "current_tps": round(throughput_tps, 2),
                    "final_result": {
                        "duration_seconds": round(duration, 2),
                        "total_transactions": total_txns,
                        "successful": successful,
                        "failed": failed,
                        "throughput_tps": round(throughput_tps, 2),
                        "avg_latency_ms": round(avg_latency, 2),
                    }
                }
            }
        )
        logger.info(f"Marked load_tests document as completed: {test_id}")

    # Clear the sampler cache
    clear_cache()

    # Stop Locust
    result = await locust_request("GET", "/stop", target=target)

    return {
        "success": True,
        "message": "Locust test stopped",
        "target": target,
        "test_id": active_test["test_id"] if active_test else None,
        "details": result
    }


@router.get("/reset")
async def reset_locust_stats(
    target: LocustTarget = Query("local", description="Where Locust is running: 'local' or 'bastion'")
):
    """
    Reset Locust statistics.

    Clears all accumulated statistics without stopping the test.
    """
    logger.info(f"Resetting Locust stats (target={target})")
    result = await locust_request("GET", "/stats/reset", target=target)

    return {
        "success": True,
        "message": "Locust statistics reset",
        "target": target,
        "details": result
    }


@router.get("/stats", response_model=LocustStats)
async def get_locust_stats(
    target: LocustTarget = Query("local", description="Where Locust is running: 'local' or 'bastion'")
):
    """
    Get current Locust statistics.

    Returns aggregated statistics including:
    - Total requests and failures
    - Current RPS
    - Response time percentiles (P50, P90, P95, P99)
    - Error messages
    """
    data = await locust_request("GET", "/stats/requests", target=target)

    # Extract stats from the "Total" entry
    stats_list = data.get("stats", [])
    total_stats = None
    for s in stats_list:
        if s.get("name") == "Aggregated":
            total_stats = s
            break

    if not total_stats:
        # Use first stat or empty
        total_stats = stats_list[0] if stats_list else {}

    # Extract error messages
    errors = data.get("errors", [])
    error_messages = [e.get("error", str(e)) for e in errors[:10]]  # Limit to 10

    # Percentiles are in the stats entries, not at root level
    # Locust uses: median_response_time (P50), response_time_percentile_0.95, response_time_percentile_0.99
    p50 = total_stats.get("median_response_time", 0) or 0
    p90 = total_stats.get("response_time_percentile_0.9", 0) or 0
    p95 = total_stats.get("response_time_percentile_0.95", 0) or 0
    p99 = total_stats.get("response_time_percentile_0.99", 0) or 0

    return LocustStats(
        state=data.get("state", "unknown"),
        user_count=data.get("user_count", 0),
        total_requests=total_stats.get("num_requests", 0),
        total_failures=total_stats.get("num_failures", 0),
        current_rps=round(data.get("total_rps", 0), 2),
        current_fail_rate=round(data.get("fail_ratio", 0) * 100, 2),
        avg_response_time=round(total_stats.get("avg_response_time", 0), 2),
        min_response_time=round(total_stats.get("min_response_time", 0), 2),
        max_response_time=round(total_stats.get("max_response_time", 0), 2),
        p50_response_time=round(p50, 2),
        p90_response_time=round(p90, 2),
        p95_response_time=round(p95, 2),
        p99_response_time=round(p99, 2),
        error_messages=error_messages,
    )


@router.get("/stats/endpoints", response_model=List[LocustEndpointStats])
async def get_locust_endpoint_stats(
    target: LocustTarget = Query("local", description="Where Locust is running: 'local' or 'bastion'")
):
    """
    Get per-endpoint statistics from Locust.

    Returns statistics broken down by endpoint (e.g., /score-transaction, /health).
    """
    data = await locust_request("GET", "/stats/requests", target=target)

    stats_list = data.get("stats", [])
    result = []

    for s in stats_list:
        if s.get("name") == "Aggregated":
            continue  # Skip the aggregate

        result.append(LocustEndpointStats(
            method=s.get("method", ""),
            name=s.get("name", ""),
            num_requests=s.get("num_requests", 0),
            num_failures=s.get("num_failures", 0),
            avg_response_time=round(s.get("avg_response_time", 0), 2),
            min_response_time=round(s.get("min_response_time", 0), 2),
            max_response_time=round(s.get("max_response_time", 0), 2),
            current_rps=round(s.get("current_rps", 0), 2),
            current_fail_rate=round(s.get("current_fail_per_sec", 0), 2),
        ))

    return result


@router.get("/config")
async def get_locust_config():
    """
    Get current Locust configuration.

    Returns the target host and other configuration details.
    """
    return {
        "local_url": get_locust_url("local"),
        "bastion_url": get_locust_url("bastion"),
        "locust_host": LOCUST_HOST,
        "locust_bastion_host": LOCUST_BASTION_HOST,
        "locust_port": LOCUST_PORT,
        "message": "Use LOCUST_HOST, LOCUST_BASTION_HOST, and LOCUST_PORT environment variables to configure"
    }


@router.get("/active-test")
async def get_active_locust_test():
    """
    Get the currently active Locust load test ID.

    The UI can use this to poll /loadtest/progress/{test_id} for
    transaction feed and risk distribution data.
    """
    db = await get_db()
    active_test = await db.load_tests.find_one(
        {"source": "locust", "status": "running"},
        {"test_id": 1, "start_time": 1, "config": 1}
    )

    if active_test:
        return {
            "active": True,
            "test_id": active_test["test_id"],
            "start_time": active_test["start_time"].isoformat() if active_test.get("start_time") else None,
            "config": active_test.get("config"),
        }
    else:
        return {
            "active": False,
            "test_id": None,
            "message": "No active Locust test"
        }
