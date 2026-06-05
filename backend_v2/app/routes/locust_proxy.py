"""
V2 Locust Proxy API - Control Locust load tests running on bastion host.

Copied from V1 with minimal changes.
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

settings = get_settings()
LOCUST_HOST = settings.locust_host
LOCUST_PORT = settings.locust_port
LOCUST_BASTION_HOST = settings.locust_bastion_host

TIMEOUT = httpx.Timeout(10.0, connect=5.0)
LocustTarget = Literal["local", "bastion"]


def get_locust_url(target: LocustTarget = "local") -> str:
    host = LOCUST_BASTION_HOST if target == "bastion" else LOCUST_HOST
    return f"http://{host}:{LOCUST_PORT}"


class LocustStartRequest(BaseModel):
    user_count: int = Field(500, ge=1, le=10000)
    spawn_rate: int = Field(100, ge=1, le=1000)
    host: Optional[str] = Field(None)
    target: Literal["local", "bastion"] = Field("local")


class LocustStats(BaseModel):
    state: str
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


class LocustStatus(BaseModel):
    available: bool
    state: str
    user_count: int = 0
    workers: int = 0
    message: str = ""


async def locust_request(method: str, endpoint: str, target: LocustTarget = "local", **kwargs) -> Dict[str, Any]:
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
            if not response.content or len(response.content.strip()) == 0:
                return {}
            try:
                return response.json()
            except Exception:
                return {}
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail={"error": "locust_unavailable", "message": f"Cannot connect to Locust at {base_url}"})
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail={"error": "locust_timeout"})
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail={"error": "locust_error", "message": e.response.text})


@router.get("/status", response_model=LocustStatus)
async def get_locust_status(target: LocustTarget = Query("local")):
    base_url = get_locust_url(target)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{base_url}/stats/requests")
            if response.status_code == 200:
                data = response.json()
                workers_list = data.get("workers", [])
                return LocustStatus(
                    available=True, state=data.get("state", "unknown"),
                    user_count=data.get("user_count", 0),
                    workers=len(workers_list) if isinstance(workers_list, list) else 0,
                    message=f"Locust is running at {base_url}",
                )
            return LocustStatus(available=False, state="error", message=f"Status {response.status_code}")
    except httpx.ConnectError:
        return LocustStatus(available=False, state="unavailable", message=f"Cannot connect to {base_url}")
    except Exception as e:
        return LocustStatus(available=False, state="error", message=str(e))


@router.post("/start")
async def start_locust_test(config: LocustStartRequest):
    test_id = f"locust-{secrets.token_hex(4)}"
    db = await get_db()
    doc = {
        "test_id": test_id, "source": "locust",
        "config": {"user_count": config.user_count, "spawn_rate": config.spawn_rate, "host": config.host, "target": config.target},
        "status": "running", "start_time": datetime.utcnow(), "end_time": None,
        "total_transactions": 0, "successful": 0, "failed": 0, "current_tps": 0.0,
        "risk_distribution": {"low": 0, "medium": 0, "high": 0},
        "latency_stats": {"sum": 0.0, "count": 0, "min": None, "max": None, "samples": [], "scoring_sum": 0.0, "persist_sum": 0.0, "computed": {"avg": 0, "p50": 0, "p95": 0, "p99": 0}},
        "recent_transactions": [], "stop_requested": False, "error_message": None, "final_result": None,
    }
    await db.load_tests.insert_one(doc)
    clear_cache()

    data = {"user_count": config.user_count, "spawn_rate": config.spawn_rate}
    if config.host:
        data["host"] = config.host
    result = await locust_request("POST", "/swarm", target=config.target, data=data)

    return {"success": True, "test_id": test_id, "message": f"Started with {config.user_count} users", "details": result}


@router.get("/stop")
async def stop_locust_test(target: LocustTarget = Query("local")):
    db = await get_db()
    active_test = await db.load_tests.find_one({"source": "locust", "status": "running"})
    if active_test:
        test_id = active_test["test_id"]
        duration = (datetime.utcnow() - active_test["start_time"]).total_seconds()
        successful = active_test.get("successful", 0)
        throughput = successful / duration if duration > 0 else 0
        await db.load_tests.update_one(
            {"test_id": test_id},
            {"$set": {"status": "completed", "end_time": datetime.utcnow(), "current_tps": round(throughput, 2)}},
        )
    clear_cache()
    result = await locust_request("GET", "/stop", target=target)
    return {"success": True, "message": "Stopped", "test_id": active_test["test_id"] if active_test else None, "details": result}


@router.get("/reset")
async def reset_locust_stats(target: LocustTarget = Query("local")):
    await locust_request("GET", "/stats/reset", target=target)
    return {"success": True, "message": "Statistics reset"}


@router.get("/stats", response_model=LocustStats)
async def get_locust_stats(target: LocustTarget = Query("local")):
    data = await locust_request("GET", "/stats/requests", target=target)
    stats_list = data.get("stats", [])
    total_stats = next((s for s in stats_list if s.get("name") == "Aggregated"), stats_list[0] if stats_list else {})
    errors = data.get("errors", [])

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
        p50_response_time=round(total_stats.get("median_response_time", 0) or 0, 2),
        p90_response_time=round(total_stats.get("response_time_percentile_0.9", 0) or 0, 2),
        p95_response_time=round(total_stats.get("response_time_percentile_0.95", 0) or 0, 2),
        p99_response_time=round(total_stats.get("response_time_percentile_0.99", 0) or 0, 2),
        error_messages=[e.get("error", str(e)) for e in errors[:10]],
    )


@router.get("/active-test")
async def get_active_locust_test():
    db = await get_db()
    active = await db.load_tests.find_one({"source": "locust", "status": "running"}, {"test_id": 1, "start_time": 1, "config": 1})
    if active:
        return {"active": True, "test_id": active["test_id"], "start_time": active["start_time"].isoformat(), "config": active.get("config")}
    return {"active": False, "test_id": None}


@router.get("/config")
async def get_locust_config():
    return {"local_url": get_locust_url("local"), "bastion_url": get_locust_url("bastion"), "locust_port": LOCUST_PORT}
