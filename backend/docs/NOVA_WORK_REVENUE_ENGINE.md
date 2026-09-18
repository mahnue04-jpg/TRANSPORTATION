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

`GET /api/nova/work/reconciliation` treats `nova_work_revenue_entries` as the authoritative source for estimated / quoted / contracted / invoiced / received totals. Opportunity revenue fields and invoice-support drafts are returned as separate context only and are not added into those totals. This avoids double-counting.

## AMICOR vs client revenue labeling

One interpretation: AMICOR money is only what lives on `nova_work_revenue_entries`.

- **Client billed amount** — invoice-support draft subtotal. Not a sent invoice.
- **Contract / opportunity amount** — owner-entered opportunity fields. Context only.
- **AMICOR expected revenue** — the current AMICOR ledger stage: contracted if present, else quoted, else estimated. Stages are not summed.
- **AMICOR owner-confirmed received** — ledger rows in `PAID` / `PARTIALLY_PAID` after explicit owner confirmation. Not processor-confirmed.
- **Contextual / non-authoritative** — opportunity and invoice-support amounts shown for comparison, never added into AMICOR totals.

Mismatch flags appear when AMICOR ledger amounts disagree with opportunity or billed-draft context. Owner confirmation is still required before money is marked received.

Partial owner confirmation uses the existing `PARTIALLY_PAID` stage: the ledger `amount` is the confirmed received portion, and `remaining_amount` keeps the unpaid expected balance. Confirming `PAYMENT_PENDING` for 40 against an expected 100 is PARTIALLY_PAID received 40 / remaining 60, not PAID 100.

Archived or cancelled engagement ledger rows remain visible as historical AMICOR records. They are labeled historical and are not added into current/active reconciliation or analytics totals. Archive is not delete.

The default operator work queue excludes `COMPLETE` and `ARCHIVED` work from items and active counts. Use status `ALL` or attention `all` to include historical work. Explicit `COMPLETE` / `ARCHIVED` filters still return those rows. Owner-fact `PUT` is create-or-update on the organization fact key and does not fail on repeated writes of the same non-verified value.

`LOGIN_REQUIRED` / `CAPTCHA_REQUIRED` describe the third-party platform. `False` is a legitimate descriptive state and does not bypass AMICOR owner approval, authentication, or disabled live submission. `HUMAN_SUBMISSION_ONLY`, `TERMS_RESTRICT_AUTOMATION`, and `MANUAL_REVIEW_REQUIRED` stay enforced.

List endpoints cap results at 200 rows. Use `limit` where exposed. Source URLs reject `javascript:`, `data:`, `file:`, credentials, loopback, link-local, and RFC1918/private addresses. URLs are never fetched.

## Owner-action model

Informational/internal actions. Categories include `VERIFY_BUSINESS_FACT`, `REVIEW_DRAFT`, `PROVIDE_MISSING_INFORMATION`, `APPROVE_MANUAL_SUBMISSION`, `CONFIRM_DELIVERABLE`, `CONFIRM_CONTRACT`, `CONFIRM_PAYMENT_RECEIVED`, `REVIEW_WEEKLY_REPORT`, and `RESOLVE_BLOCKER`.

Owner approval does not execute an external action. APPROVED is not submitted and not paid.

## Business-fact model

Catalog keys stay defined even when values are missing. The owner supplies every real-world value. Nova does not invent, scrape, or auto-fill business facts.

Value statuses: `MISSING`, `PROVIDED`, `VERIFIED`, `EXPIRED`, `NOT_APPLICABLE`. `OWNER_PROVIDED` is accepted as an alias of `PROVIDED`. Source is `OWNER`. Optional verification and expiration timestamps are stored. Verified facts are not overwritten unless the owner sets `confirm_overwrite`.

Supported owner facts include legal name, DBA, address, business email, business phone, authorized signer, ownership / contracting party, service areas, industries served, business age, insurance status, license status, certifications, relevant experience, references, pricing, rates, availability, workforce, equipment, AI-use disclosure decision, and subcontractor disclosure decision.

Sensitive financial facts are readiness flags only: `w9_readiness`, `financial_information`, `tax_identifiers`, and `banking_payment_readiness`. Allowed examples: `OWNER_SAYS_READY`, `w9_ready`, `tax_information_ready`, `banking_ready`, `NOT_APPLICABLE`.

Prohibited in every field: EIN, SSN, tax ID numbers, bank account numbers, routing numbers, Stripe secret keys, API keys, passwords, authentication secrets, and payment card information. Unsafe URLs and script markup are rejected. Email and phone values are format-checked locally with no network lookup.

Readiness is internal: required facts, provided, verified, missing, expired, and percentage complete. Readiness never submits an application, contacts a client, accepts a contract, creates an invoice, charges a payment, or enables live discovery. `externally_ready` remains false.

Owner fact entry is not application approval, bid submission, quote send, contract acceptance, message send, or payment confirmation.

## Disclosure / policy framework

Internal AI/subcontractor disclosure records: whether AI assistance is used, whether subcontractor assistance is allowed, whether disclosure is required, whether owner acknowledgment is required, and policy status. No live platform-policy scraping. No automated acceptance of third-party terms.

Platform-policy metadata flags: `LOGIN_REQUIRED`, `CAPTCHA_REQUIRED`, `HUMAN_SUBMISSION_ONLY`, `TERMS_RESTRICT_AUTOMATION`, `EXTERNAL_AUTOMATION_UNKNOWN`, `MANUAL_REVIEW_REQUIRED`. Nova does not bypass CAPTCHA, login, MFA, anti-bot measures, or website restrictions.

## Safety boundaries

- Tenant isolation and IDOR protection on every Work & Revenue query
- Source URLs stored as text; `http`/`https` only; never fetched
- Local, private, and link-local hosts are rejected, including encoded and IPv4-mapped forms
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

- The owner must still type real values into the catalog. Empty keys stay `MISSING`.
- Per-platform AI/subcontractor wording beyond the stored decision flags

Blocked by remaining internal V1 blocks:

- Tests for remaining live-integration blocks

Blocked by live integration / deferred:

- Live opportunity discovery
- Approved provider connectors that fetch the network
- Controlled live application submission
- Outbound client contact / report delivery
- Stripe or other payment-processor invoices, charges, payouts
- External calendars and notifications
- Populating real owner tax, banking, or identity numbers

## Known risks / next safe blocks

- Application dashboard still loads materials per application; keep list caps and do not add a background worker.
- Opportunity revenue fields remain owner-entered pipeline context. Do not silently copy them into revenue entries.
- Missing owner facts stay MISSING until the owner supplies them. Approval never marks an application externally ready.
- After Block 5 close-out, remaining V1 work is live-integration only. Default active queue counts exclude archived/complete work. Owner-fact PUT is safe create-or-update. AMICOR ledger amounts stay labeled separately from client billed drafts and opportunity context. Live adapters stay off.

## Testing strategy

`backend/tests/test_nova_work_revenue.py` covers Phase 1/foundation behavior.

`backend/tests/test_nova_work_revenue_completion.py` covers recurring work, queue filters, weekly reports, invoice-support, reconciliation, owner actions, facts, disclosure, platform policy, private-network URL rejection, list limits, and approval-is-not-submit.

`backend/tests/test_nova_work_revenue_owner_facts.py` covers Block 1 owner-fact intake, secret rejection, tenant isolation, readiness percentage, and the rule that fact entry does not enable external action.

`backend/tests/test_nova_work_revenue_operator_ui.py` covers Block 2 operator queue/reconciliation UI, filter/sort/pagination validation, overdue/blocked/owner-action states, received-amount confirmation boundary, tenant isolation, and disabled external controls.

`backend/tests/test_nova_work_revenue_block5.py` covers Block 5 close-out: default active queue exclusion of archived/complete work, owner-fact PUT create-or-update, remaining AMICOR/partial/archived/owner-confirmation/platform-guard proofs.

Do not run Stripe object-creation tests from this workstream.

## V2 core (supervised operating system foundation)

V2 adds configuration, safety policy, adapter contracts, an owner approval queue, a prepare-only scheduler, and processor-event recording. Live execution remains off.

- Capabilities: `LIVE_DISCOVERY`, `EXTERNAL_SUBMISSION`, `CLIENT_CONTACT`, `REPORT_SEND`, `INVOICE_SEND`, `FINANCIAL_EXECUTION`, `CALENDAR_ACTIONS`, `NOTIFICATIONS`
- Missing env vars are OFF. Master switch `NOVA_WR_ALLOW_LIVE_ACTIONS` is required in addition to each capability env var.
- Production also requires `NOVA_WR_PRODUCTION_LIVE_OVERRIDE=OWNER_AUTHORIZED_PRODUCTION_LIVE`. Live adapters are still unimplemented, so execution stays blocked.
- `GET /api/nova/work/v2/capabilities` is the status surface. Secrets are never returned.
- Safety policy requires all of: capability enabled, correct environment, tenant authorized, owner approved, adapter implemented, required facts, terms/policy, not duplicated.
- Adapter kinds exist as disabled/dry-run/mock contracts only.
- Supervised approval lifecycle is durable: REQUESTED / APPROVED / REVOKED / EXPIRED / CONSUMED / REJECTED / CANCELED. Approval is never execution. Expired, revoked, consumed, and rejected approvals cannot execute. Replay is fail-closed.
- Ordinary financial mutation is frozen on ARCHIVED / CLOSED / CANCELLED work. Historical corrections are a separate owner-authorized classification and do not change current totals.
- Payment-event idempotency is owner-scoped. Duplicate replay returns the original row without mutation.
- Owner-confirmed received is total-received-so-far. Overpayment returns `OVERPAYMENT_REQUIRES_OWNER_REVIEW`.
- Scheduler prepare uses savepoints so one duplicate insert cannot roll back sibling jobs. Paused/archived/cancelled sources create SKIPPED prepare rows, not active work.
- `GET /api/nova/work/v2/status` is the internal monitoring snapshot. Background worker and live connectors remain DISABLED.
- Scheduler `POST /api/nova/work/v2/scheduler/prepare` generates idempotent prepare jobs. No worker, cron, send, contact, or payment.
- Processor-shaped payment events are stored without changing AMICOR received cash. Owner confirmation remains authoritative.

See `backend/docs/NOVA_WORK_REVENUE_V2_MIGRATION.md` for production migration notes. Do not run production migrations without owner authorization.

`backend/tests/test_nova_work_revenue_v2.py` covers V2 config, safety, adapters, owner queue, scheduler, payment-event, tenant, and production-guard behavior.

## Schema / migration notes

Changes are additive `CREATE TABLE` / `ALTER TABLE ADD COLUMN` via `ensure_work_revenue_schema`. New tables include recurring series/occurrences, weekly reports, invoice-support, business facts, disclosure policies, and platform policies. No Stripe, Health, Delivery, Freight, or Lifesaver tables.
