# Nova Operations Agent — authenticated CSV integration contract

Status: **implementation specification only**, not deployed. Companion to draft PR #448 and issue #452. Do not import the offline SQLite queue into the production API until production persistence, authorization, and privacy design are approved.

## Confirmed integration points
- `backend/app/core/nova/router.py` defines `/api/nova` with `require_nova_access` and uses `get_current_user_context` and `NovaCoreService.resolve_organization_scope` for tenant isolation.
- `backend/app/core/nova/work_revenue/router.py` provides existing `/api/nova/work` conventions, including `require_work_revenue_owner`, `get_db`, and upload handling. Reuse existing identity and owner checks, do not invent a separate authentication scheme.
- Draft PR #448 has offline SQLite job queue, CSV processing, atomic completion + artifact persistence, review state, and restart acceptance tests. It has no authenticated endpoints.

## Proposed API (not active)
- `POST /api/nova/work/operations/csv-jobs`: authenticated owner only; multipart CSV + request id; derive tenant from authenticated context, never request body; validate MIME, filename, UTF-8, max bytes/rows, CSV schema and permissions. Returns 202 job id + queued status; no synchronous paid provider execution.
- `GET /api/nova/work/operations/csv-jobs/{job_id}`: tenant-scoped state, progress, report counts and review state; 404 on cross-tenant resources.
- `POST /api/nova/work/operations/csv-jobs/{job_id}/review`: owner-only approve/reject with reviewer identity from session; audit decision; 409 if already reviewed.
- `GET /api/nova/work/operations/csv-jobs/{job_id}/download`: owner-only, tenant-scoped; require approved artifact, verified checksum, safe Content-Disposition, no caching of sensitive content, stream from authorized encrypted storage; 404 on cross-tenant resources.

## Mandatory architecture gates
1. Use existing SQLAlchemy/DB migration patterns and an authenticated tenant-scoped service; SQLite prototype is **not** production persistence.
2. Transactional outbox / durable worker claim and completion, idempotency per tenant, crash recovery and safe retries. Atomic state + artifact manifest commit; object bytes uploaded to temporary storage then committed/renamed with recovery reconciliation.
3. Store encrypted files outside the database, with short-lived authorized access, virus/type checks, retention/deletion and audit trail. Avoid logging CSV content or personal identifiers.
4. Owner approval does not authorize customer delivery, email sending, invoice recognition or payment recognition.
5. The existing CSV prototype protects cells starting with formula characters; verify edge cases including leading tabs/newlines, encoding and spreadsheet applications before production.
6. Keep all external integrations and paid providers OFF; never use real customer data in CI.

## Required tests
- 401 unauthenticated; 403 unauthorized reviewer; 404 cross-tenant job/artifact; 413 oversize; 422 malformed CSV; 409 duplicate idempotency with conflicting input.
- Synthetic end-to-end upload -> queued -> processing -> persisted artifact -> review -> checksum-verified download.
- Failure injection at object write, DB commit, worker restart, download and approval; no false completion or leaked files.
- Concurrent claim, retry limit, lease expiration and cancellation.
- Browser/mobile upload and download; staging smoke test with cleanup and rollback.
- All tests recorded against commit SHA, with CI green and explicit owner authorization before merge/deploy.

## Rollout
1. Review issue #452 and draft PR #448; decide target storage and schema with backend maintainer.
2. Implement service and migrations in an isolated feature PR, gated OFF by default.
3. Add API/router with existing authorization conventions; tests and staged fixtures.
4. Verify staging, security/privacy, data retention and rollback.
5. Seek explicit owner approval for merge and separate production deployment. Do not claim availability before verified deployment.
