# Staging / Production Environment Checklist

Use this checklist before promoting Amicor Health ISF to staging or production.  
**Do not commit real secrets.** Store values in your host's secret manager (Render, Azure Key Vault, etc.).

## Required environment variables

| Variable | Required | Example (safe placeholder only) | Purpose |
|----------|----------|----------------------------------|---------|
| `DATABASE_URL` | Yes | `postgresql://amicor_app:***@db.example.com:5432/amicor_staging` | PostgreSQL connection string |
| `SECRET_KEY` | Yes | `openssl rand -hex 32` output | App signing / session material |
| `JWT_SECRET` | Yes | `openssl rand -hex 32` output (distinct from SECRET_KEY) | JWT access token signing |
| `ALLOWED_ORIGINS` | Yes | `https://staging.example.com,https://app.example.com` | CORS allowlist (no `*`) |
| `AMICOR_PUBLIC_URL` | Yes | `https://staging.example.com` | Rider tracking links (HTTPS, no trailing slash) |
| `APP_VERSION` | Yes | `2026.06.29-staging.1` | Release identifier surfaced in health checks |

## Recommended variables

| Variable | Example | Purpose |
|----------|---------|---------|
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `DB_POOL_SIZE` | `10` | SQLAlchemy pool size |
| `DB_MAX_OVERFLOW` | `20` | Burst pool capacity |
| `SENTRY_DSN` | `https://***@o000.ingest.sentry.io/***` | Error monitoring |
| `HEALTH_ISF_STRIPE_ENABLED` | `0` or `1` | Enable Stripe billing |
| `AMICOR_SEED_PASSWORD` | *(rotate from dev default)* | Seed account password for pilot only |

## Pre-deploy verification

```powershell
# 1. Export staging secrets from your secret manager (never paste into git)
$env:DATABASE_URL = "postgresql://..."
$env:SECRET_KEY = "..."
$env:JWT_SECRET = "..."
$env:ALLOWED_ORIGINS = "https://staging.example.com"
$env:AMICOR_PUBLIC_URL = "https://staging.example.com"
$env:APP_VERSION = "2026.06.29-staging.1"

# 2. Start backend
cd backend
$env:PYTHONPATH = "."
python -m uvicorn app.main:app --host 0.0.0.0 --port 8010

# 3. Readiness must return ready (HTTP 200)
curl http://127.0.0.1:8010/api/health/readiness

# Expected when blocked (local dev without env):
# HTTP 503, overall_status: not_ready, blocked_reasons: [...]
```

## Readiness interpretation

| `overall_status` | HTTP | Meaning |
|------------------|------|---------|
| `ready` | **200** | Production env vars, config checks, and DB connectivity all pass |
| `staging_only` | **503** | Partial configuration — not cleared for production |
| `not_ready` | **503** | Blocking issues listed in `blocked_reasons` |

Inspect `blocked_reasons` in the JSON response for the exact fix required.

## Post-deploy smoke

- [ ] `GET /api/health/live` → 200
- [ ] `GET /api/health/readiness` → 200 with `overall_status: ready`
- [ ] Login for dispatcher, driver, rider, admin
- [ ] Run `python scripts/browser_health_isf_readiness_audit.py`
- [ ] Run `python scripts/production_certification_audit.py`

See also: `DEPLOYMENT.md`, `.env.template`, `scripts/preflight_deploy.ps1`
