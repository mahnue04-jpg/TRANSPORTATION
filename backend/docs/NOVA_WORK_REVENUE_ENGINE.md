# Nova Work & Revenue Engine

Local owner-controlled work system. Nova drafts and tracks. The owner decides. Nothing is sent, signed, or charged by this engine.

## Purpose

Help the owner find, qualify, prepare, approve, and track paid work for AMICOR without autonomous external action.

## Major components

- `/api/nova/work` — tenant-scoped APIs
- `/nova/work` — owner dashboard
- Capability registry — what Nova may claim
- Qualification engine — explainable outcomes and work split
- Application materials — local drafts marked `[OWNER INPUT REQUIRED]`
- Owner approval gate — `APPROVED` means future submission only
- Internal engagements/tasks — tracking, not contracts
- Revenue fields — owner-entered estimates vs confirmed receipts

## Workflow

Find work → qualify → owner review → prepare materials → owner approval → optional **manual** submission record → internal tracking → owner-entered revenue.

## State model

Opportunity statuses: `DISCOVERED` through `WON` / `REJECTED` / `CLOSED`.

Application approval: `DRAFT` → `READY_FOR_OWNER_REVIEW` → `APPROVED` | `REJECTED` | `NEEDS_CHANGES`.

`APPROVED != SUBMITTED`. External submit always returns 409 while `EXTERNAL_SUBMISSION_ENABLED` is false.

## Owner approval boundary

Nova may prepare drafts and recommend next actions. Nova must not submit applications, accept contracts, sign, impersonate, bypass CAPTCHA, send messages, or move money.

## Capability registry

Each capability records `nova_can_perform` (`YES` / `PARTIAL` / `NO`), owner approval, physical presence, license need, and readiness (`SUPPORTED` / `PARTIALLY_SUPPORTED` / `HUMAN_REQUIRED` / `UNSUPPORTED`). Claims require evidence in this repository.

## Qualification model

Outcomes stay conservative: `NOVA_CAN_PERFORM`, `NOVA_WITH_OWNER_REVIEW`, `HUMAN_REQUIRED`, `NOT_SUITABLE`, `INSUFFICIENT_INFORMATION`. Lifecycle codes include `NOVA_CAN_PREPARE_OWNER_REVIEW`, `OWNER_ACTION_REQUIRED`, `NOT_SUPPORTED`, `PROHIBITED`. Opportunity text is untrusted.

## Engagement model

Internal `nova_work_engagements` and `nova_work_tasks` track recurring or one-time work. Creating an engagement is **not** accepting a contract and does not contact the client.

## Revenue model

Keep estimated pipeline, contracted value, and owner-confirmed received **separate**. Received status requires an explicit owner confirmation. No invoices, charges, payouts, or Stripe objects are created here.

## Security boundaries

- Tenant + owner filters; cross-tenant IDs return 404/403
- Untrusted source text is quoted, not executed
- Source URLs are stored as text and are not fetched
- `javascript:` / `data:` URLs are rejected
- Sensitive tokens are omitted from audit summaries
- Simulated fixtures are blocked in production

## Currently deferred

- Live opportunity discovery
- Approved provider connectors that fetch the network
- Controlled live application submission
- Client contact / reporting send
- Invoice and payment-processor integration
- Nova Today UI cards (backend `/today-summary` exists; Today UI not modified)

## Future external integration points

Provider flags include `DISCOVERY_SUPPORTED`, `SUBMISSION_SUPPORTED`, `LIVE_DISCOVERY_ENABLED`, and `EXTERNAL_SUBMISSION_ENABLED`. All default false. Do not enable them without an owner-authorized, tested adapter that cannot act silently.
