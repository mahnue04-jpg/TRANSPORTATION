# Receptionist Postgres recovery (disposable rehearsal)

**Revision:** `20261116_nova_ga_receptionist`  
**Migration file:** `backend/migrations/versions/20261116_nova_ga_receptionist_pilot.py`  
**Scope:** Additive DDL for Nova Growth Agent receptionist pilot tables only.

## What this migration does

Creates (if missing) these tables only:

- `nova_ga_calendar_oauth_states`
- `nova_ga_calendar_connections`
- `nova_ga_calendar_sync_jobs`
- `nova_ga_owner_notifications`
- `nova_ga_handoff_requests`
- `nova_ga_voice_agent_mappings`
- `nova_ga_voice_webhook_events`
- `nova_ga_voice_sessions`

It does **not** alter Delivery, Health ISF, Work & Revenue, Creative Studio, or earlier Growth Agent core tables.

## Production skip lock

When `AMICOR_ENVIRONMENT`, `ENVIRONMENT`, or `APP_ENV` is `production` / `prod`, both `upgrade()` and `downgrade()` return without DDL. Stamping heads on a locked environment must not create receptionist tables.

## Rollback scope

`downgrade()` drops **only** the eight receptionist tables listed above (when not production-locked). It does not touch customer Delivery data, shared Health ISF tables, or prior `nova_ga_*` core tables (profiles, appointments, retention, etc.).

Customer-facing operational data outside these eight tables is out of scope for this rollback.

## Never run on an existing service DB without approval

Do **not** apply this revision against:

- Shared / production `amicor-health-isf` databases
- Any live Render service database
- Any database whose name lacks an explicit disposable marker (`test` / `dispos` / `ci` / `nova_ga`)

Owner approval, a backup plan, and a disposable rehearsal pass are required before any shared-DB consideration. This pilot does not authorize production migration.

## Disposable rehearsal vs production

| Aspect | Disposable rehearsal (`NOVA_GA_PG_TEST_URL`) | Production / shared service DB |
|--------|-----------------------------------------------|--------------------------------|
| Allowed? | Yes — CI `growth-agent-postgres` job and local disposable DSNs | No without separate owner approval |
| Host / DB name | Must look disposable; host guards refuse prod markers | Locked by env skip; still refuse opportunistic runs |
| Proof path | Disposable rehearsal **drops** receptionist tables, runs Alembic `upgrade 20261116_nova_ga_receptionist` (or heads / stamp-parent fallback), then asserts via SQLAlchemy inspect — **before** ORM ensure | N/A until approved |
| ORM `ensure_growth_agent_schema` | Last-resort for **non-receptionist** GA tables only after Alembic assertion | Must not be used to invent production schema |
| Data | Synthetic only; safe to drop | Preserve customer data; downgrade drops receptionist tables only |

### How to run the rehearsal

```bash
cd backend
export NOVA_GA_PG_TEST_URL='postgresql+psycopg2://USER:PASS@localhost:5432/nova_ga_ci_dispos'
export TESTING=true APP_ENV=test AMICOR_ENVIRONMENT=test
export NOVA_GROWTH_AGENT_ENABLED=true
export NOVA_GROWTH_AGENT_VOICE_SIMULATOR=true
python -m pytest -q tests/test_nova_growth_agent_receptionist_postgres.py
```

CI runs the same file in the `growth-agent-postgres` job only (not the sqlite job).
