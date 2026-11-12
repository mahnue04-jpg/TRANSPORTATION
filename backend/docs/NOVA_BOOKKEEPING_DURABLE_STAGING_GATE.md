# Nova bookkeeping durable integration — staging-only release gate

**Branch:** `nova/bookkeeping-durable-csv-integration-20261111`
**Parent:** `feat/nova-saved-task-selector-issue-476` (draft PR #477)
**Integration PR:** #484 (draft)
**Existing bookkeeping foundation:** PR #483, independently based on `main`

## What code exists

- Transaction, receivable and payable review-only CSV workpapers.
- Structured `BookkeepingAssignment` permission gate with separate
  `ai_assistance_permitted`, `data_processing_authorized`,
  `human_review_required`, and explicit allowed work types.
- Default-OFF `bookkeeping_durable_jobs` backed by the existing PR #477
  job metadata table and its S3-compatible private storage adapter.
- Accounting review output uses a separate namespace, owner/tenant-scoped
  idempotency, integrity hashes and approval/rejection transitions.
- Existing CSV cleanup status, review, download and stale-recovery methods
  reject bookkeeping job records; bookkeeping methods reject legacy CSV jobs.

## Known critical gaps — not authorized to deploy

1. **HTTP endpoints now committed, but default-OFF.** The registered owner-only router exposes bookkeeping submit, status, review and private download. Actual processing requires both disabled-by-default feature flags, reviewed PostgreSQL schema, verified contract/AI-consent records and an active owner task. No production permission is granted.
2. **No trusted consent-record integration.** The structured assignment object
   must be assembled from an authenticated, server-verified contract/engagement
   record, not client headers or a browser checkbox. Current app task labels
   are not sufficient proof of AI authorization.
3. **No immutable source authorization version persisted on job row.** The source/assignment hashes
   bind identity and input but do not prove consent or current contract scope.
   Contract changes and revocation handling remain to implement.
4. **No actual staging with PostgreSQL/private S3.** Added staging-only Alembic revision `20261111_nova_bk_consent`, gated by `NOVA_BOOKKEEPING_CONSENT_SCHEMA_APPROVED=staging-only` and consistent staging environment variables; no migration was applied. Current tests use
   synthetic SQLite + fake storage; do not confuse these with production.
5. **Synchronous processing.** A crashed request may remain PROCESSING; there
   is no restart-resumable worker, reliable storage cleanup or source re-upload.
6. **No independent certified bookkeeping review.** Draft accounting numbers
   are NOT financial statements, journal postings, tax returns, payroll,
   formal bank reconciliations or cash movement.
7. **No customer delivery.** Even approved results are owner-download only.
8. **No signed release approval**, no production schema changes, no live
   activation, no customer imports, no automated applications or contract
   acceptances.

## Validation plan

1. Run dedicated CI for the new private bookkeeping job code and legacy CSV
   regression suite; fix all regressions and note exact run IDs.
2. Add server-side contract schema/migration for verified AI rights, consent
   provenance, allowed work types, client data handling and revocation.
3. Implement authenticated owner route only after this source of truth exists.
4. Validate real organization/owner/task isolation, explicit consent gates,
   replay and collision behavior, rejection, download integrity, and expired
   processing recovery with synthetic accounts on isolated Render staging.
5. Verify Postgres migration on a disposable database using Alembic; test
   actual encrypted S3-compatible retention and verified deletion.
6. Ensure dual-branch dependency (PR #477) is reviewed and CI green; resolve
   PR #483's independent main-branch modifications without blind merging.
7. Seek explicit owner review of evidence, permissions, and deployment plan
   before any code merge, live flags, paid work or client data.

## BELAY-specific constraint

BELAY is assessing the individual's bookkeeping qualifications. The ability
to prepare accounting workpapers does not demonstrate professional experience.
Before using Nova on any BELAY client record, obtain written permission for
AI usage, subcontracting/business participation if applicable, and processing
outside BELAY-provided systems. Never submit personal screening work as an
AI-agent substitution or claim unsupervised accounting competence.


## Owner-only API (development branch, disabled by default)

- POST `/operations/durable/bookkeeping/engagements/{engagement_id}/tasks/{task_id}/{work_type}/jobs` accepts bounded UTF-8 CSV body, safe CSV filename, an idempotency key and, where required, as-of date; calls server-side contract scope resolver.
- GET `/operations/durable/bookkeeping/jobs/{job_id}` checks current consent before returning scoped status.
- POST `/operations/durable/bookkeeping/jobs/{job_id}/review` requires a boolean owner decision and rechecks consent.
- GET `/operations/durable/bookkeeping/jobs/{job_id}/download` rechecks consent, hashes the private artifact and returns a review-only download with no-store headers.

Both `NOVA_BOOKKEEPING_DURABLE_ENABLED` and the inherited
`NOVA_OPERATIONS_DURABLE_CSV_ENABLED` must be enabled for successful
processing, alongside actual PostgreSQL and S3-private configuration.
**Neither is being enabled in this development pass.** There is no
application UI workflow yet. No customer deliverables are automatically sent.

The new resolver uses a separately verified consent table as the exact
task/work-type binding for existing saved tasks that do not yet have a
structured finance work-type column. A contradictory structured task type
is rejected. The legacy text-label CSV task gate alone cannot authorize
financial work.

## Remaining staging acceptance evidence

- Use a disposable PostgreSQL instance and execute the real Alembic upgrade.
- Verify expired, revoked, missing, cross-owner, altered task ID and
  changed agreement permissions at the *HTTP* layer.
- Ensure the consent-record provisioning process validates actual signed
  documents, records reviewer identity and revocation, and is auditable.
- Verify authenticated browser sessions, CSRF controls, private encrypted
  S3 retrieval, retention and erasure, interruption and orphan cleanup.
- Compare actual financial workpaper outputs against independently reviewed
  expected results, including edge cases and rounding.
- Resolve the upstream PR #477 draft dependency. No deploy or merge without
  explicit owner approval.

## Synthetic interruption and persistence tests (2026-11-11)

- Added file-backed synthetic restart test: reopen SQLite metadata and fake private storage, verify digest and owner isolation, approve for download, then reopen again to verify state persistence.
- Added bookkeeping-only stale PROCESSING recovery after 15 minutes: marks FAILED, never retries work or delivers files, and rejects different owners.
- The recovery API checks current signed consent and task scope before marking an accounting job failed.
- These synthetic checks are NOT actual PostgreSQL/S3 staging evidence. Feature flags remain OFF.

## Render verification boundary

Render connector requires explicit workspace selection before resource inspection. No workspace selected, database queried, deploy triggered, or environment changed during this work.

## Render read-only inventory and synthetic HTTP regression (2026-11-11)

- Read-only inventory of Saye's Render workspace identified `amicor-prod` (production PostgreSQL) and `amicor-casting-staging-db` (separate casting staging PostgreSQL). Neither is an approved accounting staging database.
- Service inventory included `amicor health isf PR #483` preview but no PR #484 bookkeeping integration service in the returned results. A PR #483 preview cannot prove PR #484 integration is deployed.
- Existing Render backend diagnostic workflow for earlier PR #484 commit failed in a Creative Studio scene timeout/rendering test while the operations CSV jobs passed. This is a separate concern, not proof of bookkeeping deployment.
- Added synthetic FastAPI `test_nova_bookkeeping_synthetic_http_flow.py`: submit invented invoice CSV, duplicate request replay, status, cross-owner access denial, consent revocation denial of submit/status/review/download/recovery, then simulated owner approval and protected download.
- CI run 43063656323 passed 32 pytest and 6 unittest authorization checks; three-task synthetic operator job completed again. It validates a mocked signed-in user and mocked consent resolver, not an actual identity provider or signed agreement.
- No customer processing, production modification, Render resource creation, migration or deployment occurred.

## Next release gate

Require separately approved dedicated accounting staging PostgreSQL and private storage, verified contract consent records, real login sessions, staged migration, retention controls, and approval before changes to live services.


## Ephemeral PostgreSQL verification (2026-11-11)

- Added `backend/tests/test_nova_bookkeeping_postgres_ci.py` and an isolated `postgres:16` GitHub Actions service.
- Both actual staging-gated Alembic upgrade implementations were executed against a disposable loopback PostgreSQL database, with real table/index/uniqueness inspection.
- Three PostgreSQL-specific tests passed: persisted accounting review, same-key idempotency, owner isolation, exact work-type gating, synthetic consent expiry and revocation.
- The existing synthetic suite and three invented operator tasks also passed in CI run 43091269711.
- Important separation: this is actual PostgreSQL behavior in GitHub Actions, but storage remains a fake in-memory object store, Work & Revenue saved engagement reads are mocked, and the records are invented. It is not Render staging, real client authorization, or production readiness.
- Outstanding release blockers remain real Render-isolated accounting DB, encrypted S3 storage, real login/session, signed-consent provisioning and revocation race tests, private retention/orphan cleanup, and an approved deployment plan.


## Expanded PostgreSQL HTTP and concurrency verification (2026-11-11)

- New integration test exercises actual FastAPI bookkeeping routes backed by disposable PostgreSQL consent and job metadata, while only the signed-in identity, Work & Revenue engagement lookup and object store are synthetic doubles.
- Test performs create/replay/status/download/approve; revokes the consent row directly in PostgreSQL, then verifies that submit/status/download/review/recover all fail closed. It tests missing evidence fingerprints and conflicting task accounting work types.
- Added a separate two-connection concurrent request test for exactly one accounting workpaper and a single persisted job on the PostgreSQL unique constraint.
- Distinguish these test findings from actual Render staging, customer identity provider, signed client permissions and encrypted persistent object storage, which remain unverified. No release enablement or migrations on Render.


## Accounting approval integrity and permission revalidation (2026-11-11)

- Owner approval now verifies that the private workpaper is retrievable and its SHA-256 digest equals the recorded artifact digest before changing a job to APPROVED_FOR_DOWNLOAD. Missing or altered artifacts fail closed and leave the job awaiting review.
- The bookkeeping intake route re-resolves server-side scope after the CSV body has streamed and immediately before job insertion, preventing stale permission from an upload-length delay. A simulated revocation between checks must prevent any stored job or workpaper.
- Added synthetic and PostgreSQL regressions for tampered artifact approval, plus an HTTP synthetic revocation-during-upload regression. They do not replace signed consent validation, real object storage, or a concurrency-safe consent transaction model in Render staging.
- Existing current-consent checks remain mandatory on status/review/download/recovery. Approval does not deliver a client file or move money.


## Consent revocation serialization hardening (2026-11-11)

- The PostgreSQL-backed consent resolver now supports optional `FOR UPDATE` row locking. Accounting API finalization uses this lock in the same database transaction as the job transition from PROCESSING to AWAITING_REVIEW. Review and private download also lock current consent during their operations.
- Ingestion validates consent before receiving CSV, after streaming, and again immediately before final job-state commit (following private artifact storage). If consent is revoked during private storage, processing fails closed and attempts to delete the generated private artifact; no draft is approved or delivered.
- Added a two-session disposable PostgreSQL test where concurrent consent revocation waits until the authorization lock commits, then blocks subsequent processing. Also added a synthetic revocation-during-storage test and updated the test consent resolver to accept the locking interface.
- Limitation: this ensures row-level serialization in tested PostgreSQL transactions; it does not replace actual signed consent verification, complete job audit/permission versioning, durable private storage deletion, or an approved isolated Render staging acceptance run.



## In-process private S3 adapter verification (2026-11-11)

- Added synthetic S3-compatible tests using Moto + boto3 with the production `S3PrivateDocumentStorage` adapter (not merely an in-memory replacement for its interface).
- Test requires S3 object `ServerSideEncryption=AES256`, private metadata, bucket public-access blocking, strict object retrieval, owner-review workpaper round-trip and deletion. No real cloud credentials or customer information are used.
- Added failure-path test: consent is denied after private S3 write but before review finalization. It must mark the job FAILED and delete the newly created object.
- Actual Render staging S3 credentials, bucket policy, encryption-at-rest enforcement, versioned deletes, retention and lifecycle remain UNVERIFIED. This new Moto test must not be presented as a real S3 deployment or client-readiness certification.


## Automated default-deny accounting staging preflight (2026-11-11)

Added `bookkeeping_staging_preflight.inspect_staging_readiness`, a read-only
acceptance gate designed for an **operator-confirmed isolated staging** scope:

- Rejects production or mixed production/staging environment labels.
- Requires bookkeeping and durable CSV execution flags to remain off while inspecting.
- Rejects any non-`s3_private` storage selection, absent bucket security,
  missing bucket default server-side encryption, absent PostgreSQL schema, or
  missing confirmed signed-client-AI-consent process.
- Inspects database schema only with an explicitly supplied engine and
  verified isolated staging identity; does not provision a database or schema.
- Inspects S3 bucket settings only through an explicitly supplied operator
  client. No object listing, data reads, writes, deletions, or credentials
  are logged or generated by the preflight.
- Always returns `production_release_authorized: false` and
  `customer_data_allowed: false`, even if all checks can be inspected.
  It is an evidence collection gate, never a deployment command.

Validation:
- Pure negative tests exercise missing config, mixed/production environment,
  missing staging confirmation, missing infrastructure and enabled flags.
- Separate disposable PostgreSQL test inspects both actual migrated tables but
  remains blocked on unverified storage/consent.
- Moto S3 tests verify a bucket with blocked public access and default AES256
  encryption, and reject buckets without default encryption.
- CI verification must be checked independently from the source commits.
- The real Render workspace's `amicor-prod` or casting DB must never be used
  for accounting staging. A dedicated staging database and approved private
  bucket are still prerequisites, not implicit permissions to create them.


## Retention and orphan-risk inventory (2026-11-11)

Implemented `bookkeeping_retention.plan_bookkeeping_retention` to support
future human-reviewed data cleanup decisions without doing the cleanup.
The operator must specify exact organization and owner scope, a finite
retention age, and a known database session. The inventory is capped at
500 older rows to prevent unbounded scans. It returns aggregated counts
for terminal review, active-review holds, malformed reference/hash metadata,
missing private references, and unknown statuses, without returning customer
data or storage object keys.

**All outputs are dry run**: `objects_deleted=0`,
`database_rows_changed=0`, and `deletion_authorized=false`.
Even terminal approved/rejected jobs are *not* automatically eligible for
erasure. Actual retention decisions depend on client contract terms, signed
consent, legal holds, and an approved S3 lifecycle/verification procedure.
S3 orphan object detection is not inferred from metadata and remains a
separately blocked release gate.

Tests cover exact tenant/owner isolation, age cutoff, disabled deletion,
malformed metadata, strict batch limit and missing scope. A separate
disposable PostgreSQL test checks query behavior and unchanged rows.
These tests do not represent retention policy approval or a real storage
inventory. No Render configuration or customer records were used.


## Owner accounting review queue — development only (2026-11-11)

- Added bounded `list_owner_bookkeeping_reviews` (default 25, maximum 50)
  and owner-only GET `/operations/durable/bookkeeping/review-queue`.
- Returns job ID, engagement ID, task ID, bookkeeping work type, review
  status, and one next operator action. It never exposes CSV content,
  storage keys, source/output hashes, request keys or financial amounts.
- Every candidate job is checked against the currently active server-side
  consent/engagement/task resolver before appearing in the queue. Revoked
  and wrong-owner records are excluded. A queue result cannot authorize
  a future action; review and download endpoints revalidate separately.
- Synthetic FastAPI tests verify consent filtering and data minimization.
  Disposable PostgreSQL HTTP tests verify that revoking the real CI
  consent row removes the previously visible job from the queue.
- The queue remains gated by default-off bookkeeping processing and has
  not been enabled in Render or for customer financial data. A production
  operator UI has not been delivered.
