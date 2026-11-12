# AMICOR Nova AI Business Growth Agent — Architecture Inventory

**Status:** Draft engineering handoff (Issue #485). Not production-authorized.  
**Branch:** `cursor/nova-growth-agent-mvp-1565`  
**Date:** 2026-11-12 (America/Chicago)

## 1. Live platform surfaces inspected

| Surface | Path | Role for this MVP |
|---------|------|-------------------|
| FastAPI Health ISF + Nova | `backend/` (Render `amicor-health-isf`) | **Host** for Growth Agent APIs, static UI, Alembic |
| Express dispatch | `nova-backend/`, `nova-stable/` | **Do not use** — Delivery-adjacent, no org multi-tenancy |
| Existing V3 Growth lab | `backend/app/core/nova/v3/growth/` | Synthetic outreach/CRM lab; **not reused as product** |
| Marketing leads | `backend/app/modules/marketing/` | Website early-access only; keep separate |
| Public website | `website/` | Marketing; no embeddable chat today |
| Delivery ops-shell | `backend/static/ops-shell.*` | **Frozen — do not touch** |

## 2. Auth / tenant model (reused)

- JWT + `UserContext` (`backend/app/auth.py`) with `organization_id`
- Scope helper: `NovaCoreService.resolve_organization_scope` — deny cross-tenant except support
- Growth Agent adds **deny-by-default** when org context is absent (`growth_agent/tenant.py`)
- Owner UI gated like V3 lab (`require_nova_access` + owner email allowlist / org membership)

## 3. Persistence / migrations

- Alembic under `backend/migrations/versions/`
- Head at inventory time: `20261012_casting_org_name`
- New revision: `20261112_nova_growth_agent` — **production DDL gated** (stamp-only in prod until owner approves)
- Runtime `schema_ensure.py` for local/test SQLite (same pattern as Work & Revenue)

## 4. Queues / workers

- No Celery/RQ. Pattern: DB-backed jobs + optional poll workers (Autonomy V2 / V3 scheduler)
- Growth Agent workflows use **in-process mock queue** with delivery_attempts + idempotency keys
- Background worker flags hard-default **OFF**; no production worker start

## 5. Feature flags

- New module: `NOVA_GROWTH_AGENT_ENABLED` (surface on/off), all live send/calendar/voice flags hard False
- Does **not** modify `v3/flags.py`, Work & Revenue, or Creative Studio flags

## 6. Overlap with open drafts (do not block)

| PR / Issue | Topic | Files we avoid |
|------------|-------|----------------|
| #475 | Ops CSV ↔ engagements/tasks | `nova-work/`, `operations_owner_csv_api.py`, ops CSV tests/workflows |
| #476 (issue) / #477 (PR) | Saved Work & Revenue task selector | WR CSV job queue, `owner_auth.py`, `render-backend-diagnostic.yml` edits |
| #478 | Creative Studio Kling / widescreen | `creative_studio/*`, `nova-creative/*`, `runtime_config.py` |

**Safe integration points:** new package `backend/app/core/nova/growth_agent/`, new static `backend/static/nova-growth/`, append-only `main.py` routes, dedicated CI workflow, docs under `docs/nova/growth-agent/`.

## 7. Libraries

FastAPI, SQLAlchemy 2, Alembic, Pydantic, pytest, stdlib HMAC for widget tokens. No new paid SDKs.

## 8. Secrets / Render

- No provider keys in code or fixtures
- No Render service rename; hostname remains `amicor-health-isf`
- Routes default-off via `NOVA_GROWTH_AGENT_ENABLED` (and production migration lock)

## 9. Test conventions

- pytest under `backend/tests/test_nova_growth_agent_*.py`
- `TESTING=true` + disposable SQLite (existing `conftest.py`)
- Synthetic fixtures only — no real customer data
