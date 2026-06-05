"""
V2 Load Testing API - Full HTTP Stack Testing.

Copied from V1 with V2 payload adaptations.
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
    generate_v2_transaction_payload,
    calculate_percentile,
    build_histogram,
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
    customer_id: str
    amount: float
    channel: str
    risk_level: str
    latency_ms: float
    scoring_ms: float = 0.0
    persist_ms: float = 0.0
    timestamp: str


class LoadTestConfig(BaseModel):
    target_tps: int = Field(100, ge=1, le=10000)
    duration_seconds: int = Field(10, ge=1, le=300)
    concurrency: int = Field(50, ge=1, le=500)
    fraud_rate: float = Field(0.12, ge=0, le=1)
    target_url: Optional[str] = Field(None)
    customer_pool_size: Optional[int] = Field(None, ge=100, le=50000)
    sampling_method: str = Field("chunk_based")
    force_refresh_customers: bool = Field(False)


class LoadTestProgress(BaseModel):
    test_id: str
    status: str
    elapsed_seconds: float
    total_transactions: int
    successful: int
    failed: int
    current_tps: float
    avg_latency_ms: float
    avg_scoring_ms: float = 0.0
    avg_persist_ms: float = 0.0
    p95_latency_ms: float
    p99_latency_ms: float
    risk_distribution: Dict[str, int]
    recent_transactions: List[RecentTransaction] = []
    error_message: Optional[str] = None


class LoadTestResult(BaseModel):
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
            "sum": 0.0, "count": 0, "min": None, "max": None, "samples": []
        },
        "stop_requested": False,
        "error_message": None,
        "final_result": None,
    }
    await db.load_tests.insert_one(doc)


async def get_load_test(db, test_id: str) -> Optional[Dict[str, Any]]:
    return await db.load_tests.find_one({"test_id": test_id})


async def update_load_test_progress(
    db, test_id, successful_delta, failed_delta,
    latency_sum_delta, latency_count_delta, latency_min, latency_max,
    latency_samples, risk_distribution_delta, current_tps,
    recent_transactions=None,
) -> None:
    update_ops: Dict[str, Any] = {
        "$inc": {
            "total_transactions": successful_delta + failed_delta,
            "successful": successful_delta,
            "failed": failed_delta,
            "latency_stats.sum": latency_sum_delta,
            "latency_stats.count": latency_count_delta,
        },
        "$set": {"current_tps": current_tps},
    }
    if recent_transactions is not None:
        update_ops["$set"]["recent_transactions"] = recent_transactions
    for risk_level, count in risk_distribution_delta.items():
        if count > 0:
            update_ops["$inc"][f"risk_distribution.{risk_level}"] = count

    await db.load_tests.update_one({"test_id": test_id}, update_ops)

    sample_update: Dict[str, Any] = {}
    if latency_min is not None:
        sample_update["$min"] = {"latency_stats.min": latency_min}
    if latency_max is not None:
        sample_update["$max"] = {"latency_stats.max": latency_max}
    if sample_update:
        await db.load_tests.update_one({"test_id": test_id}, sample_update)

    if latency_samples:
        await db.load_tests.update_one(
            {"test_id": test_id},
            {"$push": {"latency_stats.samples": {"$each": latency_samples, "$slice": -MAX_LATENCY_SAMPLES}}},
        )


async def complete_load_test(db, test_id, final_result, status) -> None:
    await db.load_tests.update_one(
        {"test_id": test_id},
        {"$set": {"status": status, "end_time": datetime.utcnow(), "final_result": final_result}},
    )


async def fail_load_test(db, test_id, error_message) -> None:
    await db.load_tests.update_one(
        {"test_id": test_id},
        {"$set": {"status": "failed", "end_time": datetime.utcnow(), "error_message": error_message}},
    )


async def request_stop_load_test(db, test_id) -> bool:
    result = await db.load_tests.update_one(
        {"test_id": test_id, "status": "running"},
        {"$set": {"stop_requested": True}},
    )
    return result.modified_count > 0


async def check_stop_requested(db, test_id) -> bool:
    doc = await db.load_tests.find_one({"test_id": test_id}, {"stop_requested": 1})
    return doc.get("stop_requested", False) if doc else False


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/start", response_model=LoadTestProgress)
async def start_load_test(config: LoadTestConfig, background_tasks: BackgroundTasks, request: Request):
    test_id = f"test-{secrets.token_hex(4)}"
    if config.target_url:
        base_url = config.target_url.rstrip("/")
    else:
        base_url = str(request.base_url).rstrip("/")

    config_with_url = config.model_copy()
    config_with_url.target_url = base_url

    db = await get_db()
    await create_load_test(db, test_id, config_with_url)
    background_tasks.add_task(run_load_test_http, test_id, config_with_url, base_url)

    return LoadTestProgress(
        test_id=test_id, status="running", elapsed_seconds=0,
        total_transactions=0, successful=0, failed=0,
        current_tps=0, avg_latency_ms=0, p95_latency_ms=0, p99_latency_ms=0,
        risk_distribution={},
    )


async def run_load_test_http(test_id: str, config: LoadTestConfig, base_url: str):
    db = await get_db()
    score_url = f"{base_url}/score-transaction"

    logger.info(f"[LOADTEST:{test_id}] Started: target_tps={config.target_tps}, duration={config.duration_seconds}s")

    local_state = {
        "successful": 0, "failed": 0, "latencies": [],
        "risk_distribution": {"low": 0, "medium": 0, "high": 0},
        "recent_transactions": [],
        "last_sync_successful": 0, "last_sync_failed": 0,
        "last_sync_latency_sum": 0.0, "last_sync_latency_count": 0,
        "last_sync_risk": {"low": 0, "medium": 0, "high": 0},
    }

    try:
        pool_size = config.customer_pool_size or min(config.target_tps * 10, 10000)
        customer_pool = await get_sampled_customers(
            db, size=pool_size,
            method=config.sampling_method,
            force_refresh=config.force_refresh_customers,
        )

        if not customer_pool:
            await fail_load_test(db, test_id, "No customers. Run 'make seed-v2-test' first.")
            return

        limits = httpx.Limits(max_connections=config.concurrency, max_keepalive_connections=config.concurrency)
        timeout = httpx.Timeout(30.0, connect=10.0)

        async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
            start_time = time.perf_counter()
            end_time = start_time + config.duration_seconds
            start_datetime = datetime.utcnow()
            semaphore = asyncio.Semaphore(config.concurrency)
            last_sync_time = start_time
            transactions_since_sync = 0

            async def make_request():
                nonlocal transactions_since_sync
                async with semaphore:
                    customer = random.choice(customer_pool)
                    payload = generate_v2_transaction_payload(customer)
                    req_start = time.perf_counter()
                    try:
                        response = await client.post(score_url, json=payload)
                        latency_ms = (time.perf_counter() - req_start) * 1000
                        if response.status_code == 200:
                            data = response.json()
                            local_state["successful"] += 1
                            local_state["latencies"].append(latency_ms)
                            risk_level = data.get("fraud_score", {}).get("risk_level", "unknown")
                            if risk_level in local_state["risk_distribution"]:
                                local_state["risk_distribution"][risk_level] += 1
                            local_state["recent_transactions"].append({
                                "customer_id": customer["customer_id"],
                                "amount": payload["at3"],
                                "channel": payload["channel"],
                                "risk_level": risk_level,
                                "latency_ms": round(latency_ms, 2),
                                "timestamp": datetime.utcnow().isoformat(),
                            })
                            if len(local_state["recent_transactions"]) > MAX_RECENT_TRANSACTIONS:
                                local_state["recent_transactions"] = local_state["recent_transactions"][-MAX_RECENT_TRANSACTIONS:]
                        else:
                            local_state["failed"] += 1
                    except Exception:
                        local_state["failed"] += 1
                    finally:
                        transactions_since_sync += 1

            async def sync_to_mongodb(current_tps):
                nonlocal last_sync_time, transactions_since_sync
                s_d = local_state["successful"] - local_state["last_sync_successful"]
                f_d = local_state["failed"] - local_state["last_sync_failed"]
                new_lat = local_state["latencies"][local_state["last_sync_latency_count"]:]
                risk_delta = {k: local_state["risk_distribution"][k] - local_state["last_sync_risk"][k] for k in ["low", "medium", "high"]}
                risk_delta = {k: v for k, v in risk_delta.items() if v > 0}

                if s_d > 0 or f_d > 0:
                    await update_load_test_progress(
                        db, test_id, s_d, f_d,
                        sum(new_lat), len(new_lat),
                        min(new_lat) if new_lat else None,
                        max(new_lat) if new_lat else None,
                        new_lat[-100:] if new_lat else [],
                        risk_delta, current_tps,
                        local_state["recent_transactions"][-MAX_RECENT_TRANSACTIONS:],
                    )

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

            while time.perf_counter() < end_time:
                current_time = time.perf_counter()
                elapsed = current_time - start_time

                if current_time - stop_check_time >= 1.0:
                    if await check_stop_requested(db, test_id):
                        break
                    stop_check_time = current_time

                target_transactions = int(config.target_tps * elapsed)
                for _ in range(max(0, target_transactions - transactions_sent)):
                    tasks.append(asyncio.create_task(make_request()))
                    transactions_sent += 1

                total_completed = local_state["successful"] + local_state["failed"]
                current_tps = total_completed / elapsed if elapsed > 0 else 0

                time_since_sync = (current_time - last_sync_time) * 1000
                if time_since_sync >= SYNC_INTERVAL_MS or transactions_since_sync >= SYNC_BATCH_SIZE:
                    await sync_to_mongodb(current_tps)

                if current_time - last_log_time >= 1.0:
                    lats = local_state["latencies"]
                    avg = sum(lats) / len(lats) if lats else 0
                    logger.info(f"[LOADTEST:{test_id}] {elapsed:.1f}s | TPS:{current_tps:.0f} | OK:{local_state['successful']} | Avg:{avg:.1f}ms")
                    last_log_time = current_time

                await asyncio.sleep(0.005)

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        duration = time.perf_counter() - start_time
        latencies = local_state["latencies"]
        was_stopped = await check_stop_requested(db, test_id)
        final_status = "stopped" if was_stopped else "completed"

        final_result = {
            "test_id": test_id, "config": config.model_dump(), "status": final_status,
            "start_time": start_datetime.isoformat(), "end_time": datetime.utcnow().isoformat(),
            "duration_seconds": round(duration, 2),
            "total_transactions": local_state["successful"] + local_state["failed"],
            "successful": local_state["successful"], "failed": local_state["failed"],
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
        await complete_load_test(db, test_id, final_result, final_status)

    except Exception as e:
        logger.exception(f"[LOADTEST:{test_id}] Failed: {e}")
        await fail_load_test(db, test_id, f"{type(e).__name__}: {e}")


@router.get("/progress/{test_id}", response_model=LoadTestProgress)
async def get_load_test_progress(test_id: str):
    db = await get_db()
    doc = await get_load_test(db, test_id)
    if not doc:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "Test not found"})

    start_time = doc["start_time"]
    if isinstance(start_time, str):
        start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    elapsed = (datetime.utcnow() - start_time).total_seconds()

    latency_stats = doc.get("latency_stats", {})
    latency_count = latency_stats.get("count", 0)
    avg_latency = latency_stats.get("sum", 0) / latency_count if latency_count > 0 else 0
    avg_scoring = latency_stats.get("scoring_sum", 0) / latency_count if latency_count > 0 else 0
    avg_persist = latency_stats.get("persist_sum", 0) / latency_count if latency_count > 0 else 0

    # Use pre-computed percentiles from the sampler pipeline update.
    # Falls back to client-side calculation if computed values not yet available.
    computed = latency_stats.get("computed", {})
    if computed:
        p95 = computed.get("p95", 0) or 0
        p99 = computed.get("p99", 0) or 0
    else:
        samples = latency_stats.get("samples", [])
        p95 = calculate_percentile(samples, 95)
        p99 = calculate_percentile(samples, 99)

    raw_txns = doc.get("recent_transactions", [])
    recent = [RecentTransaction(**t) for t in raw_txns]

    return LoadTestProgress(
        test_id=test_id, status=doc["status"],
        elapsed_seconds=round(elapsed, 2),
        total_transactions=doc["total_transactions"],
        successful=doc["successful"], failed=doc["failed"],
        current_tps=round(doc.get("current_tps", 0), 2),
        avg_latency_ms=round(avg_latency, 2),
        avg_scoring_ms=round(avg_scoring, 2),
        avg_persist_ms=round(avg_persist, 2),
        p95_latency_ms=round(p95, 2),
        p99_latency_ms=round(p99, 2),
        risk_distribution=doc.get("risk_distribution", {}),
        recent_transactions=recent,
        error_message=doc.get("error_message"),
    )


@router.get("/result/{test_id}", response_model=LoadTestResult)
async def get_load_test_result(test_id: str):
    db = await get_db()
    doc = await get_load_test(db, test_id)
    if not doc:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if doc["status"] == "running":
        raise HTTPException(status_code=400, detail={"error": "test_running"})

    fr = doc.get("final_result")
    if not fr:
        raise HTTPException(status_code=404, detail={"error": "no_result"})

    st = fr["start_time"]
    et = fr["end_time"]
    if isinstance(st, str):
        st = datetime.fromisoformat(st.replace("Z", "+00:00"))
    if isinstance(et, str):
        et = datetime.fromisoformat(et.replace("Z", "+00:00"))

    return LoadTestResult(
        test_id=fr["test_id"], config=LoadTestConfig(**fr["config"]),
        status=fr["status"], start_time=st, end_time=et,
        duration_seconds=fr["duration_seconds"],
        total_transactions=fr["total_transactions"],
        successful=fr["successful"], failed=fr["failed"],
        error_rate=fr["error_rate"], throughput_tps=fr["throughput_tps"],
        avg_latency_ms=fr["avg_latency_ms"], min_latency_ms=fr["min_latency_ms"],
        max_latency_ms=fr["max_latency_ms"], p50_latency_ms=fr["p50_latency_ms"],
        p95_latency_ms=fr["p95_latency_ms"], p99_latency_ms=fr["p99_latency_ms"],
        risk_distribution=fr["risk_distribution"],
        latency_histogram=fr["latency_histogram"],
    )


@router.post("/stop/{test_id}")
async def stop_load_test(test_id: str):
    db = await get_db()
    doc = await get_load_test(db, test_id)
    if not doc:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if doc["status"] != "running":
        raise HTTPException(status_code=400, detail={"error": "not_running"})
    success = await request_stop_load_test(db, test_id)
    if success:
        return {"message": "Stop requested", "test_id": test_id}
    raise HTTPException(status_code=400, detail={"error": "stop_failed"})


@router.get("/customer-pool")
async def get_customer_pool_info(
    size: int = Query(10000, ge=1, le=50000),
    method: str = Query("chunk_based"),
    force_refresh: bool = Query(False),
):
    db = await get_db()
    pool = await get_sampled_customers(db, size=size, method=method, force_refresh=force_refresh)
    cache_stats = get_customer_cache_stats()
    return {"count": len(pool), "customers_sample": pool[:10], "cache": cache_stats}


@router.get("/customer-pool/stats")
async def get_customer_pool_stats():
    return get_customer_cache_stats()


@router.post("/customer-pool/invalidate")
async def invalidate_customer_pool():
    invalidate_customer_cache()
    return {"message": "Customer cache invalidated", "cache": get_customer_cache_stats()}
