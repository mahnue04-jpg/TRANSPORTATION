# Nova Operations Agent — One-Packet Completion and Acceptance Plan

**Status:** DEVELOPMENT-ONLY / NO CUSTOMER DATA / NOT RELEASED
**Scope:** Operations CSV saved-task workflow + Work & Revenue owner approvals.
**Branch/PR:** `feat/operations-postgres-lease-foundation-20261117` / #541 (draft, stacked on #540).
**This document is an engineering handoff, not staging or production approval.**

## Customer journey being built

1. Customer chooses an authorized, owner-approved saved task.
2. Authenticated controller verifies organization, owner, engagement, task, and idempotency key.
3. Queue coordinator reserves one CSV job; private input is persisted, hash-verified and bound to a durable job reference. A duplicate request must reuse the same job, never create another charged task.
4. An explicitly invoked worker claims ONLY input-bound jobs, verifies current authorization, loads the private input by database reference, checks length and SHA-256, and performs bounded CSV cleanup.
5. Worker writes the private cleaned CSV, verifies its length, publishes a review-only artifact record while the lease still belongs to that worker, and finalizes the lease. It **never** delivers automatically.
6. Authenticated owner can inspect the output; approve/reject only after matching lease completion and private artifact integrity. Any customer delivery must be a separately authorized action.
7. Interruption, expired lease, cancellation, revoked authorization, duplicate key, corrupted private object, or ambiguous write must fail closed. Unknown output writes go to `NEEDS_RECONCILIATION`, never automatic replay.

## Code now assembled

- `operations_customer_csv_jobs.py`: existing bounded synchronous CSV owner-review records, kept unchanged.
- `operations_private_input.py`: bounded synthetic/private input adapter and SHA-256 verification.
- `operations_postgres_leases.py`: atomic enqueue, scoped immutable input reference, claim/renew/fencing, retry limits, cancel, reconciliation hold.
- `operations_lease_worker.py`: explicit one-job executor, strict bound-input option, uncertainty holds.
- `operations_owner_task_authorizer.py`: authenticated-owner adapter to the existing live saved-task eligibility check; not a background worker service principal.
- `operations_queued_csv_pipeline.py`: verifies private output by readback and SHA-256 before review publication; separately verifies private output integrity before explicit owner approval.
- `operations_queued_csv_pipeline.py`: explicit development-only queue intake -> processing -> private review -> owner decision coordinator. Requires an injected independent saved-task authorizer.
- `operations_lease_reconciliation.py` and `operations_csv_reconciliation_bridge.py`: read-only owner-scoped reconciliation helpers.
- `20261117_nova_operations_leases.py`: proposed explicit staging-only gated PostgreSQL schema migration; not applied.

## Consolidated acceptance tests

Run in CI using disposable loopback PostgreSQL and fake private storage:

```bash
cd backend
python -m pytest -v -rs \
  tests/test_nova_operations_customer_csv_postgres.py \
  tests/test_nova_operations_postgres_leases.py \
  tests/test_nova_operations_lease_worker.py \
  tests/test_nova_operations_lease_reconciliation.py \
  tests/test_nova_operations_private_input.py \
  tests/test_nova_operations_worker_subprocess.py \
  tests/test_nova_operations_lease_migration.py
```

Acceptance matrix: basic successful flow; duplicate request reuses job; changed idempotency input rejected; owner-scope denial; owner review remains pending until explicit approval; private output tampering blocked; private input corruption blocked; cancellation fenced; authorization revocation before upload or while processing; uncertain output held; two-worker concurrency; lease expiration and retries; migration approval gate; fresh DB engine and subprocess recovery.

**Do not mark acceptance passed until the actual latest-head CI run completes successfully.**

## Still REQUIRED before any staging execution

1. **Real authorization integration:** An authenticated-owner adapter now reuses existing saved-task eligibility checks, but the coordinator is not wired to an HTTP route or revocable hosted worker service principal. Require actual owner-authenticated request integration and recheck revocation at every state transition.
2. **S3 private-object security:** Owner-authorized provider credentials; real private bucket settings; key provenance/scope; immutable or versioned object behavior; non-public ACL; encryption; retention; orphan cleanup; and real storage outage testing. Current tests use fake storage.
3. **Atomicity and crash windows:** Queue and private writes cross two systems. Reservation-before-write may strand jobs; write-before-bind may orphan artifacts; successful output before DB commit may leave an orphan. Add an audited outbox/reconciler and recovery rules. Current code fails closed but cannot automatically repair every window.
4. **Lease/output reconciliation:** Held jobs whose customer CSV row remains `PROCESSING` need a private-output provenance record and deliberate owner-approved recovery, without automatic retry. SHA alone is not authorization.
5. **Worker lifecycle:** An explicit script/service, restart loop, shutdown and heartbeat, metrics, rate limits, cancellation and lease renewal, real subprocess kill/restart tests, and isolated hosted worker validation. The current one-job function is not a hosted service.
6. **Migration approval:** Verify Alembic revision ordering and isolated staging DB identity, backup and recovery. Migration is gated and has not been run. Never deploy it to the existing production or shared DB as a workaround.
7. **Revenue/customer journey:** Validate paid engagement readiness, pricing/approval, secure upload, customer scope, owner review/download, customer deliverable handoff, invoice/payout reconciliation, and audit trail. No live payments, applications, or outreach in this branch.
8. **Preview and owner acceptance:** Staging-only UI and auth/permission E2E, then a single owner-run acceptance script. Confirm production isolation and no paid providers.

## Release decisions

- **Allowed without additional owner approval:** Draft-branch code, CI, offline synthetic fixtures and reviews.
- **Not authorized by this PR:** Merge, hosted staging or production deployment, real S3 setup/credentials, staging/shared/production database migration, worker activation, customer data, real messaging, paid providers or new charges.
- **Decision gate:** After CI and isolated staging verification, provide one complete PASS/FAIL table and exact owner approvals needed; do not assert first paying-client readiness on synthetic test results.
