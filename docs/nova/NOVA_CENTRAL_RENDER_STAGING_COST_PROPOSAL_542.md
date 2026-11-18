# Nova Central isolated Render staging — priced proposal (NO-GO)

**Date:** 2026-11-17 CT  
**Status:** Planning and read-only inventory only. No infrastructure created or approved.

## Source of truth

- Confirmed Render workspace: `Saye's workspace` / `tea-d8oe81b7uimc739gujp0`.
- Read-only Render inventory: 54 services listed and four PostgreSQL resources; **no service or DB dedicated to Nova Central**.
- **Free-Postgres workspace blocker:** `amicor-casting-staging-db` (`dpg-dbap057btjjs7381egmg-a`) is listed on the `free` plan and was still `available` at the read-only inventory. Render officially permits **only one active Free Postgres per workspace**. Its listed `expiresAt` is `2026-11-18T03:35:48.655Z`; expiration does not authorize deleting or modifying it, and the status/availability must be rechecked before making a later decision. Protect its data and grace period.
- Preserve all existing resources. In particular production DB `dpg-d8uvfcugvqtc73bkgj10-a` (`amicor-prod`), Growth staging DB `dpg-dbqv7mmtlv9c73d7tnb0-a`, Receptionist staging DB `dpg-dbtk9iui0phs73dk6mm0-a`, Studio `nova-studio-validation-350`, Growth `nova-growth-validation-490`, Receptionist `nova-receptionist-staging-h799`, and main production service.
- PR #554 last confirmed pre-proposal commit `04c11eeb889286b6100225908179db4c091087fc`: **114 focused tests passed**; qualification and backend diagnostic both successful. The isolated app is **readiness only**, not a live dispatcher.
- Published public pricing reference: https://render.com/pricing (checked 2026-11-17); https://render.com/docs/free (limitations). Actual workspace eligibility, taxes and all metered usage are not yet quoted/approved.

## Options and estimated base recurring compute cost

| Option | New web service | New dedicated PostgreSQL | Base/month | Suitability |
|---|---|---|---:|---|
| A — ephemeral fictional-data trial | `free` ($0) | `free` ($0) | **$0** | **Blocked now:** another active Free Postgres already belongs to Casting. Do not delete or reuse it. Recheck eligibility only after its independent disposition is confirmed. |
| B — small paid staging | `0.5c-512mb` ($7) | `0.1c-256mb` ($6) | **$13** | Better for a repeatable isolated staging proof, pending owner approval |
| C — free web + paid isolated DB | `free` ($0) | `0.1c-256mb` ($6) | **$6** | Lower base cost if another free web service is allowed; potential spin-down, shared free-instance-hour quota and paid DB charge |

Quoted costs omit any extra bandwidth, storage, backup, project/workspace fees, tax or charges above included allowances. Paid Postgres advertises 1 GB included storage and separately priced expanded storage. Free PostgreSQL **expires 30 days after creation**, allows only one active Free database per workspace, and has **no Render-managed backups**. Free services can sleep/suspend, and free web availability depends on workspace quotas. The workspace currently lists 54 services, so **do not assume another free slot is available**. Recheck the checkout/plan selection screen before any decision.

## Proposed *new* resources (names are not IDs and do not yet exist)

- New web: `nova-central-validation-542`; region `virginia` to match existing staging, Python runtime, repo `mahnue04-jpg/TRANSPORTATION`, root directory `backend`, branch `feature/nova-central-isolated-app-542-20261117`, auto-deploy **off**.
- New Postgres: Render resource `nova-central-542-dispos`; actual DB name must be `nova_central_542_dispos`; Postgres 18 subject to app compatibility; region `virginia`; no shared/public production data. New role `nova_central_542_reader` only after an approved provisioning step. The initial provisioning role and role grants must be separate from the web service.
- Build: install pinned backend dependencies. Do not call Alembic or app.main and do not create/seed tables as part of web startup.
- Proposed startup only after approval: `uvicorn nova_central_isolated:create_app --factory --host 0.0.0.0 --port $PORT`.
- Deployment must pin a reviewed **exact 40-character commit SHA** and check it at build and startup. PR #554 is stacked on draft #553/552/.../547, so do not merge or deploy solely from a branch label.
- Environment: `AMICOR_ENVIRONMENT=staging`, `APP_ENV=staging`; isolated DB host/name/user allowlist; JWT signing key, issuer, and audience unique to this staging service, *not* reused from production; `NOVA_CENTRAL_JOURNEY_READONLY_ENABLED=false` and `NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED=false` on boot; no paid provider, live transport, background worker, real customer data, Stripe or other payment keys.
- The current factory expects configured PostgreSQL URL, but URL string checks alone **cannot prove account grants**, and real staging role credentials/column grants have not been created or tested. Auth requires fictional staged user rows, provisioned only in a separately approved schema step.

## Hard prerequisites before creating anything

1. **Do not modify Casting Free Postgres** to free a slot. Check its state/retention independently and confirm no existing data or planned work is at risk. Confirm Render plan availability on this specific workspace, actual base charge, additional usage/excess fees, free instance quota, date of any expiration, rollback/backup/restore capacity and ability to delete trial resources without affecting other services.
2. Request explicit owner approval for **separate new web and database resources**, stated plans and maximum price. A generic “continue” or prior code approval is **not** infrastructure approval.
3. Obtain explicit approval for temporary schema/fictional fixture creation, read-only role and GRANT tests, secrets and a limited test window. Never copy production accounts, records, credentials or media.
4. Verify read-only role by actual PostgreSQL permission-denial tests, including missing sensitive columns, unrelated tables, schema and function access, default grants, role inheritance, and negative DML/DDL.
5. Verify backup **and restore** and specify credential revocation/teardown. The free option is disposable and may lack required recovery features; do not represent it as a durable environment.
6. Authorize a **separate** exact-head service deployment after the DB acceptance gates, with no auto-deploy. Test startup, signed owner sessions, 401/403/404 behavior and safe restart; no real agent integrations.

## Current decision

**NO-GO to provision or deploy.** Option A ($0) is currently blocked by the existing Casting Free Postgres entry and must not be pursued by deleting or repurposing Casting. If no additional charges are approved, continue in GitHub CI with no new resources. Otherwise offer Option C (about $6 base/month, if a free web slot is available) or Option B (about $13 base/month) for **separate** exact-cost and exact-resource owner authorization. If the user does not approve new recurring charges, remain on GitHub CI and do not create or reuse any database.

This proposal **does not** create a service, database, role, secret, backup, schema or connection. Existing Nova resources are unaffected.
