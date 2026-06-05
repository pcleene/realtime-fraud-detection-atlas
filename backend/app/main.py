import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import connect_db, close_db, get_db
from app.indexes import create_all_indexes, verify_indexes, verify_sharding
from app.routes import score_router, health_router, loadtest_router
from app.routes.mock import router as mock_router
from app.routes.locust_proxy import router as locust_proxy_router
from app.cache import warmup_cache

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting up...")

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
        logger.info(
            f"Sharding verified - {sharding_info['shards']} shards active"
        )
    else:
        logger.info("Running without sharding (standalone/replica set)")

    # 5. Pre-warm caches for small collections (holidays, blacklist)
    cache_stats = await warmup_cache(db)
    logger.info(
        f"Cache pre-warmed: {cache_stats['holidays_count']} holidays, "
        f"{cache_stats['blacklist_count']} blacklist locations "
        f"(TTL: {cache_stats['cache_ttl_seconds']}s)"
    )

    logger.info("Ready to serve requests")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await close_db()
    logger.info("Database connection closed")


# Create FastAPI app
app = FastAPI(
    title="RegionalBank Fraud Scoring POC",
    description="Production-grade fraud detection POC demonstrating MongoDB as a consolidated replacement for Redis + Oracle",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(score_router, tags=["Fraud Scoring"])
app.include_router(health_router, tags=["Health"])
app.include_router(mock_router, tags=["Mock Data"])
app.include_router(loadtest_router, tags=["Load Testing"])
app.include_router(locust_proxy_router, tags=["Load Testing - External"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "RegionalBank Fraud Scoring POC",
        "version": "1.0.0",
        "docs": "/docs",
    }
