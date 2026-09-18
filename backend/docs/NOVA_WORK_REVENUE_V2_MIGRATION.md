# Work & Revenue V2 production migration notes

Status: **not applied**. Do not run on Render or production without owner authorization.

## Canonical production-safe strategy

1. **Production** uses Alembic as the only schema source once owner-authorized.
2. **Local/test** may still call `ensure_work_revenue_schema` (`CREATE TABLE` / additive `ALTER TABLE` / unique-index repair). That helper is a compatibility path for sqlite tests and empty local DBs.
3. Do not rely on lazy ensure in production after the first authorized Alembic apply.
4. This assignment does **not** apply either path to Render.

## Dual-path resolution

If a process boots this SHA before Alembic is applied, `ensure_work_revenue_schema` will create the V2 tables additively. Alembic revisions use `IF NOT EXISTS` / existing-column checks, so a later `alembic upgrade` will skip objects that already exist.

Preferred order for a future owner-authorized production apply:

```
alembic upgrade 20260918_nova_work_revenue_v2_hardening
```

That upgrade includes:

- `20260918_nova_work_revenue_v2` — four V2 tables
- `20260918_nova_work_revenue_v2_hardening` — approval columns, owner-scoped unique indexes, historical correction table, audit metadata columns

## What these revisions do not do

- No DROP of V1 `nova_work_*` data
- No rewrite of Health, Delivery, Freight, Lifesaver, or Stripe/payment tables
- No production apply in this assignment

## Rollback

`downgrade` of the hardening revision drops only `nova_work_historical_corrections` if present.

`downgrade` of `20260918_nova_work_revenue_v2` drops only the four original V2 tables if present.

Additive columns on V1 `nova_work_audit_events` are left in place on hardening downgrade to avoid data loss. Owner-scoped unique indexes are not reverted because reverting them would reintroduce a tenant/owner isolation defect.
