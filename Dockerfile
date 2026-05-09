# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
COPY backend/requirements.txt .

# Install into user-local prefix so we can copy cleanly to runtime stage
RUN pip install --user --no-cache-dir -r requirements.txt


# ── Stage 2: production runtime ───────────────────────────────────────────────
FROM python:3.11-slim

# Non-root user for security
RUN groupadd --gid 1001 amicor \
 && useradd  --uid 1001 --gid 1001 --no-create-home --shell /sbin/nologin amicor

WORKDIR /app

# Installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Application source
COPY backend/ .

# Persistent data directory for SQLite (writable by the amicor user)
RUN mkdir -p /data && chown amicor:amicor /data

# ── Environment defaults (override at runtime via --env or docker-compose) ────
ENV DB_FILENAME=/data/chat.db \
    LOG_LEVEL=INFO \
    APP_VERSION=1.0.0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER amicor

EXPOSE 8000

# Docker health check — hits the shallow liveness endpoint
HEALTHCHECK \
  --interval=30s \
  --timeout=10s  \
  --start-period=20s \
  --retries=3 \
  CMD python -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" \
      || exit 1

# 2 workers is a safe default for a single-core container.
# Scale with WEB_CONCURRENCY env var or by setting --workers directly.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--access-log"]
