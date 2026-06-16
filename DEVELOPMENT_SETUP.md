# Amicor — Local Development Setup

> Validated: May 16, 2026. Single-process stack (backend API + frontend served together).

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11 or 3.13 | `runtime.txt` targets 3.11.9 for cloud deployments; 3.13 works locally |
| pip | any recent | included with Python |
| Node.js | 18 + | only needed to run the JS test suite — not needed to run the app |

---

## 1 — One-Time Setup

### 1a. Clone and enter the repo

```bash
git clone <repo-url>
cd "Amicore_Rebuild"
```

### 1b. Create a virtual environment

```bash
python -m venv .venv
```

> On Windows with PowerShell, you may need to allow scripts first:
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
> ```

### 1c. Activate the virtual environment

**PowerShell (Windows)**
```powershell
.\.venv\Scripts\Activate.ps1
```

**Bash / macOS / Linux**
```bash
source .venv/bin/activate
```

### 1d. Install Python dependencies

```bash
pip install -r backend/requirements.txt
```

### 1e. Create your `.env` file

Copy the template and fill in your keys:

```bash
cp .env.template .env
```

Open `.env` and set at minimum:

```env
OPENAI_API_KEY=sk-...your-key-here...
SECRET_KEY=<run: python -c "import secrets; print(secrets.token_hex(32))">
```

All other variables have safe defaults for local development.

---

## 2 — Starting the Backend (and Frontend)

The frontend is **served by the backend** — there is no separate frontend dev server.  
Starting uvicorn is the only command needed to have the full app running.

**Important:** You must `cd` into `backend/` before starting uvicorn.  
Running from the repo root causes `ModuleNotFoundError: No module named 'app'`.

```powershell
# PowerShell
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

```bash
# Bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

> `--reload` is recommended during development — uvicorn will restart automatically when Python files change.

---

## 3 — Verifying the App

After starting uvicorn, open these URLs:

| URL | Expected | Purpose |
|---|---|---|
| http://localhost:8000/app | Full chat UI renders | Main application |
| http://localhost:8000/api/health | `{"ok":true,...}` | Liveness check |
| http://localhost:8000/api/health/detail | Full startup report | Env vars + DB status |
| http://localhost:8000/api/search/diagnostics | Provider call counts | Search provider health |
| http://localhost:8000/admin | Admin dashboard | Internal metrics |

---

## 4 — Active Ports

| Port | Service | Notes |
|---|---|---|
| **8000** | FastAPI / uvicorn | API + static frontend (only required port) |
| 5432 | PostgreSQL | Only if using Docker Compose with the `db` service |

No separate frontend build server runs in local development.

---

## 5 — Environment Variables

### Required (app will not function without these)

| Variable | Description | Where to get it |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key for chat and embeddings | https://platform.openai.com/api-keys |
| `SECRET_KEY` | 32-byte hex secret for JWT signing | `python -c "import secrets; print(secrets.token_hex(32))"` |

### Optional (have safe local defaults)

| Variable | Default | Description |
|---|---|---|
| `ALLOWED_ORIGINS` | `http://localhost:8000, http://127.0.0.1:8000` | CORS allowed origins (must be set in production) |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `DB_FILENAME` | `backend/data/chat.db` | SQLite database path |
| `MAX_HISTORY` | `10` | Number of previous messages sent to OpenAI as context |
| `APP_VERSION` | `dev` | Version string shown in health checks |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | JWT access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | JWT refresh token lifetime |
| `DATABASE_URL` | *(unset — uses SQLite)* | PostgreSQL connection string for cloud deployments |
| `weather_api_key` | *(unset)* | OpenWeatherMap key — weather module degrades gracefully if missing |
| `TAVILY_API_KEY` | *(unset)* | Tavily search — falls back to DuckDuckGo → Wikipedia → Google News RSS |

---

## 6 — Running Tests

### Python tests (search sanitization, unit tests)

```powershell
# From backend/
cd backend
python -m unittest discover -s tests
```

### JS test suite

The `package.json` at the repo root defines many Node-based test and benchmark scripts:

```bash
npm run test:tools         # Tool runtime tests
npm run test:capabilities  # Capabilities tests
npm run test:memory        # Memory system tests
npm run test               # Alias for test:tools
```

> Node tests test static-side JS modules only. They do not require the uvicorn server to be running unless the script name includes `-live`.

---

## 7 — Full Stack with Docker (optional)

A `docker-compose.yml` at the repo root starts the full stack including a PostgreSQL database:

```bash
docker compose up --build
```

Services started:

| Service | Port | Notes |
|---|---|---|
| `app` | 8000 | FastAPI + frontend, hot-reload via volume mount |
| `db` | 5432 | PostgreSQL 16 (optional — SQLite used if `DATABASE_URL` not set) |

---

## 8 — Cloud Deployment Notes

The app supports multiple cloud targets. The entry command in all cases is:

```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

| File | Platform |
|---|---|
| `Procfile` | Heroku, Railway, Render |
| `railway.toml` | Railway |
| `render.yaml` | Render |
| `fly.toml` | Fly.io |
| `Dockerfile` | Any container host |

All deployments require `OPENAI_API_KEY` and `SECRET_KEY` to be set as platform environment variables.

---

## 9 — Quick Diagnostic Commands

```powershell
# Check server is running
Invoke-WebRequest http://localhost:8000/api/health -UseBasicParsing | Select StatusCode

# Check env vars and DB status
Invoke-WebRequest http://localhost:8000/api/health/detail -UseBasicParsing |
  Select-Object -ExpandProperty Content | ConvertFrom-Json

# Check search provider health
Invoke-WebRequest 'http://localhost:8000/api/diagnostics/providers' -UseBasicParsing |
  Select-Object -ExpandProperty Content

# Find what process owns port 8000
netstat -ano | Select-String ':8000'

# Run Python pre-deployment readiness check
cd backend
python scripts/validate_startup.py
```
