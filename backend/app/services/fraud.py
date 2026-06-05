"""
Fraud Scoring Service - PyMongo Async API

This service orchestrates fraud scoring with native async I/O:
1. Parallel DB reads: Customer, Blacklist, and Holiday queries run concurrently
2. Parallel DB writes: Customer update and Transaction insert run concurrently
3. Detailed timing breakdown for observability

Uses PyMongo's AsyncMongoClient for true non-blocking I/O without thread pools.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from pymongo.asynchronous.database import AsyncDatabase

from app.config import get_settings
from app.models.customer import Customer, GeoPoint
from app.models.transaction import (
    FraudScore,
    RuleAnalysis,
    Transaction,
    TransactionCustomerRef,
    TransactionDevice,
    TransactionMerchant,
)
from app.models.requests import ScoreTransactionRequest
from app.services.rules import (
    check_velocity,
    check_impossible_travel,
    check_password_frequency,
    check_blacklist_proximity,
    check_holiday,
)
from app.utils.timing import compute_shard_key_month, ensure_utc, TimingBreakdown
from app.utils.scoring import calculate_final_score

logger = logging.getLogger(__name__)


# =============================================================================
# Async DB Operations (Native PyMongo Async)
# =============================================================================

async def fetch_customer_async(
    db: AsyncDatabase,
    customer_id: str
) -> Tuple[Optional[Dict], float]:
    """
    Fetch customer document using native async with projection.

    Only fetches fields needed for fraud scoring:
    - _id, customer_id, name, province: Used in Transaction.customer ref
    - features: Contains latest_time_transaction, latest_location, avg_gap_change_password

    Excludes: account_ids, created_at, updated_at (not used in scoring)
    """
    t0 = time.perf_counter()
    doc = await db.customers.find_one(
        {"customer_id": customer_id},
        projection={
            "_id": 1,
            "customer_id": 1,
            "name": 1,
            "province": 1,
            "features": 1,
        }
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return doc, elapsed_ms


async def update_customer_async(
    db: AsyncDatabase,
    customer_id: str,
    update_fields: Dict
) -> float:
    """Update customer document using native async."""
    t0 = time.perf_counter()
    await db.customers.update_one(
        {"customer_id": customer_id},
        {"$set": update_fields}
    )
    return (time.perf_counter() - t0) * 1000


async def insert_transaction_async(
    db: AsyncDatabase, 
    txn_doc: Dict
) -> Tuple[str, float]:
    """Insert transaction document using native async."""
    t0 = time.perf_counter()
    result = await db.transactions.insert_one(txn_doc)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return str(result.inserted_id), elapsed_ms


# =============================================================================
# Main Fraud Scoring Service
# =============================================================================

class FraudScoringService:
    """
    Fraud scoring orchestrator using PyMongo Async API.
    
    Execution flow:
    1. PARALLEL: Fetch customer + Query blacklist + Query holiday (native async)
    2. SEQUENTIAL: Evaluate all rules (CPU-bound, fast)
    3. PARALLEL: Update customer + Insert transaction (native async)
    """

    def __init__(self, db: AsyncDatabase):
        self.db = db
        self.settings = get_settings()

    async def score_transaction(
        self, request: ScoreTransactionRequest
    ) -> Tuple[Transaction, TimingBreakdown]:
        """
        Score a transaction for fraud risk with native async parallel execution.

        Args:
            request: Transaction scoring request

        Returns:
            Tuple of (Transaction with fraud score, TimingBreakdown)
        """
        timing = TimingBreakdown()
        start_time = time.perf_counter()

        # =====================================================================
        # PHASE 1: Parallel - Customer fetch + DB-based rules
        # =====================================================================
        parallel_read_start = time.perf_counter()
        
        # Run customer fetch and DB-based rules in parallel
        (customer_doc, customer_time), (blacklist_result, blacklist_time), (holiday_result, holiday_time) = (
            await asyncio.gather(
                fetch_customer_async(self.db, request.customer_id),
                check_blacklist_proximity(self.db, request.lon, request.lat),
                check_holiday(self.db, request.timestamp),
            )
        )
        
        timing.parallel_reads_ms = (time.perf_counter() - parallel_read_start) * 1000
        timing.db_customer_fetch_ms = customer_time
        timing.db_blacklist_query_ms = blacklist_time
        timing.db_holiday_query_ms = holiday_time
        # Note: rule_blacklist_ms and rule_holiday_ms are ~0 since the DB time 
        # dominates and is already captured above. The CPU eval is negligible.

        # Validate customer exists
        if customer_doc is None:
            raise ValueError(f"Customer {request.customer_id} not found")

        customer = Customer.from_mongo(customer_doc)
        features = customer.features

        # =====================================================================
        # PHASE 2: CPU-only rules (need customer data, sequential but fast)
        # =====================================================================
        
        # Calculate time delta for velocity/travel checks
        request_ts = ensure_utc(request.timestamp)
        delta_seconds: Optional[float] = None
        if features.latest_time_transaction:
            latest_ts = ensure_utc(features.latest_time_transaction)
            delta_seconds = (request_ts - latest_ts).total_seconds()

        # Velocity check
        t0 = time.perf_counter()
        velocity_result = check_velocity(
            features.latest_time_transaction,
            request.timestamp,
        )
        timing.rule_velocity_ms = (time.perf_counter() - t0) * 1000

        # Impossible travel check
        t0 = time.perf_counter()
        travel_result = check_impossible_travel(
            features.latest_location,
            request.lon,
            request.lat,
            delta_seconds,
        )
        timing.rule_travel_ms = (time.perf_counter() - t0) * 1000

        # Password frequency check
        t0 = time.perf_counter()
        password_result = check_password_frequency(features.avg_gap_change_password)
        timing.rule_password_ms = (time.perf_counter() - t0) * 1000

        # Collect all rule results
        analysis: List[RuleAnalysis] = [
            velocity_result,
            travel_result,
            blacklist_result,
            password_result,
            holiday_result,
        ]

        # Calculate final score
        final_score, risk_level = calculate_final_score(analysis)

        # Create fraud score
        fraud_score = FraudScore(
            final_score=final_score,
            risk_level=risk_level,
            analysis=analysis,
        )

        # Build transaction document
        location = None
        if request.lon is not None and request.lat is not None:
            location = GeoPoint.from_coords(request.lon, request.lat)

        merchant_category = self._get_merchant_category(request.mcc)

        transaction = Transaction(
            customer_id=request.customer_id,
            shard_key_month=compute_shard_key_month(request.timestamp),
            customer=TransactionCustomerRef(
                _id=customer.id,
                customer_id=customer.customer_id,
                name=customer.name,
            ),
            account_id=request.account_id,
            type="debit",
            channel=request.channel,
            amount=request.amount,
            currency="IDR",
            status="authorized",
            timestamp=request.timestamp,
            location=location,
            city=self._get_city_from_province(customer.province),
            province=customer.province,
            merchant=TransactionMerchant(
                id=request.merchant_id,
                name=request.merchant_name,
                mcc=request.mcc,
                category=merchant_category,
            ),
            device=TransactionDevice(
                device_id=request.device_id,
                device_type=request.device_type,
                ip=request.ip,
            ),
            fraud_score=fraud_score,
        )

        # Capture scoring time BEFORE DB writes
        timing.scoring_ms = (time.perf_counter() - start_time) * 1000

        # =====================================================================
        # PHASE 3: Parallel DB Writes (Best Performance)
        # Both writes run concurrently - faster but not atomic.
        # =====================================================================
        parallel_write_start = time.perf_counter()
        
        # Prepare update fields
        update_fields = {
            "features.latest_time_transaction": request.timestamp,
            "updated_at": datetime.utcnow(),
        }
        if location:
            update_fields["features.latest_location"] = location.model_dump()

        # Prepare transaction document
        txn_doc = transaction.to_mongo()

        # Run both writes in parallel using native asyncio
        update_time, (txn_id, insert_time) = await asyncio.gather(
            update_customer_async(self.db, request.customer_id, update_fields),
            insert_transaction_async(self.db, txn_doc),
        )
        
        timing.parallel_writes_ms = (time.perf_counter() - parallel_write_start) * 1000
        timing.db_customer_update_ms = update_time
        timing.db_transaction_insert_ms = insert_time
        transaction.id = txn_id

        # =====================================================================
        # ALTERNATIVE: ACID-Compliant Atomic Writes (MongoDB Transaction)
        # Uncomment below and comment out parallel writes above if you need
        # atomicity guarantees (both succeed or both fail).
        # Trade-off: slower due to transaction overhead.
        # =====================================================================
        # async with self.db.client.start_session() as session:
        #     await session.start_transaction()  # Coroutine, not context manager
        #     try:
        #         t0 = time.perf_counter()
        #         await self.db.customers.update_one(
        #             {"customer_id": request.customer_id},
        #             {"$set": update_fields},
        #             session=session
        #         )
        #         update_time = (time.perf_counter() - t0) * 1000
        #         
        #         t0 = time.perf_counter()
        #         result = await self.db.transactions.insert_one(txn_doc, session=session)
        #         insert_time = (time.perf_counter() - t0) * 1000
        #         txn_id = str(result.inserted_id)
        #         
        #         await session.commit_transaction()
        #     except Exception as e:
        #         await session.abort_transaction()
        #         logger.error(f"Transaction failed, rolling back: {e}")
        #         raise
        # 
        # timing.parallel_writes_ms = (time.perf_counter() - parallel_write_start) * 1000
        # timing.db_customer_update_ms = update_time
        # timing.db_transaction_insert_ms = insert_time
        # transaction.id = txn_id

        # Calculate total time and aggregates
        timing.total_ms = (time.perf_counter() - start_time) * 1000
        timing.calculate_aggregates()

        # Log timing breakdown
        logger.info(
            f"Timing (PyMongo Async): "
            f"Reads={timing.parallel_reads_ms:.1f}ms, "
            f"Writes={timing.parallel_writes_ms:.1f}ms, "
            f"Rules={timing.total_rules_ms:.1f}ms, "
            f"Total={timing.total_ms:.1f}ms"
        )

        return transaction, timing

    def _get_merchant_category(self, mcc: str) -> str:
        """Map MCC code to category."""
        mcc_categories = {
            "5311": "marketplace",
            "5812": "food_delivery",
            "4121": "ride_hailing",
            "5411": "retail",
            "4814": "telco",
            "4900": "utilities",
        }
        return mcc_categories.get(mcc, "retail")

    def _get_city_from_province(self, province: str) -> str:
        """Get representative city for province."""
        province_cities = {
            "DKI Jakarta": "Jakarta",
            "Jawa Barat": "Bandung",
            "Jawa Timur": "Surabaya",
            "Jawa Tengah": "Semarang",
            "Sumatera Utara": "Medan",
            "Banten": "Tangerang",
            "Sulawesi Selatan": "Makassar",
            "Bali": "Denpasar",
            "Kalimantan Timur": "Balikpapan",
            "Sumatera Selatan": "Palembang",
            "Riau": "Pekanbaru",
            "Lampung": "Bandar Lampung",
            "Nusa Tenggara Timur": "Kupang",
            "Papua": "Jayapura",
        }
        return province_cities.get(province, "Unknown")
