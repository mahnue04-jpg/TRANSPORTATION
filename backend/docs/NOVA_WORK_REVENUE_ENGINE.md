# Nova Work & Revenue Engine

Local owner-controlled work system. Nova drafts and tracks. The owner decides. Nothing is sent, signed, or charged by this engine.

## Purpose

Help the owner find, qualify, prepare, approve, and track paid work for AMICOR without autonomous external action.

## Major components

- `/api/nova/work` — tenant-scoped APIs
- `/nova/work` — owner dashboard
- `/nova/today` — informational Work & Revenue cards
- Capability registry — what Nova may claim
- Qualification engine V2 — structured evaluations, no win scores
- Owner/business fact catalog — missing vs verified vs not applicable
- Application materials — local drafts marked `[OWNER INPUT REQUIRED]`
- Owner approval gate — `APPROVED` means future submission only
- Internal engagements, tasks, deliverables — tracking, not contracts
- Revenue entries — owner-entered stages, never a payment processor

## Lifecycle

```
DISCOVER → QUALIFY → PREPARE → OWNER REVIEW → APPROVE
→ MANUAL/EXTERNAL HANDOFF → ENGAGEMENT → WORK EXECUTION
→ DELIVERABLE → INVOICE SUPPORT → PAYMENT STATUS
→ REVENUE RECONCILIATION → ARCHIVE
```

This is an internal state model. Nova does not execute the external steps.

## State machines

Opportunity statuses: `DISCOVERED` through `WON` / `REJECTED` / `CLOSED`.

Application approval: `DRAFT` → `READY_FOR_OWNER_REVIEW` → `APPROVED` | `REJECTED` | `NEEDS_CHANGES`. Aliases: `CHANGES_REQUESTED` → `NEEDS_CHANGES`, `APPROVED_FOR_FUTURE_SUBMISSION` → `APPROVED`.

Task statuses: `NOT_STARTED` / `READY` / `IN_PROGRESS` / `OWNER_REVIEW` / `BLOCKED` / `COMPLETE` / `CANCELLED`. Aliases: `TODO` → `NOT_STARTED`, `DONE` → `COMPLETE`.

Deliverable: `DRAFT` → `READY_FOR_REVIEW` → `OWNER_APPROVED` → `CONFIRMED_DELIVERED`. **Delivered requires owner confirmation. Nova does not transmit files.**

Revenue stages: `ESTIMATED` → `QUOTED` → `CONTRACTED` → `INVOICE_DRAFT` / `INVOICED_EXTERNALLY` → `PAYMENT_PENDING` → `PARTIALLY_PAID` / `PAID`. `PAID` cannot be created directly and cannot be reached silently.

## Owner approval boundary

Nova may prepare drafts and recommend next actions. Nova must not submit applications, accept contracts, sign, impersonate, bypass CAPTCHA, send messages, or move money.

**APPROVED != SUBMITTED.** External submit always returns 409 while `EXTERNAL_SUBMISSION_ENABLED` is false.

## Nova capability boundary

Nova may assist with authorized digital drafting, organization, and summarization. Nova may not invent experience, certifications, references, or pricing. Missing facts stay `[OWNER INPUT REQUIRED]`.

Qualification decisions: `NOVA_CAN_PERFORM`, `NOVA_CAN_PREPARE`, `OWNER_ACTION_REQUIRED`, `INSUFFICIENT_INFORMATION`, `NOT_SUITABLE`, `NOT_SUPPORTED`, `PROHIBITED`. Stored Phase 1 outcomes remain compatible.

## Tenant isolation

Every query is organization-scoped and owner-filtered unless the caller is an org-wide admin. Cross-tenant IDs return 404 or 403. This applies to opportunities, applications, engagements, tasks, deliverables, owner actions, revenue entries, and audit events.

## Revenue definitions

Keep these amounts separate:

- **ESTIMATED** — possible value. Not earned.
- **QUOTED** — owner-entered quote. Not a contract.
- **CONTRACTED** — owner-entered agreed value. Not an invoice and not cash.
- **INVOICED** — owner-entered invoice-support record. Not collected by Nova.
- **RECEIVED** — owner-confirmed cash. Nova did not collect it.

**ESTIMATED != CONTRACTED.**  
**CONTRACTED != INVOICED.**  
**INVOICED != RECEIVED.**

Negative amounts are rejected. Currency must be a 3-letter code. Received revenue requires explicit owner confirmation.

## Live-action feature flags

All remain **DISABLED**:

- `LIVE_DISCOVERY_ENABLED = False`
- `EXTERNAL_SUBMISSION_ENABLED = False`
- `FINANCIAL_ACTIONS_ENABLED = False`
- `AUTONOMOUS_CLIENT_CONTACT_ENABLED = False`

Do not enable them in this engine without a separate owner-authorized adapter and tests.

## Prohibited actions

- Live job-board / RFP scraping
- External application send
- Contract acceptance
- Payments, invoices, payouts, Stripe objects
- Email / SMS / client messages
- Secret or tax/bank collection in this module
- Health, Delivery, Freight, Lifesaver, or production changes

## Phase 2 architecture

Additive schema only (`ensure_work_revenue_schema`). New tables: `nova_work_deliverables`, `nova_work_revenue_entries`. Extra columns on opportunities, applications, materials, owner actions, engagements, tasks, and audit events. No drops, no Stripe tables, no Health/Delivery/Freight tables.

Source URLs are validated (`http`/`https` only; no `javascript:`, `data:`, `file:`, localhost, or embedded credentials) and **never fetched**.

Opportunity and web text is untrusted. Hostile prompt text is stored/displayed only.

Recurring templates are internal catalogs. No calendars, emails, or external schedules.

## Remaining implementation

- Live discovery adapters (owner-authorized later)
- Controlled live submission
- Client contact send
- Real invoice / payment-processor integration
- Owner-verified business profile values (must be provided by the owner; not invented)

## Testing strategy

`backend/tests/test_nova_work_revenue.py` covers creation, isolation, qualification, drafts, approval, engagements, tasks, deliverables, revenue stages, audit, filters, pagination, unsafe URLs, prompt-injection fixtures, Today cards, and dashboard access. Do not run Stripe tests from this workstream.

## Nova Today

`/api/nova/work/today-summary` feeds informational Work & Revenue cards on `/nova/today`. Cards remain informational. There is no submit, pay, send, live discovery, or contract-accept control.

## Currently deferred

- Live opportunity discovery
- Approved provider connectors that fetch the network
- Controlled live application submission
- Client contact / reporting send
- Invoice and payment-processor integration
- Populating real owner tax, banking, or identity values

## Future external integration points

Provider flags include `DISCOVERY_SUPPORTED`, `SUBMISSION_SUPPORTED`, `LIVE_DISCOVERY_ENABLED`, and `EXTERNAL_SUBMISSION_ENABLED`. All default false. Do not enable them without an owner-authorized, tested adapter that cannot act silently.

## Schema / migration notes

Phase 2 changes are additive `CREATE TABLE` / `ALTER TABLE ADD COLUMN`. SQLite test databases and local files gain columns automatically. No destructive rename. If a future production migrate is needed, add columns only; do not drop Work & Revenue tables.
