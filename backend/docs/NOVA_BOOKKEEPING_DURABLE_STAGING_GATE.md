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

1. **No HTTP endpoint registered.** No client can access accounting jobs today.
2. **No trusted consent-record integration.** The structured assignment object
   must be assembled from an authenticated, server-verified contract/engagement
   record, not client headers or a browser checkbox. Current app task labels
   are not sufficient proof of AI authorization.
3. **No source authorization version persisted.** The source/assignment hashes
   bind identity and input but do not prove consent or current contract scope.
   Contract changes and revocation handling remain to implement.
4. **No actual staging with PostgreSQL/private S3.** Current tests use
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
