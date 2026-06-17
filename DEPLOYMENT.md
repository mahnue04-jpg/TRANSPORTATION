# Amicor Nova — Production Deployment Guide

This guide deploys the **Python FastAPI** platform (port 8010) with PostgreSQL, real-time Socket.IO/WebSocket updates, Stripe payments, and Twilio SMS.

## Prerequisites

- PostgreSQL 14+ database
- Render.com account (or any container host)
- Stripe account (live or test keys)
- Twilio account (optional; simulated SMS works without it)

## 1. Environment variables

Copy `.env.template` to `.env` and set:

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Yes (prod) | `postgresql://user:pass@host:5432/amicor` |
| `SECRET_KEY` | Yes | JWT signing (32+ byte random) |
| `JWT_SECRET` | Yes | Runtime auth validation |
| `ALLOWED_ORIGINS` | Yes (prod) | Comma-separated frontend URLs |
| `AMICOR_PUBLIC_URL` | Yes | Public URL for rider tracking links |
| `HEALTH_ISF_STRIPE_ENABLED` | Recommended | Set `1` to enable Stripe |
| `STRIPE_SECRET_KEY` | If Stripe | Stripe secret key |
| `TWILIO_*` | Optional | Real SMS delivery |
| `DB_POOL_SIZE` | Recommended | Default `10` |
| `SENTRY_DSN` | Optional | Error monitoring |

## 2. Local production smoke test

```powershell
cd backend
pip install -r requirements.txt
$env:DATABASE_URL="postgresql://..."
$env:SECRET_KEY="your-secret"
$env:JWT_SECRET="your-jwt-secret"
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

Health check: `GET http://127.0.0.1:8010/api/health`

## 3. Deploy to Render.com

1. Connect this repository to Render.
2. Use the included `render.yaml` blueprint or create a **Web Service**:
   - **Root directory:** `backend`
   - **Build:** `pip install -r requirements.txt`
   - **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Health check path:** `/api/health`
3. Add a **PostgreSQL** database and set `DATABASE_URL` on the web service.
4. Set `AMICOR_PUBLIC_URL` to your Render service URL.
5. Deploy.

## 4. Seed demo / pilot data

After first deploy, log in as admin and call:

```http
POST /api/health-isf/ops/seed-production-demo
Authorization: Bearer <admin_token>
```

This creates **50+ drivers**, **100+ patients**, and **200+ trips** for live demos.

Force re-seed:

```http
POST /api/health-isf/ops/seed-production-demo?force=true
```

## 5. Test accounts (development seed)

| Role | Email | Password |
|------|-------|----------|
| Admin | `admin@amicor.local` | `Amicor123!` |
| Dispatcher | `dispatcher@amicor.local` | `Amicor123!` |
| Driver | `driver@amicor.local` | `Amicor123!` |

## 6. Application URLs

| Surface | URL |
|---------|-----|
| Ops shell (dispatch, driver mobile) | `{AMICOR_PUBLIC_URL}/app/dispatch` |
| Health ISF workspace | `{AMICOR_PUBLIC_URL}/#/health-isf/dispatch` |
| API docs (OpenAPI) | `{AMICOR_PUBLIC_URL}/docs` |

## 7. Post-deploy checklist

- [ ] `/api/health` returns 200
- [ ] Login works for dispatcher and driver roles
- [ ] Driver mobile: Accept → Arrive → Onboard → Start Transport → Complete (no UI flicker)
- [ ] Rider booking: `/app/riders` submits to `/api/health-isf/customer-requests`
- [ ] Billing tab loads live revenue from `/api/health-isf/operations/revenue-workflow`
- [ ] Stripe payment intent created on trip complete (when enabled)
- [ ] SMS confirmation on rider booking (Twilio or simulated log)

## 8. Troubleshooting

**Blinking UI:** Hard refresh (`Ctrl+Shift+R`). Use `127.0.0.1` consistently (not mixed with `localhost`).

**Database pool exhaustion:** Increase `DB_POOL_SIZE` and `DB_MAX_OVERFLOW`.

**CORS errors:** Set `ALLOWED_ORIGINS` to your exact frontend origin.

**SMS not sending:** Without Twilio, messages are logged to `health_isf_dispatch_logs` with action `notification_sms`.
