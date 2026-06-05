"""V2 scoring endpoint -- POST /score-transaction."""

import asyncio
import logging
import re

from fastapi import APIRouter, HTTPException

from app.db import get_db
from app.models.requests import ScoreTransactionRequest, ScoreTransactionResponse, ErrorResponse
from app.services.fraud import FraudScoringServiceV2
from app.services.locust_sampler import maybe_sample_transaction

logger = logging.getLogger(__name__)

router = APIRouter()

CUSTOMER_ID_PATTERN = re.compile(r"^CUST-[A-Fa-f0-9]{12}$")


@router.post(
    "/score-transaction",
    response_model=ScoreTransactionResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def score_transaction(request: ScoreTransactionRequest) -> ScoreTransactionResponse:
    """Score a V2 transaction for fraud risk. Target: <20ms, 3 DB ops."""
    if not CUSTOMER_ID_PATTERN.match(request.customer_id):
        raise HTTPException(status_code=400, detail={
            "error": "invalid_request",
            "message": "Invalid customer_id format. Expected: CUST-XXXXXXXXXXXX",
        })

    try:
        db = await get_db()
        service = FraudScoringServiceV2(db)
        response, timing = await service.score_transaction(request)

        # Sample 1-in-500 transactions for load test dashboard
        # scoring_ms = Phase 1 (reads) + Phase 2 (rules) = app_processing_ms
        # persist_ms = Phase 3 (writes) = parallel_writes_ms
        await maybe_sample_transaction(
            db,
            customer_id=request.customer_id,
            amount=request.at3,
            channel=request.channel or "Livin",
            risk_level=response.fraud_score.risk_level,
            latency_ms=timing.total_ms,
            scoring_ms=timing.app_processing_ms,
            persist_ms=timing.parallel_writes_ms,
        )

        return response

    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail={"error": "not_found", "message": error_msg})
        raise HTTPException(status_code=400, detail={"error": "invalid_request", "message": error_msg})

    except Exception as e:
        logger.exception(f"Error scoring transaction for {request.customer_id}: {e}")
        raise HTTPException(status_code=500, detail={
            "error": "internal_error", "message": "Failed to process transaction",
        })
