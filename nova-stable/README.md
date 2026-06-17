# Amicor Nova Stable

Zero-flicker dispatch platform: **Node.js + Express + SQLite + JWT**.

No WebSockets. No Socket.IO. No EventSource/SSE. The UI refreshes via quiet `fetch()` polling every 30 seconds.

## Quick start

```bash
cd nova-stable
npm install
npm start
```

Open **http://localhost:8011**

## Demo logins

| Email | Password | Role |
|-------|----------|------|
| `dispatcher@amicor.local` | `Amicor123!` | dispatcher |
| `admin@amicor.com` | `admin123` | admin |
| `driver@amicor.local` | `Amicor123!` | driver |
| `rider@amicor.local` | `Amicor123!` | rider |
| `provider@amicor.local` | `Amicor123!` | provider |

## Portals

| URL | Purpose |
|-----|---------|
| `/` | Hub — trip list, metrics, quick create |
| `/dispatcher` | Dispatch command center + map |
| `/driver` | Driver mobile workflow |
| `/rider` | Rider booking + tracking |
| `/provider` | Bulk scheduling |

## Health check

`GET /api/health` → `{ ok: true, database: "sqlite", service: "amicor-nova-stable" }`

## Deploy to Render

1. Push this repo to GitHub.
2. Create a **Web Service** with:
   - **Root directory:** `nova-stable`
   - **Build:** `npm install`
   - **Start:** `npm start`
   - **Health check path:** `/api/health`
3. Set `JWT_SECRET` (Render can auto-generate).
4. Optional: set `SQLITE_PATH` to a persistent disk path on paid plans.

Or use the included `render.yaml` Blueprint.

## Environment

Copy `.env.example` to `.env`:

```
PORT=8011
JWT_SECRET=change-me-in-production
SQLITE_PATH=./amicor_nova.db
```
