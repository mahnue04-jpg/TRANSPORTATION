# Amicor — Core Platform & Module Architecture

**Scope:** Architectural separation between Amicor Core Platform and domain modules (starting with Health ISF).  
**Principle:** MVP-first. One FastAPI process. Clear package boundaries. No microservices until warranted.

---

## 1 — Proposed Folder Structure

```
backend/
└── app/
    │
    ├── main.py                    ← Entry point only. Registers all routers.
    │
    ├── core/                      ← CORE PLATFORM (shared, never imports from modules/)
    │   ├── __init__.py
    │   ├── ai.py                  ← OpenAI client wrapper, base ask_openai()
    │   ├── auth.py                ← JWT auth: register, login, refresh, me
    │   ├── database.py            ← SQLite chat/memory persistence (legacy layer)
    │   ├── helpers.py             ← now(), ensure_user_id(), uuid4(), json utils
    │   ├── image_ocr.py           ← File/image upload parsing
    │   ├── logging_utils.py       ← Logging configuration
    │   ├── middleware.py          ← SecurityHeadersMiddleware, RequestTracingMiddleware
    │   ├── models.py              ← Shared Pydantic types (ChatRequest, ResetRequest)
    │   ├── observability.py       ← Metrics, telemetry hooks
    │   ├── response_engine.py     ← Response normalization and formatting
    │   ├── router.py              ← Chat message routing, intent detection, memory context
    │   ├── startup.py             ← Startup validation, env checks, shutdown handlers
    │   ├── validation.py          ← Upload validation, filename sanitization
    │   ├── voice.py               ← TTS (OpenAI, ElevenLabs, Azure)
    │   ├── web_search.py          ← Search engine (Tavily → DDG → Wikipedia → RSS)
    │   │
    │   ├── db/                    ← SQLAlchemy ORM (platform tables)
    │   │   ├── __init__.py
    │   │   ├── models.py          ← platform_users, conversations, messages, etc.
    │   │   └── session.py         ← SessionLocal, Base, init_platform_db()
    │   │
    │   ├── providers/             ← Search provider implementations + circuit breaker
    │   │   ├── __init__.py
    │   │   └── resilience.py
    │   │
    │   ├── capabilities/          ← Generic shared capabilities (available to all modules)
    │   │   ├── __init__.py
    │   │   ├── business.py        ← General small-business advisory
    │   │   ├── education.py
    │   │   ├── email.py           ← Generic email drafting
    │   │   ├── news.py
    │   │   ├── search.py
    │   │   ├── time.py
    │   │   └── weather.py
    │   │
    │   └── tools/                 ← BaseTool, ToolRegistry, ToolExecutionEngine + generic tools
    │       ├── __init__.py
    │       ├── registry.py        ← BaseTool, ToolExecutionResult, ToolRegistry
    │       ├── execution.py       ← ToolExecutionEngine (detection + dispatch)
    │       ├── business_tools.py  ← BusinessPlanTool, ProposalTool, InvoiceTool, etc.
    │       ├── news_tool.py
    │       ├── search_tool.py
    │       ├── time_tool.py
    │       └── weather_tool.py
    │
    └── modules/                   ← DOMAIN MODULES (each is a self-contained vertical)
        ├── __init__.py
        │
        ├── health_isf/            ← Health ISF: first live operational module
        │   ├── __init__.py
        │   ├── router.py          ← FastAPI router, prefix=/api/isf
        │   ├── models.py          ← Domain Pydantic models (TripRequest, DriverProfile, etc.)
        │   ├── db/
        │   │   ├── __init__.py
        │   │   └── models.py      ← ORM tables prefixed isf_ (isf_trips, isf_drivers, etc.)
        │   ├── services/
        │   │   ├── __init__.py
        │   │   ├── dispatch.py    ← Driver matching and trip assignment
        │   │   ├── scheduling.py  ← Trip scheduling and calendar coordination
        │   │   ├── notifications.py ← SMS/email notifications for trips
        │   │   ├── payouts.py     ← Driver payout tracking
        │   │   └── reporting.py   ← Operational and grant reporting
        │   └── tools/
        │       ├── __init__.py
        │       └── transport_tool.py ← BaseTool for AI-assisted trip intake
        │
        └── [future_module]/       ← Drop-in pattern — see Section 4
```

### What stays flat (current → target mapping)

| Current location | Target location | Notes |
|---|---|---|
| `app/ai.py` | `app/core/ai.py` | No change in logic |
| `app/auth.py` | `app/core/auth.py` | No change |
| `app/business.py` | `app/core/capabilities/business.py` | Generic advisory stays in core |
| `app/database.py` | `app/core/database.py` | No change |
| `app/ecosystem.py` | `app/core/ecosystem.py` (interim) | Large file — split incrementally |
| `app/modules/` | `app/core/capabilities/` | Rename only |
| `app/tools/` | `app/core/tools/` | Rename only |
| `app/tool_registry.py` | `app/core/tools/registry.py` | Rename only |
| `app/tool_execution_engine.py` | `app/core/tools/execution.py` | Rename only |
| `app/tool_actions.py` | `app/core/tools/business_tools.py` | Rename only |
| `app/db/` | `app/core/db/` | No change in logic |
| `app/providers/` | `app/core/providers/` | No change |

> **Migration note:** Do this as a phased rename, not a big bang. Keep the old paths alive with re-exports (`from app.core.ai import *`) until all internal imports are updated.

---

## 2 — Module Ownership Map

### Core Platform — owns everything shared

| Component | Owner | What it provides |
|---|---|---|
| **Auth layer** | `core.auth` | JWT tokens, user registration, login, refresh, `/api/auth/*` routes |
| **AI engine** | `core.ai` | OpenAI client, `ask_openai()`, model config |
| **Chat router** | `core.router` | Intent detection, memory context injection, capability dispatch |
| **Tool engine** | `core.tools.registry` + `core.tools.execution` | `BaseTool`, `ToolRegistry`, `ToolExecutionEngine` |
| **Search** | `core.web_search` + `core.providers` | Multi-provider search, circuit breaker, diagnostics |
| **Voice** | `core.voice` | TTS via OpenAI / ElevenLabs / Azure |
| **Database** | `core.database` + `core.db` | SQLite chat memory (legacy) + SQLAlchemy platform tables |
| **Middleware** | `core.middleware` | Security headers, request tracing |
| **Startup** | `core.startup` | Env validation, DB check, shutdown handlers |
| **Observability** | `core.observability` | Request metrics, error rates |
| **Capabilities** | `core.capabilities.*` | Weather, news, search, time, email, education, business advisory |

---

### Health ISF Module — owns its own domain entirely

| Component | Owner | What it provides |
|---|---|---|
| **API routes** | `modules.health_isf.router` | `/api/isf/*` — all Health ISF HTTP endpoints |
| **Domain models** | `modules.health_isf.models` | `TripRequest`, `DriverProfile`, `ProviderOrg`, `PayoutRecord` |
| **ORM tables** | `modules.health_isf.db.models` | `isf_trips`, `isf_drivers`, `isf_providers`, `isf_payouts` |
| **Dispatch** | `modules.health_isf.services.dispatch` | Driver-to-trip matching, assignment workflow |
| **Scheduling** | `modules.health_isf.services.scheduling` | Trip windows, calendar slots |
| **Notifications** | `modules.health_isf.services.notifications` | SMS/email for drivers + providers |
| **Payouts** | `modules.health_isf.services.payouts` | Per-trip payout tracking and records |
| **Reporting** | `modules.health_isf.services.reporting` | Operational dashboards, grant export |
| **AI tool** | `modules.health_isf.tools.transport_tool` | `TransportTool(BaseTool)` for conversational intake |

### Role breakdown (Health ISF)

| Role | Capabilities |
|---|---|
| `provider` | Submit trip requests, view request status, view history |
| `driver` | View assigned trips, accept/decline, mark complete |
| `admin` | Full visibility, manual assignment, payout approval, reports |

---

## 3 — Dependency Boundaries

### Rule: modules import core. Core never imports modules.

```
┌─────────────────────────────────────────────────────┐
│                    app/main.py                       │
│     (registers routers, applies middleware)          │
└──────────────┬──────────────────────────────────────┘
               │ imports routers from both
       ┌───────┴────────┐
       │                │
       ▼                ▼
┌─────────────┐   ┌──────────────────────────────┐
│  app/core/  │   │       app/modules/            │
│             │   │                              │
│  auth       │◄──│  health_isf/                 │
│  ai         │◄──│    router.py                 │
│  router     │◄──│    services/dispatch.py      │
│  tools/     │◄──│    services/scheduling.py    │
│  database   │◄──│    services/notifications.py │
│  web_search │◄──│    services/payouts.py       │
│  voice      │◄──│    services/reporting.py     │
│  ...        │◄──│    tools/transport_tool.py   │
└─────────────┘   └──────────────────────────────┘

  ▲ allowed         ✘ core never imports modules
  ─ modules never import sibling modules
```

### Enforced import rules

| Allowed | Forbidden |
|---|---|
| `modules.health_isf` → `core.*` | `core.*` → `modules.*` |
| `modules.health_isf` → `core.tools.registry` (BaseTool) | `modules.health_isf` → `modules.business_advisor` |
| `main.py` → `core.*` | Any module importing a sibling module |
| `main.py` → `modules.*` | |

### Shared Auth Contract

All module routers consume the **same** JWT dependency from `core.auth`:

```python
# In any module router
from app.core.auth import get_current_user, require_role

@router.get("/api/isf/trips")
async def list_trips(user=Depends(get_current_user)):
    ...

@router.post("/api/isf/trips/{id}/assign")
async def assign_trip(id: str, user=Depends(require_role("admin"))):
    ...
```

No module defines its own auth — they all use the same tokens and user table.

### Shared Database Contract

- Core platform tables: `platform_*` prefix (users, conversations, messages, etc.)
- Health ISF tables: `isf_*` prefix (trips, drivers, providers, payouts)
- Both share the same `SessionLocal` from `core.db.session`
- `init_platform_db()` in `core.db.session` creates all tables on startup; Health ISF registers its ORM models in the same Base

```python
# health_isf/db/models.py
from app.core.db.session import Base

class ISFTrip(Base):
    __tablename__ = "isf_trips"
    ...
```

---

## 4 — Module Expansion Strategy

### Adding a new module: 3 files minimum

Any new vertical (grants, scheduling, driver-network, partner-portal) follows the same pattern:

```
app/modules/<module_name>/
    __init__.py
    router.py          ← defines APIRouter(prefix="/api/<name>")
    models.py          ← domain Pydantic + ORM models
    services/
        __init__.py
        <core_service>.py
```

Then register in `main.py`:

```python
from app.modules.health_isf import router as isf_router
from app.modules.grant_management import router as grants_router   # future

app.include_router(isf_router)
app.include_router(grants_router)   # drops in cleanly
```

### Module checklist (before adding a new module)

- [ ] Domain is distinct from core and existing modules
- [ ] Tables use the module-specific prefix (`isf_`, `grant_`, `sched_`, etc.)
- [ ] Pydantic models defined in module's own `models.py`
- [ ] Router prefix is unique (`/api/isf`, `/api/grants`, `/api/sched`)
- [ ] No cross-module service imports
- [ ] Auth uses `core.auth.get_current_user` / `require_role()`
- [ ] ORM models registered in `core.db.session.Base` (same DB, separate tables)
- [ ] Unit tests in `backend/tests/<module_name>/`

### Planned module slots (from ecosystem docs)

| Module | Router prefix | Status |
|---|---|---|
| Health ISF | `/api/isf` | **Next to build** |
| Grant Management | `/api/grants` | Planned |
| Scheduling System | `/api/sched` | Planned |
| Driver Network | `/api/drivers` | Planned (shared with ISF initially) |
| Partner Portal | `/api/partners` | Planned |
| Admin Dashboard | `/api/admin` | Partial (exists in main.py) |
| Notifications | `/api/notify` | Will be shared core utility |

### When to break out a microservice

Keep modules in the monolith until **at least one** of these is true:

- A module needs independent scaling (e.g., dispatch gets 100× traffic)
- A module has incompatible Python dependency versions
- A module needs separate deployment cadence (different team, different SLA)
- A module's DB tables are large enough to warrant dedicated Postgres instance

For MVP and early production: **stay monolith**.

---

## 5 — Migration Path (Current → Target)

### Phase 1 — Create module structure (no breaking changes)

1. Create `app/core/` as a package with re-exports of everything currently in `app/`
2. Create `app/modules/` as an empty package
3. Scaffold `app/modules/health_isf/` with router, models, and service stubs
4. Register `health_isf` router in `main.py`
5. Run all tests — nothing should break (old import paths still work via re-exports)

### Phase 2 — Migrate core files

6. Move files one-by-one into `app/core/`, updating internal imports
7. Keep re-export shims at old paths until all references are updated
8. Update `requirements.txt` if Health ISF adds new deps (e.g., SMS SDK)
9. Add `backend/tests/health_isf/` test suite

### Phase 3 — Clean up

10. Remove re-export shims once all imports are updated
11. Add import linting (e.g., `flake8-import-order`, `ruff`) to enforce the boundary rule
12. Update `DEVELOPMENT_SETUP.md` with module onboarding steps

---

## Summary

| Concept | Decision |
|---|---|
| Deployment model | Single FastAPI process (monolith) — no microservices at MVP |
| Auth | One shared JWT layer in `core.auth` consumed by all modules |
| AI engine | One shared client in `core.ai` — modules call `ask_openai()` or extend `BaseTool` |
| Workflow engine | `ToolRegistry` + `ToolExecutionEngine` in `core.tools` — modules add domain tools |
| Module isolation | Own router, own ORM tables, own services, own Pydantic models |
| Import direction | Modules → Core only. Core is dependency-free of domain concerns. |
| DB strategy | One SQLAlchemy `Base`, one `SessionLocal`, table prefixes per module |
| New module cost | ~3 files to scaffold (router, models, one service) + register in main.py |
