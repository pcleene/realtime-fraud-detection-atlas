FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install gunicorn for production multi-worker support
RUN pip install --no-cache-dir gunicorn

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

# Expose port (V2 uses 8001)
EXPOSE 8001

# Environment variables for production tuning
ENV WORKERS=""
ENV WORKER_CONNECTIONS=1000
ENV TIMEOUT=120
ENV LOG_LEVEL=info
ENV BIND_PORT=8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run with Gunicorn + Uvicorn workers for production
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
