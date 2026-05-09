# Amicor Platform Architecture

> Generated during the platformisation phase (2025). Describes production deployment
> topology, auth lifecycle, database schema, observability strategy, and operational
> guidelines for the Amicor AI assistant platform.

---

## Table of Contents

1. [Overview](#overview)
2. [Database Topology](#database-topology)
3. [Auth Lifecycle](#auth-lifecycle)
4. [Upload Lifecycle](#upload-lifecycle)
5. [Deployment Topology](#deployment-topology)
6. [Observability Strategy](#observability-strategy)
7. [Resilience Architecture](#resilience-architecture)
8. [Scaling Strategy](#scaling-strategy)
9. [Security Architecture](#security-architecture)
10. [Platform Tables Reference](#platform-tables-reference)

---

## Overview

Amicor runs as a FastAPI application backed by two database layers:

| Layer | Technology | Purpose |
|-------|------------|---------|
| Legacy | SQLite (raw sqlite3) | Existing chat messages, preferences, memory summaries |
| Platform | SQLAlchemy 2.0 (SQLite dev / PostgreSQL prod) | Users, auth tokens, uploads, provider logs, audit logs |

In production the platform layer connects to PostgreSQL via the `DATABASE_URL`
environment variable. In development it defaults to SQLite for zero-config startup.

---

## Database Topology

```
Development
───────────
 FastAPI process
   ├── Legacy DB    → backend/data/chat.db      (raw sqlite3)
   └── Platform DB  → backend/data/platform.db  (SQLAlchemy / SQLite)

Production (Docker Compose)
────────────────────────────
 nginx (port 80/443)
   └── FastAPI (api:8000, 4 workers)
         ├── Legacy DB    → /data/chat.db         (volume: amicor_data)
         └── Platform DB  → postgresql://db:5432  (volume: amicor_pg)

PostgreSQL service (db:5432)
   └── Persistent volume: amicor_pg
```

### SQLite → PostgreSQL migration

Set `DATABASE_URL=postgresql://user:pass@host:5432/amicor` and run:

```bash
cd backend
alembic upgrade head
```

The Alembic migration in `migrations/versions/0001_initial_platform_tables.py`
creates all 8 `platform_*` tables. It is idempotent and safe to run on an empty
or existing database.

---

## Auth Lifecycle

```
Client                     FastAPI /api/auth/*             platform_users / platform_refresh_tokens
  │                               │                                │
  │── POST /register ────────────>│                                │
  │                               │── PBKDF2-HMAC-SHA256 hash ──>│
  │                               │── INSERT platform_users ─────>│
  │<── {user_id, email} ─────────│                                │
  │                               │                                │
  │── POST /login ───────────────>│                                │
  │                               │── SELECT + verify hash ──────>│
  │                               │── CREATE access_token (JWT, HS256, 60min)
  │                               │── CREATE refresh_token (256-bit random, 7d)
  │                               │── INSERT platform_refresh_tokens ─>│
  │<── {access_token, refresh_token, email} ────────────────────│
  │                               │                                │
  │── GET /api/auth/me ──────────>│                                │
  │   Authorization: Bearer <AT> │                                │
  │                               │── _jwt_verify(token) ─────────│
  │                               │── SELECT platform_users ──────>│
  │<── {email, display_name} ────│                                │
  │                               │                                │
  │── POST /refresh ─────────────>│                                │
  │   {refresh_token} ──────────>│                                │
  │                               │── hash(token) lookup ─────────>│
  │                               │── check not revoked, not expired│
  │                               │── issue new access_token ──────│
  │<── {access_token} ───────────│                                │
  │                               │                                │
  │── POST /logout ──────────────>│                                │
  │   {refresh_token} ──────────>│                                │
  │                               │── UPDATE revoked=1 ───────────>│
  │<── {status: "ok"} ───────────│                                │
```

### Token properties

| Token | Algorithm | Expiry | Storage |
|-------|-----------|--------|---------|
| Access | JWT HS256 (stdlib only) | 60 min (env: `ACCESS_TOKEN_EXPIRE_MINUTES`) | Client memory only |
| Refresh | 256-bit random hex | 7 days (env: `REFRESH_TOKEN_EXPIRE_DAYS`) | `platform_refresh_tokens` (hashed) |

Passwords are stored as PBKDF2-HMAC-SHA256 with 260,000 iterations and a random
16-byte salt (stored in the hash string). No external JWT library is required.

---

## Upload Lifecycle

```
Client                    FastAPI /api/upload           platform_uploads
  │                              │                            │
  │── POST /api/upload ─────────>│                            │
  │   multipart/form-data file  │                            │
  │                              │── MIME type detection ─────│
  │                              │── size check (max 10 MB) ──│
  │                              │── text extraction:         │
  │                              │     PDF  → pypdf           │
  │                              │     DOCX → python-docx     │
  │                              │     IMG  → OpenAI Vision   │
  │                              │     TXT  → direct read     │
  │                              │── chunk text (512-token)   │
  │                              │── INSERT platform_uploads ─>│
  │                              │── observability.increment() │
  │<── {filename, chunks, ocr} ─│                            │
```

Upload metadata (filename, MIME type, size, OCR results) is written to
`platform_uploads` via `log_upload()` in `app/middleware.py`.

---

## Deployment Topology

### Development

```bash
# Start backend
Push-Location backend
$env:PYTHONPATH = (Get-Location).Path
$env:DB_FILENAME = (Join-Path (Get-Location).Path "data\chat.db")
& "..\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Docker Compose (local integration)

```bash
cp .env.template .env   # fill in OPENAI_API_KEY, SECRET_KEY, POSTGRES_PASSWORD
docker compose up --build
```

Services: `api` (FastAPI) + `db` (PostgreSQL 16).  
Access: `http://localhost:8000`

### Production (Docker Compose + nginx)

```bash
# Build immutable image
docker build -t amicor:1.0.0 .

# Start production stack
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Services: `nginx` (port 80/443) → `api` (4 uvicorn workers) + `db` (PostgreSQL).

### Render / Railway / Fly.io

Set environment variables:
- `DATABASE_URL` — PostgreSQL connection string from your managed DB
- `SECRET_KEY` — 32-byte random hex
- `OPENAI_API_KEY`
- `PORT` (Render sets this automatically)

Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

---

## Observability Strategy

All metrics are collected in-process using stdlib only (no external metrics server).

### Counters (`observability.increment`)

| Counter | Meaning |
|---------|---------|
| `uploads.total` | Total files uploaded |
| `uploads.images` | Image uploads specifically |
| `requests.total` | Total HTTP requests (via middleware) |
| `errors.4xx` | 4xx client errors |
| `errors.5xx` | 5xx server errors |

### Latencies (`observability.record_latency`)

Circular buffer of 200 samples per key; reports p50/p95/p99/avg/max.

### Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/admin/dashboard` | Full platform status snapshot |
| `GET /api/admin/metrics` | Lightweight counters + latencies |
| `GET /api/diagnostics/providers` | Circuit breaker states |
| `GET /admin` | Admin UI (browser) |

### Structured audit logging

Every 4xx/5xx response is written to `platform_audit_logs` by
`RequestTracingMiddleware`. Includes: request ID, path, method, status code,
IP address, latency.

---

## Resilience Architecture

Provider calls (OpenAI, weather, search, news) are wrapped in a circuit breaker
with retry budget (`app/providers/resilience.py`):

```
States:   CLOSED → (failure threshold) → OPEN → (recovery window) → HALF_OPEN → CLOSED
Metrics:  platform_provider_logs (success, latency_ms, error_msg per call)
Endpoint: GET /api/diagnostics/providers
```

### Failure thresholds (defaults)

| Parameter | Value |
|-----------|-------|
| Failure rate to open | 50% of last 10 calls |
| Recovery window | 30 seconds |
| Half-open probe calls | 1 |

---

## Scaling Strategy

### Horizontal

- FastAPI is stateless; scale horizontally by increasing worker count or running
  multiple containers behind nginx.
- Platform DB must point to PostgreSQL (not SQLite) for multi-instance deployments.
- Rate limiting is per-process (in-memory); use a Redis-backed store for
  multi-instance deployments.

### Vertical

- `uvicorn --workers N` defaults to 4 in production (`docker-compose.prod.yml`).
- PostgreSQL connection pool is managed by SQLAlchemy with sensible defaults.

---

## Security Architecture

| Layer | Control |
|-------|---------|
| Transport | nginx TLS termination (TLSv1.2+) |
| Headers | OWASP security headers via `SecurityHeadersMiddleware` |
| Auth | JWT HS256 + PBKDF2-HMAC-SHA256 passwords (no external deps) |
| Rate limiting | Sliding window per IP (RATE_LIMIT_AUTH, RATE_LIMIT_CHAT) |
| Input validation | Pydantic schemas on all request bodies |
| Upload safety | MIME detection, 10 MB size cap, allowlist validation |
| Audit | Every 4xx/5xx logged to `platform_audit_logs` |
| CORS | Origin allowlist (dev: localhost only; prod: configured domain) |
| Request tracing | `X-Request-ID` injected per request for correlation |

---

## Platform Tables Reference

| Table | Rows | Purpose |
|-------|------|---------|
| `platform_users` | 1 per account | Email, hashed password, profile |
| `platform_conversations` | 1 per conversation | Title, owner |
| `platform_messages` | N per conversation | Role + content |
| `platform_uploads` | 1 per upload | Filename, MIME, OCR metadata |
| `platform_memory` | 1 per user | Long-term conversation summary |
| `platform_provider_logs` | 1 per provider call | Latency, success, errors |
| `platform_refresh_tokens` | 1 per active session | Token hash, expiry, revoked flag |
| `platform_audit_logs` | 1 per 4xx/5xx request | Path, status, IP, latency |

All tables are managed by SQLAlchemy + Alembic. To apply migrations:

```bash
cd backend
alembic upgrade head        # apply all pending migrations
alembic downgrade -1        # roll back one step
alembic history             # show migration history
```
