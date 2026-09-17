# Nova Work & Revenue Engine

Local owner-controlled work system. Nova drafts and tracks. The owner decides. Nothing is sent, signed, or charged by this engine.

## Purpose

Help the owner find, qualify, prepare, approve, and track paid work for AMICOR without autonomous external action.

## Current architecture

- `/api/nova/work` — tenant-scoped APIs
- `/nova/work` — owner dashboard
- `/nova/today` — informational Work & Revenue cards
- Capability registry, qualification V2, application drafts, owner approval
- Internal engagements, tasks, deliverables
- Recurring managed-work series (internal only)
- Weekly managed-service report drafts (generate ≠ send)
- Invoice-support drafts (not Stripe invoices)
- Revenue entries and reconciliation summaries
- Owner-action center, business-fact catalog, disclosure and platform-policy metadata

All live flags remain off: live discovery, external submission, financial execution, report send, invoice send.

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

Application approval: `DRAFT` → `READY_FOR_OWNER_REVIEW` → `APPROVED` | `REJECTED` | `NEEDS_CHANGES`.

**APPROVED != SUBMITTED.** **APPROVED != PAID.** **COMPLETE != PAID.**

Task statuses: `NOT_STARTED` / `READY` / `IN_PROGRESS` / `OWNER_REVIEW` / `BLOCKED` / `COMPLETE` / `CANCELLED`.

Deliverable: `DRAFT` → `READY_FOR_REVIEW` → `OWNER_APPROVED` → `CONFIRMED_DELIVERED`. Delivered requires owner confirmation. Nova does not transmit files.

Internal work queue statuses: `NEW`, `READY`, `ACTIVE`, `BLOCKED`, `OWNER_ACTION_REQUIRED`, `COMPLETE`, `ARCHIVED`. Stored engagement values such as `NOT_STARTED` map to `NEW` for queue views.

## Recurring managed work

Internal series only. Fields: frequency (`daily` / `weekly` / `monthly`), expected next work date, status (`ACTIVE` / `PAUSED` / `ARCHIVED`), generated tasks, completion records, overdue/internal attention. The next work date advances only after an occurrence is completed, so the same period cannot be generated twice.

- Pause, resume, and archive are internal.
- Duplicate series titles on the same engagement are rejected.
- Duplicate period keys on the same series are rejected.
- Nova does not send notifications, contact customers, create calendars, or make network requests.

## Engagement / task model

Engagements are tracking records, not contracts. Tasks are internal. Queue list/filter/sort supports status, priority, source, client/engagement, due date (`due_before`), owner action, and last update. Tenant isolation is preserved. No outbound messages.

## Weekly report workflow

`POST /api/nova/work/reports/weekly` builds an internal draft covering activity, completed work, pending work, blockers, owner actions, opportunity pipeline, estimated revenue, contracted revenue, and owner-confirmed received revenue.

States: `DRAFT` → `READY_FOR_OWNER_REVIEW` → `APPROVED_FOR_MANUAL_USE` → `ARCHIVED`.

Generating a report is not sending it. `POST .../send` returns 409. There is no email, SMS, or client delivery.

## Invoice-support workflow

Internal draft with engagement, client, work period, deliverable IDs, quantity, rate, calculated subtotal, adjustment notes, invoice-required flag, and owner review.

States: `DRAFT` → `READY_FOR_OWNER_REVIEW` → `APPROVED` → `ARCHIVED`.

Allowed: internal totals from owner-entered data and a printable summary payload.

Not allowed: Stripe invoice creation, payment intents, charges, payouts, bank actions, external send, or automatically marking money received.

## Revenue-state rules

Keep these separate:

- **ESTIMATED** — possible value. Not received.
- **QUOTED** — owner-entered quote. Not a contract.
- **CONTRACTED** — owner-entered agreed value. Not an invoice and not cash.
- **INVOICED / MANUAL_RECORD_ONLY** — owner-entered invoice-support or manual invoice record. Not collected by Nova.
- **OWNER_CONFIRMED_RECEIVED** — only after explicit owner confirmation on an existing entry.

Nova never infers payment from contract existence, task completion, draft invoice, approval, application acceptance, or estimated opportunity value.

`GET /api/nova/work/reconciliation` summarizes estimated pipeline, quoted, contracted, awaiting invoice, manually recorded invoice, awaiting owner payment confirmation, and owner-confirmed received.

## Owner-action model

Informational/internal actions. Categories include `VERIFY_BUSINESS_FACT`, `REVIEW_DRAFT`, `PROVIDE_MISSING_INFORMATION`, `APPROVE_MANUAL_SUBMISSION`, `CONFIRM_DELIVERABLE`, `CONFIRM_CONTRACT`, `CONFIRM_PAYMENT_RECEIVED`, `REVIEW_WEEKLY_REPORT`, and `RESOLVE_BLOCKER`.

Owner approval does not execute an external action. APPROVED is not submitted and not paid.

## Business-fact model

Catalog keys stay defined even when values are missing. Value statuses: `MISSING`, `OWNER_PROVIDED`, `VERIFIED`, `EXPIRED`, with optional verification date, expiration date, source description, and notes.

Nova does not fabricate legal name, insurance, licenses, tax data, W-9 status, bank details, experience, pricing, or certifications. Sensitive keys accept readiness flags only. Secrets and banking credentials are rejected.

## Disclosure / policy framework

Internal AI/subcontractor disclosure records: whether AI assistance is used, whether subcontractor assistance is allowed, whether disclosure is required, whether owner acknowledgment is required, and policy status. No live platform-policy scraping. No automated acceptance of third-party terms.

Platform-policy metadata flags: `LOGIN_REQUIRED`, `CAPTCHA_REQUIRED`, `HUMAN_SUBMISSION_ONLY`, `TERMS_RESTRICT_AUTOMATION`, `EXTERNAL_AUTOMATION_UNKNOWN`, `MANUAL_REVIEW_REQUIRED`. Nova does not bypass CAPTCHA, login, MFA, anti-bot measures, or website restrictions.

## Safety boundaries

- Tenant isolation and IDOR protection on every Work & Revenue query
- Source URLs stored as text; `http`/`https` only; never fetched
- Untrusted opportunity text is quoted, not executed
- Dashboard HTML is escaped
- Negative amounts and malformed dates are rejected
- Invalid lifecycle transitions are rejected
- Audit events record tenant, entity, action, previous/new state, actor, and timestamp without secrets
- No shell or arbitrary code execution
- No outbound HTTP from this engine

## Disabled live features

- `LIVE_DISCOVERY_ENABLED = False`
- `EXTERNAL_SUBMISSION_ENABLED = False`
- `FINANCIAL_ACTIONS_ENABLED = False`
- `AUTONOMOUS_CLIENT_CONTACT_ENABLED = False`
- `REPORT_SEND_ENABLED = False`
- `INVOICE_SEND_ENABLED = False`

## Remaining V1 gaps

Blocked by owner input:

- Real verified legal name, insurance, licenses, experience, pricing, and similar facts
- Owner policy decisions about AI/subcontractor disclosure on specific platforms

Blocked by live integration / deferred:

- Live opportunity discovery
- Approved provider connectors that fetch the network
- Controlled live application submission
- Outbound client contact / report delivery
- Stripe or other payment-processor invoices, charges, payouts
- External calendars and notifications
- Populating real owner tax, banking, or identity values

## Testing strategy

`backend/tests/test_nova_work_revenue.py` covers Phase 1/foundation behavior.

`backend/tests/test_nova_work_revenue_completion.py` covers recurring work, queue filters, weekly reports, invoice-support, reconciliation, owner actions, facts, disclosure, and platform policy.

Do not run Stripe object-creation tests from this workstream.

## Schema / migration notes

Changes are additive `CREATE TABLE` / `ALTER TABLE ADD COLUMN` via `ensure_work_revenue_schema`. New tables include recurring series/occurrences, weekly reports, invoice-support, business facts, disclosure policies, and platform policies. No Stripe, Health, Delivery, Freight, or Lifesaver tables.
