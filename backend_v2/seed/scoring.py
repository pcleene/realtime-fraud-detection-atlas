"""
Lightweight synchronous scoring for seeding.

Loads blacklist/service caches synchronously (via PyMongo sync driver),
then evaluates all 31 rules using the actual check_var_* functions from
app.services.rules.*. This ensures seeded transactions have realistic
fraud scores derived from rolling state, not random values.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.models.customer import LoanIncoming
from app.models.transaction import RuleResult

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


class SeedBlacklistCache:
    """Synchronous blacklist cache for seeding.

    Mirrors the interface of app.cache.BlacklistCache so the existing
    check_var_* functions work unchanged.
    """

    def __init__(self):
        self.dest_accounts: set = set()           # pot_bf (var_1)
        self.fraud_cascade: Dict[str, dict] = {}  # pot_bf24 (var_2)
        self.suspicious_merchants: set = set()     # pot_sm (var_5)
        self.gambling_accounts: set = set()        # pot_anj (var_6)
        self.loan_providers: Dict[str, str] = {}   # pot_pp (var_9)
        self.watchlist_accounts: set = set()       # pot_cb (var_23)

    def load(self, db) -> Dict[str, int]:
        """Load all blacklist collections synchronously."""
        for doc in db.pot_bf.find({}, {"b23": 1}):
            self.dest_accounts.add(doc["b23"])

        for doc in db.pot_bf24.find({}):
            self.fraud_cascade[doc["b23"]] = doc

        for doc in db.pot_sm.find({}, {"n3": 1}):
            self.suspicious_merchants.add(doc["n3"].lower())

        for doc in db.pot_anj.find({}, {"b23": 1}):
            self.gambling_accounts.add(doc["b23"])

        for doc in db.pot_pp.find({}):
            self.loan_providers[doc["b23"]] = doc.get("q2", "")

        for doc in db.pot_cb.find({}, {"b23": 1}):
            self.watchlist_accounts.add(doc["b23"])

        # Pre-compute lists for O(1) random.choice during transaction generation.
        # Sets don't support indexing, and list() on 470K+ entries per transaction
        # would be O(n) × 100M calls = catastrophic.
        self.dest_accounts_list: list = list(self.dest_accounts)
        self.suspicious_merchants_list: list = list(self.suspicious_merchants)
        self.gambling_accounts_list: list = list(self.gambling_accounts)
        self.watchlist_accounts_list: list = list(self.watchlist_accounts)

        stats = {
            "pot_bf": len(self.dest_accounts),
            "pot_bf24": len(self.fraud_cascade),
            "pot_sm": len(self.suspicious_merchants),
            "pot_anj": len(self.gambling_accounts),
            "pot_pp": len(self.loan_providers),
            "pot_cb": len(self.watchlist_accounts),
        }
        logger.info(f"Seed blacklist cache loaded: {stats}")
        return stats


class SeedServiceConfig:
    """Synchronous service config cache for seeding.

    Mirrors the interface of app.cache.ServiceConfigCache.
    """

    def __init__(self):
        self.limits: Dict[int, float] = {}
        self.avg_bounds: Dict[int, Tuple[float, float]] = {}

    def load(self, db) -> Dict[str, int]:
        """Load pot_sl_va synchronously."""
        for doc in db.pot_sl_va.find({}):
            svc = doc.get("service")
            if svc is not None:
                if "x" in doc:
                    self.limits[svc] = doc["x"]
                if "at1" in doc and "at2" in doc:
                    self.avg_bounds[svc] = (doc["at1"], doc["at2"])

        stats = {"service_limits": len(self.limits), "avg_bounds": len(self.avg_bounds)}
        logger.info(f"Seed service config loaded: {stats}")
        return stats


class SeedCaches:
    """Combined blacklist + service config caches for seeding."""

    def __init__(self, db):
        self.blacklist = SeedBlacklistCache()
        self.service_config = SeedServiceConfig()
        self.blacklist.load(db)
        self.service_config.load(db)


def score_transaction_for_seed(
    txn: dict,
    rolling: dict,
    caches: SeedCaches,
    settings,
) -> dict:
    """Compute realistic fraud score during seeding using actual rule logic.

    Args:
        txn: Transaction fields (customer_id, at3, tp, b2, n2, service, z1, h1, etc.)
        rolling: In-memory rolling state dict for this customer
        caches: SeedCaches with loaded blacklist + service config
        settings: App settings with rule weights and thresholds

    Returns:
        Compact fraud_score dict: {final_score, risk_level, rule_scores, triggered_count}
    """
    s = settings
    bl_cache = caches.blacklist
    sc_cache = caches.service_config

    z1 = txn["z1"]
    at3 = txn["at3"]
    tp = txn["tp"]
    b2 = txn["b2"]
    n2 = txn["n2"]
    service = txn["service"]
    customer_id = txn["customer_id"]

    # Extract rolling state
    z1_prev = rolling.get("z1_prev")
    at3_prev = rolling.get("at3_prev")
    at3_recent = rolling.get("at3_recent", [])
    tp_recent = rolling.get("tp_recent", [])
    at3_sum = rolling.get("at3_sum", 0)
    at6 = rolling.get("at6", 0)
    bl = rolling.get("bl")
    z3 = rolling.get("z3")
    z4 = rolling.get("z4")
    w2_latest = rolling.get("w2_latest")
    pt_latest = rolling.get("pt_latest")
    service_ever = rolling.get("service_ever", [])
    b24_list = rolling.get("b24_list", [])
    b24_count = rolling.get("b24_count", 0)
    flags = rolling.get("flags", {})
    av1 = rolling.get("av1")
    av2 = rolling.get("av2")

    # Convert pot_i_recent dicts to LoanIncoming objects for var_9
    pot_i_raw = rolling.get("pot_i_recent", [])
    pot_i_recent = []
    for loan in pot_i_raw:
        if isinstance(loan, dict):
            pot_i_recent.append(LoanIncoming(**loan))
        else:
            pot_i_recent.append(loan)

    results: List[RuleResult] = []

    # --- Blacklist rules (var_1-7, 23, 25) ---
    results.append(check_var_1(b2, bl_cache, s.weight_var_1))
    results.append(check_var_2(customer_id, b2, z1, bl_cache, s.fraud_cascade_hours, s.weight_var_2))
    results.append(check_var_3(flags.get("var_3", False), s.weight_var_3))
    results.append(check_var_4(flags.get("var_4", False), s.weight_var_4))
    results.append(check_var_5(n2, bl_cache, s.weight_var_5))
    results.append(check_var_6(b2, bl_cache, s.weight_var_6))
    results.append(check_var_7(flags.get("var_7", False), s.weight_var_7))
    results.append(check_var_23(b2, bl_cache, s.weight_var_23))
    results.append(check_var_25(flags.get("var_25", False), s.weight_var_25))

    # --- Velocity rules (var_8, 10, 13, 24, 26) ---
    results.append(check_var_8(z1, z1_prev, s.min_txn_gap_seconds, s.weight_var_8))
    results.append(check_var_10(z1, z1_prev, s.min_txn_gap_days, s.weight_var_10))
    results.append(check_var_13(z1, z3, z4, s.weight_var_13))
    results.append(check_var_24(z1, w2_latest, s.post_card_change_hours, s.weight_var_24))
    results.append(check_var_26(z1, pt_latest, s.post_provisioning_hours, s.weight_var_26))

    # --- Amount rules (var_12, 14, 15, 16, 17, 18, 19, 20, 21, 28, 29) ---
    results.append(check_var_12(at3, service, sc_cache.limits, s.amount_to_limit_ratio, s.weight_var_12))
    results.append(check_var_14(at3, service, sc_cache.avg_bounds, s.weight_var_14))
    results.append(check_var_15(at3, bl, s.amount_to_balance_ratio, s.weight_var_15))
    results.append(check_var_16(at3, at3_recent, s.weight_var_16))
    results.append(check_var_17(at3, at3_prev, s.amount_spike_ratio, s.weight_var_17))
    results.append(check_var_18(at3, at3_sum, bl, s.amount_to_balance_ratio, s.weight_var_18))
    results.append(check_var_19(at3, at3_sum, bl, pt_latest, z1,
                                s.post_prov_cumulative_hours, s.amount_to_balance_ratio, s.weight_var_19))
    results.append(check_var_20(at3, at3_recent, s.exact_repeat_count, s.weight_var_20))
    results.append(check_var_21(at3, at3_prev, s.amount_drop_ratio, s.weight_var_21))
    results.append(check_var_28(at6, av1, s.weight_var_28))
    results.append(check_var_29(at3_sum, av2, s.weight_var_29))

    # --- Behavioral rules (var_9, 11, 22) ---
    results.append(check_var_9(at3, z1, pot_i_recent, s.loan_moneyout_hours, s.loan_outflow_ratio, s.weight_var_9))
    results.append(check_var_11(service, service_ever, s.weight_var_11))
    # For var_22 during seeding, skip overflow check (just use embedded list)
    results.append(check_var_22(b2, b24_list, b24_count, s.beneficiary_embed_limit, s.weight_var_22))

    # --- Pattern rules (var_30, 31) ---
    results.append(check_var_30(tp, tp_recent, s.weight_var_30))
    results.append(check_var_31(tp, at3, s.purpose_amount_ratio_threshold, s.weight_var_31))

    # Calculate final score (sparse — only triggered rules stored)
    rule_scores = {r.rule: r.score for r in results if r.score > 0}
    total = min(sum(rule_scores.values()), 100)
    triggered_count = sum(1 for r in results if r.triggered)

    if total >= s.risk_threshold_high:
        risk_level = "high"
    elif total >= s.risk_threshold_medium:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "final_score": total,
        "risk_level": risk_level,
        "rule_scores": rule_scores,
        "triggered_count": triggered_count,
    }
