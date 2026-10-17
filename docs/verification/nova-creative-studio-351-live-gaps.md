# Issue #351 — LIVE public revenue gaps (investigation + fix)

**Date:** 2026-10-17  
**Branch:** `cursor/creative-studio-presenter-351-09a7`  
**Do not merge / do not deploy until owner approves.**

## Preserved (untouched)

| Surface | Status |
| --- | --- |
| Approved **60s** commercial / demo | Unchanged |
| Lifesaver / LifeStraw page Nova research (#348) | Unchanged |
| Offline montage + walking presenter core | Unchanged (still working E2E in TEST) |
| FAL / Kling / D-ID live flags + credit purchases | Still OFF |
| Delivery freeze surfaces | Untouched |

## Second commercial (public revenue product)

The **30s AMICOR Creative Studio walking commercial** + AMICOR Stripe checkout at **$49** (internal render ceiling **$8**). This is the customer-facing commercial product for worldwide public purchase — not a toy dashboard.

## What already worked (TEST)

- 5s walking presenter proof + 30s H.264/AAC walking commercial
- Voice license AMBER → GREEN
- AMICOR TEST checkout (simulated or `sk_test_`) + receipts + job status
- Guardrails / UI TEST readiness card

## Gaps that blocked TEST → LIVE public carry-over

| Gap | Fix in this branch |
| --- | --- |
| Orders only in process memory (`_ORDERS`) — lost on restart | Durable `nova_creative_orders` table + schema ensure |
| No Studio Stripe webhook | `POST /api/nova/creative/stripe/webhook` (unsigned auth; Stripe signature required in real mode) |
| LIVE checkout hard-blocked even with owner flag | Gated LIVE when `NOVA_CREATIVE_STRIPE_LIVE_ENABLED=true` + `sk_live_` |
| Paid order did not fulfill production status | Webhook / sync → receipt + `fulfill_paid_order` (local walking path; no FAL spend) |

## Owner steps for public LIVE (after TEST host smoke)

1. Keep PR draft until TEST host smoke passes on this branch.
2. Configure Stripe **LIVE** keys only when ready for real money.
3. Set `NOVA_CREATIVE_STRIPE_LIVE_ENABLED=true` (explicit owner switch).
4. Create Stripe webhook → `https://<host>/api/nova/creative/stripe/webhook` with signing secret in `STRIPE_NOVA_CREATIVE_WEBHOOK_SECRET`.
5. Smoke: checkout → pay → webhook → receipt → download 30s MP4.
6. Do **not** flip FAL/Kling/D-ID live or publish ads without separate approval.

## Explicitly still OFF

- Paid Genova / FAL / Kling / D-ID activation and credit top-ups
- Public advertisement publish without owner review
- Changes to the approved 60s commercial
- Auto-merge / auto-deploy from this agent
