# Nova Workspace — authenticated read-only integration gate

**Status:** design-only review note for draft PR #546; NOT a production endpoint.

## Exact code inspected

- Draft Growth Workspace PR #517, `backend/app/auth.py`:
  `get_current_user_context` derives `UserContext` from an authenticated
  account and the current token role, while `require_any_role(ROLE_ADMIN,
  ROLE_SUPER_ADMIN_SUPPORT)` checks the JWT role against persisted authorized
  roles. It does not authorize an arbitrary synthetic `opaque_session`
  callback for a live API.
- Draft PR #517, `backend/app/core/nova/growth_agent/tenant.py`:
  `require_growth_owner` requires feature availability, a role dependency,
  matching `UserContext.role`, `user_id`, and `organization_id`. This code
  is NOT in PR #546's stack.
- Draft PR #517, `backend/app/core/nova/service.py`:
  `resolve_organization_scope` permits `super_admin_support` to request
  another tenant explicitly and can return `global` when tenant is absent.
  Any new *customer journey* endpoint must prohibit global reads and should
  not automatically grant tenant-owner access to support staff.

## Required production adapter design (future independent PR)

1. The FastAPI route must use the existing `get_current_user_context` and
   `require_any_role(ROLE_ADMIN)` dependencies (or a reviewed equivalent).
   Do not accept a user ID, organization, role, or agent identity from browser
   JSON or query strings as authority.
2. The server derives the exact organization from authenticated context and
   separately validates tenant membership as required by existing policy.
   Fail closed on missing org, global scope, support-only session, and
   mismatch. Request-supplied `organization_id` cannot override this.
3. Resolve the correlation ID in a **tenant-scoped durable store**, never the
   disposable SQLite test ledger. No joined real CRM records, PII,
   credentials, private media URLs, or raw payload references in the response.
4. Return a typed, minimal read-only projection (journey ID, status,
   responsible agent, pending owner action, event timestamps) with no
   write endpoints. Use feature flag default-off and same-origin authenticated
   requests; no public access.
5. Test anonymous (401), revoked/expired or role-invalid tokens (401/403),
   staff/support users (403), cross-tenant (403 or not-found),
   missing org/global scope, stale records, and status after restart.
   Perform tests using application dependencies with a disposable DB and
   explicit CI coverage; synthetic callback tests alone are insufficient.
6. Preserve existing Nova Core V1, Growth #490/#517 and Operations #477
   unmerged branches, Studio SQLite/media and production settings.
   No paid providers, real messaging, migrations or deployment without
   explicit owner approval.

## Release gate

Only after real HTTP authorization and tenant-scoped persistence pass CI
should an owner consider a **separate staging-only deployment approval**.
PR #546 currently validates a fake session verifier interface, not live JWT.
