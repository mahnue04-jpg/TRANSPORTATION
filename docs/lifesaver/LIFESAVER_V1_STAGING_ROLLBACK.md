# Lifesaver V1 — Staging rollback plan

This plan applies only to a future **staging** host and **staging** database.
Production is unaffected if those stay isolated.

Do not run these commands against production.
Do not apply them during Phase 3A review.

## How to stop a bad staging release

1. Stop or unroute the staging Lifesaver URL so testers cannot keep using it.
2. Do not fail over to production `amicor-health-isf`.
3. Keep the staging database online long enough to collect evidence and, if needed, downgrade.

## App rollback method

Preferred:

- Restore the previous staging application image/build that does not include the Lifesaver router and `/lifesaver` static page.

Alternate:

- Redeploy the prior git revision on the staging service only.
- Or serve a build with the additive Lifesaver `include_router` and `/lifesaver` routes removed.

Do not roll back Nova, Delivery, Freight, Driver 001, or Health ISF application code to “fix” Lifesaver.

## Migration downgrade order

Alembic `downgrade <rev>` means downgrade **to** that revision.

Current prepared head: `20260911_lifesaver_phase2_schema`

On the **staging** database only, after backup:

1. Undo Phase 2 (drops `lifesaver_transport_requests`, `lifesaver_notification_outbox`, and the two additive reading columns):

   `cd backend && alembic downgrade 20260911_lifesaver_phase1_schema`

2. Undo Phase 1 (drops remaining `lifesaver_*` tables):

   `cd backend && alembic downgrade 20260909_nova_freight_settlement`

Stop there. The previous freight settlement revision is the last non-Lifesaver head.

Do **not** run `alembic downgrade 20260911_lifesaver_phase2_schema` when already at Phase 2; that is a no-op.

Downgrade removes only Lifesaver-owned tables/columns. It does not drop Health ISF, Nova, Delivery, Freight, Driver 001, or Stripe tables.

## Database backup expectation

Before any approved staging upgrade:

- Take a logical or snapshot backup of the **staging** database.
- Record the backup id, time, and `alembic_version` value.

Restore that backup if downgrade is unsafe or incomplete.

## Restore checkpoint

A staging restore is successful when:

- `alembic_version` is `20260909_nova_freight_settlement` (or the pre-Lifesaver staging head)
- No `lifesaver_*` tables remain (unless the restored backup already had none)
- Health ISF ride tables are unchanged from the pre-change backup
- `/lifesaver` is either absent or returns the rolled-back application behavior

## Smoke checks after rollback

1. `GET /api/health/live` on the staging host still responds if that host shared other products.
2. `GET /lifesaver` is gone or matches the previous build.
3. `GET /api/lifesaver/health` is gone or 404.
4. Confirm no new Health ISF rides were created during the failed Lifesaver attempt.
5. Do not run authenticated Lifesaver writes after rollback.

## Evidence to collect before retry

- Staging URL and exact build/commit
- `alembic_version` before and after
- Smoke script stdout/stderr (no passwords)
- Failing request path and status (no journal bodies or reading values)
- Confirmation that production `DATABASE_URL` and Render production service were not used
- Backup id used for restore, if any

## Production isolation

Production is unaffected when:

- Staging `DATABASE_URL` is not the production database
- Staging secrets are not production `JWT_SECRET` / `SECRET_KEY`
- The production Render service `amicor-health-isf` was not changed
- No production Alembic command was run
