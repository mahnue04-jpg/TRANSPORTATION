# Amicor Dual Deployment Runbook

Deploy **both** production surfaces from this repo:

| Service | Folder | Role | Primary URL path |
|---------|--------|------|------------------|
| **nova-stable** | `nova-stable/` | Stable dispatch pilot (SQLite, HTTP polling) | `/dispatcher` |
| **Python backend** | `backend/` | Full Nova ops platform (Postgres) | `/app/dashboard` |

**Operator rule:** Full enterprise sidebar (Billing, Reports, AI, etc.) → Python **`/app/dashboard`**. Stable dispatch-only UI → **nova-stable** **`/dispatcher`**. Do **not** use Python **`/dispatcher`** for Nova ops — that route serves Health ISF (`health-isf.js`), not `ops-shell.js`.

---

## Render layout (recommended)

```
GitHub: Amicore_Rebuild
├── Web Service: amicor-nova-stable     rootDir=nova-stable
├── Web Service: amicor-health-isf      rootDir=backend
└── PostgreSQL: amicor-prod             → DATABASE_URL (Python service only)
```

Optional custom domains:

- `dispatch.yourdomain.com` → nova-stable
- `ops.yourdomain.com` → Python backend → `/app/dashboard`

---

## Track A — nova-stable (pilot dispatch)

### Git push

```powershell
cd "C:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild"
git add nova-stable DEPLOY_BOTH.md
git commit -m "Add dual-deploy runbook and nova-stable pilot stack"
git push origin HEAD
```

Use the GitHub account that owns the remote (prior 403 errors were from the wrong user).

### Render Web Service settings

| Setting | Value |
|---------|--------|
| Runtime | Node |
| Root directory | `nova-stable` |
| Build command | `npm install` |
| Start command | `npm start` |
| Health check path | `/api/health` |
| Plan | Free = demo only; **Starter + Persistent Disk** for data that survives redeploys |

Or deploy via Blueprint: `nova-stable/render.yaml`.

### Render environment variables (paste block)

Copy into **Render → amicor-nova-stable → Environment**:

```env
NODE_ENV=production
JWT_SECRET=<generate in Render: "Generate" button>
SQLITE_PATH=/var/data/amicor_nova.db
```

**Persistent disk (required for live ops):**

1. Render → Service → **Disks** → Add disk, mount path `/var/data`, size 1 GB+
2. Ensure `SQLITE_PATH=/var/data/amicor_nova.db` matches the mount

`PORT` is set automatically by Render — do not override.

### Local pre-flight

```powershell
cd nova-stable
npm install
$env:JWT_SECRET="local-preflight-secret"
$env:PORT="8011"
npm start
```

In another terminal:

```powershell
curl http://127.0.0.1:8011/api/health
```

Expected:

```json
{ "ok": true, "database": "sqlite", "service": "amicor-nova-stable" }
```

### Post-deploy smoke test

Replace `BASE` with your Render URL (e.g. `https://amicor-nova-stable.onrender.com`).

| Step | URL | Pass |
|------|-----|------|
| Health | `GET BASE/api/health` | `ok: true` |
| Hub | `BASE/` | Login works |
| Dispatch | `BASE/dispatcher` | Map + trips, ~30s refresh, no flicker storm |
| Driver | `BASE/driver` | Trip workflow |
| Rider | `BASE/rider` | Book + track |
| Provider | `BASE/provider` | Bulk list loads |

Demo logins (rotate before external users):

| Email | Password | Role |
|-------|----------|------|
| `dispatcher@amicor.local` | `Amicor123!` | dispatcher |
| `admin@amicor.com` | `admin123` | admin |
| `driver@amicor.local` | `Amicor123!` | driver |

### Before external users

- [ ] `JWT_SECRET` set in Render (never rely on code fallback)
- [ ] Persistent disk attached if trips must survive redeploys
- [ ] Demo passwords rotated or seed disabled
- [ ] Custom domain + HTTPS if applicable

---

## Track B — Python backend (full ops platform)

### Render Web Service settings

| Setting | Value |
|---------|--------|
| Runtime | Python 3 |
| Root directory | `backend` |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/api/health` |

Or deploy via root `render.yaml`.

### PostgreSQL

Create **Render PostgreSQL**, copy the **Internal Database URL**, set as `DATABASE_URL` on the Python service.

### Render environment variables (paste block)

Copy into **Render → amicor-health-isf → Environment**. Replace placeholders.

Generate secrets locally:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Run twice — one value for `SECRET_KEY`, one for `JWT_SECRET`.

```env
# ── Required ─────────────────────────────────────────────────────────────
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/amicor
SECRET_KEY=<64-char-hex-from-secrets.token_hex(32)>
JWT_SECRET=<64-char-hex-different-from-SECRET_KEY>
ALLOWED_ORIGINS=https://YOUR-PYTHON-APP.onrender.com
AMICOR_PUBLIC_URL=https://YOUR-PYTHON-APP.onrender.com
AMICOR_SEED_PASSWORD=<strong-password-not-Amicor123!>
APP_VERSION=1.0.0-pilot
LOG_LEVEL=INFO

# ── Connection pool (defaults in render.yaml) ─────────────────────────────
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# ── Optional — enable when needed ────────────────────────────────────────
OPENAI_API_KEY=
HEALTH_ISF_STRIPE_ENABLED=0
STRIPE_SECRET_KEY=
STRIPE_PUBLISHABLE_KEY=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
SENTRY_DSN=
```

Replace `YOUR-PYTHON-APP.onrender.com` with the actual Render hostname (no trailing slash).

### Local pre-flight

```powershell
cd "C:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild"
.\.venv\Scripts\Activate.ps1
cd backend
# Ensure .env or env vars include SECRET_KEY, JWT_SECRET, DATABASE_URL (or SQLite for local)
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Verify:

```powershell
curl http://127.0.0.1:8010/api/health
curl http://127.0.0.1:8010/api/health/readiness
```

Readiness targets:

| `overall_status` | Meaning |
|----------------|---------|
| `ready` | Production criteria met |
| `staging_only` | Deploy OK; fix config warnings before public launch |
| `not_ready` | Missing `DATABASE_URL`, `SECRET_KEY`, or `JWT_SECRET` |

Open **`http://127.0.0.1:8010/app/dashboard`** (not `/dispatcher`).

Flicker validation: stay on Dispatch 2+ minutes — no constant full-page flash; “Last updated” pill updates ~every 30s.

### Post-deploy smoke test

Replace `OPS` with Python Render URL.

| Step | URL | Pass |
|------|-----|------|
| Liveness | `GET OPS/api/health` | 200 |
| Readiness | `GET OPS/api/health/readiness` | `overall_status` ≠ `not_ready` |
| Ops shell | `OPS/app/dashboard` | Nova sidebar loads |
| Dispatch | `OPS/app/dispatch` or sidebar Dispatch | Trips + assign flow |
| Create flows | Riders, Drivers, Providers, Trips | CRUD works |
| Session | Refresh page | Still logged in |

### Production hardening

- [ ] Postgres (not SQLite) in `DATABASE_URL`
- [ ] `ALLOWED_ORIGINS` locked to your domain(s) — no `*`
- [ ] `AMICOR_SEED_PASSWORD` changed from defaults
- [ ] `DEBUG` unset or `false`
- [ ] Database migrations applied if required by your pipeline
- [ ] Revenue E2E complete per `DEPLOYMENT_LOCK.md` before billing go-live

---

## Readiness matrix

| Milestone | nova-stable | Python 8010 |
|-----------|-------------|-------------|
| Demo / internal pilot | Git push + JWT + `/api/health` | Postgres + 3 secrets + `/app/*` smoke |
| Persistent live ops | Persistent disk + password rotation | Postgres + CORS + readiness `ready` |
| Revenue / billing live | Out of scope | Stripe + Phase 4 E2E gates |

---

## Suggested rollout order

1. **Day 1:** Push repo → deploy nova-stable → pilot dispatch with 2–3 users
2. **Day 1–2:** Provision Postgres → deploy Python backend → validate `/app/dashboard`
3. **Day 3:** Document URLs for team; rotate demo passwords
4. **Day 4+:** Stripe/Twilio, nova-stable persistent disk, load-test Python ops refresh

---

## Troubleshooting

| Issue | Likely cause | Fix |
|-------|--------------|-----|
| UI flickers on Python | On `/dispatcher` (Health ISF) | Use `/app/dashboard` or nova-stable |
| Data lost after Render redeploy (nova-stable) | Ephemeral disk | Add persistent disk + `SQLITE_PATH` |
| Readiness `not_ready` | Missing env vars | Set `DATABASE_URL`, `SECRET_KEY`, `JWT_SECRET` |
| Git push 403 | Wrong GitHub account | Push as repo owner or fix remote credentials |
| CORS errors in browser | `ALLOWED_ORIGINS` mismatch | Set exact public URL including `https://` |

---

## Related files

- `nova-stable/render.yaml` — nova-stable Blueprint
- `nova-stable/README.md` — nova-stable quick start
- `render.yaml` — Python backend Blueprint
- `.env.template` — full local env reference
- `backend/app/deployment/readiness.py` — readiness scoring logic
- `DEPLOYMENT_LOCK.md` — phased go-live gates

---

## Local pre-flight results (2026-06-17)

Run from this machine against locally running services.

### nova-stable

| Check | Result |
|-------|--------|
| `npm install` | Pass |
| `GET /api/health` on **:8012** (fresh `node server.js`) | **Pass** — `service: amicor-nova-stable`, `database: sqlite` |
| Port **:8011** | **Not nova-stable** — returns Python-style `{ok,data,meta}` envelope; use `:8012` or stop conflicting process before local test |

To re-run nova-stable pre-flight on a free port:

```powershell
cd nova-stable
$env:JWT_SECRET="local-preflight-secret"
$env:PORT="8012"
npm start
# other terminal:
curl http://127.0.0.1:8012/api/health
```

### Python backend (`:8010`)

| Check | Result |
|-------|--------|
| `GET /api/health` | **Pass** — 200 |
| `GET /api/health/readiness` | **503 / not_ready** — missing `DATABASE_URL` locally |
| `GET /app/dashboard` | **Pass** — ops-shell HTML served |
| `SECRET_KEY` / `JWT_SECRET` | Present locally |
| Blockers before Render | Set `DATABASE_URL` (Postgres), `ALLOWED_ORIGINS`, `APP_VERSION`, `AMICOR_SEED_PASSWORD` |

Readiness response summary (local):

- `overall_status`: `not_ready`
- `score`: 25
- Critical: `Missing required env var: DATABASE_URL`
- Config: `APP_VERSION` placeholder, `production_database` not configured

After Render Postgres is wired, re-check:

```powershell
curl https://YOUR-PYTHON-APP.onrender.com/api/health/readiness
```

Target: `overall_status` = `ready` or `staging_only` (not `not_ready`).

### Deploy gate summary

| Stack | Local pre-flight | Ready to deploy? |
|-------|------------------|-------------------|
| **nova-stable** | Health OK on dedicated port | **Yes** — pilot deploy after Git push + Render env |
| **Python 8010** | App runs; readiness blocked without Postgres | **Yes for staging** — set Render env block below first |

### Quick local verification (after starting servers)

```powershell
.\scripts\start_both_local.ps1
.\scripts\preflight_deploy.ps1
```

Target: all checks **PASS**. Python readiness may show `not_ready` locally until `DATABASE_URL` is set — that is expected; on Render with Postgres it should reach `staging_only` or `ready`.

### Render deploy order (required — not automatic)

1. Push latest branch to GitHub
2. Deploy **nova-stable** Web Service (`rootDir: nova-stable`, health `/api/health`)
3. Create **Render PostgreSQL** → set `DATABASE_URL` on Python service
4. Deploy **Python backend** (`rootDir: backend`, health `/api/health`)
5. Set env vars from blocks above; re-check `GET /api/health/readiness` on live URL
6. Smoke test live URLs (drivers workflow, dispatch create/assign)

**Code is deploy-ready; Render services must still be created manually.**
