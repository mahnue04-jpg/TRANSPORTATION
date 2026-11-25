# Nova four-plan payment integration — November 24, 2026

Status: owner-supplied live price mapping recorded; production checkout remains disabled. No live transaction authorized.

| Offer | USD | Mode | Proposed existing key |
| --- | --- | --- | --- |
| Starter Plan | 9.99 monthly | subscription | starter |
| Starter Task | 49 once | payment | separate order, never subscription |
| Launch Operations | 99 monthly | subscription | professional |
| Business Operations | 299 monthly | subscription | business |

Owner created four live Payment Links and activated a hosted billing portal. Their URLs are not price IDs or proof of payment. Do not publish checkout links before acceptance. Confirm product entitlements and independently verify the owner-supplied Stripe price IDs below before enabling runtime mapping. Do not infer a customer tenant from email or an untrusted client_reference_id alone.

## Integration direction
Prefer authenticated server-created Checkout sessions for subscriptions, reusing POST /api/nova/billing/checkout and the existing tenant binding. Existing direct links require a separately verified order/account association and must not automatically grant access. The $49 one-time workflow must remain isolated. Use the authenticated portal endpoint or verified hosted portal for billing management. Keep the free demo available without paid access. Existing trial behavior remains the default for legacy services. For the four-plan subscription release, explicitly set NOVA_BILLING_CHECKOUT_TRIAL_ENABLED=false; the checkout service now honors that setting.

## Required verification before live launch
- Confirm live Stripe price IDs, currency, interval, amount, active state, and distinct product scope. Verify test/live mode isolation.
- Verify signed webhook account/mode, exact known customer/session/subscription/order and price; reject conflicts, unknown products and unrelated billing events. Existing service currently prioritizes metadata tenant lookup and can update identifiers; harden before launch.
- Handle replay, concurrent duplicate events, out-of-order events, renewals, payment failures, cancellation at period end, expired sessions, partial/full refunds (incremental amounts rather than cumulative double-counting), and cross-tenant attempts.
- Verify actual entitlement enforcement per plan, not merely subscription status. Existing enforcement defaults off; preserve unrelated/free access.
- Verify $49 paid order to private delivery and revocation; never treat a one-time charge as a recurring entitlement.
- Confirm legal terms, cancellation/refund policy, service limits, tax obligations, support and payout verification.
- Test with synthetic data and sandbox only, then obtain explicit owner approval for any controlled live test and production publication.

Keep NOVA_STRIPE_LIVE_ENABLED=false. No keys or signing secrets in GitHub. No real charges or changes to other AMICOR billing surfaces.

## Owner-confirmed price inventory (November 24, 2026 CT)

| Offer | Live Price ID | Expected USD cents | Mode |
| --- | --- | --- | --- |
| Starter Plan | `price_1UfWpDBCDlIbm4gm7kY4yIva` | 999 | monthly subscription |
| Starter Task | `price_1URDdoBCDlIbm4gmtQqEQgey` | 4900 | one-time payment |
| Launch Operations | `price_1UfWrXBCDlIbm4gmsdgH2js5` | 9900 | monthly subscription |
| Business Operations | `price_1UfWsqBCDlIbm4gm8dVahkxS` | 29900 | monthly subscription |

Owner supplied all four identifiers after creating or confirming the products in the live dashboard. Support email saved and hosted portal activated per owner confirmation. Live API verification of price objects, portal configuration and link-to-price association remains pending. This inventory is documentation only, not runtime configuration. Never substitute these IDs into sandbox tests. Live checkout and public links remain disabled pending all release gates above.

## Deployment configuration checklist (not applied)

For the subscription service, the existing environment keys map to the owner-supplied inventory as follows:

- `NOVA_STRIPE_PRICE_STARTER`: $9.99 monthly Starter Plan.
- `NOVA_STRIPE_PRICE_PROFESSIONAL`: $99 monthly Launch Operations.
- `NOVA_STRIPE_PRICE_BUSINESS`: $299 monthly Business Operations.
- `NOVA_BILLING_CHECKOUT_TRIAL_ENABLED=false`: no automatic trial for this offer set. Do not change shared legacy deployments without reviewing scope.
- `NOVA_STRIPE_LIVE_ENABLED=false`: retain the live-payment hold.

Use independently verified sandbox prices in staging; use independently verified live prices only in the approved isolated production configuration. Do not set the $49 price in any subscription variable. Its separate one-time checkout and delivery integration must be reviewed independently. Configure signing secrets only in the deployment secret store, never in source control. Keep subscription enforcement unchanged until entitlement tests and migration review pass.

Validation evidence for commit `2fc36529ba24d3b87558567d0abbc10a1fd1a5cc`: Nova Stripe billing tests (45556294391), Jekyll site CI (45556294218), and website upload package (45556294227) succeeded. Backend diagnostic and Work & Revenue regression were still running at the time of this review. This is not production acceptance.
