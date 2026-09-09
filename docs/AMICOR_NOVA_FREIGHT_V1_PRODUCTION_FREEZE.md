# AMICOR Nova Freight V1 — Production Freeze

**Date:** 2026-09-09  
**Software status:** **SAFE TO FREEZE**  
**Stripe mode:** TEST only (LIVE not enabled)  
**Carrier payout mode:** SIMULATED / TEST only (no bank transfer, no Stripe Connect live transfer)  
**Driver 001:** Untouched  
**AMICOR Delivery:** Remains frozen  
**AMICOR Health:** Unchanged  

**AMICOR NOVA FREIGHT V1 SOFTWARE BUILD FROZEN**

No further Nova Freight code changes unless required by:

1. a verified production bug  
2. a security issue  
3. a legal/compliance requirement  
4. a launch-critical business requirement  

This freeze covers the Nova Freight V1 TMS software path only. It does **not** freeze Mrs. Nova Brain, Health ISF, or Delivery except to restate that those products stay on their existing freeze rules.

---

## Architecture

Nova Freight V1 is a namespaced TMS on the shared FastAPI / Render service `amicor-health-isf`.

- Data tables: `nova_freight_*` only
- API prefix: `/api/nova/freight`
- UI prefix: `/nova/freight*`
- Customer TEST charges: Nova-only Stripe TEST PaymentIntent + Nova webhook
- Carrier payouts: Nova-only simulated executor (`simulated_test`)
- Delivery `amicor_customer_payments`, Health `health_isf_payouts`, and `financial_engine.py` are not used

Money uses `Decimal` / integer minor units. The 70% carrier share is a TEST placeholder in `payout_config.py`, not permanent policy.

---

## Phase 1–7 capabilities

| Phase | Capability |
|-------|------------|
| 1 | Shipper intake + `nova_freight_shipments` |
| 2 | Dispatch board, carrier offers, first-accept-wins |
| 3 | Execution lifecycle `accepted` → `completed` |
| 4 | Proof of pickup / proof of delivery (warning-only for payout) |
| 5 | Rate engine, quote, invoice, Stripe TEST customer charge |
| 6 | Carrier payout, finance approval, simulated payout, settlement/remittance, carrier earnings |
| 7 | Ops dashboard, completed history, cancel, void-invoice recreate, launch hardening, this freeze |

---

## Routes / APIs

### UI

- `/nova/freight`, `/nova/freight/new`, `/nova/freight/shipments`, `/nova/freight/shipments/{id}`
- `/nova/freight/dispatch`
- `/nova/freight/carrier/offers`
- `/nova/freight/carrier/shipments`, `/nova/freight/carrier/shipments/{id}`
- `/nova/freight/carrier/earnings`
- `/nova/freight/finance`
- `/nova/freight/ops`
- `/nova/freight/history`, `/nova/freight/history/{id}`

### API (all authenticated except Stripe webhook)

Prefix `/api/nova/freight`:

- Shipments: create, list (`scope=active|history`), get, patch, cancel
- Dispatch board, carriers, offers accept/decline/cancel
- Carrier active shipments, status transitions, events
- Proofs create/upload/list/get/file/delete
- Quote suggest/save/finalize/get, customer quote
- Invoice create/finalize/void/pay/confirm
- `POST /stripe/webhook`
- Payout eligibility/create, finance adjust/hold/approve/void/execute, settlement, remittance
- `GET /carrier/earnings`
- `GET /ops/summary`
- `GET /history`, `GET /history/{shipment_id}`

---

## User roles

| Role | Freight rights |
|------|----------------|
| rider / provider (shipper) | Create/view own-org shipments, customer quote/invoice/TEST pay, cancel pre-assignment, **no** margin, **no** ops/finance |
| driver (carrier) | Offers, assigned execution, proofs, own earnings/remittance, **no** rate edit, **no** payout approve |
| dispatcher / staff / supervisor | Dispatch, quotes, invoices, pending payout create, ops/history, **no** money approve/execute |
| admin / super_admin_support | All dispatch rights plus payout adjust/hold/approve/void/execute |

Cross-tenant reads return 404. Proof files are org- and viewer-scoped. Stripe secret keys never go to the browser.

---

## Shipment lifecycle

`ready_for_dispatch` → `offered` → `accepted` → `en_route_to_pickup` → `arrived_pickup` → `picked_up` → `in_transit` → `arrived_delivery` → `delivered` → `completed`

Cancel is allowed before completion unless a paid invoice or processing/paid payout exists. Cancelled and completed loads are excluded from active dispatch and carrier work queues.

---

## Proof flow

POP at `arrived_pickup` / `picked_up`. POD at `arrived_delivery` / `delivered`. Soft-delete supported. Missing proof is a payout **warning**, not an automatic block. Files are served only through the authenticated proof-file endpoint; raw filesystem paths are not returned.

---

## Billing flow

1. Dispatch calculates and finalizes a quote  
2. After completion, create/finalize invoice  
3. Customer starts Stripe TEST PaymentIntent  
4. Confirm (simulate succeed/fail) or Nova webhook  
5. Duplicate PI reuse and unique `stripe_event_id`  
6. Failed TEST payment can retry with a new PI  
7. Voided unpaid invoices can be recreated  

Customer UI uses the Nova TEST confirm path. Live Stripe keys are rejected.

---

## Payout / settlement flow

1. Eligible when completed + paid invoice + assigned carrier + no active payout  
2. Split from `payout_config.py` (TEST 70/30 placeholder)  
3. Admin may adjust before ready/paid  
4. Approve → ready → simulated execute → paid  
5. Settlement + remittance text marked SIMULATED / TEST — no money moved  
6. Duplicate create blocked; approve/execute retries are idempotent  

---

## Test results (Phase 7 session)

| Suite | Result |
|-------|--------|
| Phase 7 launch-readiness | 6 passed |
| Phase 1–6 Nova Freight | 59 passed |
| Nova shell + Delivery branding | 7 passed |
| Health onboarding + revenue-pilot smoke | 5 passed |
| **Total this session** | **77 passed, 0 failed** |

Local TEST E2E covered: create → quote → finalize → offer → accept → full lifecycle + POP/POD → invoice → Stripe TEST simulate pay → payout → approve → simulated execute → history/archive → retry execute with no second payout.

---

## Current deployed commit

Recorded at freeze commit time as the Phase 7 commit on `main` / Render `amicor-health-isf`. Verify live:

`GET https://amicor-health-isf-py.onrender.com/api/health/live` → `deploy_commit`

---

## Known non-blocking limitations

- Customer pay UI uses server-side TEST confirm, not Stripe Payment Element
- 70% carrier share is a TEST placeholder
- No Stripe Connect TEST/live transfers
- Proof is not a hard completion gate
- `assigned` status exists in the enum but accept writes `accepted`
- Dispatch board is dense on small phones (horizontal scroll)
- Finance/earnings lists are compact, not a BI tool
- One settlement per payout/shipment (no batching)
- No shipment archive table; history is a filtered completed/cancelled view

---

## External / business / compliance dependencies (not software blockers)

- Legal entity, contracts, and insurance for freight brokerage / carrier operations
- Permanent payout policy (replace 70% placeholder)
- Carrier banking / tax identity collection (W-9/1099 later)
- Stripe LIVE decision and PCI operating procedures
- Real carrier payout rails (Connect, ACH, or check)
- Fuel surcharge / accessorial / tax configuration
- Customer and carrier onboarding, SLAs, and claims process
- State operating authority and broker bonding if required
- Document retention and audit policy for proofs/remittances

---

## Intentionally deferred

- Tax / 1099 filing  
- Payout batching and bulk remittance files  
- Advanced revenue / profitability analytics  
- Predictive pricing  
- Live Stripe customer charges  
- Live carrier payouts  
- Nationwide compliance engine  
- Load-board / broker / ELD / hardware integrations  
- Mrs. Nova Brain ecosystem expansion  

---

## Rollback notes

- Safe deploy branch: `fix/httpx-stripe-dep` tracking `origin/main`
- Do **not** push local diverged `main`
- Rollback: redeploy the previous known-good `main` commit (`ada2abf370926f575cd8301be5225f30a53a3f0d` = Phase 6)
- Freight schema is additive (`nova_freight_*`). Rolling back code leaves unused tables/columns; do not drop them unless a dedicated rollback migration is written
- Do not roll back Delivery, Health, or Driver 001 data to “fix” Freight

---

## Freeze statement

AMICOR NOVA FREIGHT V1 SOFTWARE BUILD FROZEN.

Treat the deployed Freight V1 path as frozen with Delivery and Health. Further Freight work requires an explicit launch-critical, security, legal, or verified-production-bug request.
