"""
V2 Customer Sampling Service for Load Testing.

Copied from V1, adapted for V2 customer document structure (no account_ids).
"""

import logging
import random
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

from bson import MinKey, MaxKey
from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger(__name__)

CUSTOMER_CACHE_TTL = 3600
SamplingMethod = Literal["chunk_based", "random"]

_customer_cache: Dict[str, Any] = {
    "customers": None, "loaded_at": None,
    "method": None, "size": None, "chunk_distribution": None,
}


async def get_chunk_boundaries(db: AsyncDatabase) -> List[Dict[str, Any]]:
    try:
        config_db = db.client.get_database("config")
        namespace = f"{db.name}.customers"
        coll_doc = await config_db.collections.find_one({"_id": namespace})

        if coll_doc and "uuid" in coll_doc:
            collection_uuid = coll_doc["uuid"]
            cursor = config_db.chunks.find({"uuid": collection_uuid}, {"min": 1, "max": 1, "shard": 1}).sort("min", 1)
            chunks = await cursor.to_list(length=1000)
        else:
            cursor = config_db.chunks.find({"ns": namespace}, {"min": 1, "max": 1, "shard": 1}).sort("min", 1)
            chunks = await cursor.to_list(length=1000)

        logger.info(f"Found {len(chunks)} chunks for {namespace}")
        return chunks
    except Exception as e:
        logger.warning(f"Failed to get chunk boundaries: {e}")
        return []


async def sample_from_chunk(db: AsyncDatabase, min_key: Any, max_key: Any, sample_size: int) -> List[Dict[str, str]]:
    try:
        query: Dict[str, Any] = {}

        def extract_key_value(key_obj):
            if key_obj is None or isinstance(key_obj, (MinKey, MaxKey)):
                return None
            if isinstance(key_obj, dict) and "customer_id" in key_obj:
                return key_obj["customer_id"]
            if isinstance(key_obj, str):
                return key_obj
            return None

        min_val = extract_key_value(min_key)
        if min_val is not None:
            query["customer_id"] = {"$gte": min_val}

        max_val = extract_key_value(max_key)
        if max_val is not None:
            if "customer_id" in query:
                query["customer_id"]["$lt"] = max_val
            else:
                query["customer_id"] = {"$lt": max_val}

        pipeline = []
        if query:
            pipeline.append({"$match": query})
        pipeline.extend([
            {"$sample": {"size": sample_size}},
            {"$project": {"_id": 0, "customer_id": 1}},
        ])

        cursor = await db.customers.aggregate(pipeline)
        docs = await cursor.to_list(length=sample_size)

        return [{"customer_id": doc["customer_id"]} for doc in docs]
    except Exception as e:
        logger.warning(f"Failed to sample from chunk: {e}")
        return []


async def get_customers_chunk_based(db: AsyncDatabase, size: int) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    chunks = await get_chunk_boundaries(db)
    if not chunks:
        customers = await get_customers_random(db, size)
        return customers, {"method": "random_fallback", "reason": "no_chunks"}

    num_chunks = len(chunks)
    base_per_chunk = size // num_chunks
    remainder = size % num_chunks

    all_customers: List[Dict[str, str]] = []
    chunk_info = []

    for i, chunk in enumerate(chunks):
        chunk_size = base_per_chunk + (1 if i < remainder else 0)
        if chunk_size == 0:
            continue

        min_key = chunk.get("min", {}).get("customer_id")
        max_key = chunk.get("max", {}).get("customer_id")
        shard = chunk.get("shard", "unknown")

        customers = await sample_from_chunk(db, min_key, max_key, chunk_size)
        all_customers.extend(customers)
        chunk_info.append({"shard": shard, "requested": chunk_size, "sampled": len(customers)})

    random.shuffle(all_customers)
    distribution = {"method": "chunk_based", "num_chunks": num_chunks, "chunks": chunk_info, "total_sampled": len(all_customers)}
    return all_customers, distribution


async def get_customers_random(db: AsyncDatabase, size: int) -> List[Dict[str, str]]:
    cursor = await db.customers.aggregate([
        {"$sample": {"size": size}},
        {"$project": {"_id": 0, "customer_id": 1}},
    ])
    docs = await cursor.to_list(length=size)
    customers = [{"customer_id": doc["customer_id"]} for doc in docs]
    logger.info(f"Random sampling: {len(customers)} customers")
    return customers


async def get_sampled_customers(
    db: AsyncDatabase, size: int = 10000,
    method: SamplingMethod = "chunk_based", force_refresh: bool = False,
) -> List[Dict[str, str]]:
    global _customer_cache

    if not force_refresh and _customer_cache["customers"] is not None:
        cache_age = (datetime.utcnow() - _customer_cache["loaded_at"]).total_seconds()
        if cache_age < CUSTOMER_CACHE_TTL and _customer_cache["size"] == size and _customer_cache["method"] == method:
            return _customer_cache["customers"]

    distribution = None
    if method == "chunk_based":
        customers, distribution = await get_customers_chunk_based(db, size)
        if len(customers) < size * 0.8:
            additional = await get_customers_random(db, size - len(customers))
            customers.extend(additional)
    else:
        customers = await get_customers_random(db, size)
        distribution = {"method": "random"}

    _customer_cache = {
        "customers": customers, "loaded_at": datetime.utcnow(),
        "method": method, "size": size, "chunk_distribution": distribution,
    }
    logger.info(f"Cached {len(customers)} customers (method: {method})")
    return customers


def get_customer_cache_stats() -> Dict[str, Any]:
    if _customer_cache["customers"] is None:
        return {"loaded": False, "count": 0, "method": None}

    age = (datetime.utcnow() - _customer_cache["loaded_at"]).total_seconds()
    return {
        "loaded": True, "count": _customer_cache["size"],
        "method": _customer_cache["method"],
        "age_seconds": round(age, 1),
        "ttl_remaining_seconds": round(max(0, CUSTOMER_CACHE_TTL - age), 1),
    }


def invalidate_customer_cache() -> None:
    global _customer_cache
    _customer_cache = {"customers": None, "loaded_at": None, "method": None, "size": None, "chunk_distribution": None}
    logger.info("Customer cache invalidated")
