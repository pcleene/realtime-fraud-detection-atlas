"""
V2 Fraud Scoring Service — Main orchestrator.

3-phase pattern:
  Phase 1: Read customer (find_one or aggregate — see reads.py)
  Phase 2: Evaluate all 31 rules (CPU only, no I/O)
  Phase 3: Parallel writes (update_one + insert_one — see writes.py)

Optional 4th DB op for beneficiary overflow (b24_count > 500, <1% of customers).
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import List, Tuple

from pymongo.asynchronous.database import AsyncDatabase

from app.config import get_settings
from app.cache import get_blacklist_cache, get_service_config_cache
from app.runtime_config import get_modes
from app.services.lookup_service import LookupCacheAdapter, query_txn_lookups
from app.models.customer import CustomerV2
from app.models.transaction import (
    FraudScore, RuleAnalysis, RuleResult,
    RULE_CATEGORIES, RULE_NAMES,
)
from app.models.requests import ScoreTransactionRequest, ScoreTransactionResponse
from app.utils.timing import TimingBreakdown, Timer, compute_shard_key_month
from app.utils.scoring import calculate_final_score

from app.services.fraud.reads import find_customer, aggregate_customer_read
from app.services.fraud.writes import (
    build_customer_update, update_customer, insert_transaction,
)

from app.services.rules.blacklist import (
    check_var_1, check_var_2, check_var_3, check_var_4,
    check_var_5, check_var_6, check_var_7, check_var_23, check_var_25,
)
from app.services.rules.velocity import (
    check_var_8, check_var_10, check_var_13, check_var_24, check_var_26,
)
from app.services.rules.amount import (
    check_var_12, check_var_14, check_var_15, check_var_16, check_var_17,
    check_var_18, check_var_19, check_var_20, check_var_21,
    check_var_28, check_var_29,
)
from app.services.rules.behavioral import check_var_9, check_var_11, check_var_22
from app.services.rules.pattern import check_var_30, check_var_31

logger = logging.getLogger(__name__)


class FraudScoringServiceV2:
    """V2 scoring service — 31 rules, 3 DB ops, <20ms target."""

    def __init__(self, db: AsyncDatabase):
        self.db = db
        self.settings = get_settings()
        self.blacklist_cache = get_blacklist_cache()
        self.service_config = get_service_config_cache()

    async def score_transaction(
        self, request: ScoreTransactionRequest
    ) -> Tuple[ScoreTransactionResponse, TimingBreakdown]:
        timing = TimingBreakdown()
        total_start = time.perf_counter()

        # =====================================================================
        # PHASE 1: Read customer (single find_one or aggregate with projection)
        # =====================================================================
        s = self.settings
        modes = await get_modes(self.db)
        update_mode = modes["update_mode"]
        lookup_mode = modes["lookup_mode"]

        if update_mode == "aggregation":
            with Timer("customer_fetch") as t:
                customer_doc = await aggregate_customer_read(
                    self.db,
                    request.customer_id,
                    request.at3,
                    request.z1,
                    s.recent_amounts_limit,
                    s.cumulative_window_hours,
                )
            timing.db_customer_fetch_ms = t.elapsed_ms

            if customer_doc is None:
                raise ValueError(f"Customer {request.customer_id} not found")

            computed_at6 = customer_doc.pop("_computed_at6", 0.0)
            computed_window_reset = customer_doc.pop("_window_reset", True)
            customer = CustomerV2.from_mongo(customer_doc)
        else:
            with Timer("customer_fetch") as t:
                customer_doc = await find_customer(self.db, request.customer_id)
            timing.db_customer_fetch_ms = t.elapsed_ms

            if customer_doc is None:
                raise ValueError(f"Customer {request.customer_id} not found")

            customer = CustomerV2.from_mongo(customer_doc)
            computed_at6 = None
            computed_window_reset = None
        rolling = customer.rolling

        # =====================================================================
        # LOOKUP: Resolve transaction-level blacklists + service config
        # =====================================================================
        if lookup_mode == "db":
            with Timer("txn_lookups") as t_lookup:
                lookup = await query_txn_lookups(
                    self.db, request.b2, request.c2, request.n2, request.service
                )
            timing.db_txn_lookups_ms = t_lookup.elapsed_ms
            bl_cache = LookupCacheAdapter(lookup, request.b2, request.c2, request.n2)
            svc_limits = {request.service: lookup.service_limit} if lookup.service_limit is not None else {}
            svc_bounds = {request.service: lookup.service_avg_bounds} if lookup.service_avg_bounds is not None else {}
        else:
            bl_cache = self.blacklist_cache
            svc_limits = self.service_config.limits
            svc_bounds = self.service_config.avg_bounds

        # =====================================================================
        # PHASE 2: Evaluate all 31 rules (CPU only, no I/O)
        # =====================================================================
        rules_start = time.perf_counter()
        results: List[RuleResult] = []

        # Blacklist rules (var_1-7, 23, 25)
        results.append(check_var_1(request.b2, bl_cache, s.weight_var_1))
        results.append(check_var_2(request.customer_id, request.b2, request.z1,
                                   bl_cache, s.fraud_cascade_hours, s.weight_var_2))
        results.append(check_var_3(customer.flags.var_3, s.weight_var_3))
        results.append(check_var_4(customer.flags.var_4, s.weight_var_4))
        results.append(check_var_5(request.n2, bl_cache, s.weight_var_5))
        results.append(check_var_6(request.b2, bl_cache, s.weight_var_6))
        results.append(check_var_7(customer.flags.var_7, s.weight_var_7))

        # Velocity rules (var_8, 10, 13, 24, 26)
        results.append(check_var_8(request.z1, rolling.z1_prev, s.min_txn_gap_seconds, s.weight_var_8))
        results.append(check_var_10(request.z1, rolling.z1_prev, s.min_txn_gap_days, s.weight_var_10))
        results.append(check_var_13(request.z1, rolling.z3, rolling.z4, s.weight_var_13))
        results.append(check_var_24(request.z1, rolling.w2_latest, s.post_card_change_hours, s.weight_var_24))
        results.append(check_var_26(request.z1, rolling.pt_latest, s.post_provisioning_hours, s.weight_var_26))

        # Amount rules (var_12, 14, 15, 16, 17, 18, 19, 20, 21, 28, 29)
        results.append(check_var_12(request.at3, request.service, svc_limits,
                                    s.amount_to_limit_ratio, s.weight_var_12))
        results.append(check_var_14(request.at3, request.service, svc_bounds, s.weight_var_14))
        results.append(check_var_15(request.at3, rolling.bl, s.amount_to_balance_ratio, s.weight_var_15))
        results.append(check_var_16(request.at3, rolling.at3_recent, s.weight_var_16))
        results.append(check_var_17(request.at3, rolling.at3_prev, s.amount_spike_ratio, s.weight_var_17))
        results.append(check_var_18(request.at3, rolling.at3_sum, rolling.bl,
                                    s.amount_to_balance_ratio, s.weight_var_18))
        results.append(check_var_19(request.at3, rolling.at3_sum, rolling.bl, rolling.pt_latest,
                                    request.z1, s.post_prov_cumulative_hours,
                                    s.amount_to_balance_ratio, s.weight_var_19))
        results.append(check_var_20(request.at3, rolling.at3_recent, s.exact_repeat_count, s.weight_var_20))
        results.append(check_var_21(request.at3, rolling.at3_prev, s.amount_drop_ratio, s.weight_var_21))
        results.append(check_var_28(rolling.at6, customer.av1, s.weight_var_28))
        results.append(check_var_29(rolling.at3_sum, customer.av2, s.weight_var_29))

        # Behavioral rules (var_9, 11, 22)
        results.append(check_var_9(request.at3, request.z1, rolling.pot_i_recent,
                                   s.loan_moneyout_hours, s.loan_outflow_ratio, s.weight_var_9))
        results.append(check_var_11(request.service, customer.service_ever, s.weight_var_11))

        var_22_result = check_var_22(request.b2, customer.b24_list, customer.b24_count,
                                     s.beneficiary_embed_limit, s.weight_var_22)

        if var_22_result.needs_overflow_check:
            with Timer("overflow_check") as t_overflow:
                overflow_match = await self.db.pot_nb_overflow.find_one(
                    {"customer_id": request.customer_id, "b2": request.b2}
                )
            timing.db_overflow_check_ms = t_overflow.elapsed_ms
            if overflow_match is None:
                var_22_result = RuleResult(
                    rule="var_22", triggered=True, weight=s.weight_var_22,
                    score=s.weight_var_22,
                    details={"b2": request.b2, "known": False, "checked_overflow": True},
                )
            else:
                var_22_result = RuleResult(
                    rule="var_22", triggered=False, weight=s.weight_var_22, score=0,
                    details={"b2": request.b2, "known": True, "found_in_overflow": True},
                )
        results.append(var_22_result)

        # Watchlist (var_23)
        results.append(check_var_23(request.b2, bl_cache, s.weight_var_23))

        # Device (var_25)
        results.append(check_var_25(customer.flags.var_25, s.weight_var_25))

        # Pattern rules (var_30, 31)
        results.append(check_var_30(request.tp, rolling.tp_recent, s.weight_var_30))
        results.append(check_var_31(request.tp, request.at3, s.purpose_amount_ratio_threshold, s.weight_var_31))

        timing.rules_eval_ms = (time.perf_counter() - rules_start) * 1000

        # Calculate final score
        final_score, risk_level = calculate_final_score(results)

        rule_scores = {r.rule: r.score for r in results if r.score > 0}
        triggered_count = sum(1 for r in results if r.triggered)

        fraud_score = FraudScore(
            final_score=final_score,
            risk_level=risk_level,
            rule_scores=rule_scores,
            triggered_count=triggered_count,
        )

        analysis = [
            RuleAnalysis(
                rule=r.rule,
                name=RULE_NAMES.get(r.rule, r.rule),
                category=RULE_CATEGORIES.get(r.rule, "unknown"),
                triggered=r.triggered,
                score=r.score,
                details=r.details,
            )
            for r in results
        ]

        timing.app_processing_ms = (time.perf_counter() - total_start) * 1000

        # =====================================================================
        # PHASE 3: Parallel writes (update customer + insert transaction)
        # =====================================================================
        update_doc = build_customer_update(request, rolling, s,
                                           update_mode=update_mode,
                                           computed_at6=computed_at6,
                                           computed_window_reset=computed_window_reset)
        shard_key_month = compute_shard_key_month(request.z1)

        location = None
        if request.lat is not None and request.lon is not None:
            location = {
                "type": "Point",
                "coordinates": [request.lon, request.lat],
            }

        txn_doc = {
            "customer_id": request.customer_id,
            "shard_key_month": shard_key_month,
            "z1": request.z1,
            "at3": request.at3,
            "at7": request.at7,
            "tp": request.tp,
            "b1": request.b1,
            "service": request.service,
            "service_name": request.service_name,
            "is_financial": request.is_financial,
            "status": request.status,
            "pot_dataset_dest": {
                "b2": request.b2,
                "c2": request.c2,
                "d2": request.d2,
                "n2": request.n2,
            },
            "pot_master_id_dp": {
                "h1": request.h1,
                "channel": request.channel,
            },
            "location": location,
            "fraud_score": fraud_score.model_dump(),
        }

        insert_mode = modes.get("insert_mode", "sync")

        if insert_mode == "sync":
            with Timer("parallel_writes") as t_writes:
                update_result, insert_result = await asyncio.gather(
                    update_customer(self.db, request.customer_id, update_doc),
                    insert_transaction(self.db, txn_doc),
                )
            timing.parallel_writes_ms = t_writes.elapsed_ms
            timing.db_customer_update_ms = update_result
            timing.db_transaction_insert_ms = insert_result[1]
            txn_id = insert_result[0]
        else:
            with Timer("parallel_writes") as t_writes:
                update_result = await update_customer(self.db, request.customer_id, update_doc)
            timing.parallel_writes_ms = t_writes.elapsed_ms
            timing.db_customer_update_ms = update_result
            timing.db_transaction_insert_ms = 0.0
            txn_id = "score-only"

        timing.total_ms = (time.perf_counter() - total_start) * 1000
        timing.calculate_aggregates()

        response = ScoreTransactionResponse(
            transaction_id=txn_id,
            customer_id=request.customer_id,
            fraud_score=fraud_score,
            analysis=analysis,
            app_processing_ms=timing.app_processing_ms,
            total_time_ms=timing.total_ms,
            timing=timing.to_dict(),
            recorded_at=datetime.utcnow(),
        )
        return response, timing
