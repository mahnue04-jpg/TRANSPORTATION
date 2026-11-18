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


## Staging schema packaging — automatic migrations isolated

The Operations-only proposed schema has been relocated to `backend/staging_migrations/operations_lease_schema.py`, **outside** `backend/migrations/versions`. This prevents routine Alembic upgrades for unrelated products from either creating Operations tables or failing because Operations staging approval is absent. The module still checks the explicit staging environment, approval flag and exact PostgreSQL database name before executing any DDL; it refuses silent downgrade. No automatic staging runner or deployment is configured. It must not be marked applied in the shared Alembic history. A future approved isolated Operations-only migration procedure and backup/rollback plan are still required.


## Dedicated resources provisioned — diagnostic-only acceptance checkpoint (Nov 18 UTC)

The owner separately approved a **maximum $13/month base compute** for a dedicated Operations staging web service and PostgreSQL instance. Both were created in Render workspace `tea-d8oe81b7uimc739gujp0`, Virginia:

| Resource | ID | Verified state |
|---|---|---|
| `nova-operations-staging-541` | `srv-dbujmrmk1f9s73afmp6g` | Diagnostic-only initial deploy `dep-dbujms6k1f9s73afmqkg` LIVE |
| `nova-operations-staging-db-541` | `dpg-dbujmp6k1f9s73afmed0-a` | PostgreSQL 18, `0.1c-256mb`, AVAILABLE; exact database `nova_operations_staging_db_541` |

- Web service plan is Starter and auto-deploy is OFF. Pinned initial commit `3ea5f4ac738d2d36ec8408a8082fc8ff70861fcc`; build command explicitly rejects any other commit.
- The diagnostic-only startup is a Python standard-library HTTP server on PORT 10000. GET and POST are designed to return HTTP 503 with a disabled-service message; HEAD currently yields HTTP 501 because it is not implemented. Render deployment was LIVE and logs showed successful startup. **No independent public HTTP 503 acceptance was recorded.**
- Web service currently uses Render's default Python 3.14.10; the backend CI uses Python 3.12. Pin a tested Python version **before** any approved actual-app staging deployment; do not mistake diagnostic runtime success for backend compatibility.
- No customer application build/dependencies were installed by the diagnostic build; no DATABASE_URL/credentials binding, private S3, schema DDL, background worker, task execution, paid provider, payment workflow or messaging was activated.
- Production service `srv-d8of2kmrnols73d06h50`, Growth, Studio, Casting, Receptionist and other shared resources were not changed. No new resource creation or plan upgrade is authorized beyond the two approved base-compute resources.

### Next approval boundary — one controlled isolated application acceptance

**Do not execute automatically under the earlier $13/month infrastructure approval.** Prepare an exact-action, owner-reviewed staging-only request covering:

1. Confirm dedicated DB owner and `nova_operations_staging_db_541` identity; verify restorable backup/snapshot mechanism and cost/retention in advance. A bare available DB is **not** backup evidence.
2. Verify full PR stack (#477 -> #540 -> #541), exact SHA and CI; prepare a build command that installs the correct backend dependencies on pinned Python 3.12 and starts the app with **all Operations job execution/paid/outbound flags OFF**.
3. Propose connecting only `srv-dbujmrmk1f9s73afmp6g` to `dpg-dbujmp6k1f9s73afmed0-a` via an authorized secret reference. Never print/expose the connection string in GitHub comments, logs, or documents.
4. Separately approve the guarded standalone DDL in `backend/staging_migrations/operations_lease_schema.py` for that exact DB, with a restore procedure. It is intentionally outside the normal Alembic graph; no automatic migrations.
5. Use a synthetic-only, isolated private-object store for full CSV processing acceptance. Real private S3 setup is **not** included in the approved $13/month; cost/security design and approval required before any object write.
6. Run supervised owner-only staging auth/roles/UI, SQL state transitions, private input/output, owner approval/download, cancellation, crash/orphan scenarios, and real process restart after all gates are authorized. No unattended production worker or external delivery.
7. Capture one PASS/FAIL record: exact web/DB IDs, test SHA, live logs, schema identity, backup/restore proof, access controls, costs and unverified blockers. Do not move production or merge these draft PRs on the strength of a diagnostic LIVE deploy.

**Current verdict:** infrastructure diagnostic stage PASS (Render LIVE / DB AVAILABLE); independent HTTP endpoint response unverified; actual Operations staging application, connected DB migration, S3, hosted worker and customer readiness NOT TESTED.


## Staging application activation preflight — November 18, 2026 (read-only)

**Live inventory:** Render dedicated web `srv-dbujmrmk1f9s73afmp6g` remains configured for diagnostic-only Python HTTP 503 responses, autoDeploy OFF, build pinned to `3ea5f4ac738d2d36ec8408a8082fc8ff70861fcc`. Dedicated PostgreSQL `dpg-dbujmp6k1f9s73afmed0-a` remains AVAILABLE, DB name `nova_operations_staging_db_541`. These are the only two resources approved under the $13/month base-compute ceiling.

**GitHub:** Draft PR #541 head `2433f7db0b1ee5e44b3c8eb8f61228db9a4ed047` after documentation updates. At inspection its PR-triggered CI run #44247026385 had three specialist jobs SUCCESS; the broad backend diagnostic was still IN PROGRESS. Reconfirm the final exact code SHA and all four tests immediately before any deployment. A documentation commit changing the head is not automatically an accepted application SHA.

**Critical configuration hazard:** repository `render.yaml` targets a separate production-oriented AMICOR deployment, includes `releaseCommand: alembic upgrade heads && ...ensure_customer_payment_tables()`, and enables `HEALTH_ISF_AUTO_DISPATCH_ENABLED=true`. **Do not apply this root Blueprint or reuse its environment/secrets** for Operations staging. Keep autoDeploy OFF and explicit staging-only service settings.

### Proposed controlled application sequence — NOT YET APPROVED

A. Read-only inventory and backup review: prove the dedicated PostgreSQL identity, backup/restore approach, retention, and any charges. Do not claim recovery capability without a successful restore rehearsal.
B. Prepare a **staging-only build and startup configuration** using tested Python 3.12, `backend/requirements.txt`, `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, and **no releaseCommand**. All auto-dispatch, scheduled workers, Operations queued/legacy processing flags, Stripe/payment, external communications, and private S3 remain OFF; no production secrets.
C. Explicitly review all application startup side effects before enabling any connection; the general `app.main` entrypoint runs multiple AMICOR modules, not an Operations-only minimal router. Do not assume that flags alone prevent startup writes.
D. With explicit owner approval, pin the exact reviewed code SHA to the already approved staging web service, and do one isolated diagnostic app deployment **without connecting a database or running any schema migration**. Validate startup/readiness; if the global app requires a DB to start, stop and return to the owner with evidence, not a production DB workaround.
E. Only after a separate backup/identity approval: bind the **dedicated** database using secret-scoped settings and independently execute the separately approved `backend/staging_migrations/operations_lease_schema.py` on that database only. No routine Blueprint/release-command migration.
F. Only after independent private S3 cost and security approval: connect isolated non-public storage and run complete synthetic owner-authenticated CSV intake, review, download, cancellation, worker restart and orphan inventory tests. No actual customers or autonomous worker.
G. Record exact service/DB/commit IDs, pass/fail logs, backup/restore proof, no-cost-overrun check, permissions, and rollback plan. Keep all unsafe flags OFF unless individually authorized.

### Current boundary

The $13/month compute approval **does not approve** changing the running diagnostic startup, connecting the database, staging schema DDL, private S3, hosted workers, actual client processing, or third-party charges. Resource provisioning is complete; application acceptance is pending an explicit separate approval. The correct next decision is a single controlled staging-only application smoke-test request after reviewed startup side effects and final CI verification.
