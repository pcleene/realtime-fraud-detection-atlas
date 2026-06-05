"""
Phase 3: Customer update builders + transaction insert.

Three update strategies, switchable at runtime via UPDATE_MODE:

  standard    — Python computes at6 + window_reset, writes plain $set/$push/$inc.
                Minimal exclusive lock. Requires Phase 1 to provide rolling data.

  pipeline    — Server computes at6 ($reduce/$sqrt) + window_reset ($dateDiff).
                Single DB round trip (no separate read needed for these values).
                Self-contained: all logic in one update_one call.

  aggregation — Server computes at6 ($stdDevPop) + window_reset ($dateDiff) in
                the Phase 1 aggregate read (shared lock), then writes plain
                $set/$push/$inc here. 2 round trips total.

PERFORMANCE AT SCALE (observed at 10K+ TPS, 35M customers, Atlas M60 3-shard):

  Pipeline mode consistently shows better P50 and P99 than aggregation mode.

  Why: pipeline uses a single DB round trip vs aggregation's two. Each round
  trip carries network jitter risk, so 2 ops = 2x the surface area for tail
  spikes. Pipeline also halves connection pool pressure. The theoretical
  advantage of aggregation (shorter exclusive lock) rarely activates because
  same-customer contention is ~0.03% at that cardinality.

  Recommendation: pipeline as default for production at scale. Aggregation
  for workloads with small customer pools or hot-account patterns where
  same-customer contention is frequent.

  Standard mode is the simplest and fastest when Python CPU overhead for at6
  is acceptable (it always is at <50K TPS).
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings
from app.models.requests import ScoreTransactionRequest
from app.utils.timing import Timer


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

async def update_customer(
    db: AsyncDatabase,
    customer_id: str,
    update_doc: dict | list,
) -> float:
    """Execute customer update_one. Returns elapsed ms."""
    with Timer("customer_update") as t:
        await db.customers.update_one(
            {"customer_id": customer_id},
            update_doc,
        )
    return t.elapsed_ms


async def insert_transaction(
    db: AsyncDatabase,
    txn_doc: dict,
) -> Tuple[str, float]:
    """Insert transaction document. Returns (txn_id, elapsed_ms)."""
    with Timer("transaction_insert") as t:
        result = await db.transactions.insert_one(txn_doc)
    return str(result.inserted_id), t.elapsed_ms


# ---------------------------------------------------------------------------
# Update document builders
# ---------------------------------------------------------------------------

def build_customer_update(
    request: ScoreTransactionRequest,
    rolling,
    settings: Settings,
    update_mode: str = "standard",
    computed_at6: Optional[float] = None,
    computed_window_reset: Optional[bool] = None,
) -> dict | list:
    """Build the customer update document.

    Returns a standard update dict (standard/aggregation modes) or a pipeline
    list (pipeline mode).
    """
    if update_mode == "pipeline":
        # Pipeline computes window_reset server-side via $dateDiff — no Python
        # datetime arithmetic needed.
        return _build_pipeline_update(request, rolling, settings)

    if computed_window_reset is not None:
        # Aggregation mode: window reset already computed server-side via $dateDiff
        window_reset = computed_window_reset
    else:
        # Standard mode: compute window reset in Python from rolling.window_start
        window_reset = _compute_window_reset_python(
            request.z1, rolling.window_start, settings.cumulative_window_hours
        )

    if update_mode == "aggregation":
        return _build_standard_update(request, rolling, settings, window_reset,
                                      override_at6=computed_at6)
    else:
        return _build_standard_update(request, rolling, settings, window_reset)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_window_reset_python(
    now: datetime,
    window_start: Optional[datetime],
    cumulative_window_hours: float,
) -> bool:
    """Compute window reset in Python (standard mode fallback).

    Also usable as an alternative to $dateDiff in pipeline mode — pass the
    result as a boolean literal into the $cond expressions instead of using
    stage 0's server-side computation. See _build_pipeline_update docstring.
    """
    if window_start is None:
        return True
    w_start = window_start
    if w_start.tzinfo:
        w_start = w_start.replace(tzinfo=None)
    now_n = now.replace(tzinfo=None) if now.tzinfo else now
    hours_elapsed = (now_n - w_start).total_seconds() / 3600
    return hours_elapsed > cumulative_window_hours


def _build_standard_update(
    request: ScoreTransactionRequest,
    rolling,
    settings: Settings,
    window_reset: bool,
    override_at6: Optional[float] = None,
) -> dict:
    """Standard mode: $set + $push + $addToSet + $inc."""
    now = request.z1

    if override_at6 is not None:
        new_at6 = override_at6
    else:
        recent = list(rolling.at3_recent) + [request.at3]
        recent = recent[-settings.recent_amounts_limit:]
        if len(recent) >= 2:
            mean = sum(recent) / len(recent)
            new_at6 = (sum((x - mean) ** 2 for x in recent) / len(recent)) ** 0.5
        else:
            new_at6 = 0.0

    update: Dict = {
        "$set": {
            "rolling.z1_prev": now,
            "rolling.at3_prev": request.at3,
            "rolling.at3_prev2": rolling.at3_prev,
            "rolling.at6": new_at6,
        },
        "$push": {
            "rolling.at3_recent": {"$each": [request.at3], "$slice": -settings.recent_amounts_limit},
            "rolling.tp_recent": {"$each": [request.tp], "$slice": -settings.recent_purposes_limit},
        },
        "$addToSet": {
            "service_ever": request.service,
        },
    }

    if window_reset:
        update["$set"]["rolling.at3_sum"] = request.at3
        update["$set"]["rolling.window_start"] = now
        update["$set"]["rolling.bl_window_start"] = rolling.bl
    else:
        update["$inc"] = {"rolling.at3_sum": request.at3}

    # bl: decrement for successful financial transactions (atomic, no race conditions)
    if request.is_financial == 1 and request.status == "SUCCESS":
        update.setdefault("$inc", {})["rolling.bl"] = -request.at3

    return update


def _build_pipeline_update(
    request: ScoreTransactionRequest,
    rolling,
    settings: Settings,
) -> list:
    """Pipeline mode: three $set stages — window reset, rolling fields, at6.

    Window reset is computed server-side via $dateDiff so the pipeline is fully
    self-contained (no dependency on Python-side datetime arithmetic).

    Alternative: pass a Python-computed boolean literal into the $cond
    expressions (avoids the $dateDiff stage but requires the app to have read
    rolling.window_start beforehand). To use that approach, add a `window_reset`
    param, replace "$_wr" references with it, and remove stage 0.
    """
    now = request.z1

    # Stage 0: Compute window reset server-side via $dateDiff
    stage_0 = {"$set": {
        "_wr": {
            "$cond": {
                "if": {"$eq": [{"$ifNull": ["$rolling.window_start", None]}, None]},
                "then": True,
                "else": {
                    "$gt": [
                        {"$dateDiff": {
                            "startDate": "$rolling.window_start",
                            "endDate": now,
                            "unit": "second",
                        }},
                        settings.cumulative_window_hours * 3600
                    ]
                }
            }
        }
    }}

    # Stage 1: Update all rolling fields including arrays
    stage_1_sets = {
        "rolling.z1_prev": now,
        "rolling.at3_prev": request.at3,
        "rolling.at3_prev2": "$rolling.at3_prev",

        "rolling.at3_recent": {
            "$slice": [
                {"$concatArrays": [
                    {"$ifNull": ["$rolling.at3_recent", []]},
                    [request.at3]
                ]},
                -settings.recent_amounts_limit
            ]
        },
        "rolling.tp_recent": {
            "$slice": [
                {"$concatArrays": [
                    {"$ifNull": ["$rolling.tp_recent", []]},
                    [request.tp]
                ]},
                -settings.recent_purposes_limit
            ]
        },

        "service_ever": {
            "$setUnion": [
                {"$ifNull": ["$service_ever", []]},
                [request.service]
            ]
        },

        "rolling.at3_sum": {
            "$cond": {
                "if": "$_wr",
                "then": request.at3,
                "else": {"$add": [{"$ifNull": ["$rolling.at3_sum", 0]}, request.at3]}
            }
        },

        "rolling.window_start": {
            "$cond": {
                "if": "$_wr",
                "then": now,
                "else": "$rolling.window_start"
            }
        },

        "rolling.bl_window_start": {
            "$cond": {
                "if": "$_wr",
                "then": "$rolling.bl",
                "else": "$rolling.bl_window_start"
            }
        },
    }

    if request.is_financial == 1 and request.status == "SUCCESS":
        stage_1_sets["rolling.bl"] = {
            "$add": [{"$ifNull": ["$rolling.bl", 0]}, -request.at3]
        }

    stage_1 = {"$set": stage_1_sets}

    # Stage 2: Compute at6 (population std dev) from the already-updated at3_recent
    stage_2 = {"$set": {
        "rolling.at6": {
            "$cond": {
                "if": {"$gte": [{"$size": {"$ifNull": ["$rolling.at3_recent", []]}}, 2]},
                "then": {
                    "$let": {
                        "vars": {
                            "arr": "$rolling.at3_recent",
                            "mean": {"$avg": "$rolling.at3_recent"},
                            "n": {"$size": "$rolling.at3_recent"}
                        },
                        "in": {
                            "$sqrt": {
                                "$divide": [
                                    {"$reduce": {
                                        "input": "$$arr",
                                        "initialValue": 0,
                                        "in": {
                                            "$add": [
                                                "$$value",
                                                {"$pow": [
                                                    {"$subtract": ["$$this", "$$mean"]},
                                                    2
                                                ]}
                                            ]
                                        }
                                    }},
                                    "$$n"
                                ]
                            }
                        }
                    }
                },
                "else": 0.0
            }
        },
        "_wr": "$$REMOVE",
    }}

    return [stage_0, stage_1, stage_2]
