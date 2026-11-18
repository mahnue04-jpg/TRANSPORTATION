# Nova Workspace owner authorization bridge — review checklist (#542)

Status: **draft design only**. No runtime wiring, endpoints, production permissions,
migrations, deployment or paid/live-provider activation.

## Verified source baseline (2026-11-17)

- PR #544 `feature/nova-agent-event-contract-542`: versioned `AgentEvent`
  envelope and route allowlist; CI 16/16 on `ce3c393`. Its consent/approval fields
  are **reference strings**, not validated entitlements.
- PR #545 `feature/nova-synthetic-handoff-542`: isolated disposable harness,
  SQLite replay ledger and read-only status projection; 33/33 isolated tests on
  `8dc6e33d`. Test principals and consent/approval fixtures are not authenticated
  user or organization records.
- PR #517 `e23e268f` (draft, based on Growth Agent #490): proposed
  `require_growth_owner` uses an authenticated `UserContext` and
  `require_any_role(ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT)`. Growth `counts`
  endpoint resolves organization context and queries filtered organization counts.
  Its read-only Workspace JS fetches `health` and `counts` using session
  authentication. **This is an existing candidate boundary, not approval to
  import or merge the draft directly.**
- PR #517 separately changes `render-backend-diagnostic.yml` Python pin
  from `3.11.9` to `3.11`; do not quietly copy unrelated CI changes into
  the integration branch. Confirm runner matrix and backend compatibility first.

## Required bridge before real reads/writes

1. Authenticate from server-side session or signed service principal and derive
   organization from trusted auth context. Never trust client-supplied
   `organization_id`, role, or `source_agent` without server verification.
2. Centralize authorization at Workspace endpoints: privileged owner/admin
   role **AND** membership/authorization for the specific organization; support
   least-privilege service identities separately. Avoid treating global support
   access as automatic tenant-owner access.
3. Map the canonical correlation ID to each product's existing tenant-scoped
   record by reference; do not duplicate CRM/customer tables or join product
   databases directly. Consent must be checked against a trusted, current
   record and scoped to the action. Approval must bind owner, tenant,
   subject, action, expiry, and single-use/revocation rules.
4. Make read-only status queries explicitly scoped to the verified tenant,
   return only permitted journey metadata, and avoid returning payload
   references or customer PII. Return 401/403 for unauthorized requests.
5. Provide a durable transaction/outbox/retry design separately from the test
   fixture. Persist audit, dedupe and state transitions atomically and verify
   actual restart behavior with disposable integration infrastructure.
6. No live sends, marketing publication, payments, signing, human assignment
   or paid generation without action-specific approval.

## Acceptance gates for a future separate draft PR

- Negative HTTP tests: anonymous, wrong role, role-context mismatch, wrong
  organization, nonexistent/forged service identity, and cross-tenant reads.
- Provenance tests: missing/revoked/expired/wrong-scope consent and approval.
- Persistence tests: duplicate delivery, restart, stale event, partial failure,
  concurrent claims, and no duplicate execution.
- A browser exercise showing owner-only journey metadata and pending approvals.
- Exact source SHA, CI links, data isolation plan, rollback plan, and owner
  acceptance recorded **before** considering merge or staging deployment.

Do not portray the isolated green pytest suite as verification of actual
Workspace authorization or a customer-ready integration.
