# Nova V3 Phase 1 — Live Work & Revenue Infrastructure

Canonical Cursor integration on merged V2/main. Synthetic lab only.

- Branch: `feature/nova-v3-canonical-integration`
- Grok source reviewed: `feature/nova-v3-live-work-infrastructure` @ `9e2052b4c7260760eb27b9d0c4b11082cf719368`
- Does not enable live discovery, submission, contact, invoices, payments, workers, or connectors
- Production Alembic exists as additive revision `20260918_nova_v3_live_infrastructure` and is **not applied**

## What this phase is

A provider-neutral foundation so Nova can later grow from owner-controlled V2 tracking into live operation **after** separate owner authorization, credentials, and terms review.

Phase 1 transport is mock/synthetic. APPROVED is not EXECUTED. Processor events are not cash. V3 payment events never write `nova_work_revenue_entries`.

## Package

`backend/app/core/nova/v3/`

- adapters + registry
- ingestion pipeline
- client/engagement workspace
- work execution
- mock communications
- prepare-only scheduler
- invoice drafts + mock delivery
- payment event inbox + owner confirm
- credential metadata (no secrets)
- CAPTCHA/login/terms human gates
- monitoring snapshot
- owner lab UI at `/nova/v3-lab`

## Explicitly not in Phase 1

1. Real job-board/API credentials
2. Real email/SMS
3. Stripe or bank feeds
4. Production worker/cron
5. Applying the V3 Alembic revision to production
6. Merge/deploy
