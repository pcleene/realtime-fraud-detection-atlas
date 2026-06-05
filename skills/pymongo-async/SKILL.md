---
name: pymongo-async
description: Use PyMongo's native AsyncMongoClient (pymongo>=4.10) instead of Motor for async MongoDB operations. Motor is deprecated and uses thread pools which limit true async performance. Use this skill when building Python async applications with MongoDB that need high throughput (1K+ TPS), when you see Motor imports in existing code, or when asked to implement async MongoDB connections.
---

# PyMongo Native Async

Use `AsyncMongoClient` from pymongo>=4.10 for native async I/O without thread pools.

## Why Not Motor?

Motor wraps synchronous PyMongo in thread pools, creating overhead:
- Thread pool contention at high concurrency
- Extra memory per connection
- Not true non-blocking I/O

PyMongo 4.10+ provides native async that eliminates these issues.

## Installation

```bash
pip install "pymongo[srv]>=4.10"
```

## Connection Module Pattern

```python
"""
Database connection module using PyMongo Async API.
Uses AsyncMongoClient for native async I/O without thread pools.
"""

from typing import Any, Dict, Optional

from pymongo import AsyncMongoClient, ReadPreference
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import ConnectionFailure

# Singleton instances
_client: Optional[AsyncMongoClient] = None
_db: Optional[AsyncDatabase] = None

# Optimized connection settings for high throughput
CLIENT_OPTIONS: Dict[str, Any] = {
    # Connection Pool - tune based on worker count and Atlas tier
    # Example: 258 workers × 15 pool = 3,870 max connections
    "maxPoolSize": 15,           # Max connections per worker
    "minPoolSize": 3,            # Keep connections warm
    "maxIdleTimeMS": 45000,      # 45s idle timeout
    "waitQueueTimeoutMS": 10000, # 10s wait for connection

    # Timeouts
    "connectTimeoutMS": 20000,   # 20s to establish connection
    "socketTimeoutMS": 30000,    # 30s for operations
    "serverSelectionTimeoutMS": 30000,

    # Compression (reduces network transfer 60-80%)
    "compressors": ["zstd", "snappy", "zlib"],

    # Read/Write settings
    "retryWrites": True,
    "retryReads": True,
    "w": "majority",
    "readPreference": "nearest",  # Best for PrivateLink

    # App identification for monitoring
    "appName": "my-async-app",
}


async def connect_db(uri: str, db_name: str) -> None:
    """Connect to MongoDB using AsyncMongoClient."""
    global _client, _db

    _client = AsyncMongoClient(uri, **CLIENT_OPTIONS)

    # Verify connection
    try:
        await _client.admin.command("ping")
    except ConnectionFailure as e:
        raise RuntimeError(f"MongoDB connection failed: {e}")

    _db = _client[db_name]


async def close_db() -> None:
    """Close MongoDB connection."""
    global _client, _db
    if _client:
        await _client.close()
        _client = None
        _db = None


async def get_db() -> AsyncDatabase:
    """Get async database instance."""
    if _db is None:
        raise RuntimeError("Database not connected. Call connect_db() first.")
    return _db


def get_client() -> Optional[AsyncMongoClient]:
    """Get client instance for monitoring."""
    return _client
```

## FastAPI Integration

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends

from .db import connect_db, close_db, get_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await connect_db(
        uri=os.getenv("MONGODB_URI"),
        db_name=os.getenv("DB_NAME", "mydb")
    )
    yield
    # Shutdown
    await close_db()

app = FastAPI(lifespan=lifespan)

# Dependency for routes
async def get_database():
    return await get_db()

@app.get("/items/{item_id}")
async def get_item(item_id: str, db = Depends(get_database)):
    item = await db.items.find_one({"_id": item_id})
    return item
```

## Async CRUD Operations

```python
from pymongo.asynchronous.database import AsyncDatabase

async def fetch_one(db: AsyncDatabase, collection: str, filter: dict, projection: dict = None):
    """Fetch single document with optional projection."""
    return await db[collection].find_one(filter, projection=projection)

async def fetch_many(db: AsyncDatabase, collection: str, filter: dict, limit: int = 100):
    """Fetch multiple documents."""
    cursor = db[collection].find(filter).limit(limit)
    return await cursor.to_list(length=limit)

async def insert_one(db: AsyncDatabase, collection: str, doc: dict) -> str:
    """Insert document, return inserted ID."""
    result = await db[collection].insert_one(doc)
    return str(result.inserted_id)

async def update_one(db: AsyncDatabase, collection: str, filter: dict, update: dict):
    """Update single document."""
    await db[collection].update_one(filter, {"$set": update})

async def delete_one(db: AsyncDatabase, collection: str, filter: dict):
    """Delete single document."""
    await db[collection].delete_one(filter)
```

## Pool Sizing Guidelines

| Atlas Tier | Max Connections | Workers | maxPoolSize |
|------------|-----------------|---------|-------------|
| M10        | 350             | 50      | 7           |
| M30        | 1,500           | 100     | 15          |
| M50        | 3,000           | 200     | 15          |
| M60        | 6,000           | 300     | 20          |

Formula: `maxPoolSize = Atlas_Max_Connections / Total_Workers`

## Connection Monitoring

```python
async def get_pool_stats() -> Optional[Dict[str, Any]]:
    """Get connection pool statistics for health checks."""
    if _client is None:
        return None

    try:
        topology = _client.topology_description
        return {
            "topology_type": topology.topology_type_name,
            "nodes": len(_client.nodes),
            "max_pool_size": CLIENT_OPTIONS["maxPoolSize"],
            "compression": CLIENT_OPTIONS["compressors"][0],
            "read_preference": CLIENT_OPTIONS["readPreference"],
        }
    except Exception:
        return None
```

## Common Mistakes to Avoid

1. **Using Motor**: Replace `from motor.motor_asyncio import AsyncIOMotorClient` with `from pymongo import AsyncMongoClient`

2. **Missing await on cursors**:
   ```python
   # Wrong
   docs = db.items.find({})

   # Correct
   cursor = db.items.find({})
   docs = await cursor.to_list(length=100)
   ```

3. **Not using projections**: Always project only needed fields for performance:
   ```python
   # Slow - fetches entire document
   doc = await db.users.find_one({"user_id": uid})

   # Fast - fetches only needed fields
   doc = await db.users.find_one(
       {"user_id": uid},
       projection={"name": 1, "email": 1}
   )
   ```

4. **Blocking the event loop**: Never use synchronous MongoClient in async code:
   ```python
   # Wrong - blocks event loop
   from pymongo import MongoClient
   client = MongoClient(uri)  # This blocks!

   # Correct
   from pymongo import AsyncMongoClient
   client = AsyncMongoClient(uri)
   ```
