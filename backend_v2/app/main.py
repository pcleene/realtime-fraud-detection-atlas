"""V2 FastAPI application with lifespan manager."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import connect_db, close_db, get_db
from app.indexes import create_all_indexes, verify_indexes, verify_sharding
from app.cache import warmup_caches
from app.runtime_config import seed_defaults
from app.routes import score_router, health_router, mock_router, config_router
from app.routes.loadtest import router as loadtest_router
from app.routes.locust_proxy import router as locust_proxy_router

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting up V2...")

    # 1. Connect to MongoDB
    await connect_db()
    logger.info("Database connected")

    # 2. Create indexes (idempotent)
    db = await get_db()
    await create_all_indexes(db)
    logger.info("Indexes created")

    # 3. Verify indexes exist
    await verify_indexes(db)
    logger.info("Indexes verified")

    # 4. Verify sharding (if enabled)
    sharding_info = await verify_sharding(db)
    if sharding_info["enabled"]:
        logger.info(f"Sharding verified - {sharding_info['shards']} shards active")
    else:
        logger.info("Running without sharding (standalone/replica set)")

    # 5. Pre-warm caches (blacklists + service config)
    cache_stats = await warmup_caches(db)
    bl = cache_stats.get("blacklists", {})
    sc = cache_stats.get("service_config", {})
    total_bl = sum(bl.values())
    logger.info(
        f"Cache pre-warmed: {total_bl} blacklist entries, "
        f"{sc.get('service_limits', 0)} service configs"
    )

    # 6. Seed runtime config (modes) from Settings if not already in MongoDB
    await seed_defaults(db, settings)

    logger.info("V2 ready to serve requests")

    yield

    # Shutdown
    logger.info("Shutting down V2...")
    await close_db()
    logger.info("Database connection closed")


app = FastAPI(
    title="RegionalBank Fraud Scoring V2",
    description="V2 fraud detection with 31 rules, 3 DB ops, <20ms target",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(score_router, tags=["Fraud Scoring"])
app.include_router(health_router, tags=["Health"])
app.include_router(mock_router, tags=["Mock Data"])
app.include_router(loadtest_router, tags=["Load Testing"])
app.include_router(locust_proxy_router, tags=["Load Testing - External"])
app.include_router(config_router)


@app.get("/")
async def root():
    return {
        "name": "RegionalBank Fraud Scoring V2",
        "version": "2.0.0",
        "rules": 31,
        "docs": "/docs",
    }
