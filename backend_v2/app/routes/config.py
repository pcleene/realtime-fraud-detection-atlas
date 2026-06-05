"""V2 configuration toggle endpoints for update mode and lookup mode.

Modes are stored in MongoDB (runtime_config collection) and propagate
to all workers across all instances within 2 seconds.
"""

from fastapi import APIRouter, HTTPException, Depends

from app.db import get_db
from app.runtime_config import get_modes, set_mode

router = APIRouter(prefix="/config", tags=["Configuration"])

AT6_DESCRIPTIONS = {
    "standard": "application",
    "pipeline": "database (pipeline update)",
    "aggregation": "database (aggregation $stdDevPop)",
}


# ---- Update Mode (Task 1) ----

@router.get("/update-mode")
async def get_update_mode(db=Depends(get_db)):
    modes = await get_modes(db)
    return {
        "update_mode": modes["update_mode"],
        "at6_computed_by": AT6_DESCRIPTIONS.get(modes["update_mode"], "unknown"),
    }


@router.post("/update-mode/{mode}")
async def set_update_mode(mode: str, db=Depends(get_db)):
    """Toggle between 'standard', 'pipeline', or 'aggregation' update modes.

    Propagates to all workers on all instances within 2 seconds.
    """
    if mode not in ("standard", "pipeline", "aggregation"):
        raise HTTPException(400, "Mode must be 'standard', 'pipeline', or 'aggregation'")
    modes = await set_mode(db, "update_mode", mode)
    return {
        "update_mode": modes["update_mode"],
        "at6_computed_by": AT6_DESCRIPTIONS[mode],
        "propagation": "all workers within 2 seconds",
    }


# ---- Lookup Mode (Task 2) ----

@router.get("/lookup-mode")
async def get_lookup_mode(db=Depends(get_db)):
    modes = await get_modes(db)
    return {
        "lookup_mode": modes["lookup_mode"],
        "db_ops_per_txn": 3 if modes["lookup_mode"] == "memory" else 4,
    }


@router.post("/lookup-mode/{mode}")
async def set_lookup_mode(mode: str, db=Depends(get_db)):
    """Toggle between 'memory' (3 ops) and 'db' (4 ops) lookup modes.

    Propagates to all workers on all instances within 2 seconds.
    """
    if mode not in ("memory", "db"):
        raise HTTPException(400, "Mode must be 'memory' or 'db'")
    modes = await set_mode(db, "lookup_mode", mode)
    return {
        "lookup_mode": modes["lookup_mode"],
        "db_ops_per_txn": 3 if mode == "memory" else 4,
        "propagation": "all workers within 2 seconds",
    }


# ---- Insert Mode ----

INSERT_DESCRIPTIONS = {
    "sync": "insert scored transaction into MongoDB (current behavior)",
    "none": "skip insert — pure scoring only (measures reads + rules + customer update)",
}


@router.get("/insert-mode")
async def get_insert_mode(db=Depends(get_db)):
    modes = await get_modes(db)
    return {
        "insert_mode": modes["insert_mode"],
        "description": INSERT_DESCRIPTIONS.get(modes["insert_mode"], "unknown"),
    }


@router.post("/insert-mode/{mode}")
async def set_insert_mode(mode: str, db=Depends(get_db)):
    if mode not in ("sync", "none"):
        raise HTTPException(400, "Mode must be 'sync' or 'none'")
    modes = await set_mode(db, "insert_mode", mode)
    return {
        "insert_mode": modes["insert_mode"],
        "description": INSERT_DESCRIPTIONS[mode],
        "propagation": "all workers within 2 seconds",
    }


# ---- Combined view ----

@router.get("/modes")
async def get_all_modes(db=Depends(get_db)):
    """Get all modes in one call."""
    modes = await get_modes(db)
    return {
        "update_mode": modes["update_mode"],
        "at6_computed_by": AT6_DESCRIPTIONS.get(modes["update_mode"], "unknown"),
        "lookup_mode": modes["lookup_mode"],
        "db_ops_per_txn": 3 if modes["lookup_mode"] == "memory" else 4,
        "insert_mode": modes["insert_mode"],
        "insert_description": INSERT_DESCRIPTIONS.get(modes["insert_mode"], "unknown"),
    }
