"""
DB-based transaction lookup service.

Alternative to in-memory BlacklistCache + ServiceConfigCache.
Single $in query against the consolidated txn_lookups collection
resolves var_1, var_2, var_5, var_6, var_9, var_12, var_14, var_23.

Uses prefixed lookup_value pattern: "category::value" (e.g., "account::1234567890").
One index scan with multiple seek points -- no $or, no compound index.
"""

from typing import Dict, List, Optional, Tuple

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.read_preferences import ReadPreference


class LookupResult:
    """Results of the consolidated txn_lookups query, mapped to rule inputs."""

    def __init__(self):
        self.is_dest_blacklisted: bool = False          # var_1 (pot_bf)
        self.fraud_cascade_match: Optional[dict] = None  # var_2 (pot_bf24)
        self.is_merchant_suspicious: bool = False        # var_5 (pot_sm)
        self.is_dest_gambling: bool = False              # var_6 (pot_anj)
        self.loan_provider_match: Optional[str] = None   # var_9 (pot_pp)
        self.service_limit: Optional[float] = None       # var_12 (pot_sl)
        self.service_avg_bounds: Optional[Tuple[float, float]] = None  # var_14 (pot_va)
        self.is_dest_watchlisted: bool = False           # var_23 (pot_cb)


class LookupCacheAdapter:
    """Adapts LookupResult to mimic BlacklistCache interface for rule functions.

    Rule functions (var_1, 2, 5, 6, 23) access cache attributes like
    cache.dest_accounts, cache.fraud_cascade, etc. This adapter builds
    minimal sets/dicts so those attribute accesses work unchanged.
    """

    def __init__(self, lookup: LookupResult,
                 b2: str, c2: Optional[str], n2: Optional[str]):
        self.dest_accounts: set = set()
        if lookup.is_dest_blacklisted:
            self.dest_accounts.add(b2)
            if c2:
                self.dest_accounts.add(c2)

        self.fraud_cascade: dict = {}
        if lookup.fraud_cascade_match is not None:
            self.fraud_cascade[b2] = lookup.fraud_cascade_match

        self.suspicious_merchants: set = set()
        if lookup.is_merchant_suspicious and n2:
            self.suspicious_merchants.add(n2.lower())

        self.gambling_accounts: set = set()
        if lookup.is_dest_gambling:
            self.gambling_accounts.add(b2)
            if c2:
                self.gambling_accounts.add(c2)

        self.loan_providers: dict = {}
        if lookup.loan_provider_match is not None:
            self.loan_providers[b2] = lookup.loan_provider_match

        self.watchlist_accounts: set = set()
        if lookup.is_dest_watchlisted:
            self.watchlist_accounts.add(b2)
            if c2:
                self.watchlist_accounts.add(c2)


async def query_txn_lookups(
    db: AsyncDatabase,
    b2: str,
    c2: Optional[str],
    n2: Optional[str],
    service: int,
) -> LookupResult:
    """
    Single $in query against txn_lookups resolving 8 rules.

    Builds prefixed lookup values and queries a single indexed field.
    One index scan with multiple seek points. Expected latency: 1-3ms.
    """
    result = LookupResult()

    # Build prefixed lookup values
    lookup_values = [
        f"account::{b2}",
        f"service::{service}",
        f"provider::{b2}",
    ]
    if c2 and c2 != b2:
        lookup_values.append(f"account::{c2}")
        lookup_values.append(f"provider::{c2}")
    if n2:
        lookup_values.append(f"merchant::{n2.lower()}")

    # Single query, single index scan — reads distributed to secondaries
    collection = db.txn_lookups.with_options(read_preference=ReadPreference.SECONDARY_PREFERRED)
    cursor = collection.find({"lookup_value": {"$in": lookup_values}})
    async for doc in cursor:
        doc_type = doc["type"]

        if doc_type == "bf":
            result.is_dest_blacklisted = True
        elif doc_type == "bf24":
            result.fraud_cascade_match = doc.get("metadata")
        elif doc_type == "sm":
            result.is_merchant_suspicious = True
        elif doc_type == "anj":
            result.is_dest_gambling = True
        elif doc_type == "pp":
            result.loan_provider_match = doc.get("metadata", {}).get("q2")
        elif doc_type == "sl":
            result.service_limit = doc.get("metadata", {}).get("x")
        elif doc_type == "va":
            meta = doc.get("metadata", {})
            if "at1" in meta and "at2" in meta:
                result.service_avg_bounds = (meta["at1"], meta["at2"])
        elif doc_type == "cb":
            result.is_dest_watchlisted = True

    return result
