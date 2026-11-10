# Nova Operations: Durable CSV owner-job release gate

Status: **IMPLEMENTED IN DRAFT; NOT PRODUCTION VERIFIED.** Issue #476, PR #477.

## Implemented flow
The owner chooses an eligible saved Work & Revenue CSV task, confirms client
data-processing authority, and submits a bounded CSV (<= 1 MB; <= 10,000 rows).
The owner UI sends an Idempotency-Key to the gated durable API:
- POST /api/nova/work/operations/durable/engagements/{engagement_id}/tasks/{task_id}/jobs
- GET /api/nova/work/operations/durable/jobs/{job_id}
- POST /api/nova/work/operations/durable/jobs/{job_id}/review
- POST /api/nova/work/operations/durable/jobs/{job_id}/recover
- GET /api/nova/work/operations/durable/jobs/{job_id}/download

The API derives org/owner from authenticated session; validates the saved
engagement/task on every operation; stores metadata in PostgreSQL and cleaned
artifacts via the existing private S3 storage adapter. Data is not automatically
sent to a customer, and a review decision is not delivery or payment.

## Provisioning / environment (owner approval required)
1. Select the intended **isolated staging** Render workspace and service.
2. Configure a dedicated staging PostgreSQL database using secure env settings;
   never reuse production credentials in staging.
3. Configure a private S3-compatible bucket, Block Public Access, encrypted
   objects, least-privilege credentials, secure rotation, retention and deletion.
   Existing private adapter uses PLATFORM_OPS_DOCUMENT_STORAGE=s3_private and
   AMICOR_DOCUMENT_S3_BUCKET, AMICOR_DOCUMENT_S3_REGION,
   AMICOR_DOCUMENT_S3_ACCESS_KEY, AMICOR_DOCUMENT_S3_SECRET_KEY; optional
   AMICOR_DOCUMENT_S3_ENDPOINT must use HTTPS. Do not expose credentials.
4. Have a migration reviewer evaluate
   `backend/migrations/versions/20261109_nova_operations_csv_jobs.py` and its
   reference SQL. On isolated PostgreSQL staging only, set all configured
   environment indicators consistently to `staging` and set
   `NOVA_OPERATIONS_CSV_SCHEMA_APPROVED=staging-only` after approval, then
   run the Alembic chain against the staging database. A staging run without
   approval raises rather than silently stamping this migration. Production
   does not execute this draft's DDL and requires a separate approved
   production schema rollout.
5. Leave NOVA_OPERATIONS_DURABLE_CSV_ENABLED=false until all staging gates pass.
   The old in-memory /csv-clean owner-demo endpoint is distinct.

## Required executed evidence before enabling
- JS syntax, Python syntax, synthetic service/HTTP/owner-UI regression tests PASS.
- Genuine authenticated 401/403/404/409 checks with multiple organizations
  and actual non-admin/owner roles. No dependency overrides for this stage.
- 1 MB/10,000-row, invalid MIME/UTF-8/CSV, formula injection, failed upload and
  corrupted-object checks with **synthetic data only**.
- Same Idempotency-Key replay never repeats processing or creates a second
  object; mismatched content/engagement returns conflict; simultaneous requests
  from separate instances preserve uniqueness.
- PostgreSQL migration deploy/restart and failed schema/credential paths fail
  closed, not silently using SQLite or local files.
- S3 read/write private with encryption, unavailable/read-only/expired-key
  handling; output SHA-256 verified at download.
- Simulate a crash after database reservation and after object storage.
  Owner recovery may mark stranded jobs FAILED after 15 minutes but cannot yet
  automatically replay the original input. Verify orphan-object reconciliation
  before commercial use.
- Review, reject, revoke, owner download, and audit events. No external send.
- Perform controlled browser walkthrough, rollback rehearsal, and report exact
  environment, commit SHA, test cases, observed artifacts and failures.

## Current limitations blocking production
- No completed staging evidence for this new customer-job path.
- Alembic migration is included but staging-gated, unexecuted, and not production-approved.
- The request is processed synchronously. Stale recovery marks FAILED and
  requires a fresh user upload; fully restart-resumable worker processing is
  **not** implemented.
- Object orphan reconciliation, retention/deletion automation, lifecycle
  audit logging, and true customer upload/review acceptance remain incomplete.
- Text-based CSV task scope recognition is not verified contract authorization.
- Neither real S3 credentials nor authorized Render workspace/configuration
  has been verified in this PR.

## Rollback / safety
- Set NOVA_OPERATIONS_DURABLE_CSV_ENABLED=false before reverting application.
- Do not drop the job table or delete encrypted objects during application
  rollback. Preserve metadata and audit; reconcile orphaned objects and retention.
- No customer assignments, billing, signatures, external sends or production
  activation until owner explicitly approves the full release evidence.
