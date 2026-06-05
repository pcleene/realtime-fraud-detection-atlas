"""
Gunicorn configuration for production deployment.

This configuration is optimized for high-throughput fraud scoring:
- Uses uvicorn workers for async support
- Auto-scales workers based on CPU cores
- Configures connection pooling for MongoDB
- Enables graceful shutdown for load balancer health checks

Usage:
    gunicorn -c gunicorn.conf.py app.main:app

Environment Variables:
    WORKERS: Number of worker processes (default: 2 * CPU + 1)
    WORKER_CONNECTIONS: Max concurrent connections per worker (default: 1000)
    BIND_HOST: Host to bind to (default: 0.0.0.0)
    BIND_PORT: Port to bind to (default: 8000)
    TIMEOUT: Worker timeout in seconds (default: 120)
"""

import multiprocessing
import os

# Server socket
bind = f"{os.getenv('BIND_HOST', '0.0.0.0')}:{os.getenv('BIND_PORT', '8000')}"
backlog = 2048

# Worker processes
# Formula: 2 * CPU cores + 1 (recommended for I/O bound applications)
# For CPU-bound, use: CPU cores + 1
default_workers = (2 * multiprocessing.cpu_count()) + 1
workers = int(os.getenv("WORKERS", default_workers))

# Use uvicorn's async worker class for FastAPI
worker_class = "uvicorn.workers.UvicornWorker"

# Worker connections (for async workers, this is the max concurrent connections)
worker_connections = int(os.getenv("WORKER_CONNECTIONS", "1000"))

# Timeout for graceful workers restart
timeout = int(os.getenv("TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5

# Request handling
max_requests = 10000  # Restart workers after this many requests (prevents memory leaks)
max_requests_jitter = 1000  # Add randomness to prevent all workers restarting at once

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# Logging
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
accesslog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "RegionalBank-fraud-api"

# SSL (optional - usually handled by load balancer)
# keyfile = None
# certfile = None

# Hooks for monitoring and debugging
def on_starting(server):
    """Called just before the master process is initialized."""
    print(f"Starting Gunicorn with {workers} workers")
    print(f"Worker class: {worker_class}")
    print(f"Max connections per worker: {worker_connections}")


def on_reload(server):
    """Called to recycle workers during a reload via SIGHUP."""
    print("Reloading workers...")


def worker_int(worker):
    """Called when a worker receives SIGINT or SIGQUIT."""
    print(f"Worker {worker.pid} interrupted")


def worker_abort(worker):
    """Called when a worker receives SIGABRT (usually from timeout)."""
    print(f"Worker {worker.pid} aborted (timeout?)")


def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass


def post_fork(server, worker):
    """Called just after a worker has been forked."""
    print(f"Worker {worker.pid} spawned")


def post_worker_init(worker):
    """Called just after a worker has initialized the application."""
    print(f"Worker {worker.pid} ready to serve requests")


def worker_exit(server, worker):
    """Called just after a worker has been exited."""
    print(f"Worker {worker.pid} exited")


def nworkers_changed(server, new_value, old_value):
    """Called just after num_workers has been changed."""
    print(f"Worker count changed from {old_value} to {new_value}")


def on_exit(server):
    """Called just before exiting Gunicorn."""
    print("Shutting down Gunicorn")
