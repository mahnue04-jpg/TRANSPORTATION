# Nova Operations Agent — One-Packet Completion and Acceptance Plan

**Status:** DEVELOPMENT-ONLY / NO CUSTOMER DATA / NOT RELEASED
**Scope:** Operations CSV saved-task workflow + Work & Revenue owner approvals.
**Branch/PR:** `feat/operations-postgres-lease-foundation-20261117` / #541 (draft, stacked on #540).
**This document is an engineering handoff, not staging or production approval.**

## Customer journey being built

1. Customer chooses an authorized, owner-approved saved task.
2. Authenticated controller verifies organization, owner, engagement, task, and idempotency key.
3. Queue coordinator atomically reserves the CSV record AND its unbound lease in one PostgreSQL transaction before private upload. Thus the original `/durable/` routes cannot bypass queued authorization, even in an interrupted upload. Private input is then persisted, hash-verified and bound to the existing lease. A duplicate request must reuse the same job, never create another charged task.
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
- `operations_owner_csv_api.py`: separately gated `/operations/queued/` owner-only HTTP endpoints for task-specific intake, supervised exact-job process, explicit owner review, sanitized status, and approval-only download. These do not run a background service. Requires `NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED=true` plus all existing DB/private-storage gates; default off.
- `backend/static/nova-work/index.html` and `operations-csv.js`: owner-facing explicit opt-in for the supervised queue, separate process button, status and approval-only download; legacy `/durable/` mode remains default. No unattended processing. JavaScript syntax and static UI contract are CI-gated.
- `operations_queued_csv_pipeline.py`: verifies private output by readback and SHA-256 before review publication; separately verifies private output integrity before explicit owner approval.
- `operations_queued_csv_pipeline.py`: explicit development-only queue intake -> processing -> private review -> owner decision coordinator. Requires an injected independent saved-task authorizer.
- `operations_lease_reconciliation.py` and `operations_csv_reconciliation_bridge.py`: read-only owner-scoped reconciliation helpers.
- `operations_recovery_diagnostics.py`: read-only owner-scoped job-state assessment for missing input binding, active/expired lease, uncertain output, metadata mismatch, failed/cancelled, and completed-for-review records. No raw refs, hashes, contents, automatic retry, approval or release are returned.
- `operations_owner_csv_api.py`: development-only `/operations/queued/jobs/{id}/recovery` and explicit `/cancel` routes (same owner auth, saved-task recheck and default-off gate). Only queued/running leases can be cancelled; held/completed jobs require separate reconciliation.
- Owner UI: separate recovery inspection and confirmed cancellation controls; no hidden automated processing.
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

Acceptance matrix: authenticated owner HTTP intake -> exact-job process -> status -> explicit review -> approval-gated download; basic successful flow; duplicate request reuses job; changed idempotency input rejected; owner-scope denial; owner review remains pending until explicit approval; private output tampering blocked; private input corruption blocked; cancellation fenced; authorization revocation before upload or while processing; uncertain output held; two-worker concurrency; lease expiration and retries; migration approval gate; fresh DB engine and subprocess recovery.

**Do not mark acceptance passed until the actual latest-head CI run completes successfully.**

## Still REQUIRED before any staging execution

1. **Real authorization integration:** Development-only supervised owner routes now reuse the existing owner guard and saved-task eligibility checks; the runtime gate is default off. A revocable hosted worker service principal remains absent. HTTP acceptance has not yet been established on a deployed isolated staging instance; do not interpret these routes as autonomous customer processing.
2. **S3 private-object security:** Owner-authorized provider credentials; real private bucket settings; key provenance/scope; immutable or versioned object behavior; non-public ACL; encryption; retention; orphan cleanup; and real storage outage testing. Exact organization/job/owner storage-key prefixes are now checked on write receipt, database binding, and read; this is NOT a substitute for real S3 authorization. Tests still use fake storage.
3. **Atomicity and crash windows:** The CSV and lease reservation are now one PostgreSQL transaction and legacy `/durable/` endpoints reject queued records. Private objects and database records still cross two systems: reservation-before-write may strand an unbound job; write-before-bind may orphan input; successful output before DB commit may orphan output. An audited outbox/reconciler and explicit owner recovery rules remain required. Never misrepresent current fail-closed behavior as automatic repair.
4. **Lease/output reconciliation:** Held jobs whose customer CSV row remains `PROCESSING` need a private-output provenance record and deliberate owner-approved recovery, without automatic retry. SHA alone is not authorization.
5. **Worker lifecycle:** An explicit script/service, restart loop, shutdown and heartbeat, metrics, rate limits, cancellation and lease renewal, real subprocess kill/restart tests, and isolated hosted worker validation. The current one-job function is not a hosted service.
6. **Migration approval:** Verify Alembic revision ordering and isolated staging DB identity, backup and recovery. Migration is gated and has not been run. Never deploy it to the existing production or shared DB as a workaround.
7. **Revenue/customer journey:** Validate paid engagement readiness, pricing/approval, secure upload, customer scope, owner review/download, customer deliverable handoff, invoice/payout reconciliation, and audit trail. No live payments, applications, or outreach in this branch.
8. **Preview and owner acceptance:** Staging-only UI and auth/permission E2E, then a single owner-run acceptance script. Confirm production isolation and no paid providers.

## Release decisions

- **Allowed without additional owner approval:** Draft-branch code, CI, offline synthetic fixtures and reviews.
- **Not authorized by this PR:** Merge, hosted staging or production deployment, real S3 setup/credentials, staging/shared/production database migration, worker activation, customer data, real messaging, paid providers or new charges.
- **Decision gate:** After CI and isolated staging verification, provide one complete PASS/FAIL table and exact owner approvals needed; do not assert first paying-client readiness on synthetic test results.

## Verification checkpoint

- A consolidated CI run for head `3355642040caecde475a497151d5f123d75c2962` completed successfully (run `44236365391`). This predates the new supervised HTTP endpoints.
- The new owner-only HTTP routes, optional UI and tests are on the later PR head; **require latest-head four-job CI success** before acceptance. No assertion of staging or live readiness.
- Current route flag: `NOVA_OPERATIONS_QUEUED_CSV_HTTP_ENABLED` defaults to disabled. No agent background loop or scheduled work is enabled.

- Legacy-route bypass tests now cover status, recover, approval and download of queued jobs, including records whose private input has not yet been bound. Queued owner review remains available only through the separately gated supervised route.

## Recovery triage safety checkpoint

- The owner can inspect a known scoped job and distinguish waiting for input, processing, expired lease, completed-but-held, cancellation and integrity mismatch without changing job state.
- Explicit cancellation invalidates queued/running lease claims; a running worker cannot then publish a new completion. Cancellation is not proof that an already-written private artifact has been deleted.
- The recovery status is diagnostic only; no automatic cleanup, retry, release, customer notification, invoice, or delivery is implemented.
- Latest recovery and owner UI tests are part of CI and require successful full-head verification before staging signoff.

## Interrupted private-input restoration (development only)

- A new owner-supervised `restore_unbound_queued_csv` path accepts an explicit reupload of the **original** CSV for the **same** reserved job; it rejects another owner, changed bytes, claimed jobs, completed jobs and already-bound inputs.
- The private adapter writes the reuploaded input and reads it back to verify SHA-256 and size **before** binding its reference. That job remains unclaimable until the binding succeeds.
- The gated `POST /operations/queued/jobs/{job_id}/restore-input` endpoint requires the same authenticated owner and saved-task eligibility checks, an explicit owner-action header, a bounded CSV and exact job identity. UI offers restore only after diagnosing `input_binding_incomplete`, with owner confirmation.
- This is **not** automatic orphan cleanup. Because the adapter uses random object keys, a prior uncertain upload may have left an unknown private object. The response reports `orphan_cleanup_verified=false`; actual object provenance/retention cleanup requires an approved storage service with audit evidence.
- Integration and UI tests are added to the consolidated CI; verify the latest code SHA before acceptance.


## Read-only S3 orphan candidate audit (development acceptance)

- `operations_orphan_audit.py` compares a single job's owner-scoped PostgreSQL input/output refs with an **injected** private prefix listing. It reports only bounded counts of present bound objects, missing bound objects and unknown orphan candidates; no raw object keys or customer content are returned.
- `operations_orphan_s3_listing.py` implements a bounded, fail-closed S3-compatible `list_objects_v2` adapter restricted to an exact organization/job prefix, including pagination, duplicate, overflow, provider-error and foreign-prefix checks. It neither creates credentials nor exposes a web endpoint.
- `inspect_job_s3_objects` connects these components, checking exact owner scope against the job and lease records **before** invoking the supplied S3 client. Synthetic tests verify cross-owner denial before any S3 call and no deletion behavior.
- **Not a verified hosted storage audit:** The tests use a fake client, not AMICOR's actual private bucket. A trusted authenticated caller, least-privilege private bucket credentials, audit logging, retention policy and independently approved cleanup plan are still required.
- **No automatic deletion or retry:** Candidate discovery is not evidence that an object is safe to delete, and the system does not clean or release uncertain customer work.
