# Work & Revenue V2 production migration notes

Status: **not applied**. Do not run on Render or production without owner authorization.

## Current production behavior

V1 Work & Revenue tables are created additively at runtime by `ensure_work_revenue_schema` (`CREATE TABLE` / `ALTER TABLE ADD COLUMN`). Alembic `include_object` previously ignored `nova_work_*` tables.

V2 adds four tables:

- `nova_work_live_action_audits`
- `nova_work_supervised_actions`
- `nova_work_scheduler_jobs`
- `nova_work_payment_events`

Local/test runtimes still call `ensure_work_revenue_schema`, so these tables appear without running Alembic.

## What the Alembic revision does

Revision: `20260918_nova_work_revenue_v2`

- Additive only.
- Creates the four V2 tables if they do not already exist.
- Creates unique indexes used for idempotency (`organization_id` + `idempotency_key`, and scheduler `job_kind` + `period_key`).
- Does not drop or rewrite V1 tables.
- Does not touch Stripe, Health, Delivery, Freight, Lifesaver, payments, or platform tables.
- Downgrade drops only the four V2 tables if present.

## What a future V1 Alembic freeze would do (not in this revision)

A later owner-authorized revision could snapshot the existing V1 `nova_work_*` tables with `IF NOT EXISTS` so production no longer depends on lazy schema ensure. That revision is not included tonight because production already has V1 tables from lazy ensure, and rewriting them in Alembic without a production backup window is unnecessary risk.

## How to apply later (owner-authorized only)

From `backend/`:

```
alembic upgrade 20260918_nova_work_revenue_v2
```

Do not run this against production in this session.
