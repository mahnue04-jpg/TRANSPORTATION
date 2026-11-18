# Nova Central journey read model — controlled staging schema plan

**Status: architecture / migration proposal only. NOT an executable migration.**
Prepared from draft PR #552, issue #542. No production or staging data change is authorized.

## Existing verified implementation

- `GET /api/nova/workspace/central/journeys` uses actual authenticated owner role, persisted user organization, signed JWT/cookie organization binding, and no-store response headers.
- `NOVA_CENTRAL_JOURNEY_READONLY_ENABLED=true` permits the empty readiness response.
- `NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED=true` *additionally* permits a journey preview exclusively in explicitly configured staging/test environments. Without both flags, there is no journey read.
- The proposed `central_read_model.py` SQLAlchemy table is NOT in `Base.metadata`, startup creates no table, and the read path fails closed on a missing table or query error.
- The proposed table is `nova_central_journey_read_model`. Composite key: (`organization_id`, `correlation_id`). Fields: `state`, `assigned_agent`, `owner_action`, `revision` plus the key. No name, email, phone, conversation, media URL, payload or payment details.

## The next code changes require separate review

1. **Isolated staging migration PR:** create the table ONLY in a verified disposable/staging database with an explicit migration; never add it to unconditional startup `create_all`. Confirm applicable Alembic heads and a downgrade/rollback strategy. A migration included in normal production `alembic upgrade heads` needs independent production impact assessment **before merging**.
2. **Producer and source-of-truth contract:** define who may project approved journey status from existing Growth, Work & Revenue, Operations, Creative Studio and HR events. Never copy personal data. Source references must be tenant-bound and audited, and the projector must not start without an explicit owner-approved deployment.
3. **Write rules:** validate state transitions; require idempotent (`organization_id`, `correlation_id`, `revision`) updates; reject stale revisions and cross-tenant writes; persist source-event provenance in a separately controlled audit store; use transactional outbox/replay semantics rather than simple in-memory assumptions.
4. **Retention, scope and access:** agree retention period, delete/erasure mapping, owner role, service principal scope, and whether support accounts are always excluded. No global administrator fallthrough to another tenant.
5. **Read limits:** preserve bounded response sizes (20 maximum), stable order, minimal five-field status projection, no-store/private responses, default-off feature flags and production denial.

## Staging execution acceptance (separate owner approval)

- Identify exact staging service, database, restore point, branch SHA, migration revision and maintenance/rollback instructions; verify no Studio SQLite/media/backend production DB overlap.
- Perform backup and **read-only preflight** of schema, Alembic state and version before any migration. Abort if the target could be production or if current heads are ambiguous.
- Apply the migration only following explicit approval; insert fictional records into staging through a controlled test fixture, not existing customer tables.
- Verify an authorized staging owner sees only their own fictional status, foreign organization sees 404/no records, staff/support receive 403, anonymous 401, expired/revoked/old-tenant tokens denied, production configuration denied even with flags on.
- Verify missing table 503, connection failure 503, no writes from GET, privacy/no-store headers, restart persistence, and no external messaging or charges.
- Keep flags disabled after acceptance unless separately approved; record evidence and rollback.

## Blockers before any live customer use

This PR does not include an approved migration, a populated staging table, a source-of-truth projector, durable provenance, an owner UI, or actual agent-to-agent job execution. Passing pytest and backend CI does not establish staging or production readiness. Do not merge or deploy for the purpose of testing until the exact staging resource and approval are documented.
