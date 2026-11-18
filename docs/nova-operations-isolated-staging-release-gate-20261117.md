# Nova Operations Agent — Isolated Staging Release Gate

**Inspection date:** 2026-11-17
**Scope:** Read-only inventory and planned checks. **No staging service, database, migration, private bucket, or worker was created or changed.**

## Verified evidence

- Draft Operations PR #541 head `cab3e9004aa2d219add510b03adc7ae926d76cd0` passed all 4 GitHub Actions jobs in run [44237775663](https://github.com/mahnue04-jpg/TRANSPORTATION/actions/runs/44237775663).
- Existing live `amicor health isf` Render service is `srv-d8of2kmrnols73d06h50`, follows `main`, and has automatic deploys enabled. **Do not merge to main to test Operations.**
- Read-only Render inventory of **Saye's workspace** (`tea-d8oe81b7uimc739gujp0`) shows dedicated staging web services for Growth (`nova-growth-validation-490`), Creative Studio (`nova-studio-validation-350`), Receptionist (`nova-receptionist-staging-h799`), and other products, but **no dedicated Operations Agent staging service**.
- Database inventory shows `amicor-prod`, casting staging, `nova-ga-490-dispos`, and `nova-receptionist-staging-db-h799`, but **no dedicated Operations Agent staging PostgreSQL**. These existing databases must not be reused for Operations. Casting staging expiry appears as November 18, 2026; do not rely on it.
- Existing assets and service plans must not be assumed to have no incremental cost. No new-cost authorization has been given.

## Exact pre-deployment acceptance requirements

1. **Branch and commit** — Owner approves exact reviewed SHA from PR #541 and any separately approved safety PR dependencies. Worktree and Render commit pins must match. Check no production or unrelated agent resources are in a Render Blueprint plan.
2. **Dedicated isolation** — Unique Operations-only staging service plus disposable Operations-only PostgreSQL database, with private storage and environment credentials scoped exclusively to staging. Verify no connection URI, identifier or bucket is shared with production, Growth, Receptionist, Casting, or Studio. **Do not provision until owner explicitly approves costs/resource plan.**
3. **Backup and rollback** — Approved restorable staging backup and documented recovery before any schema change. Never use production as backup or apply production migrations as a workaround.
4. **Migration gate** — Check Alembic head order on the exact chosen branch. Require explicit staging environment variables and migration approval flag only for the chosen isolated Operations DB. Verify table/index/check constraints against source; no implicit create-all.
5. **Flags** — Before deployment all queued/worker/HTTP/legacy CSV flags are OFF. Keep paid providers, external messaging, automated job discovery, and customer delivery OFF. Activate each test gate only in the isolated synthetic test environment and restore disabled state afterwards.
6. **Private storage** — Confirm encrypted non-public S3-compatible bucket, owner-scoped credentials, object key provenance, retention/revocation, cleanup, and outage simulations. Verify no public URL or user-supplied storage ref can read arbitrary objects.
7. **Synthetic acceptance** — Repeat full suite from completion packet, plus owner-authenticated UI/browser flow, 401/403/404/409 role/tenant tests, idempotent request, same-job concurrency, corrupted private input/output, revoke/cancel, approval-gated download, and never-delivered status.
8. **Actual worker restart** — Use separately approved, staging-only worker with revocable service identity; kill the process after private object writes and before commit, restart, and inspect state. A fresh session/subprocess CI test is **not** hosted failure recovery.
9. **Crash/orphan reconciliation** — Provide auditable handling for reserved-without-input, written-without-binding, and output-written-but-not-finalized objects. Never automatically redeliver or retry uncertain customer work.
10. **Owner signoff** — One consolidated PASS/FAIL artifact with current SHA, test/run IDs, staging service and DB IDs, cost impact, logs, restore evidence, and exact production approval request. No production deploy or real customer files until separate owner approval.

## Current release decision

- **Development acceptance:** PASS at SHA `cab3e9004aa2d219add510b03adc7ae926d76cd0`.
- **Hosted staging acceptance:** NOT RUN, because approved isolated Operations infrastructure is absent.
- **Real private S3 integration:** NOT VERIFIED.
- **Hosted background worker and kill/restart:** NOT VERIFIED.
- **Automatic orphan recovery:** NOT COMPLETE.
- **Paid customer release:** BLOCKED.

**Permitted work without new deployment approval:** Draft code, read-only audits, CI and synthetic fixtures. Any new Render resource, database, paid plan, private bucket, schema migration, worker activation, merge, production deploy, real customer processing, outbound message or payment requires separate explicit approval.


## Verified GitHub dependency chain and scope (read-only audit)

The Operations package is **not** a self-contained pull request against `main`. The reviewed stack is:

1. PR #477 `feat/nova-saved-task-selector-issue-476`, base `feat/nova-operations-engagement-scoped-csv-20261109`, open draft, 54 commits, 27 changed files.
2. PR #540 `fix/operations-review-atomic-20261117`, base `feat/nova-saved-task-selector-issue-476`, open draft, 4 commits, 4 changed files.
3. PR #541 `feat/operations-postgres-lease-foundation-20261117`, base `fix/operations-review-atomic-20261117`, open draft, 124 commits, 26 changed files at head `230723e0daa6bec9804eb5c3dc9139bff0370755`.

**Do not merge PR #541 into `main`, rebase it blindly, or move a production Render commit pin.** Verify the exact ancestor commits, migrations and runtime flags across the entire stacked branch before any isolated staging release. The current PR mergeable status is a GitHub mergeability check, **not** authorization to deploy.

The dedicated CI for PR #541 at SHA `230723e0daa6bec9804eb5c3dc9139bff0370755`, run #44244423782, passed Operations PostgreSQL integration, CSV regression, and Work & Revenue qualification; the broad backend diagnostic was still running when last inspected. Do not declare the full latest-head CI green until that job completes successfully.

**Staging plan prerequisite:** produce a read-only combined diff manifest from all ancestor PRs and confirm no unrelated module, database, secret, paid-provider, Render resource, or production auto-deploy is altered. Then make a single owner approval request naming precise staging-only resources, expected charges, migration target, recovery method and SHA.


## Alembic integrity review — before staging

A migration safety audit found that the initial proposed Operations lease revision could return successfully outside authorized staging without creating its table, or return successfully on downgrade without removing the schema. Such operations could advance or rewind Alembic's version ledger without equivalent database changes. This has been corrected **in draft source**, not executed.

- `upgrade()` now fails rather than silently no-ops when environment/approval conditions are missing or incompatible.
- An explicit `NOVA_OPERATIONS_EXPECTED_STAGING_DATABASE` must match PostgreSQL `SELECT current_database()` before any table DDL. An approval flag alone is insufficient to select the destination.
- `downgrade()` fails unless a separately approved, retention-safe rollback is designed.
- Disposable table metadata and the draft migration now share the private-input binding check constraint. Tests cover prohibited environments, missing/wrong DB target, schema parity and refused rollback.
- The older successful full run #44244423782 verified SHA `230723e0daa6bec9804eb5c3dc9139bff0370755` **before these migration hardening changes**. The newer migration changes have their own CI gate; do not treat the previous success as evidence that the new migration has passed.

This is not permission to apply the migration to any connected database. A dedicated Operations staging service/database, review of Alembic ancestry, approved backup, and separate owner approval are still mandatory.
