# AMICOR Nova: Recovery staging and owner acceptance

Status: **DEVELOPMENT DRAFT — NOT DEPLOYED OR APPROVED FOR CUSTOMER DATA.**

Implementation branch: `feat/nova-recoverable-csv-worker-20261110`.
Stacked PRs: #477 (durable owner jobs) -> #479 (job history) -> #480 (recovery preview).

## Safety and isolation
- Use an **isolated Render staging service**, **dedicated staging PostgreSQL**, and
  **separate private S3-compatible bucket**. Do not reuse the production database,
  production credentials, or the casting staging database.
- Do not accept any real customer data in this phase. Use invented rows only.
- Verify encryption at rest, bucket block-public-access, least-privilege storage
  credentials, HTTPS transport, retention policy, and object access restrictions.
- Staging env indicators must all resolve to `staging`. Any mismatched environment
  or disabled feature must return a controlled HTTP 503.
- Explicit owner approval is required before any staging provisioning, migrations,
  credentials, or changes to existing deployed services. Never modify production.
- Migration: `20261110_nova_csv_recovery_jobs.py`, gated by
  `NOVA_OPERATIONS_CSV_SCHEMA_APPROVED=staging-only` on isolated staging.
- Keep `NOVA_OPERATIONS_RECOVERABLE_CSV_ENABLED=false` until storage, auth and
  schema checks are verified. Legacy CSV flag is independent.

## Current owner rehearsal (requires an approved and configured staging service)
Staging page: `https://<approved-staging-host>/static/nova-work/recovery-preview.html`.
Use the staging site's owner login session; the preview does not create logins.

1. Load eligible saved assignments, create an **ACTIVE synthetic engagement**
   and review-required Nova CSV task if none are available. This requires
   the existing owner-controlled Work & Revenue workflow.
2. Upload `Name\nAda\nAda\n` as `sample.csv` with explicit authorization
   confirmation. Confirm status `QUEUED` and a single private input object.
3. Reopen the job from its saved history after a browser refresh.
4. Click **Run one staging processing attempt**. Expect
   `AWAITING_REVIEW` and output `Name\nAda\n`.
5. Create two more fictional queued CSV jobs. Click **Run up to five queued staging
   jobs** and confirm each is processed once, remains available in saved
   history, and is never marked delivered. This is a manual supervised worker
   pass, **not an autonomous background scheduler**.
6. Download the review copy. Verify SHA-256, then **Approve for download**.
   Verify `APPROVED_FOR_DOWNLOAD`, **not** delivered, invoiced or paid.
7. Repeat with a second job and reject it. Rejected outputs must be
   unavailable for download.
8. Block/revoke the synthetic engagement; listing, status, processing,
   review and download must reject or hide it.

## Restart, security and reliability exercises (engineering verification)
- Terminate an isolated worker after a valid claim; after the lease expires,
  reclaim the **same** job and verify only the new token can finish.
- Run two independent PostgreSQL connections trying to claim a single queued
  job; expect exactly one active claim.
- Simulate crash before input storage, after storage but before queue commit,
  after claim, and after output storage but before final DB update.
- Test old-worker failure after new-worker completion: its cleanup must not
  remove the winner's output.
- Test invalid UTF-8, oversize CSV, damaged checksum, wrong owner and wrong
  organization, expired authorization, and private storage outage.
- Reconcile abandoned uploads, exhausted retries, and orphaned files.
  Audit cleanup failures and enforce documented retention/deletion rules.
- Test from the actual authenticated owner browser and an unauthorized user,
  **without dependency overrides**.

## Required release blockers to close
- **No autonomous scheduler/service worker is deployed.** The owner-preview
  processing endpoint is a supervised test route, not unattended customer work.
- **No real Render staging deployment or bucket policy evidence yet.**
- **No confirmed server restart/recovery exercise** in a live staging service.
- **No audited orphan-object reconciliation, retention/deletion automation,
  or contract-specific authorization record**.
- No external delivery connector or billing confirmation.
- Production migration and rollout plan require separate review after
  staging proof. Do not promote this preview route as production fulfillment.

## Evidence record (fill only with observed results)
- Review date and operator:
- Isolated staging service ID and commit SHA:
- Database identifier (nonsecret only):
- Storage bucket policy/encryption checked by:
- GitHub workflow URL and exact test counts:
- Authenticated owner and unauthorized browser results:
- Job IDs (fictional data only), input/output checksums:
- Restart injection and lease-recovery observations:
- Orphan/retention/revocation findings:
- Owner acceptance decision:
- Production release approval and rollback plan:

Never call a green synthetic test run "customer-ready" without the staging
and business-process evidence above.

## Current development worker interface
The default-off staging queue now supports `due_job_ids` and `run_due_jobs`
with explicit owner/org scoping, a batch limit (up to 25 at the code layer,
5 through the owner rehearsal API), and fresh saved-task authorization.
No unattended scheduler, service deployment, restart proof, or production
processing has been established. A green CI result is not proof of those.


## Dedicated staging worker — development command

Implemented module:
`app.core.nova.work_revenue.operations_recovery_worker`.

The command supports `--once` for an owner-approved one-pass rehearsal
and `--loop --poll-seconds 30` for a future isolated background worker.
**No autonomous worker service has been deployed.**

Minimum separate staging settings (values are examples, not secrets):
- `AMICOR_ENVIRONMENT=staging` and `APP_ENV=staging`;
  never tolerate mismatched environment indicators.
- `NOVA_OPERATIONS_RECOVERABLE_CSV_ENABLED=true` **only after**
  isolated staging acceptance prerequisites are met.
- `NOVA_OPERATIONS_RECOVERY_WORKER_ENABLED=true` **only on**
  an approved dedicated staging worker, not the production API.
- `NOVA_OPERATIONS_STAGING_DB_APPROVED=isolated-reviewed` only
  after the dedicated database is separately verified.
- `NOVA_OPERATIONS_STAGING_DATABASE_URL`: secret URL for the dedicated
  Operations staging PostgreSQL database (must differ from `DATABASE_URL`,
  including when credentials differ).
- `NOVA_OPERATIONS_RECOVERY_OWNER_EMAIL`: verified owner email, looked up
  in the staging `platform_users` table; no seeded owner fallback.
- `PLATFORM_OPS_DOCUMENT_STORAGE=s3_private` and separately stored
  limited staging storage credentials; never copy production secrets.

Starting the process is **not sufficient** to prove recovery. Before
launching it, verify staging schema is present, the owner and engagement
records are isolated, storage permissions and encryption are verified,
and the worker's designated permissions are restricted.

The worker re-resolves the active owner each pass, rechecks the current
saved-assignment scope for every job, and stops when its configured owner
or database changes. It never transmits customer files. Run scripted
restart/reclaim tests with fictional data before considering it reliable.

The current worker is a foundation, not a hardened multi-tenant scheduler.
Further release requirements include an approved service deployment,
health monitoring, audited retention/orphan cleanup, lock-concurrency
observability, and human review before external delivery.
