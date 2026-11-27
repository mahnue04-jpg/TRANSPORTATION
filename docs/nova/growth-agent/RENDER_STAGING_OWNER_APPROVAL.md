# Owner approval gate — isolated Render Growth Agent staging

**Status:** Prepared only. **Not provisioned.** PR #490 remains Draft.

## Why this gate exists

Creating a new Render web service + PostgreSQL database may incur cost if free-plan slots are unavailable. This agent has **no Render API credentials** and will **not** create paid resources without explicit owner approval.

## CI status (latest tip)

| Item | Value |
|------|-------|
| Commit | `3ff7de35baa0ee262c3f49aaa3e552aa5437f5de` |
| GitHub checks | **15/15 green** (including `growth-agent-tests`, `growth-agent-postgres-dispos`) |
| Graceful-shutdown fix | Present in ancestor `a81de10b` (preserved) |

## Blueprint ready to apply

File: `docs/nova/growth-agent/render.nova-growth-staging.yaml`

Creates (when owner applies):

- Service: `amicor-nova-growth-staging` (plan: **free**)
- Database: `amicor-nova-growth-staging-db` (plan: **free**, DB name `nova_ga_staging`)
- Expected URL: `https://amicor-nova-growth-staging.onrender.com/nova/growth`

Hard-off on this service:

- Live email/SMS/AI/Stripe charges
- Retention deletion (`NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED=false`)
- Prospect outreach

Does **not** modify Creative Studio, Operations Agent, Work & Revenue, or production `amicor-health-isf` / its DB.

## Cost estimate

| Scenario | Est. cost |
|----------|-----------|
| Free web + free Postgres slots available | **$0** incremental |
| Free slots exhausted → Starter web + Starter Postgres | Paid Render rates (owner must approve before create) |
| Paid AI / Twilio / Stripe live | **$0** — secrets unset; live flags hard-off |

## Owner actions required (explicit)

Reply with approval wording such as:

> Approve provisioning isolated Render Growth Agent staging using free plan only. If free plan unavailable, stop and report cost before creating paid resources.

Then either:

1. Apply the blueprint in Render Dashboard from branch `cursor/nova-growth-agent-mvp-1565`, **or**
2. Provide a Render API key / dashboard access so the agent can create **free-plan only** resources and stop if upgrade is required.

Staging-only secrets to set (never production values):

- `SECRET_KEY`, `JWT_SECRET`, `AMICOR_SEED_PASSWORD`, `AMICOR_DEPLOYMENT_SYNC_KEY`, `NOVA_GROWTH_AGENT_WIDGET_SECRET`

## After provision (agent will run)

1. Deploy tip including graceful-shutdown fix.
2. Verify: website chat → CRM → owner booking → mock reminders → restart recovery → graceful shutdown → tenant isolation → retention dry-run.
3. Update Draft PR #490 with the live staging URL, commit SHA, results, costs.

## Already verified (local isolated staging)

`http://127.0.0.1:8770/nova/growth` on dedicated disposable DB `nova_ga_staging_dispos` — journey **PASS** (see `STAGING_VERIFICATION.json`). Not remotely accessible.
