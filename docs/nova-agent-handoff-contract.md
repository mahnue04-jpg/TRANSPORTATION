# Nova agent handoff contract — design draft

Status: **proposal only** (2026-11-14). Parent issues: [#496](https://github.com/mahnue04-jpg/TRANSPORTATION/issues/496), [#497](https://github.com/mahnue04-jpg/TRANSPORTATION/issues/497). Existing Growth Agent implementation: draft [PR #490](https://github.com/mahnue04-jpg/TRANSPORTATION/pull/490). No runtime integration or deployment is asserted by this document.

## Goal and first verified slice
Pass a **synthetic** visitor's consented inquiry from the Growth Agent intake/CRM boundary to the Nova Workspace owner review queue, then to an authorized Operations Agent work intake. Show the same correlation ID through every stage. Creative Studio campaign assets may be associated by an actual validated ID only once a real interface exists; otherwise the UI must show **planned / not connected**.

## Systems of record (to validate against code before implementation)
| Record | Proposed owner | Consumer | Boundary |
|---|---|---|---|
| Inquiry, consent/opt-out, lead, conversation, appointment | Growth Agent | Workspace owner dashboard | Tenant-scoped authenticated read |
| Pending approval, decision, operator, audit trail | Workspace approval service (new if absent) | Agent coordinator | Explicit owner authorization |
| Authorized job intake and output artifacts | Operations Agent | Workspace owner dashboard | Only after approval; exact-API mapping required |
| Generated media, assets and creative project state | Creative Studio | Marketing attribution only | Read-only verified asset reference; do not touch SQLite/media |
| Approved business FAQs, service/pricing policy | A versioned business-knowledge service (design target, not yet implemented) | Growth Agent, Operations | Approved revision and tenant scope |

**Discovery gate:** Before code, identify existing route names, storage ownership, schemas, authenticated service identity and tenant enforcement. Do not assume these target interfaces exist. Prefer existing APIs over duplicate records. Avoid a general memory store of unfiltered customer messages.

## Proposed exchange envelope (not an existing API)

```json
{
  "schema_version": "nova.handoff.v1",
  "tenant_id": "synthetic-tenant-001",
  "correlation_id": "synthetic-journey-001",
  "event_id": "synthetic-event-002",
  "source_system": "growth_agent",
  "source_record_id": "synthetic-lead-123",
  "target_system": "workspace_approval",
  "action_type": "review_consultation_request",
  "data_class": "synthetic",
  "consent_reference": "synthetic-consent-123",
  "business_knowledge_revision": "approved-fixture-v1",
  "approval_policy": "owner_required",
  "idempotency_key": "synthetic-tenant-001:consultation:synthetic-lead-123:v1",
  "status": "pending_approval",
  "attempt_count": 0,
  "created_at": "2026-11-14T17:00:00Z"
}
```

All identifiers and timestamp in the example are **illustrative synthetic fixtures**. This envelope is not permission to copy private contact information across systems. The receiving service must re-check principal authorization, tenant match, consent scope and action-specific policy. Derive tenant identity from authenticated context, not from a user-controlled request body. Data payload schemas should be separately versioned and limited to necessary fields. Do not place tokens, bank details, secrets or full contact data in audit/event logs.

## State machine and audit
Suggested statuses: `received` -> `validated` -> `pending_approval` -> `approved` / `rejected` / `expired` / `needs_details` -> `dispatching` -> `completed` / `retryable_failure` / `terminal_failure`. A `paused` state must prevent new dispatch; an explicit, audited resume must re-validate approval and consent. Reject unexpected transitions.

Only an authenticated owner can authorize consequential dispatch. Approval records must bind tenant, action, payload hash/revision, operator identity, timestamp, expiry, and one-time decision token. A changed payload or expired approval requires a new review; a UI button alone is not approval. Record before and after state, attempt count and safe error category without logging personal details.

## Idempotency, recovery and isolation
1. Enforce uniqueness of `tenant_id + idempotency_key + action_type` in durable storage, using transactional claim/lease semantics. Detect replay and prevent duplicate booking, messaging, invoice, paid render or payment.
2. Retries must check persisted completion status and current opt-out/consent, pause state, approval freshness, and feature mode. Only retry explicitly safe operations; use capped exponential backoff and dead-letter/owner escalation.
3. Deny cross-tenant reads, handoffs and approval decisions. Client-provided tenant IDs cannot override authenticated server-side tenancy.
4. Keep `synthetic`, `staging` and `live` modes clearly distinct. Never allow a synthetic event to trigger live transports.
5. Expose a recoverable audit chain from website source/UTM (if actually present), lead, request, approval, dispatch and outcome. Unknown attribution remains `unknown`.
6. Protect PII with least-privilege access, limited retention and redaction; define any deletion/migration separately and require safeguarding existing backups.

## Integration order
- **Discovery:** map exact Nova Workspace nav/session/tenant routes, Growth Agent PR #490 backend, Operations API, Studio asset interfaces and persistent storage. Record current behavior and missing APIs. Preserve Studio staging and data.
- **Read-only:** owner-authenticated overview/inbox, synthetic fixtures, no fabricated KPIs.
- **Review:** durable approval/decline/needs-details with audit; fail closed.
- **Mock handoff:** consented synthetic lead -> consultation request -> owner-approved Operations intake using existing supported API or a clearly marked fake adapter.
- **Browser test:** confirm mobile owner review, duplicate/replay denial, tenant isolation, expiry/revocation, restart recovery, failure handling and correlation across records.
- **Release review:** separately request owner approval for isolated staging deployment; only after staging acceptance consider live site, email/SMS, billing, paid providers, customer outreach or production.

## Test evidence required
- Unit: envelope validation, unknown schema rejection, tenant mismatch, missing/withdrawn consent, unauthorized owner, expired/changed approval, duplicate idempotency key, invalid transitions.
- Integration: one end-to-end synthetic intake-to-approval-to-mock-operations journey and audited status; repeat the same event across restart with no duplicate side effect.
- Browser: desktop and mobile; explicit mock/live labels; disabled not-yet-connected Creative Studio links; failed/empty/retry states.
- Report: exact branch/commit, test command and passed/failed/skipped counts, routes verified, screenshot or trace evidence, blockers and one next action. Do not claim operational integration from documentation alone.

## Explicit exclusions
No changes to paid Kling/fal, R2, PostgreSQL migration, Studio SQLite/projects/media/backups, production or existing Render staging. Do not merge PR #490/#515, deploy, spend, send outreach, post marketing, charge, invoice, accept commitments or activate live transports under this document.
