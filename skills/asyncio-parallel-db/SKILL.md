---
name: asyncio-parallel-db
description: Use asyncio.gather() to parallelize database operations and reduce latency. Use this skill when building async Python applications that make multiple database calls, when you see sequential await statements for independent operations, when optimizing API response times, or when implementing high-throughput services that need to minimize end-to-end latency.
---

# Parallel Database Operations with asyncio

Sequential database operations waste time. Use `asyncio.gather()` to run independent operations concurrently.

## The Problem

```python
# Sequential - SLOW
# Total time: fetch(20ms) + update(15ms) + insert(15ms) = 50ms
customer = await db.customers.find_one({"id": customer_id})
await db.customers.update_one({"id": customer_id}, {"$set": update})
result = await db.transactions.insert_one(doc)
```

## The Solution

```python
# Parallel - FAST
# Total time: max(20ms, 15ms, 15ms) = 20ms
customer, _, result = await asyncio.gather(
    db.customers.find_one({"id": customer_id}),
    db.customers.update_one({"id": customer_id}, {"$set": update}),
    db.transactions.insert_one(doc),
)
```

## Three-Phase Execution Pattern

For complex operations, organize into phases based on dependencies:

```python
import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass
class TimingBreakdown:
    """Track timing for observability."""
    parallel_reads_ms: float = 0.0
    cpu_processing_ms: float = 0.0
    parallel_writes_ms: float = 0.0
    total_ms: float = 0.0

    # Individual operation times
    db_fetch_ms: float = 0.0
    db_query1_ms: float = 0.0
    db_query2_ms: float = 0.0
    db_update_ms: float = 0.0
    db_insert_ms: float = 0.0


async def process_request(db, request) -> Tuple[dict, TimingBreakdown]:
    """
    Process a request with parallel database operations.

    Execution phases:
    1. PARALLEL: Multiple DB reads (run concurrently)
    2. SEQUENTIAL: CPU processing (depends on read results)
    3. PARALLEL: Multiple DB writes (run concurrently)
    """
    timing = TimingBreakdown()
    start_time = time.perf_counter()

    # =========================================================================
    # PHASE 1: Parallel Database Reads
    # =========================================================================
    parallel_read_start = time.perf_counter()

    # Define timed fetch functions
    async def timed_fetch():
        t0 = time.perf_counter()
        result = await db.items.find_one({"id": request.item_id})
        return result, (time.perf_counter() - t0) * 1000

    async def timed_query1():
        t0 = time.perf_counter()
        result = await db.cache.find_one({"type": "config"})
        return result, (time.perf_counter() - t0) * 1000

    async def timed_query2():
        t0 = time.perf_counter()
        cursor = db.related.find({"parent_id": request.item_id})
        result = await cursor.to_list(length=100)
        return result, (time.perf_counter() - t0) * 1000

    # Run all reads in parallel
    (item, fetch_time), (config, query1_time), (related, query2_time) = await asyncio.gather(
        timed_fetch(),
        timed_query1(),
        timed_query2(),
    )

    timing.parallel_reads_ms = (time.perf_counter() - parallel_read_start) * 1000
    timing.db_fetch_ms = fetch_time
    timing.db_query1_ms = query1_time
    timing.db_query2_ms = query2_time

    if item is None:
        raise ValueError(f"Item {request.item_id} not found")

    # =========================================================================
    # PHASE 2: CPU Processing (Sequential, depends on Phase 1 results)
    # =========================================================================
    cpu_start = time.perf_counter()

    # Process data (CPU-bound, fast)
    processed_result = {
        "item": item,
        "config": config,
        "related_count": len(related),
        "score": calculate_score(item, config, related),
    }

    timing.cpu_processing_ms = (time.perf_counter() - cpu_start) * 1000

    # =========================================================================
    # PHASE 3: Parallel Database Writes
    # =========================================================================
    parallel_write_start = time.perf_counter()

    async def timed_update():
        t0 = time.perf_counter()
        await db.items.update_one(
            {"id": request.item_id},
            {"$set": {"last_processed": time.time()}}
        )
        return (time.perf_counter() - t0) * 1000

    async def timed_insert():
        t0 = time.perf_counter()
        result = await db.results.insert_one(processed_result)
        return str(result.inserted_id), (time.perf_counter() - t0) * 1000

    # Run writes in parallel
    update_time, (result_id, insert_time) = await asyncio.gather(
        timed_update(),
        timed_insert(),
    )

    timing.parallel_writes_ms = (time.perf_counter() - parallel_write_start) * 1000
    timing.db_update_ms = update_time
    timing.db_insert_ms = insert_time

    timing.total_ms = (time.perf_counter() - start_time) * 1000

    return {"id": result_id, **processed_result}, timing
```

## Pattern: Wrapper Functions for Timing

```python
async def fetch_with_timing(db, collection: str, filter: dict) -> Tuple[dict, float]:
    """Fetch document and return with timing."""
    t0 = time.perf_counter()
    doc = await db[collection].find_one(filter)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return doc, elapsed_ms


async def update_with_timing(db, collection: str, filter: dict, update: dict) -> float:
    """Update document and return timing."""
    t0 = time.perf_counter()
    await db[collection].update_one(filter, {"$set": update})
    return (time.perf_counter() - t0) * 1000


async def insert_with_timing(db, collection: str, doc: dict) -> Tuple[str, float]:
    """Insert document and return ID with timing."""
    t0 = time.perf_counter()
    result = await db[collection].insert_one(doc)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return str(result.inserted_id), elapsed_ms
```

## Pattern: Parallel with Error Handling

```python
async def parallel_with_fallback(db, item_id: str):
    """Run parallel operations with individual error handling."""

    async def safe_fetch(collection, filter, default=None):
        """Fetch with fallback on error."""
        try:
            return await db[collection].find_one(filter)
        except Exception as e:
            logger.warning(f"Fetch from {collection} failed: {e}")
            return default

    # All operations run even if some fail
    item, config, related = await asyncio.gather(
        safe_fetch("items", {"id": item_id}),
        safe_fetch("config", {"type": "default"}, default={}),
        safe_fetch("related", {"parent": item_id}, default=[]),
    )

    return item, config, related
```

## Pattern: Conditional Parallel Operations

```python
async def conditional_parallel(db, request):
    """Only parallelize operations that are needed."""

    # Always needed
    fetch_task = db.items.find_one({"id": request.item_id})

    # Conditionally needed
    tasks = [fetch_task]
    task_names = ["item"]

    if request.include_related:
        tasks.append(db.related.find({"parent": request.item_id}).to_list(100))
        task_names.append("related")

    if request.include_history:
        tasks.append(db.history.find({"item": request.item_id}).to_list(50))
        task_names.append("history")

    # Run all needed tasks in parallel
    results = await asyncio.gather(*tasks)

    # Map results to names
    return dict(zip(task_names, results))
```

## Pattern: Batched Parallel Operations

For many independent operations, batch them:

```python
async def fetch_many_parallel(db, item_ids: list, batch_size: int = 50):
    """Fetch many items in parallel batches."""

    async def fetch_batch(ids):
        cursor = db.items.find({"id": {"$in": ids}})
        return await cursor.to_list(length=len(ids))

    # Split into batches
    batches = [
        item_ids[i:i + batch_size]
        for i in range(0, len(item_ids), batch_size)
    ]

    # Run batches in parallel
    results = await asyncio.gather(*[fetch_batch(batch) for batch in batches])

    # Flatten results
    return [item for batch_result in results for item in batch_result]
```

## When to Use Sequential vs Parallel

| Scenario | Use | Reason |
|----------|-----|--------|
| Operations on different collections | Parallel | No dependencies |
| Read then write same document | Sequential | Write depends on read |
| Multiple independent reads | Parallel | No dependencies |
| Multiple independent writes | Parallel | No dependencies |
| Transactional writes (all-or-nothing) | Sequential + Transaction | ACID requirements |

## Timing Breakdown for Observability

```python
@dataclass
class TimingBreakdown:
    """Detailed timing for API response."""

    # Phase timings (wall-clock time per phase)
    parallel_reads_ms: float = 0.0
    cpu_processing_ms: float = 0.0
    parallel_writes_ms: float = 0.0

    # Individual operation timings
    db_customer_fetch_ms: float = 0.0
    db_blacklist_query_ms: float = 0.0
    db_holiday_query_ms: float = 0.0
    db_customer_update_ms: float = 0.0
    db_transaction_insert_ms: float = 0.0

    # Aggregates
    total_ms: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {k: round(v, 2) for k, v in self.__dict__.items()}

    def log_summary(self):
        """Log timing summary."""
        logger.info(
            f"Timing: Reads={self.parallel_reads_ms:.1f}ms, "
            f"CPU={self.cpu_processing_ms:.1f}ms, "
            f"Writes={self.parallel_writes_ms:.1f}ms, "
            f"Total={self.total_ms:.1f}ms"
        )
```

## Include Timing in API Response

```python
from fastapi import FastAPI, Depends
from pydantic import BaseModel

class ProcessResponse(BaseModel):
    result: dict
    timing: dict

@app.post("/process", response_model=ProcessResponse)
async def process(request: ProcessRequest, db = Depends(get_db)):
    result, timing = await process_request(db, request)
    return ProcessResponse(
        result=result,
        timing=timing.to_dict(),
    )
```

## Common Mistakes

1. **Sequential awaits for independent operations**:
   ```python
   # Wrong - sequential
   a = await fetch_a()
   b = await fetch_b()
   c = await fetch_c()

   # Correct - parallel
   a, b, c = await asyncio.gather(fetch_a(), fetch_b(), fetch_c())
   ```

2. **Gathering dependent operations**:
   ```python
   # Wrong - fetch depends on check
   result, item = await asyncio.gather(
       process(item),  # Needs item!
       db.items.find_one({"id": id}),
   )

   # Correct - sequential for dependencies
   item = await db.items.find_one({"id": id})
   result = await process(item)
   ```

3. **Not capturing individual timings**:
   ```python
   # Wrong - only know total time
   results = await asyncio.gather(op1(), op2(), op3())

   # Correct - track each operation
   async def timed_op1():
       t0 = time.perf_counter()
       result = await op1()
       return result, (time.perf_counter() - t0) * 1000
   ```

4. **Missing return_exceptions for resilience**:
   ```python
   # Wrong - one failure cancels all
   results = await asyncio.gather(op1(), op2(), op3())

   # Correct - get all results, handle errors individually
   results = await asyncio.gather(op1(), op2(), op3(), return_exceptions=True)
   for r in results:
       if isinstance(r, Exception):
           logger.error(f"Operation failed: {r}")
   ```
