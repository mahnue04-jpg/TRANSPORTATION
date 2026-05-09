# Amicor — Production Readiness Guide

This document covers everything needed to take Amicor from development to a healthy production deployment.

---

## Table of Contents

1. [Overview](#overview)
2. [Pre-Deployment Checklist](#pre-deployment-checklist)
3. [Environment Variables](#environment-variables)
4. [Deployment Options](#deployment-options)
   - [Docker (recommended)](#docker-recommended)
   - [Docker Compose — local development](#docker-compose--local-development)
   - [Docker Compose — production](#docker-compose--production)
   - [Bare-metal / PaaS](#bare-metal--paas)
5. [Health Endpoints](#health-endpoints)
6. [Monitoring Strategy](#monitoring-strategy)
7. [File Upload Constraints](#file-upload-constraints)
8. [Security Notes](#security-notes)
9. [Scaling Considerations](#scaling-considerations)
10. [Recovery Procedures](#recovery-procedures)
11. [Production Hardening Checklist](#production-hardening-checklist)

---

## Overview

Amicor is a FastAPI + SQLite application served as a single container. The frontend is a vanilla JS SPA served as static files from the same container. Communication is same-origin (`/api/*`), so no CORS complexity in production.

Key production characteristics:

| Property | Value |
|---|---|
| Runtime | Python 3.11, FastAPI, uvicorn |
| Database | SQLite (file-based, `/data/chat.db`) |
| Workers | 2 (default), 4 (prod compose) |
| Port | 8000 |
| Non-root user | `amicor` (uid/gid 1001) |
| Health endpoint | `GET /api/health` |

---

## Pre-Deployment Checklist

Run the bundled validator before every deployment:

```bash
# From project root
python backend/scripts/validate_startup.py
```

It checks:

- [ ] Python >= 3.11
- [ ] `OPENAI_API_KEY` is set and starts with `sk-`
- [ ] Optional env vars present (`weather_api_key`, `ALLOWED_ORIGINS`, etc.)
- [ ] Database directory is writable
- [ ] All required packages importable (`fastapi`, `uvicorn`, `openai`, `aiofiles`, `multipart`)

**Exit 0** = ready to deploy. **Exit 1** = fix the listed failures first.

---

## Environment Variables

Copy `.env.template` to `.env` and fill in secrets. **Never commit `.env`.**

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | **Yes** | — | OpenAI API key (starts with `sk-`) |
| `weather_api_key` | No | — | OpenWeatherMap API key |
| `ALLOWED_ORIGINS` | No | `*` (dev) | Comma-separated allowed CORS origins. Set to your domain in production. |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `APP_VERSION` | No | `1.0.0` | Shown in `/api/health/detail` response |
| `DB_FILENAME` | No | `/data/chat.db` | Absolute path to SQLite database file |
| `MAX_HISTORY` | No | `10` | Number of conversation turns kept in memory per user |

### Production ALLOWED_ORIGINS example

```
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

---

## Deployment Options

### Docker (recommended)

```bash
# Build
docker build -t amicor:1.0.0 .

# Run
docker run -d \
  --name amicor \
  -p 8000:8000 \
  -e OPENAI_API_KEY=sk-... \
  -e ALLOWED_ORIGINS=https://yourdomain.com \
  -v amicor_data:/data \
  --restart unless-stopped \
  amicor:1.0.0
```

The container runs as the non-root user `amicor` (uid 1001). The `/data` volume persists the SQLite database across container restarts.

### Docker Compose — local development

```bash
# Start (with live-reload)
docker compose up

# Stop
docker compose down
```

Source code is bind-mounted, so edits to `backend/` take effect immediately.

### Docker Compose — production

```bash
# Build and deploy
APP_VERSION=1.0.0 docker compose -f docker-compose.prod.yml up -d

# View logs
docker compose -f docker-compose.prod.yml logs -f

# Rolling update
docker build -t amicor:1.1.0 .
APP_VERSION=1.1.0 docker compose -f docker-compose.prod.yml up -d --no-deps amicor
```

Production compose features:
- 4 uvicorn workers
- CPU limit: 2 cores, memory limit: 512 MB
- `restart: always`
- JSON log rotation (10 MB × 5 files)
- Healthcheck targets `/api/health/detail`

### Bare-metal / PaaS

```bash
# Install dependencies
cd backend
pip install -r requirements.txt

# Run (set env vars first)
export OPENAI_API_KEY=sk-...
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

For Heroku / Render: the `Procfile` in `backend/` is `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

---

## Health Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Liveness ping — always 200 |
| `/api/health` | GET | Shallow liveness — checks app is running |
| `/api/health/detail` | GET | Deep health — includes DB check, startup report, returns 503 if degraded |

### `/api/health/detail` response shape

```json
{
  "status": "ok",
  "version": "1.0.0",
  "startup": {
    "env_ok": true,
    "db_ok": true,
    "warnings": [],
    "errors": []
  },
  "db": {
    "ok": true,
    "path": "/data/chat.db"
  }
}
```

Status is `"degraded"` (HTTP 503) if either `env_ok` or `db_ok` is false.

---

## Monitoring Strategy

### Client-side (`productionMonitor.js`)

The frontend monitors itself via `window.AmiCorMonitor`:

- **Response times** — p50 / p95 / p99 per API call, updated in real time
- **Error rate** — rolling 5-minute window
- **Heartbeat** — GET `/api/health` every 60 seconds
- **Health indicator** — status dot in the UI header turns amber/red on problems
- **Subscriber API** — `AmiCorMonitor.subscribe(fn)` for custom dashboards
- **DOM mirror** — `#amicor-monitor-data[data-report]` holds JSON for Playwright/extensions

### Server-side

- Structured logs via Python `logging` with `%(asctime)s %(levelname)s %(name)s %(message)s` format
- Docker json-file log rotation (prod compose)
- `/api/health/detail` for uptime monitors (UptimeRobot, Checkly, etc.)

### Recommended external checks

| Check | Target | Expected |
|---|---|---|
| Uptime | `GET /api/health` | HTTP 200 |
| Deep health | `GET /api/health/detail` | HTTP 200, `status: ok` |
| Static asset | `GET /static/index.html` | HTTP 200 |

Run `scripts/health_check.sh` from CI or a monitoring system:

```bash
BASE_URL=https://yourdomain.com bash scripts/health_check.sh
```

---

## File Upload Constraints

| Constraint | Value |
|---|---|
| Max file size | 10 MB |
| Allowed MIME types | `text/plain`, `text/markdown`, `text/csv`, `application/json`, `application/pdf`, `image/png`, `image/jpeg`, `image/webp` |
| Text extraction | Enabled for `text/*` and `application/json` (first 8,000 chars) |
| Upload endpoint | `POST /api/upload` |
| Retry on failure | Up to 2 retries with 1.5 s / 3 s backoff (frontend) |

---

## Security Notes

- **Secrets** — all secrets in env vars; `.env` is gitignored. Use a secrets manager (AWS Secrets Manager, Vault) in production.
- **CORS** — set `ALLOWED_ORIGINS` to your specific domain(s) in production. Wildcard `*` is for development only.
- **Non-root container** — the Docker image runs as `amicor` (uid 1001), not root.
- **Input validation** — all `/api/*` endpoints validate content-type, body schema, and user_id format server-side.
- **File upload** — MIME type and size checked on both client and server. Text extraction limited to 8,000 chars to prevent prompt injection via large files.
- **No eval / innerHTML with user content** — user messages are set via `textContent`; only AI replies go through the renderer (which sanitises HTML).
- **Rate limiting** — not built-in; add an API gateway or nginx rate-limit layer in front of uvicorn for public deployments.
- **HTTPS** — terminate TLS at a reverse proxy (nginx, Caddy, Traefik) or load balancer. Never expose uvicorn directly on port 443.

---

## Scaling Considerations

| Concern | Recommendation |
|---|---|
| Stateful sessions | SQLite is single-writer. Suitable for single-node. For multi-node, migrate to PostgreSQL. |
| Workers | Start at 2 × CPU cores. Cap at 4 for the 512 MB memory limit. |
| Concurrent uploads | Each upload is sync I/O; aiofiles reads are async. Should handle 10–20 concurrent uploads comfortably. |
| Long conversations | `MAX_HISTORY` caps context sent to OpenAI. Increase for better continuity at the cost of token spend. |
| Static assets | Serve via CDN (CloudFront, Cloudflare) by proxying `/static/*` for high-traffic deployments. |

---

## Recovery Procedures

### Container crashes

Docker `restart: always` restarts automatically. Check logs:

```bash
docker logs amicor --tail 100
```

### Database corruption

```bash
# Check integrity
sqlite3 /data/chat.db "PRAGMA integrity_check;"

# If corrupt, reset (loses all conversation history)
docker exec amicor rm /data/chat.db
docker restart amicor
```

### OpenAI API outage

Chat requests will return HTTP 500. The frontend shows error bubbles with retry buttons (exponential backoff: 1.5 s → 3 s → 6 s, max 3 attempts). No data is lost; users can retry when the API recovers.

### Out of disk (SQLite)

```bash
# Check size
docker exec amicor du -sh /data/chat.db

# Vacuum (reclaim space from deleted rows)
docker exec amicor sqlite3 /data/chat.db "VACUUM;"
```

---

## Production Hardening Checklist

- [ ] `OPENAI_API_KEY` set in environment (not in source code)
- [ ] `ALLOWED_ORIGINS` set to specific domain(s)
- [ ] `LOG_LEVEL=INFO` (not DEBUG)
- [ ] TLS termination at reverse proxy
- [ ] `/data` volume backed up (SQLite file)
- [ ] `python backend/scripts/validate_startup.py` passes
- [ ] `scripts/health_check.sh` passes against production URL
- [ ] External uptime monitor configured for `/api/health`
- [ ] Docker image built from a tagged commit (not `latest` in prod)
- [ ] `restart: always` set in compose or orchestrator
- [ ] Log rotation configured
- [ ] Rate limiting at proxy layer (nginx `limit_req` or equivalent)
- [ ] Node production tests passing: `npm run test:production`
