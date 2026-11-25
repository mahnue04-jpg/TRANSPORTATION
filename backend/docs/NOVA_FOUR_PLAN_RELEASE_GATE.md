# Nova four-plan payment integration — November 24, 2026

Status: proposed mapping; production checkout remains disabled. No live transaction authorized.

| Offer | USD | Mode | Proposed existing key |
| --- | --- | --- | --- |
| Starter Plan | 9.99 monthly | subscription | starter |
| Starter Task | 49 once | payment | separate order, never subscription |
| Launch Operations | 99 monthly | subscription | professional |
| Business Operations | 299 monthly | subscription | business |

Owner created four live Payment Links and activated a hosted billing portal. Their URLs are not price IDs or proof of payment. Do not publish checkout links before acceptance. Confirm product entitlements and exact Stripe price IDs before mapping. Do not infer a customer tenant from email or an untrusted client_reference_id alone.

## Integration direction
Prefer authenticated server-created Checkout sessions for subscriptions, reusing POST /api/nova/billing/checkout and the existing tenant binding. Existing direct links require a separately verified order/account association and must not automatically grant access. The $49 one-time workflow must remain isolated. Use the authenticated portal endpoint or verified hosted portal for billing management. Keep the free demo available without paid access. Existing trial behavior applies seven days automatically to eligible tenants; resolve this against the no-trial Payment Links before release.

## Required verification before live launch
- Confirm live Stripe price IDs, currency, interval, amount, active state, and distinct product scope. Verify test/live mode isolation.
- Verify signed webhook account/mode, exact known customer/session/subscription/order and price; reject conflicts, unknown products and unrelated billing events. Existing service currently prioritizes metadata tenant lookup and can update identifiers; harden before launch.
- Handle replay, concurrent duplicate events, out-of-order events, renewals, payment failures, cancellation at period end, expired sessions, partial/full refunds (incremental amounts rather than cumulative double-counting), and cross-tenant attempts.
- Verify actual entitlement enforcement per plan, not merely subscription status. Existing enforcement defaults off; preserve unrelated/free access.
- Verify $49 paid order to private delivery and revocation; never treat a one-time charge as a recurring entitlement.
- Confirm legal terms, cancellation/refund policy, service limits, tax obligations, support and payout verification.
- Test with synthetic data and sandbox only, then obtain explicit owner approval for any controlled live test and production publication.

Keep NOVA_STRIPE_LIVE_ENABLED=false. No keys or signing secrets in GitHub. No real charges or changes to other AMICOR billing surfaces.
