---
name: gunicorn-multiworker
description: Configure Gunicorn with multiple workers for production Python web applications. Use this skill when deploying FastAPI, Flask, or Django apps to production, when asked about scaling Python web servers, when you see single-worker uvicorn commands, or when building high-throughput APIs that need to handle 1K+ requests per second.
---

# Gunicorn Multi-Worker Configuration

Gunicorn enables multi-process parallelism for Python WSGI/ASGI apps. Single-worker setups waste CPU cores and limit throughput.

## Why Multi-Worker?

- Python's GIL limits single-process concurrency
- Multiple workers utilize all CPU cores
- Each worker handles requests independently
- Worker crashes don't bring down the server

## Worker Count Formula

```python
# I/O-bound applications (API servers, web apps)
workers = (2 * cpu_count) + 1

# CPU-bound applications (ML inference, heavy computation)
workers = cpu_count + 1
```

| Instance Type | vCPUs | I/O-bound Workers | CPU-bound Workers |
|---------------|-------|-------------------|-------------------|
| t3.medium     | 2     | 5                 | 3                 |
| c6i.xlarge    | 4     | 9                 | 5                 |
| c6i.2xlarge   | 8     | 17                | 9                 |
| c6i.4xlarge   | 16    | 33                | 17                |

## Complete gunicorn.conf.py

```python
"""
Gunicorn configuration for production deployment.

Usage:
    gunicorn -c gunicorn.conf.py app.main:app

Environment Variables:
    WORKERS: Number of worker processes (default: 2 * CPU + 1)
    WORKER_CONNECTIONS: Max concurrent connections per worker (default: 1000)
    BIND_HOST: Host to bind to (default: 0.0.0.0)
    BIND_PORT: Port to bind to (default: 8000)
    TIMEOUT: Worker timeout in seconds (default: 120)
    LOG_LEVEL: Logging level (default: info)
"""

import multiprocessing
import os

# Server socket
bind = f"{os.getenv('BIND_HOST', '0.0.0.0')}:{os.getenv('BIND_PORT', '8000')}"
backlog = 2048

# Worker processes
default_workers = (2 * multiprocessing.cpu_count()) + 1
workers = int(os.getenv("WORKERS", default_workers))

# Async worker class for FastAPI/Starlette
worker_class = "uvicorn.workers.UvicornWorker"

# Max concurrent connections per worker
worker_connections = int(os.getenv("WORKER_CONNECTIONS", "1000"))

# Timeouts
timeout = int(os.getenv("TIMEOUT", "120"))
graceful_timeout = 30  # Time for graceful shutdown
keepalive = 5          # Keep-alive connections

# Memory leak prevention
max_requests = 10000        # Restart worker after N requests
max_requests_jitter = 1000  # Randomize to prevent thundering herd

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# Logging
errorlog = "-"  # stderr
accesslog = "-"  # stdout
loglevel = os.getenv("LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "my-api"

# Lifecycle hooks for monitoring
def on_starting(server):
    """Called just before master process is initialized."""
    print(f"Starting Gunicorn with {workers} workers")
    print(f"Worker class: {worker_class}")
    print(f"Max connections per worker: {worker_connections}")


def post_fork(server, worker):
    """Called just after a worker is forked."""
    print(f"Worker {worker.pid} spawned")


def post_worker_init(worker):
    """Called just after worker initializes application."""
    print(f"Worker {worker.pid} ready")


def worker_exit(server, worker):
    """Called just after worker exits."""
    print(f"Worker {worker.pid} exited")


def worker_abort(worker):
    """Called when worker times out."""
    print(f"Worker {worker.pid} aborted (timeout)")


def on_exit(server):
    """Called just before exiting."""
    print("Shutting down Gunicorn")
```

## FastAPI Integration

```python
# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - runs in EACH worker
    print(f"Worker starting up...")
    await connect_db()
    yield
    # Shutdown
    await close_db()
    print(f"Worker shutting down...")

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

## Running Gunicorn

```bash
# Development (single worker for debugging)
uvicorn app.main:app --reload

# Production (multi-worker)
gunicorn -c gunicorn.conf.py app.main:app

# Override workers at runtime
WORKERS=4 gunicorn -c gunicorn.conf.py app.main:app

# Quick production start without config file
gunicorn app.main:app \
    --workers 17 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --max-requests 10000 \
    --max-requests-jitter 1000
```

## Docker Integration

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Create non-root user
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Environment defaults (can override at runtime)
ENV WORKERS=4
ENV WORKER_CONNECTIONS=1000
ENV TIMEOUT=120
ENV LOG_LEVEL=info

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
```

## docker-compose.yml

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - WORKERS=${WORKERS:-17}
      - WORKER_CONNECTIONS=${WORKER_CONNECTIONS:-1000}
      - TIMEOUT=${TIMEOUT:-120}
      - LOG_LEVEL=${LOG_LEVEL:-info}
    deploy:
      resources:
        limits:
          cpus: '7'
          memory: 14G
        reservations:
          cpus: '4'
          memory: 8G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

## Worker Memory Considerations

Each worker has its own memory space. Plan accordingly:

| Workers | Base Memory | Per-Worker Overhead | Total Memory |
|---------|-------------|---------------------|--------------|
| 4       | 500MB       | 200MB each          | 1.3GB        |
| 9       | 500MB       | 200MB each          | 2.3GB        |
| 17      | 500MB       | 200MB each          | 3.9GB        |
| 33      | 500MB       | 200MB each          | 7.1GB        |

Set memory limits in docker-compose or container orchestrator accordingly.

## Common Mistakes

1. **Using uvicorn directly in production**:
   ```bash
   # Wrong - single process
   uvicorn app.main:app --host 0.0.0.0

   # Correct - multi-process with gunicorn
   gunicorn -c gunicorn.conf.py app.main:app
   ```

2. **Wrong worker class for async frameworks**:
   ```python
   # Wrong - sync worker for async app
   worker_class = "sync"

   # Correct - async worker for FastAPI/Starlette
   worker_class = "uvicorn.workers.UvicornWorker"
   ```

3. **Too many workers for available memory**:
   - Monitor memory usage during load tests
   - Each worker consumes 100-500MB depending on app

4. **Missing graceful_timeout for load balancers**:
   ```python
   # ALB health checks need time to drain
   graceful_timeout = 30  # Match ALB deregistration delay
   ```

5. **Not restarting workers to prevent memory leaks**:
   ```python
   # Prevents memory growth over time
   max_requests = 10000
   max_requests_jitter = 1000
   ```

## Monitoring Worker Health

```python
# Add to your health endpoint
@app.get("/health")
async def health():
    import os
    return {
        "status": "healthy",
        "worker_pid": os.getpid(),
        "workers_configured": os.getenv("WORKERS", "unknown"),
    }
```

Check all workers are responding:
```bash
for i in {1..20}; do curl -s localhost:8000/health | jq .worker_pid; done | sort | uniq -c
```
