"""
Gunicorn configuration for V2 production deployment.

Usage:
    gunicorn -c gunicorn.conf.py app.main:app
"""

import multiprocessing
import os

# Server socket (V2 defaults to port 8001)
bind = f"{os.getenv('BIND_HOST', '0.0.0.0')}:{os.getenv('BIND_PORT', '8001')}"
backlog = 2048

# Worker processes: 2 * CPU cores + 1 (auto-detect if WORKERS env is empty/unset)
default_workers = (2 * multiprocessing.cpu_count()) + 1
workers = int(os.getenv("WORKERS") or default_workers)

# Uvicorn async worker class for FastAPI
worker_class = "uvicorn.workers.UvicornWorker"

# Worker connections
worker_connections = int(os.getenv("WORKER_CONNECTIONS", "1000"))

# Timeout
timeout = int(os.getenv("TIMEOUT", "30"))
graceful_timeout = 30
keepalive = 5

# Request handling
max_requests = 0
max_requests_jitter = 0

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
proc_name = "RegionalBank-fraud-v2-api"


def on_starting(server):
    print(f"Starting V2 Gunicorn with {workers} workers on {bind}")


def post_fork(server, worker):
    print(f"V2 Worker {worker.pid} spawned")


def post_worker_init(worker):
    print(f"V2 Worker {worker.pid} ready")


def worker_exit(server, worker):
    print(f"V2 Worker {worker.pid} exited")


def on_exit(server):
    print("Shutting down V2 Gunicorn")
