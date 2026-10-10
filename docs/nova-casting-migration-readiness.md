# Nova Casting — migration readiness (NOT an executable migration)

Verified against repository configuration on 2026-10-10.

- `backend/alembic.ini` uses `script_location = migrations` and runtime `DATABASE_URL`.
- `backend/migrations/env.py` imports `app.db.session.Base`, the existing Creative Studio models, and other live models, but **does not import casting_db_models**.
- Alembic's `include_object` currently permits table prefixes including `nova_creative_`, but not `nova_casting_`. Autogenerate therefore will not manage the draft casting tables by default.
- Do not add a standalone Alembic revision without confirming the migration heads/revision graph, identity-table FKs, data retention and rollback strategy.
- Current casting schema uses draft owner identifiers and should be reviewed for consistent tenant-safe database constraints before generating an executable migration.

## Pre-migration tasks

1. Inspect current Alembic heads and any merge revisions in `backend/migrations/versions`; check all outstanding branch heads.
2. Map the canonical user and organization IDs from existing Nova storage and confirm foreign keys and tenant constraints.
3. Confirm explicit organization verification and casting membership revocation lifecycle.
4. Design forward and downgrade Alembic revision using the existing chain; verify `upgrade` and `downgrade` on disposable PostgreSQL, then staging.
5. Register casting models in Alembic metadata and `include_object` **only when** explicitly approving the migration.
6. Retain disabled casting routes, inactive memberships, draft campaigns and no public uploads through migration rollout.

This document does not create tables, run Alembic or change the live database.
