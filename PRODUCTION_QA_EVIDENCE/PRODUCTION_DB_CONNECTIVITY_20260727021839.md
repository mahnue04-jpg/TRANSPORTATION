# Production Database Connectivity Audit

**Run:** 20260727021839
**Target:** https://amicor-health-isf-py.onrender.com
**Verdict:** **FAIL**
**PostgreSQL connected:** False

## Probe summary

| Endpoint | HTTP | Notes |
|----------|------|-------|
| `/api/health/live` | 200 |  |
| `/api/health` | 200 |  |
| `/api/health/readiness` | 503 | Database unreachable |
| `/api/health/operational` | 200 |  |
| `/api/health/detail` | 200 | {'ok': True, 'db_path': '/opt/render/project/src/backend/data/chat.db'} |
| `/api/admin/dashboard` | 200 |  |
| `/api/auth/login` | 503 |  |
| `/api/health-isf/drivers/mobile-login` | 503 |  |

## Required Render actions

- Open Render dashboard → PostgreSQL and confirm the database instance is Available (not suspended).
- Copy the Postgres Internal Connection String from the database service page.
- Open the web service amicor-health-isf-py → Environment → set DATABASE_URL to that internal connection string.
- Remove any external/public Postgres URL; Render web services must use the internal hostname.
- Redeploy the web service after saving DATABASE_URL.
- In Render Shell (web service): cd backend && alembic upgrade heads
- Verify GET /api/health/readiness returns 200 and database.connected=true.
- Verify POST /api/auth/login returns 401 (not 503) for invalid credentials.
- Verify POST /api/health-isf/drivers/mobile-login returns 200 for phone 917-555-1004.

Evidence: `PRODUCTION_DB_CONNECTIVITY_20260727021839.json`
