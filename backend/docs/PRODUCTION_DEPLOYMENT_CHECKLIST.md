# Amicor Health ISF — Production Deployment Checklist

**Status:** Platform passed production stabilization (score 96/100).  
**Use this checklist for Render production promotion.**  
**Do not commit secrets.** Store values in Render Environment or your secret manager.

**Related docs:** `STAGING_PRODUCTION_ENV_CHECKLIST.md`, `DEPLOYMENT.md`, `render.yaml`, `artifacts/final_production_readiness_report.json`

---

## 1. Required Render environment variables

Set these on the **Render Web Service** (`amicor-health-isf`, rootDir: `backend`).

### Required for production readiness (`/api/health/readiness` → HTTP 200, `overall_status: ready`)

| Variable | Required | Example (placeholder only) | Notes |
|----------|----------|----------------------------|-------|
| `DATABASE_URL` | **Yes** | `postgresql://user:***@host:5432/amicor` | PostgreSQL only in production (SQLite blocked by readiness) |
| `SECRET_KEY` | **Yes** | `openssl rand -hex 32` | App signing material; must not be `changeme`, `dev`, etc. |
| `JWT_SECRET` | **Yes** | `openssl rand -hex 32` | Distinct from `SECRET_KEY`; signs access tokens |
| `ALLOWED_ORIGINS` | **Yes** | `https://amicor-health-isf-py.onrender.com` | Comma-separated; **no wildcard `*`** |
| `AMICOR_PUBLIC_URL` | **Yes** | `https://amicor-health-isf-py.onrender.com` | HTTPS, no trailing slash; rider links + runtime topology |
| `APP_VERSION` | **Yes** | `2026.06.29-production.1` | Release ID surfaced in health checks |

### Required in `render.yaml` (verify or override in dashboard)

| Variable | Purpose |
|----------|---------|
| `AMICOR_ENVIRONMENT` | Set to `production` |
| `DB_POOL_SIZE` | Default `10` — increase under heavy concurrent polling |
| `DB_MAX_OVERFLOW` | Default `20` — burst capacity for parallel panel refresh |

### Strongly recommended (non-blocking warnings if unset)

| Variable | Default | Purpose |
|----------|---------|---------|
| `AMICOR_SEED_PASSWORD` | `Amicor123!` (dev) | Password for seeded pilot accounts; **rotate in production** |
| `HEALTH_ISF_WS_MAX_ORG_CONNECTIONS` | `500` | WebSocket connection cap per organization |
| `HEALTH_ISF_WS_MAX_USER_CONNECTIONS` | `5` | WebSocket connection cap per user |
| `LOG_LEVEL` | `INFO` | Use `INFO`, `WARNING`, or `ERROR` in production |
| `SENTRY_DSN` | — | Error monitoring |

### Optional integrations (enable when going live with billing/comms)

| Variable | When needed |
|----------|-------------|
| `HEALTH_ISF_STRIPE_ENABLED` | Set `1` to enable Stripe billing |
| `STRIPE_SECRET_KEY` | Required if Stripe enabled |
| `TWILIO_ACCOUNT_SID` | Real SMS delivery |
| `TWILIO_AUTH_TOKEN` | Real SMS delivery |
| `TWILIO_FROM_NUMBER` | Real SMS delivery |

### Render-managed (usually auto-set)

| Variable | Notes |
|----------|-------|
| `PORT` | Injected by Render; used by `uvicorn ... --port $PORT` |
| `RENDER_EXTERNAL_URL` | Fallback for public URL resolution if `AMICOR_PUBLIC_URL` unset |

---

## 2. Required OpenAI environment variables

OpenAI is **optional for core dispatch** but **required for AI Assistant, chat routing, OCR, and TTS**.

| Variable | Required for AI | Default / notes |
|----------|-----------------|-----------------|
| `OPENAI_API_KEY` | **Yes** | Secret; never log or commit |
| `OPENAI_TTS_MODEL` | No | Default `gpt-4o-mini-tts` |
| `OPENAI_TTS_VOICE` | No | Default `nova` |
| `OPENAI_TTS_SPEED` | No | Default `0.97` |
| `OPENAI_TTS_VOICE_FALLBACKS` | No | Default `nova,shimmer,alloy` |
| `OPENAI_TTS_INSTRUCTIONS` | No | Optional instructions for gpt-4o TTS models |
| `OPENAI_TTS_TIMEOUT_SECONDS` | No | Default `15` |

**Behavior without `OPENAI_API_KEY`:**

- Dispatch, driver workflow, billing, and compliance continue to operate.
- AI Assistant, Nova chat routing, image OCR, and voice TTS degrade or fail gracefully.
- Readiness probe reports `has_openai_api_key: false` but does **not** block production readiness.

**Pre-deploy OpenAI check:**

```powershell
# Presence only — do not echo the key
if ($env:OPENAI_API_KEY) { "OPENAI_API_KEY is set" } else { "OPENAI_API_KEY missing — AI features degraded" }
```

---

## 3. Database requirements

### Engine and connectivity

- [ ] **PostgreSQL 14+** provisioned (Render PostgreSQL or managed instance)
- [ ] `DATABASE_URL` uses `postgresql://` (not SQLite)
- [ ] Connection pool sized for concurrent Health ISF panel polling:
  - [ ] `DB_POOL_SIZE=10` (minimum for production)
  - [ ] `DB_MAX_OVERFLOW=20`
- [ ] Readiness check passes DB connectivity: `GET /api/health/readiness` → `"database": { "connected": true }`

### Schema and migrations

- [ ] Database backup/snapshot taken before schema changes
- [ ] Migrations applied (if using Alembic in your release process):

```powershell
cd backend
$env:DATABASE_URL = "<postgresql-url>"
alembic upgrade head
```

- [ ] Core Health ISF tables present (rides, drivers, providers, dispatch assignments, payouts, audit logs)
- [ ] Application startup completes without DB init errors

### Production data policy

- [ ] Seed/demo data policy decided (pilot vs. clean production)
- [ ] `AMICOR_SEED_PASSWORD` rotated from dev default if seed accounts remain enabled
- [ ] No secrets stored in database JSON fields or commit history

### Optional demo seed (pilot only)

After deploy, admin may call:

```http
POST /api/health-isf/ops/seed-production-demo
Authorization: Bearer <admin_token>
```

Use `?force=true` only when intentionally re-seeding a non-production pilot environment.

---

## 4. Redis / WebSocket requirements

### WebSocket (live dispatch updates) — **required for real-time ops**

WebSocket runs **in-process** on the same Render web service. **No separate Redis broker is required for WebSocket fan-out.**

| Item | Value |
|------|-------|
| Endpoint pattern | `wss://{AMICOR_PUBLIC_URL}/api/health-isf/ws/live/{organization_id}/{user_id}` |
| Query params | `role`, `token` (JWT), optional `last_sequence`, `restore_subscriptions` |
| Health check path | `/api/health` (HTTP only — not WebSocket) |
| Connection limits | `HEALTH_ISF_WS_MAX_ORG_CONNECTIONS` (default 500), `HEALTH_ISF_WS_MAX_USER_CONNECTIONS` (default 5) |

**Render notes:**

- [ ] Single web service instance supports WebSocket on the same `$PORT`
- [ ] `AMICOR_PUBLIC_URL` matches the browser origin (HTTPS → WSS)
- [ ] No localhost URLs leak in `/api/runtime/topology` on production
- [ ] Browser console shows **no** `WebSocket handshake: Unexpected response code: 500` after login

**WebSocket verification:**

```powershell
# After login, confirm topology
curl https://<your-service>/api/runtime/topology

# Expected websocket_url:
# wss://<your-service>/api/health-isf/ws/live
```

Run automated smoke:

```powershell
cd backend
$env:PYTHONPATH = "."
$env:AMICOR_BROWSER_BASE = "https://<your-service>"
python scripts/render_production_smoke.py
# Expected: verdict "GO", checks_passed 13/13, blocking_console empty
```

### Redis (AI Assistant) — **optional but recommended**

Redis is used for **AI Assistant confirmation token replay protection** and preview caching (`ASSISTANT_REDIS_URL`). It is **not** the WebSocket transport.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ASSISTANT_REDIS_URL` | `redis://127.0.0.1:6379/0` | Assistant confirmation/preview store |
| `ASSISTANT_REDIS_PREFIX` | `amicor:assistant:phase14` | Key namespace |
| `REDIS_URL` | — | Optional; tracked in runtime config validation |

**Without Redis:**

- Assistant may operate in fail-closed mode for distributed replay protection.
- Core dispatch workflow is unaffected.

**If enabling Redis on Render:**

- [ ] Provision Render Redis (or external Redis)
- [ ] Set `ASSISTANT_REDIS_URL=redis://...` on the web service
- [ ] Verify assistant confirmation flow in post-deploy AI checklist (Section 7)

---

## 5. Deployment order

Execute in this sequence to avoid partial outages and false readiness.

### Phase A — Infrastructure (before code deploy)

1. [ ] Create or verify **PostgreSQL** database
2. [ ] (Optional) Create **Redis** for AI Assistant
3. [ ] Generate secrets: `SECRET_KEY`, `JWT_SECRET` (unique values)
4. [ ] Configure **Render Web Service** from `render.yaml` (rootDir: `backend`)

### Phase B — Environment configuration

5. [ ] Set all **required Render env vars** (Section 1)
6. [ ] Set **OpenAI env vars** if AI Assistant is in scope (Section 2)
7. [ ] Set `ALLOWED_ORIGINS` to exact production origin(s)
8. [ ] Set `AMICOR_PUBLIC_URL` to final HTTPS service URL
9. [ ] Set `APP_VERSION` to this release tag
10. [ ] Rotate `AMICOR_SEED_PASSWORD` if pilot seed accounts are used

### Phase C — Database

11. [ ] Run database migrations (`alembic upgrade head`) if applicable
12. [ ] Confirm DB connectivity from Render shell or local psql

### Phase D — Application deploy

13. [ ] Deploy web service (`git push` → Render auto-deploy, or manual deploy)
14. [ ] Wait for health check: `GET /api/health` → 200
15. [ ] Confirm readiness: `GET /api/health/readiness` → 200, `overall_status: ready`
16. [ ] Confirm topology: `GET /api/runtime/topology` → no `127.0.0.1` / `localhost` backend URL

### Phase E — Post-deploy verification

17. [ ] Run **Post-deployment verification checklist** (Section 6)
18. [ ] Run **AI Assistant verification** (Section 7) if OpenAI enabled
19. [ ] Run **Operations verification** (Section 8)
20. [ ] Complete **Provider onboarding** (Section 9) and **Dispatcher onboarding** (Section 10)
21. [ ] Sign off release in change log / runbook

---

## 6. Post-deployment verification checklist

### Automated gates (run from `backend/`)

```powershell
$env:PYTHONPATH = "."
$env:AMICOR_BROWSER_BASE = "https://<your-production-url>"

# 1. Render smoke (13 checks incl. WebSocket console)
python scripts/render_production_smoke.py

# 2. Full 9-app browser audit
python scripts/browser_health_isf_readiness_audit.py

# 3. Deployment-critical pytest (against local or CI — not production DB)
python -m pytest tests/test_deployment_readiness_ride_lifecycle.py `
  tests/test_driver_dispatch_lifecycle.py `
  tests/test_deployment_readiness.py `
  tests/test_health_isf_live_flow.py::TestRealtimeWebSocketFlow -q
```

**Expected results:**

| Check | Expected |
|-------|----------|
| Render smoke `verdict` | `GO` |
| Render smoke `checks_passed` | `13/13` |
| 9-app audit `all_pass` | `true` |
| Deployment-critical pytest | All pass |

### Manual HTTP probes

- [ ] `GET /api/health/live` → 200
- [ ] `GET /api/health/readiness` → 200, `overall_status: ready`, `blocked_reasons: []`
- [ ] `GET /api/runtime/topology` → `backend_url` and `websocket_url` use production HTTPS/WSS
- [ ] `GET /app` → 200, canonical production URL in shell bootstrap
- [ ] `POST /api/auth/login` → 200 for dispatcher, admin, rider

### Authenticated API probes (dispatcher token)

- [ ] `GET /api/health-isf/dashboard` → 200
- [ ] `GET /api/health-isf/rides` → 200
- [ ] `GET /api/health-isf/drivers` → 200
- [ ] `GET /api/health-isf/providers` → 200
- [ ] `GET /api/health-isf/dispatch/queue` → 200
- [ ] `GET /api/health-isf/activity-feed` → 200

### UI panel hydration (admin browser session)

- [ ] Dashboard — KPI cards loaded (not stuck on “loading dashboard”)
- [ ] Dispatch — worklist hydrated
- [ ] Drivers — roster loaded
- [ ] Providers — roster loaded
- [ ] Customer — request history loaded
- [ ] Billing — KPIs loaded
- [ ] Admin — summary loaded
- [ ] Analytics / Grant tabs loaded

### Revenue-critical workflow (end-to-end)

- [ ] Rider submits request → appears in dispatcher queue
- [ ] AI recommendation generated → dispatcher approves
- [ ] Driver assigned → driver accepts → route progresses to **completed**
- [ ] Billing payout row created for completed trip
- [ ] Compliance audit log entries present for ride lifecycle

### Console and network hygiene

- [ ] No blocking 401/403/500 on `/api/` calls after login
- [ ] No WebSocket handshake 500 in browser console
- [ ] No requests to `127.0.0.1` or `localhost` from production origin

---

## 7. AI Assistant verification checklist

Run after `OPENAI_API_KEY` is set.

### Configuration

- [ ] `OPENAI_API_KEY` present in Render (secret, not logged)
- [ ] (Recommended) `ASSISTANT_REDIS_URL` points to reachable Redis
- [ ] Readiness / runtime config shows `has_openai_api_key: true`

### API verification (admin or dispatcher session)

- [ ] `GET /api/health-isf/ai/intelligence/summary` → 200
- [ ] `GET /api/health-isf/ai/intelligence/anomalies` → 200
- [ ] `GET /api/health-isf/dispatch/recommendations` → 200 (may return empty queue)
- [ ] AI dispatch snapshot / advisory endpoints respond without 500

### UI verification (`/#/health-isf/analytics` or advisory panels)

- [ ] Operational alerts feed hydrates (not stuck on “waiting for analytics”)
- [ ] Dispatch intelligence queue shows queue depth / awaiting approval counts
- [ ] AI recommendation appears on new ride intake (dispatcher dispatch tab)
- [ ] Approve recommendation issues driver offer (assignment state → `offered`)

### Assistant execution (if Nova / assistant workspace enabled)

- [ ] Assistant preview generates without timeout
- [ ] Confirmation token flow works (with Redis: replay protection active)
- [ ] No repeated 500 errors in assistant execution routes

### 9-app audit cross-check

- [ ] `AI Assistant/Advisory` → **PASS** in `health_isf_readiness_audit_report.json`

---

## 8. Operations verification checklist

For platform / ops admin sign-off after deploy.

### Runtime health

- [ ] `GET /api/health/readiness` → score ≥ 95, no `blocked_reasons`
- [ ] `GET /api/health-isf/operations/runtime-state` → compliance module reachable
- [ ] `GET /api/health-isf/operations/timeline?limit=40` → 200
- [ ] `GET /api/health-isf/operations/lifecycle-matrix` → 200

### Admin command center

- [ ] Admin dashboard API → 200
- [ ] Admin summary panel hydrated (`#health-admin-summary`)
- [ ] Dispatch queue depth reflects live data
- [ ] Billing KPIs show completed-ride revenue
- [ ] Grant metrics panel loads

### Compliance and audit

- [ ] `GET /api/health-isf/dispatcher/audit-log?limit=40` → 200
- [ ] Lifecycle events recorded for test ride (create → assign → complete)
- [ ] `Compliance/Audit` → **PASS** in 9-app audit

### Monitoring and logging

- [ ] `LOG_LEVEL=INFO` (not DEBUG) in production
- [ ] (Optional) Sentry receiving events — test a controlled error in staging first
- [ ] Supervision logs rotating (`SUPERVISION_LOG_RETENTION_DAYS`, default 5)

### Seed accounts (pilot operations)

Default seed emails (password = `AMICOR_SEED_PASSWORD`):

| Role | Email |
|------|-------|
| Admin | `admin@amicor.local` |
| Dispatcher | `dispatcher@amicor.local` |
| Driver | `driver@amicor.local` |
| Rider | `rider@amicor.local` |
| Provider | `provider@amicor.local` |
| Compliance | `compliance@amicor.local` |

- [ ] All role logins succeed
- [ ] Password rotated from dev default in production

---

## 9. Provider onboarding checklist

For each network partner joining live operations.

### Account and access

- [ ] Provider user account created (or seed `provider@amicor.local` replaced with real account)
- [ ] Role = provider; organization scoped correctly
- [ ] Provider can log in at `/#/health-isf/providers` or assigned surface

### Provider record setup

- [ ] Provider record created in Health ISF (`/api/health-isf/providers`)
- [ ] `is_active=true`, valid phone and address
- [ ] Service type / clinic metadata accurate
- [ ] Provider appears in dispatcher provider roster

### Operational readiness

- [ ] Provider queue shows incoming ride volume
- [ ] Completed rides visible in provider metrics
- [ ] Provider panel hydrates without stuck “loading providers” state
- [ ] 9-app audit: **Provider** → **PASS**

### Go-live sign-off

- [ ] Provider contact confirmed for escalation path
- [ ] Test ride completed with provider_id attached end-to-end
- [ ] Billing/revenue attribution correct for provider-linked trips

---

## 10. Dispatcher onboarding checklist

For each dispatch operator before taking live queue ownership.

### Account and access

- [ ] Dispatcher account created (replace seed `dispatcher@amicor.local` for production)
- [ ] Login at `/#/health-isf/dispatch` or ops shell dispatch route
- [ ] WebSocket connects after login (no console handshake errors)
- [ ] Live operational feed updates without manual refresh loop

### Queue and assignment workflow training

- [ ] Create ride from dispatch form → ride appears in pending queue
- [ ] AI recommendation visible (`awaiting_approval` → approve)
- [ ] Active assignments panel shows offered driver for **this ride**
- [ ] Manual assign / reassign API available as fallback
- [ ] Escalation workflow tested (`/api/health-isf/workflows/escalate`)

### Post-completion operations

- [ ] Completed ride visible on rides board with correct status
- [ ] Dashboard metrics update (`completed_rides` counter)
- [ ] Activity feed shows dispatch events for test ride
- [ ] Cancel/reassign correctly blocked or allowed on terminal rides

### Verification sign-off

- [ ] 9-app audit: **Dispatcher** → **PASS**
- [ ] Dispatcher completes supervised test ride with driver James Smith (or production driver)
- [ ] Dispatcher acknowledges escalation and compliance audit log locations

---

## Quick reference — production URLs

| Surface | URL |
|---------|-----|
| Public app shell | `{AMICOR_PUBLIC_URL}/app` |
| Health ISF workspace | `{AMICOR_PUBLIC_URL}/#/health-isf/dashboard` |
| API health | `{AMICOR_PUBLIC_URL}/api/health` |
| Readiness | `{AMICOR_PUBLIC_URL}/api/health/readiness` |
| WebSocket base | `wss://<host>/api/health-isf/ws/live` |
| OpenAPI docs | `{AMICOR_PUBLIC_URL}/docs` |

---

## Release sign-off

| Gate | Owner | Date | Pass |
|------|-------|------|------|
| Render env vars configured | | | ☐ |
| PostgreSQL + migrations | | | ☐ |
| WebSocket smoke GO | | | ☐ |
| 9-app audit all PASS | | | ☐ |
| Revenue workflow verified | | | ☐ |
| AI Assistant verified (if in scope) | | | ☐ |
| Provider onboarded | | | ☐ |
| Dispatcher onboarded | | | ☐ |
| **Production promoted** | | | ☐ |

**Evidence bundle for audit trail:**

- `backend/artifacts/final_production_readiness_report.json`
- `backend/artifacts/render_production_smoke_report.json`
- `backend/artifacts/health_isf_readiness_audit_report.json`
