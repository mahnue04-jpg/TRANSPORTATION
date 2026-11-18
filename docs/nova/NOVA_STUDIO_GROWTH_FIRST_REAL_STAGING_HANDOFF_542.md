# Nova Central Studio → Growth: first real staging handoff contract

**Status:** Design and approval boundary only; no new HTTP route, SQL schema, migration, service connection, customer data use, publication, or deployed integration.

## Verified repository surfaces

- Creative Studio's `backend/app/core/nova/creative_studio/router.py` has authenticated project and asset routes, but **no endpoint that persists an owner-approved share-to-Growth authorization**.
- `CreativeStudioStore` and `DbCreativeStudioStore` provide `get_project(project_id, owner_id)` and `list_assets(project_id, owner_id)`. `CreativeAsset` has `id`, `owner_id`, `project_id`, `kind`, `status`; successful generated media uses `GENERATED` (not `completed`).
- Growth Agent's draft PR #490 `backend/app/core/nova/growth_agent/router.py` has `/profile`, `/leads`, `/consent`, `/workflows/preview` and synthetic demo, **but no campaign-asset intake endpoint**. `GrowthAgentService.get_profile(org_id)` includes `configured`, `organization_id`, `is_synthetic_demo`, `activated`, `agent_disabled`; it may also include private contact details that must not cross this boundary.
- The default-off pure contract `studio_growth_adapter.py` and synthetic first-customer acceptance tests are in draft PR #545. Passing tests are **not** proof of deployed service trust.

## Phase 1: explicit owner share grant, prepared as a separate draft (do not migrate yet)

Proposed grant record with dedicated, isolated schema and no automatic application startup creation:

| Field | Required rule |
|---|---|
| `grant_id` | Opaque unique ID; never a credential |
| `organization_id` | Server-verified tenant ID |
| `owner_user_id` | Persisted authorized owner who approved |
| `project_id` / `asset_id` | Must resolve by owner-scoped Studio storage |
| `campaign_id` | Opaque stable reference, no customer name |
| `action` | Exact value `share_campaign_asset_with_growth` |
| `approved_at` / `expires_at` | UTC timestamps; positive bounded lifetime |
| `revoked_at` | Null unless explicitly revoked |
| `status` | `approved` or `revoked`, with audited change |
| `idempotency_key` | Unique per tenant/action/asset approval transaction |
| `schema_version` | `nova.studio-growth-grant.v0.1` |

Never accept a request-body `approved=true` as proof. The owner-only create/revoke route, if later approved, must authenticate a persisted account and tenant and check `owner_id`; write an auditable, transactionally unique grant and refuse replays, forgery, expiry, revocation, wrong project, cross-tenant data and unapproved assets. Schema writer/migration identity must not be a Studio or Growth runtime account.

## Phase 2: read-only server-side handoff preparation

Proposed server operation (not implemented in this PR):

1. Require a signed, service-scoped principal and server-selected tenant; never trust a supplied principal/tenant header. Do **not** reuse public Growth widget credentials for this.
2. Fetch Studio project by `get_project(project_id, owner_id)` and asset via `list_assets(project_id, owner_id)`, require exactly one result, `status=GENERATED` and allowed `kind`.
3. Read the **persisted** grant from a trusted tenant-scoped repository, require correct owner, matching project/asset/campaign, action, signature of approval event if used, unexpired and not revoked.
4. Read Growth Agent's business profile in the **same tenant**. For synthetic acceptance require `configured=true`, `is_synthetic_demo=true`, `activated=false`, `agent_disabled=true`. This read must be authenticated server-side; client profile JSON cannot establish trust.
5. Generate only the `ASSET_READY` metadata envelope and synthetic read-only preview, not full media, customer data, outreach content or a lead record. Idempotency must be tenant- and campaign-scoped and race-safe in a durable staging ledger.
6. Return `integration_status=preview_only`, `lead_created=false`, `messages_sent=false`, `published=false`, `customer_data_connected=false` with `Cache-Control: private, no-store`.
7. Capture a redacted correlation ID, tenant, grant ID, actor ID and outcome in an audit trail; no secret, customer, video byte, arbitrary URL or token in logs.

## Phase 3: future Growth campaign ingest

Separate **new** owner-authenticated internal contract is required; not `/widget/chat`, `/consent`, or `/workflows/execute`.

Proposed future preview route: `POST /api/nova/growth-agent/internal/campaign-assets/preview` (staging only, default-off, read-only). Contract should take a server-verified, scoped Nova event ID or grant ID and resolve that reference itself; **never** accept arbitrary customer/profile/media data as trusted values.

The real ingestion/write route, if eventually approved, needs its own transactional data model, tenant-scoped dedupe, consent provenance, replay protection, expiry/revoke, operational health checks, dead-letter recovery and rollback. Explicit owner approval is mandatory before any customer outreach, ad publication, paid media or provider call. Work & Revenue and Operations should remain behind the existing owner approval boundary.

## Acceptance criteria before staging activation

- Exact approved source heads for Studio, Growth PR #490 and Nova PR #545; coherent merge/dependency review.
- Isolated staging service identity, verified database/resource IDs, network/secret isolation and owner-approved test window.
- Dedicated migration for grant storage with independent backup/restore; no Studio SQLite migration or media overwrite.
- Tests against **real** signed server principal, Studio persisted owner/asset records and persisted grants: wrong tenant, wrong project, forged approval, expired/revoked approval, duplicate/parallel requests, missing Growth profile, profile activated or real, restart, no-write/no-outbound behavior.
- Observe a **real staging-only** Studio → Growth preview with fictional test data; record exact logs and restore/teardown evidence.
- No merge/deploy/migration/provider activation until a separate explicit approval identifies resources and maximum spending.

**Decision now: NO-GO for real handoff.** The test-only synthetic path is verified; server-backed approval storage and Growth campaign intake are not implemented.
