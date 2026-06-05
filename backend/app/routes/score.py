import asyncio
import logging
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.db import get_db
from app.models.requests import (
    ScoreTransactionRequest,
    ScoreTransactionResponse,
    RuleAnalysisResponse,
    TimingBreakdownResponse,
    ErrorResponse,
)
from app.services.fraud import FraudScoringService
from app.services.locust_sampler import maybe_sample_transaction

logger = logging.getLogger(__name__)

router = APIRouter()

# Regex pattern for customer_id validation
CUSTOMER_ID_PATTERN = re.compile(r"^CUST-[A-F0-9]{12}$")


@router.post(
    "/score-transaction",
    response_model=ScoreTransactionResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        404: {"model": ErrorResponse, "description": "Customer not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def score_transaction(request: ScoreTransactionRequest) -> ScoreTransactionResponse:
    """
    Score a transaction for fraud risk.

    This endpoint:
    1. Fetches customer features (single read)
    2. Checks blacklist proximity (geospatial query)
    3. Checks holiday calendar (date range query)
    4. Updates customer features atomically
    5. Persists scored transaction with full analysis

    Target: <50ms end-to-end
    """
    logger.debug(
        f"[SCORE] Request: customer_id={request.customer_id}, "
        f"amount={request.amount}, channel={request.channel}"
    )
    
    # Validate customer_id format
    if not CUSTOMER_ID_PATTERN.match(request.customer_id):
        logger.warning(f"[SCORE] Invalid customer_id format: {request.customer_id}")
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_request",
                "message": "Invalid customer_id format. Expected format: CUST-XXXXXXXXXXXX (12 hex chars)",
            },
        )

    try:
        db = await get_db()
        service = FraudScoringService(db)

        transaction, timing = await service.score_transaction(request)
        
        logger.debug(
            f"[SCORE] Result: customer_id={request.customer_id}, "
            f"risk_level={transaction.fraud_score.risk_level}, "
            f"score={transaction.fraud_score.final_score}, "
            f"timing: total={timing.total_ms:.1f}ms (reads={timing.parallel_reads_ms:.1f}ms, "
            f"rules={timing.total_rules_ms:.1f}ms, writes={timing.parallel_writes_ms:.1f}ms)"
        )

        # Build response
        analysis = [
            RuleAnalysisResponse(
                rule=rule.rule,
                score=rule.score,
                triggered=rule.triggered,
                details=rule.details,
            )
            for rule in transaction.fraud_score.analysis
        ]

        # Build timing breakdown response
        timing_response = TimingBreakdownResponse(**timing.to_dict())

        # Sample transaction for Locust load tests (non-blocking)
        # This checks if there's an active Locust test and samples at ~1% rate
        asyncio.create_task(
            maybe_sample_transaction(
                db=db,
                customer_id=request.customer_id,
                amount=request.amount,
                channel=request.channel,
                risk_level=transaction.fraud_score.risk_level,
                latency_ms=timing.total_ms,
                scoring_ms=timing.scoring_ms,
                persist_ms=timing.persistence_ms,
            )
        )

        return ScoreTransactionResponse(
            transaction_id=transaction.id,
            risk_score=transaction.fraud_score.final_score,
            risk_level=transaction.fraud_score.risk_level,
            analysis=analysis,
            scoring_time_ms=round(timing.scoring_ms, 2),
            total_time_ms=round(timing.total_ms, 2),
            timing=timing_response,
            recorded_at=datetime.utcnow(),
        )

    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            logger.warning(f"[SCORE] Customer not found: {request.customer_id}")
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": error_msg,
                },
            )
        logger.warning(f"[SCORE] Invalid request for {request.customer_id}: {error_msg}")
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_request",
                "message": error_msg,
            },
        )

    except Exception as e:
        logger.exception(f"[SCORE] Error processing transaction for {request.customer_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": "Failed to process transaction",
            },
        )
