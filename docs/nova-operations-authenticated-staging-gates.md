# Nova Operations Agent — Authenticated staging integration gate

Status: design and acceptance contract only; no production route activation.

## Existing code boundaries
- Work & Revenue API uses `require_nova_access` and `require_work_revenue_owner`; the owner check derives identity from `UserContext` and a DB-backed dependency.
- `operations_csv_api.py` has four disabled placeholder routes and is intentionally not registered. Its 503 responses must remain until a separate reviewed implementation.
- Draft PR #448 contains an offline SQLite approval ledger, assignment-to-job handoff, guarded claim, artifact review and read-only release eligibility. These helpers do **not** authenticate users or establish live permissions.
- Draft PR #447 contains offline evidence transitions; a mock owner decision or a mock transport receipt is not independent proof of a real action.

## Required authenticated execution design
1. At the HTTP boundary, run both `require_nova_access` and `require_work_revenue_owner`. Resolve tenant/org from the authenticated `UserContext` using the established `NovaCoreService.resolve_organization_scope` pattern; never use a client-supplied tenant as authority.
2. Load a server-owned Work & Revenue opportunity from the tenant-scoped database. Check its scope, status, payload fingerprint and immutable owner approval event. A string reference or a client-provided `reviewer_authorized=true` is **not** proof.
3. Persist approval, opportunity fingerprint and queue handoff in one production-grade transaction or equivalent durable outbox protocol. Reject mismatches and replay conflicts.
4. Claim only the exact approved job through the guarded path. All worker-entry paths must enforce tenant/job linkage; do not expose the generic offline `claim_job` to live customer requests.
5. Put customer files in tenant-private encrypted object storage. Verify content digest, size, ownership, authorization, malware/format limits and retention policy. Keep customer CSV bytes out of queue metadata and application logs.
6. Authenticate the reviewer at release time. Require an immutable, tenant-scoped review event and recheck the current deliverable digest. Store audit events for approval, processing, rejection, release eligibility and external delivery.
7. Release eligibility is not delivery permission. Introduce a separate owner-approved external delivery command, idempotent transport receipt capture, and deny-by-default policies.
8. The production enablement switch must be explicit, default-off, separately reviewed and separately owner-approved; staged tests alone must never enable it.

## Mandatory isolated staging acceptance checks
- Anonymous request: 401; authenticated non-owner: 403; wrong tenant: 403/404 without information leakage.
- Missing/forged/changed owner approval: denied before queue insert, including concurrent submissions.
- Duplicate approved request: exactly one job and exactly one handoff; changed input fingerprint: conflict.
- Stale lease and worker restart: old worker cannot complete; subsequent worker recovers only the intended tenant job.
- Corrupted approval, reviewer, job or storage linkage: fail closed without releasing or deleting files.
- Uploaded file survives restart and cleanup; cross-tenant list/read/download: denied.
- Finished output remains unavailable for external delivery before approved review; rejected result stays blocked after restart.
- Browser demonstration verifies upload, job state, review, protected download and audit events with **synthetic** files.
- CI, migrations, secure-storage configuration, rollback, observability and owner sign-off are documented before any production request.

## Launch blockers
- No verified production-grade authenticated assignment adapter is wired to the offline prototype.
- No real tenant-private storage + worker + retention + audit stack is verified end-to-end.
- The disabled API is not registered; the prototype is not a live service.
- No real customer data, external submission, deployment or paid provider activation is authorized by this document.

Owner approval here authorizes design and isolated staging-preparation work only; production activation requires a separate explicit decision.
