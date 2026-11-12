# Staging proposal — Nova Growth Agent (#485 / PR #490)

**Status:** Proposal only. Do **not** deploy, apply migrations to shared databases, activate paid providers, or send real messages.

## Candidate revision

| Item | Value |
|------|-------|
| Branch | `cursor/nova-growth-agent-mvp-1565` |
| Candidate / CI tip | `3ff7de35baa0ee262c3f49aaa3e552aa5437f5de` (CI 15/15 green; graceful-shutdown in `a81de10b`) |
| Verified local isolated staging URL | `http://127.0.0.1:8770/nova/growth` (agent-environment disposable staging; dedicated DB `nova_ga_staging_dispos`) |
| Remote Render isolated service | **Prepared, not provisioned** — see `render.nova-growth-staging.yaml` + `RENDER_STAGING_OWNER_APPROVAL.md` (owner approval required; no paid create without explicit OK) |
| PR | https://github.com/mahnue04-jpg/TRANSPORTATION/pull/490 (**Draft** — keep Draft) |
| Issue | #485 |

## Exact service / start commands (isolated only)

```bash
# 1) Disposable Postgres (example local names — never shared/prod)
createdb nova_ga_staging_dispos
export DATABASE_URL='postgresql+psycopg2://USER:PASS@127.0.0.1:5432/nova_ga_staging_dispos'

# 2) Environment (staging-isolated)
export APP_ENV=staging
export AMICOR_ENVIRONMENT=staging
export NOVA_GROWTH_AGENT_ENABLED=true
export NOVA_GROWTH_AGENT_DEMO_MODE=true
export NOVA_GROWTH_AGENT_WIDGET_ENABLED=true
export NOVA_GROWTH_AGENT_WIDGET_SECRET='staging-only-widget-secret'
export NOVA_GROWTH_AGENT_BACKGROUND_WORKER=true          # mock worker only
export NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED=true # dry-run unless delete also on
export NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED=false  # keep off until owner dry-run review
export NOVA_STRIPE_LIVE_ENABLED=false
export SECRET_KEY='staging-only'
export JWT_SECRET='staging-only'
unset OPENAI_API_KEY STRIPE_SECRET_KEY TWILIO_AUTH_TOKEN TWILIO_ACCOUNT_SID ANTHROPIC_API_KEY

# 3) Migrations against disposable DB only (from backend/)
cd backend
alembic upgrade 20261112_nova_ga_retention
# Sequence: … → 20261112_nova_growth_agent → 20261112_nova_ga_worker → 20261112_nova_ga_retention

# 4) Start API (isolated host/port — not production amicor-health-isf rename)
uvicorn app.main:app --host 127.0.0.1 --port 8765

# Optional explicit workers if not relying on lifespan auto-start:
# Mock delivery worker starts when NOVA_GROWTH_AGENT_BACKGROUND_WORKER=true
# Retention scheduler starts when NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED=true
```

## Isolated database requirements

1. New disposable Postgres database/schema only (example: `nova_ga_staging_dispos`).
2. Never point `DATABASE_URL` at production / shared Health ISF DB.
3. Take `pg_dump` backup of the disposable DB before first migration.
4. Production schema lock still skips Growth Agent DDL when `APP_ENV=production`.

## Migration sequence

1. `20261112_nova_growth_agent` — core tenant tables  
2. `20261112_nova_ga_worker` — delivery leases, rate-limit counters, heartbeats  
3. `20261112_nova_ga_retention` — `nova_ga_retention_schedule_runs`  

Confirm with: `alembic current` → `20261112_nova_ga_retention`.

## Feature flags

| Flag | Staging proposal | Notes |
|------|------------------|-------|
| `NOVA_GROWTH_AGENT_ENABLED` | `true` | Master surface |
| `NOVA_GROWTH_AGENT_DEMO_MODE` | `true` | Synthetic demo only |
| `NOVA_GROWTH_AGENT_WIDGET_ENABLED` | `true` | Public widget gate |
| `NOVA_GROWTH_AGENT_BACKGROUND_WORKER` | `true` | **Mock** deliveries only |
| `NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED` | `true` | Scheduled processor; **dry-run by default** |
| `NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED` | `false` | Separate explicit enablement for deletion |
| Live email/SMS/calendar/voice/Stripe | hard-coded `False` in `flags.py` | Cannot enable via UI/headers |

## Worker / scheduler launch

- Lifespan auto-starts mock delivery worker when `BACKGROUND_WORKER=true`.
- Lifespan auto-starts retention scheduler when `RETENTION_SCHEDULE_ENABLED=true`.
- Owner ticks: `POST /api/nova/growth-agent/workflows/worker/tick`, `POST /api/nova/growth-agent/retention/schedule/tick`.
- Deletion still requires `RETENTION_DELETE_ENABLED=true` separately.

## Health checks

1. `GET /api/nova/growth-agent/health` (authenticated owner) → configured/activated.  
2. `GET /api/nova/growth-agent/flags` → `REAL_*` false; schedule/delete flags as set.  
3. `GET /api/nova/growth-agent/diagnostics` → `live_delivery=false`, retention `mode=dry_run` unless delete enabled.  
4. UI `/nova/growth` diagnostics flag strip: `live_delivery=false · retention_mode=dry_run · retention_delete=off`.

## Owner review steps (staging)

1. Sign in as staging Nova owner → `/nova/growth`.  
2. Run **synthetic demo** — confirm Synthetic labels.  
3. Widget FAQ chat with consent on allowlisted staging domain.  
4. CRM edit → book → cancel → rebook → reschedule.  
5. Mock worker tick / diagnostics → `sent_mock` / `live_send=false`.  
6. Retention **preview** + schedule tick (**dry-run**); leave delete disabled.  
7. Kill switch Disable → Resume.  
8. Confirm Ops Agent / Work & Revenue / Creative Studio unchanged.  
9. Attach sanitized screenshots + diagnostics JSON; owner decides merge readiness.

## Rollback

1. App: redeploy previous known-good commit; set `NOVA_GROWTH_AGENT_ENABLED=false`.  
2. Workers: unset `NOVA_GROWTH_AGENT_BACKGROUND_WORKER` and `NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED`; process shutdown.  
3. Schema (disposable only): restore `pg_dump` **or** `alembic downgrade 20261012_casting_org_name`. Never downgrade Growth Agent against production.  
4. Kill switches: owner Disable agent; env master flag off.

## New cost identification

| Item | Cost signal |
|------|-------------|
| Disposable staging Postgres | Extra DB instance/schema compute + storage (staging only) |
| Isolated staging web service | Extra Render/preview compute hours while running |
| Mock worker / retention scheduler | CPU idle polls only — **no** paid provider spend while live flags remain hard-off |
| Paid AI / Twilio / Stripe | **$0** if secrets unset and hard-off flags preserved |
| Retention delete | Still off; dry-run does not write deletions |

No new paid third-party subscriptions are required for this staging proposal.

## Explicit non-goals

- No production migration  
- No paid provider activation  
- No real SMS/email  
- No prospect outreach  
- No merge without owner approval  
- Do not rename away from `amicor-health-isf` hostname for shared Health ISF  
