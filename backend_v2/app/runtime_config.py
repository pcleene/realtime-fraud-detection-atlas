"""
Runtime configuration stored in MongoDB — shared across all workers.

Modes (UPDATE_MODE, LOOKUP_MODE) are stored in a `runtime_config` collection
as a single document. Workers cache the values with a 2-second TTL to avoid
hitting MongoDB on every request.

This replaces the per-process Settings mutation pattern which only affected
the single Gunicorn worker that handled the toggle request.
"""

import logging
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

_DOC_ID = "modes"
_CACHE_TTL = 2.0  # seconds

_cache: Dict[str, Any] = {
    "update_mode": None,
    "lookup_mode": None,
    "insert_mode": None,
    "timestamp": 0.0,
}


async def get_modes(db) -> Dict[str, str]:
    """Get current modes from cache (refreshes from MongoDB every 2s)."""
    now = time.time()
    if now - _cache["timestamp"] < _CACHE_TTL and _cache["update_mode"] is not None:
        return {"update_mode": _cache["update_mode"], "lookup_mode": _cache["lookup_mode"], "insert_mode": _cache["insert_mode"]}

    try:
        doc = await db.runtime_config.find_one({"_id": _DOC_ID})
        if doc:
            _cache["update_mode"] = doc.get("update_mode", "standard")
            _cache["lookup_mode"] = doc.get("lookup_mode", "memory")
            _cache["insert_mode"] = doc.get("insert_mode", "sync")
        else:
            # No doc yet — use defaults (will be seeded on first toggle or startup)
            _cache["update_mode"] = _cache["update_mode"] or "standard"
            _cache["lookup_mode"] = _cache["lookup_mode"] or "memory"
            _cache["insert_mode"] = _cache["insert_mode"] or "sync"
        _cache["timestamp"] = now
    except Exception as e:
        logger.warning(f"Failed to read runtime config: {e}")
        # Keep stale cache values on error
        if _cache["update_mode"] is None:
            _cache["update_mode"] = "standard"
            _cache["lookup_mode"] = "memory"
            _cache["insert_mode"] = "sync"

    return {"update_mode": _cache["update_mode"], "lookup_mode": _cache["lookup_mode"], "insert_mode": _cache["insert_mode"]}


async def set_mode(db, key: str, value: str) -> Dict[str, str]:
    """Set a mode in MongoDB (propagates to all workers within 2s)."""
    await db.runtime_config.update_one(
        {"_id": _DOC_ID},
        {"$set": {key: value}},
        upsert=True,
    )
    # Update local cache immediately for this worker
    _cache[key] = value
    _cache["timestamp"] = time.time()

    return await get_modes(db)


async def seed_defaults(db, settings) -> None:
    """Seed runtime_config doc from Settings if it doesn't exist yet.

    Uses update_one with upsert + $setOnInsert to avoid race conditions
    when multiple workers start simultaneously.
    """
    result = await db.runtime_config.update_one(
        {"_id": _DOC_ID},
        {"$setOnInsert": {
            "update_mode": settings.UPDATE_MODE,
            "lookup_mode": settings.LOOKUP_MODE,
            "insert_mode": "sync",
        }},
        upsert=True,
    )
    doc = await db.runtime_config.find_one({"_id": _DOC_ID})
    if result.upserted_id is not None:
        logger.info(
            f"Seeded runtime_config: update_mode={settings.UPDATE_MODE}, "
            f"lookup_mode={settings.LOOKUP_MODE}, insert_mode=sync"
        )
    else:
        logger.info(
            f"Runtime config exists: update_mode={doc.get('update_mode')}, "
            f"lookup_mode={doc.get('lookup_mode')}, insert_mode={doc.get('insert_mode')}"
        )
    # Prime the cache from actual DB state
    _cache["update_mode"] = doc.get("update_mode", settings.UPDATE_MODE)
    _cache["lookup_mode"] = doc.get("lookup_mode", settings.LOOKUP_MODE)
    _cache["insert_mode"] = doc.get("insert_mode", "sync")
    _cache["timestamp"] = time.time()
