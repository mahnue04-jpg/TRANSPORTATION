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


## Consolidation acceptance matrix — November 25, 2026

Payment branch PR #589: all five workflows passed at dbdd72fdd4da63b242d52bf685329d4432e3d176. Operations allowance branch PR #583: allowance staging checks and backend diagnostic passed at 9231fdc93a905295cf4f09b09545f1ee51cc1a63. Starter branch PR #582: isolated payment binding and entitlement tests passed at f779a4c412895a29a3d029627eaf80c37a401835. These are separate candidates, not an integrated deployment.

| Offer | Approved staging allowance | Integration requirement |
| --- | --- | --- |
| Free Scope Check | Qualification only | Preserve public inquiry path |
| $9.99 Starter Plan | Not yet approved | Owner defines benefits; do not infer task allowance |
| $49 Starter Task | One small scoped task | Exact paid order, PaymentIntent, task binding, private reviewed delivery |
| $99 Launch Operations | Up to 3 tasks per verified subscription month | Current paid invoice, exact price and tenant/customer binding, durable reservations |
| $299 Business Operations | Up to 10 tasks per verified subscription month; relative priority support | Same controls as Launch, distinct allowance and support triage |

Source for allowances: docs/nova-operations-approved-package-readiness-20261122.md on PR #583. Approval covers staging only.

### Integration sequence
1. Preserve the tested PR #589 baseline; prepare a separate integration candidate, not a production merge. Review stacked PR #574–582 dependencies and PR #583 base dependencies before importing code.
2. Establish one authoritative tenant-to-customer/subscription/order binding. Existing SaaS billing and anonymous Operations marketing leads are distinct; never link by email alone. Confirm explicit authenticated association and exact price, quantity, mode, and period.
3. Reuse Operations reconciliation, owner approval and durable task reservation logic from PR #583. Keep synthetic-only gates and test credentials. Review additive migrations on disposable PostgreSQL with backup/restore and concurrency tests. Do not treat the isolated paid-access policy as sufficient payment proof.
4. Reuse Starter payment binding and private delivery from PR #582 and its dependencies. Wire refund/dispute reconciliation to the exact PaymentIntent and revoke grants on reversal. Test recipient isolation, expiry, replay, concurrent requests, and revocation.
5. Run integrated staging tests for all approved tiers; verify current paid invoice, renewal, failure, cancellation, refund, quota boundary, owner approval, execution, delivery and audit receipt. Keep $9.99 access unprovisioned pending explicit benefits approval.
6. Complete legal/tax/support review and obtain separate owner authorization before live credentials, deployment, public links or real charges.

No migrations, runtime configuration, checkout links or production flags are changed by this document.
