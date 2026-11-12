# Staging proposal — Nova Growth Agent (#485 / PR #490)

**Status:** Proposal only. Do **not** deploy, apply migrations to shared databases, activate paid providers, or send real messages.

## Target requirements

| Item | Proposal |
|------|----------|
| Exact commit | Tip of `cursor/nova-growth-agent-mvp-1565` (record SHA at approval time; verification pass built on post-`3775b0cb` worker/retention commit) |
| App surface | Isolated Render **preview** or disposable staging service — **not** production `amicor-health-isf` hostname rename |
| Database | Dedicated disposable Postgres schema/database (never shared production). Apply Growth Agent migrations only after owner approval on that disposable DB |
| Secrets | Staging-only widget secret + JWT/SECRET_KEY. No live Stripe/Twilio/OpenAI keys. No prospect lists |
| Feature flags | See environment block below — all live transports hard-off in code regardless of env |

## Environment flags (staging)

```bash
NOVA_GROWTH_AGENT_ENABLED=true
NOVA_GROWTH_AGENT_DEMO_MODE=true
NOVA_GROWTH_AGENT_WIDGET_ENABLED=true
NOVA_GROWTH_AGENT_WIDGET_SECRET=<staging-only-secret>
NOVA_GROWTH_AGENT_BACKGROUND_WORKER=true          # mock worker only
NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED=false  # keep off until owner dry-run review
APP_ENV=staging
AMICOR_ENVIRONMENT=staging
NOVA_STRIPE_LIVE_ENABLED=false
# Do not set live Twilio/OpenAI/Stripe secrets for this surface
```

Live send / calendar / voice / Stripe charge flags remain **hard-coded False** in `flags.py`.

## Database isolation

1. Provision a new disposable Postgres instance or schema named e.g. `nova_ga_staging`.
2. Take a blank baseline backup before first migration.
3. Run Alembic only against that disposable DB:
   - `20261112_nova_growth_agent`
   - `20261112_nova_ga_worker`
4. Confirm production schema lock still skips DDL when `APP_ENV=production`.

## Backup / rollback

1. **Before migration:** `pg_dump` disposable DB → dated artifact.
2. **Rollback app:** redeploy previous known-good commit; disable flags (`NOVA_GROWTH_AGENT_ENABLED=false`).
3. **Rollback schema (disposable only):** `alembic downgrade 20261012_casting_org_name` **or** restore dump. Never run Growth Agent downgrade against production.
4. **Kill switches:** owner UI Disable agent; set `NOVA_GROWTH_AGENT_ENABLED=false`; stop mock worker via process shutdown / unset `NOVA_GROWTH_AGENT_BACKGROUND_WORKER`.

## Owner review journey (staging)

1. Sign in as staging Nova owner → open `/nova/growth`.
2. Run **synthetic demo** (DEMO_MODE=true) — confirm Synthetic labels.
3. Create widget install for an allowlisted staging domain; send FAQ chat with consent.
4. CRM edit → book → cancel → rebook → reschedule.
5. With mock worker on: queue reminder, confirm diagnostics show pending then `sent_mock` after tick/worker; **live_send=false**.
6. Retention **preview** only; leave delete disabled.
7. Confirm Ops Agent / Work & Revenue / Creative Studio paths unchanged.
8. Record evidence screenshots (sanitized) + diagnostics JSON; owner decides merge readiness.

## Explicit non-goals for staging

- No production migration
- No paid provider activation
- No real SMS/email
- No prospect outreach (Makkan/Botora/AMICOR)
- No merge without owner approval
