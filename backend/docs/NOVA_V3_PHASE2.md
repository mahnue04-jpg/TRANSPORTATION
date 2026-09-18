# Nova V3 Phase 2 — Durable Storage, Scheduler, Owner Lab, Connector Simulation

Canonical Cursor integration on merged V2. Synthetic / pre-production lab only.

- Branch: `feature/nova-v3-canonical-integration`
- Does not enable live discovery, submission, contact, invoices, payments, workers, connectors, or public webhooks
- Additive Alembic revision `20260918_nova_v3_live_infrastructure` revises `20260918_nova_work_revenue_v2_owner_scheduler`
- That revision is **not applied to production** in this session

## Storage model

V3 persistence uses the shared SQLAlchemy `Base` and `nova_v3_*` tables.

- Owner-scoped and tenant-scoped on every row
- Indexed for owner isolation, fingerprints, scheduler periods, and webhook/payment event IDs
- Production schema source is Alembic only (no lazy create unless pytest or explicit `NOVA_V3_LAZY_SCHEMA=1`, never set on Render)
- Never a second uncontrolled production schema path
- Never writes the AMICOR ledger `nova_work_revenue_entries`

Entities persisted: opportunities, opportunity sources, classifications/provenance, clients, engagements, proposals/applications, work items/tasks/deliverables, approvals, communications, invoices, payment events, corrections/reconciliation records, scheduler jobs/runs, connector metadata, credential metadata, webhooks, monitoring, audit, idempotency, plus Growth/Shield tables.

## Shared V2 primitives

V3 reuses V2 freeze constants, idempotency lookup/replay helpers, and secret redaction. It does not import Grok's competing `v2_reference` kernel.

## Scheduler architecture

`backend/app/core/nova/v3/worker.py` plus `NovaV3Kernel.tick_worker`.

- Job kinds: opportunity_refresh, application_followup, client_followup, work_deadline, recurring_work, invoice_followup, payment_reconciliation, stale_engagement_check, credential_expiry_check, connector_health_check
- Owner + tenant isolation
- Idempotent schedule key `(organization_id, owner_user_id, kind, period_key)` with IANA timezone in the period key
- Pause / resume / cancel / retry
- Lease + stale-lock recovery
- Exponential backoff and dead-letter
- `BACKGROUND_WORKER_ENABLED` remains OFF; no production daemon

## Safety flags (all hard OFF)

LIVE_DISCOVERY, LIVE_LEAD_DISCOVERY, REAL_EXTERNAL_SUBMISSION, REAL_CLIENT_CONTACT, REAL_EMAIL_SEND, REAL_SMS_SEND, REAL_SOCIAL_POST, REAL_AD_SPEND, REAL_CALENDAR_WRITE, REAL_OUTREACH_SEND, REAL_PROPOSAL_SEND, REAL_CONTRACT_ACCEPTANCE, REAL_INVOICE_SEND, REAL_FINANCIAL_EXECUTION, REAL_PAYMENT_EXECUTION, REAL_BACKGROUND_WORKER, REAL_CONNECTORS, REAL_WEBHOOK_PUBLIC_ENDPOINT, STRIPE, RENDER, PRODUCTION.
