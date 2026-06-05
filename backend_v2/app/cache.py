"""
V2 In-Memory Cache -- Transaction-level blacklists + service config.

Loaded at startup, refreshed on TTL. Each Gunicorn worker maintains its own copy.
Cache sizes:
- pot_bf (dest accounts): ~470K entries -> ~30MB
- pot_bf24 (fraud cascade): ~49K entries -> ~5MB
- pot_sm (suspicious merchants): ~132K entries -> ~10MB
- pot_anj (gambling accounts): ~470K entries -> ~30MB
- pot_pp (loan providers): ~1.7K entries -> <1MB
- pot_cb (watchlist): ~1M entries -> ~60MB
- pot_sl + pot_va (service config): ~40 entries -> <1KB
Total: ~135MB per worker
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger(__name__)

CACHE_TTL = 3600  # 1 hour


class BlacklistCache:
    """Transaction-level blacklists loaded into memory from separate collections."""

    def __init__(self):
        self.dest_accounts: Set[str] = set()            # pot_bf (var_1)
        self.fraud_cascade: Dict[str, dict] = {}        # pot_bf24 (var_2) -- keyed by account
        self.suspicious_merchants: Set[str] = set()      # pot_sm (var_5)
        self.gambling_accounts: Set[str] = set()         # pot_anj (var_6)
        self.loan_providers: Dict[str, str] = {}         # pot_pp (var_9) -- account -> provider name
        self.watchlist_accounts: Set[str] = set()        # pot_cb (var_23)
        self._loaded_at: Optional[datetime] = None

    async def load(self, db: AsyncDatabase) -> Dict[str, int]:
        """Load all transaction-level blacklists from separate MongoDB collections."""
        # Build new sets (atomic swap pattern)
        new_dest = set()
        new_cascade = {}
        new_merchants = set()
        new_gambling = set()
        new_providers = {}
        new_watchlist = set()

        # Load from separate collections (per user spec)
        cursor = db.pot_bf.find({}, {"b23": 1})
        async for doc in cursor:
            new_dest.add(doc["b23"])

        cursor = db.pot_bf24.find({})
        async for doc in cursor:
            new_cascade[doc["b23"]] = doc

        cursor = db.pot_sm.find({}, {"n3": 1})
        async for doc in cursor:
            new_merchants.add(doc["n3"].lower())

        cursor = db.pot_anj.find({}, {"b23": 1})
        async for doc in cursor:
            new_gambling.add(doc["b23"])

        cursor = db.pot_pp.find({})
        async for doc in cursor:
            new_providers[doc["b23"]] = doc.get("q2", "")

        cursor = db.pot_cb.find({}, {"b23": 1})
        async for doc in cursor:
            new_watchlist.add(doc["b23"])

        # Atomic swap
        self.dest_accounts = new_dest
        self.fraud_cascade = new_cascade
        self.suspicious_merchants = new_merchants
        self.gambling_accounts = new_gambling
        self.loan_providers = new_providers
        self.watchlist_accounts = new_watchlist
        self._loaded_at = datetime.utcnow()

        stats = {
            "pot_bf": len(self.dest_accounts),
            "pot_bf24": len(self.fraud_cascade),
            "pot_sm": len(self.suspicious_merchants),
            "pot_anj": len(self.gambling_accounts),
            "pot_pp": len(self.loan_providers),
            "pot_cb": len(self.watchlist_accounts),
        }
        logger.info(f"Blacklist cache loaded: {stats}")
        return stats

    def get_stats(self) -> Dict[str, Any]:
        age = None
        if self._loaded_at:
            age = (datetime.utcnow() - self._loaded_at).total_seconds()
        return {
            "loaded": self._loaded_at is not None,
            "pot_bf": len(self.dest_accounts),
            "pot_bf24": len(self.fraud_cascade),
            "pot_sm": len(self.suspicious_merchants),
            "pot_anj": len(self.gambling_accounts),
            "pot_pp": len(self.loan_providers),
            "pot_cb": len(self.watchlist_accounts),
            "total_entries": (
                len(self.dest_accounts) + len(self.fraud_cascade)
                + len(self.suspicious_merchants) + len(self.gambling_accounts)
                + len(self.loan_providers) + len(self.watchlist_accounts)
            ),
            "age_seconds": round(age, 1) if age else None,
        }


class ServiceConfigCache:
    """Service limits and amount thresholds loaded into memory."""

    def __init__(self):
        self.limits: Dict[int, float] = {}                     # service_code -> max amount (x)
        self.avg_bounds: Dict[int, Tuple[float, float]] = {}   # service_code -> (at1_lower, at2_upper)
        self._loaded_at: Optional[datetime] = None

    async def load(self, db: AsyncDatabase) -> Dict[str, int]:
        """Load pot_sl + pot_va merged config from pot_sl_va collection."""
        new_limits = {}
        new_bounds = {}

        cursor = db.pot_sl_va.find({})
        async for doc in cursor:
            svc = doc.get("service")
            if svc is not None:
                if "x" in doc:
                    new_limits[svc] = doc["x"]
                if "at1" in doc and "at2" in doc:
                    new_bounds[svc] = (doc["at1"], doc["at2"])

        self.limits = new_limits
        self.avg_bounds = new_bounds
        self._loaded_at = datetime.utcnow()

        stats = {"service_limits": len(self.limits), "avg_bounds": len(self.avg_bounds)}
        logger.info(f"Service config cache loaded: {stats}")
        return stats

    def get_stats(self) -> Dict[str, Any]:
        return {
            "loaded": self._loaded_at is not None,
            "service_limits": len(self.limits),
            "avg_bounds": len(self.avg_bounds),
        }


# Module-level cache instances
_blacklist_cache: Optional[BlacklistCache] = None
_service_config_cache: Optional[ServiceConfigCache] = None


async def warmup_caches(db: AsyncDatabase) -> Dict[str, Any]:
    """Pre-warm all caches at startup. Logs warnings for empty collections."""
    global _blacklist_cache, _service_config_cache

    _blacklist_cache = BlacklistCache()
    _service_config_cache = ServiceConfigCache()

    bl_stats = await _blacklist_cache.load(db)
    sc_stats = await _service_config_cache.load(db)

    total = sum(bl_stats.values())
    if total == 0:
        logger.warning(
            "ALL BLACKLIST COLLECTIONS ARE EMPTY. This is expected for a fresh database "
            "before seeding, but in production means NO blacklist rules will trigger. "
            "Run 'make seed-v2' to populate blacklist data."
        )
    else:
        for collection, count in bl_stats.items():
            if count == 0:
                logger.warning(f"Blacklist collection {collection} is empty -- related rules won't trigger")

    if sc_stats["service_limits"] == 0:
        logger.warning(
            "SERVICE CONFIG (pot_sl_va) IS EMPTY -- var_12 and var_14 will not trigger. "
            "Run 'make seed-v2' to populate service config."
        )

    return {"blacklists": bl_stats, "service_config": sc_stats}


def get_blacklist_cache() -> BlacklistCache:
    if _blacklist_cache is None or _blacklist_cache._loaded_at is None:
        logger.critical(
            "BLACKLIST CACHE NOT LOADED -- all blacklist rules (var_1, var_2, var_5, var_6, var_23) "
            "will silently pass. Scoring is UNRELIABLE. Check startup logs for cache loading errors."
        )
        raise RuntimeError(
            "Blacklist cache not loaded. Cannot score transactions without blacklist data. "
            "Ensure warmup_caches() completes successfully at startup."
        )
    return _blacklist_cache


def get_service_config_cache() -> ServiceConfigCache:
    if _service_config_cache is None or _service_config_cache._loaded_at is None:
        logger.critical(
            "SERVICE CONFIG CACHE NOT LOADED -- amount rules (var_12, var_14) "
            "will have no service limits. Scoring is UNRELIABLE."
        )
        raise RuntimeError(
            "Service config cache not loaded. Cannot score transactions without service config. "
            "Ensure warmup_caches() completes successfully at startup."
        )
    return _service_config_cache


def get_cache_stats() -> Dict[str, Any]:
    bl = _blacklist_cache.get_stats() if _blacklist_cache else {"loaded": False}
    sc = _service_config_cache.get_stats() if _service_config_cache else {"loaded": False}
    return {"blacklists": bl, "service_config": sc}
