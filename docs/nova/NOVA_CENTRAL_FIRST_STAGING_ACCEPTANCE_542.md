# Nova Central Intelligence — first staging acceptance gate (#542)

**Prepared for review only, 2026-11-17 CT.** No owner approval to merge, deploy, enable a feature, migrate data, or activate external services is implied.

## Exact verified code

- Draft PR #550 at `fedad2d6269961afb511a3ef815d3fc46a9ed6f5`.
- Read-only Workspace HTTP CI [run 44212457482](https://github.com/mahnue04-jpg/TRANSPORTATION/actions/runs/44212457482): **60 passed**, 11 dependency warnings, zero failures.
- Full Render backend diagnostic [run 44212457432](https://github.com/mahnue04-jpg/TRANSPORTATION/actions/runs/44212457432): both `qualification-regression` and `backend-diagnostic` passed.
- Current `GET /api/nova/workspace/central/journeys` is **default-off**, owner-only, tenant-bound by persisted user context and signed session organization, and returns `integration_status=not_connected` with **no** customer journeys. Successful responses carry `Cache-Control: private, no-store` and `Vary: Authorization, Cookie`.

## Dependencies / sequencing

1. Review stack in order: CI-only #547; Workspace default-off #548; synthetic tenant journey fixture #549; endpoint session-tenant hardening #550. Prior contract/synthetic PRs #544–#546 have separate bases and approvals. Verify current heads and conflicts before any merge plan.
2. Preserve Studio SQLite/media/backups and Growth/Work & Revenue/Operations existing data. No unreviewed migrations, R2 or PostgreSQL cutover, provider payment, real messages, auto-apply, or production routing.
3. A real journey source is **not implemented**. Design a durable tenant-scoped read model and migration in a separate PR, with owner-approved data retention, audit and rollback; do not connect the synthetic fixture to customer records or misrepresent dummy statuses.
4. The current endpoint's tenant check covers this route only. Audit JWT and cookie precedence, token issuance, organization changes, auth-version invalidation, and role/member lookup before enabling data reads. Test with ordinary and support accounts, real signed sessions, revoked sessions, and cross-tenant requests.

## Proposed isolated staging exercise (requires explicit owner approval later)

- Use **staging-only** service and disposable/approved test account records, never live customers.
- Back up staging database/media before changes; capture commit SHA, feature flags, DB target, and rollback steps.
- Deploy only approved PR heads, initially with `NOVA_CENTRAL_JOURNEY_READONLY_ENABLED=false`; verify 404/readiness, app boot and other regressions.
- With **separate explicit approval**, enable read-only feature for authorized staging owner; verify 200 `not_connected`, zero customer records, no-store headers, org mismatch 403, no-token 401, staff/support 403, role/auth-version invalidation and cookie behavior.
- Before any real journey store connection, verify tenant-bound immutable references, no PII in outputs, error handling, audit and restart recovery in disposable integration tests.
- Save owner screenshots/log references and exact results; leave feature off after testing unless the owner separately authorizes continued staging enablement.

## Do not confuse CI with readiness

Passing `60/60` is a solid code gate, **not** evidence of staging/live data flow, real multi-agent service coordination, usable Workspace UI, or revenue operations. Approval of merge or staging deploy must be requested as a separate action. Production activation is a later, distinct decision.
