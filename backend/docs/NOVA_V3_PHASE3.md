# Nova V3 Phase 3 — Growth Engine + Shield Automation

Canonical Cursor integration. Growth + Shield are required V3 capabilities. Synthetic / owner-controlled only.

- Branch: `feature/nova-v3-canonical-integration`
- No live outreach, ads, email, SMS, calendar writes, contracts, or payments
- Production Alembic includes Growth/Shield tables and is **not applied**

## What this phase adds

Package: `backend/app/core/nova/v3/growth/`

- Normalized Lead model and explainable scoring
- Configurable targeting profiles (Delivery / Nova / Health as data, not architecture)
- Outreach drafts grounded in known facts
- Follow-up sequences (Day 0/3/7/14) with pause/resume/cancel
- Inbound website sales assistant (synthetic)
- Demo scheduler with IANA timezone and synthetic calendar adapter
- CRM views and Growth / Shield command centers
- Catalog-only quotes; missing price → OWNER_ACTION_REQUIRED
- Conversion to an internal customer + onboarding prep (no external account)
- Shield decisions on every growth action

## Shield

States: ALLOW_SYNTHETIC, OWNER_APPROVAL_REQUIRED, HUMAN_ACTION_REQUIRED, BLOCK, DO_NOT_CONTACT, RATE_LIMIT, LEGAL_REVIEW_REQUIRED, PRIVACY_REVIEW_REQUIRED.

Every decision is stored with reasons. Approvals bind owner, lead, action, content fingerprint, resource, expiration, and refuse replay.

## Persistence / migration

Leads and growth artifacts persist on canonical `nova_v3_*` tables (`nova_v3_leads`, messages, sequences, demos, quotes, customers, shield decisions, growth approvals).

## Still synthetic

Discovery datasets, sends, replies, demos, proposals, and conversion. Processor/Stripe untouched. Live flags remain hard off.

## Owner authorization still required before live use

1. Real lead discovery credentials
2. Real outreach/email/SMS/social/ads
3. Real calendar writes, proposal send, contract acceptance, and payment execution
4. Applying production `nova_v3_*` migration after owner review
