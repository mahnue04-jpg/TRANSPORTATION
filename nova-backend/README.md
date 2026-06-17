# Amicor Nova Backend (Express · Port 8011)

Node.js API + PostgreSQL + Socket.IO + Stripe for health transportation dispatch.

## Quick start (your 10-step checklist)

| Step | Command |
|------|---------|
| 1 | `npm install` |
| 2 | `npm run setup` |
| 3 | `npm start` |
| 4 | Open **http://localhost:8011** |
| 5 | Login: `dispatcher@amicor.local` / `Amicor123!` |

### Prerequisites

**Option A — Docker (recommended on Windows)**

```powershell
cd nova-backend
docker compose up --build
```

Uses PostgreSQL on host port **5433** and API on **8011**.

**Option B — Local PostgreSQL**

1. Install PostgreSQL and create database `amicor_nova`
2. Copy `.env.example` → `.env` and set `DATABASE_URL`
3. Run setup + start:

```powershell
cd nova-backend
copy .env.example .env
npm install
npm run setup
npm start
```

## Demo accounts

| Email | Password | Role |
|-------|----------|------|
| admin@amicor.local | Amicor123! | admin |
| dispatcher@amicor.local | Amicor123! | dispatcher |
| driver@amicor.local | Amicor123! | driver |

## API endpoints

- `GET /api/health` — health check
- `POST /api/auth/login` — JWT login
- `GET /api/trips` — list trips
- `PUT /api/trips/:id/assign` — assign driver
- `PUT /api/trips/:id/complete` — complete + fare
- `POST /api/create-payment-intent` — Stripe/simulated payment
- `GET /api/revenue` — revenue summary

See root `API_REFERENCE.md` for the full Python platform; this service uses `/api/trips`, `/api/drivers`, etc.

## Live operations (production)

### Local live stack

```powershell
cd nova-backend
npm run postgres:docker   # or use local PostgreSQL
npm run setup             # schema + demo drivers/patients/trips
npm start                 # http://localhost:8011
```

### Operational URLs

| Surface | URL |
|---------|-----|
| Hub / login | http://localhost:8011 |
| Dispatch Command Center | http://localhost:8011/dispatcher |
| Driver PWA | http://localhost:8011/driver |
| Rider booking | http://localhost:8011/rider |
| Provider portal | http://localhost:8011/provider |

### Readiness checks

- `GET /api/health` — process + database up
- `GET /api/ops/readiness` — active trips, pending dispatch, available drivers

### Deploy to Render (live PostgreSQL)

1. Push `nova-backend/` to GitHub (repo must contain this folder).
2. **New → Blueprint** → use `nova-backend/render.yaml`.
3. Service **`amicor-nova-live`** uses Render PostgreSQL + `npm start`.
4. Set `AMICOR_PUBLIC_URL` to your Render URL after first deploy.
5. Login: `dispatcher@amicor.local` / `Amicor123!`

**Quick demo (no Postgres):** deploy **`amicor-nova-stable`** with `npm run start:stable` (SQLite).

## Deploy to Render (legacy single service)

## Stripe (step 8–9)

Set real keys in `.env`:

```
STRIPE_SECRET_KEY=sk_live_...
HEALTH_ISF_STRIPE_ENABLED=1
```

Payment intents are created on trip complete from the web UI.

## Note: two backends in this repo

| Service | Port | Stack |
|---------|------|-------|
| **nova-backend** (this folder) | 8011 | Express + npm |
| **backend/** (main platform) | 8010 | Python FastAPI + full Health ISF |

Use **8011** for the npm checklist. Use **8010** for the full enterprise Health ISF workspace.
