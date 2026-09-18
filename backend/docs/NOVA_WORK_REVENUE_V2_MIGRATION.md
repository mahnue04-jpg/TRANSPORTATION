# Work & Revenue V2 production migration notes

Status: **not applied**. Do not run on Render or production without owner authorization.

## Canonical production-safe strategy

**Alembic is the only production schema source for V2 tables.**

1. Production must not lazy-create V2 tables. `ensure_work_revenue_schema` skips V2 table creation when `AMICOR_ENVIRONMENT`/`runtime` is production, unless `NOVA_WR_LAZY_V2_SCHEMA=1` is explicitly set. Do **not** set that override on Render.
2. If a V2 HTTP route is called before Alembic is applied, the API returns `503 SCHEMA_MIGRATION_REQUIRED` instead of creating tables.
3. Local/test (pytest, development sqlite) still uses `ensure_work_revenue_schema` so empty DBs can boot tests.
4. V1 Work tables/columns may still be repaired additively by lazy ensure. That path does not create the five V2 tables in production.
5. This assignment does **not** apply either path to Render.

## Dual-path resolution

The previous dual-path (boot creates V2 tables, Alembic later `IF NOT EXISTS`) is closed for production:

- Production boot + `_ensure()` → V1 additive only
- Production V2 routes without Alembic → 503
- Owner-authorized future apply:

```
alembic upgrade 20260918_nova_work_revenue_v2_owner_scheduler
```

That upgrade includes:

- `20260918_nova_work_revenue_v2` — four original V2 tables
- `20260918_nova_work_revenue_v2_hardening` — approval columns, owner-scoped unique indexes, historical correction table, audit metadata columns
- `20260918_nova_work_revenue_v2_owner_scheduler` — scheduler unique index includes `owner_user_id`

## What these revisions do not do

- No DROP of V1 `nova_work_*` data
- No rewrite of Health, Delivery, Freight, Lifesaver, or Stripe/payment tables
- No production apply in this assignment

## Rollback

`downgrade` of `20260918_nova_work_revenue_v2_owner_scheduler` is a no-op. Reverting the owner-scoped scheduler unique index would reintroduce owner collision.

`downgrade` of the hardening revision drops only `nova_work_historical_corrections` if present.

`downgrade` of `20260918_nova_work_revenue_v2` drops only the four original V2 tables if present.

Additive columns on V1 `nova_work_audit_events` are left in place on hardening downgrade to avoid data loss. Owner-scoped unique indexes are not reverted because reverting them would reintroduce a tenant/owner isolation defect.
