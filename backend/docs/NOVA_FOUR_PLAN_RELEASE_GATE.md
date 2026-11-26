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
| $9.99 Starter Plan | Basic workspace, planning, templates, self-service assistance; zero managed tasks | Owner approved staging only; require authenticated paid subscription |
| $49 Starter Task | One small scoped task | Exact paid order, PaymentIntent, task binding, private reviewed delivery |
| $99 Launch Operations | Up to 3 tasks per verified subscription month | Current paid invoice, exact price and tenant/customer binding, durable reservations |
| $299 Business Operations | Up to 10 tasks per verified subscription month; relative priority support | Same controls as Launch, distinct allowance and support triage |

Source for allowances: docs/nova-operations-approved-package-readiness-20261122.md on PR #583. Approval covers staging only.

### Integration sequence
1. Preserve the tested PR #589 baseline; prepare a separate integration candidate, not a production merge. Review stacked PR #574–582 dependencies and PR #583 base dependencies before importing code.
2. Establish one authoritative tenant-to-customer/subscription/order binding. Existing SaaS billing and anonymous Operations marketing leads are distinct; never link by email alone. Confirm explicit authenticated association and exact price, quantity, mode, and period.
3. Reuse Operations reconciliation, owner approval and durable task reservation logic from PR #583. Keep synthetic-only gates and test credentials. Review additive migrations on disposable PostgreSQL with backup/restore and concurrency tests. Do not treat the isolated paid-access policy as sufficient payment proof.
4. Reuse Starter payment binding and private delivery from PR #582 and its dependencies. Wire refund/dispute reconciliation to the exact PaymentIntent and revoke grants on reversal. Test recipient isolation, expiry, replay, concurrent requests, and revocation.
5. Run integrated staging tests for all approved tiers; verify current paid invoice, renewal, failure, cancellation, refund, quota boundary, owner approval, execution, delivery and audit receipt. Keep $9.99 access restricted to synthetic staging until hosted acceptance.
6. Complete legal/tax/support review and obtain separate owner authorization before live credentials, deployment, public links or real charges.

No migrations, runtime configuration, checkout links or production flags are changed by this document.


## Updated staging evidence — November 25, 2026

- Consolidated draft PR #590, not merged. At commit 76611d1c3fc6e4bf6ab4ee459b01f62266c1e040 all three workflows passed (45714298740, 45714298775, 45714298726).
- Starter $9.99: owner approved four self-service benefits and no managed tasks. Authenticated feature routes and private HTML interface implemented; planning is unsaved and guidance is static. Synthetic tests pass, but actual login, Stripe sandbox payment, cancellation and browser verification remain pending. Stripe connector currently lists only live mode; sandbox price creation rejected. Do not substitute live price.
- $49: previously verified hosted synthetic payment-to-private-delivery and revocation; no real revenue. Renew scoped staging storage credential before Dec 2 expiry.
- $99/$299: disposable PostgreSQL integration passed with simulated Stripe/storage. Hosted checkout creation awaits existing sandbox access tokens; do not reset or expose tokens. Hosted fulfillment is not verified.
- Live tax determination, refund/dispute and renewal lifecycle verification, migration review, production authorization and website publication remain release gates. No live sales authorized.


## Monthly lifecycle and reversal integration update

Verified Operations CI at commit 607173cdbec9ee2ddb91ddfc11d52ae67dd09aa6 (run 45723624279), and Casting regression (45723624321). Backend diagnostic 45723624244 remained in progress when checked.

- Starter authenticated self-service checks freshly retrieve the current invoice payment, PaymentIntent and charge. Synthetic HTTP tests deny partial/full refunds, disputes and missing payment evidence.
- Launch and Business owner reservation and bound execution/delivery guards require fresh unreversed payment verification. Synthetic PostgreSQL integration denies execution and download when the payment verifier denies access; reservation tests deny consumption when verification is false or missing.
- Monthly renewal and cancellation boundaries tested with synthetic evidence. Previous-period reservations are conservatively blocked rather than rolled over.
- These results are not hosted Stripe acceptance. The shared verifier assumes a single full card payment, denies unsupported response shapes, and requires actual sandbox SDK/API verification. Persistent reversal-event reconciliation, restored/dispute-won handling, exact invoice line price/item identity, and legacy route bypass review remain open.
- Next hosted acceptance requires access to Stripe test mode (the connector currently exposes live mode only) and the existing Launch/Business sandbox access tokens. Never substitute live credentials or rotate tokens without owner approval.
- No production deployment or live checkout publication authorized.


## Owner-provided Starter sandbox price — November 26, 2026 UTC

The owner reported active test catalog entries for all four offers and supplied the $9.99 monthly USD Starter product `prod_VhG6ddXy8MvHCs` and price `price_1UfraiBCDlIbm4gmdMLtof9d`. These identifiers are non-secret, owner-provided evidence only; independent Stripe test-mode API retrieval is still required. The connector currently exposes only the live account. Do not use live credentials as a workaround.

For an isolated authenticated Starter rehearsal, after verifying the price object in test mode, configure both `NOVA_STRIPE_PRICE_STARTER` and `NOVA_STARTER_SELF_SERVICE_TEST_PRICE_ID` to that same sandbox price. Keep both environment markers staging, live Stripe and customer sales false, and the checkout trial disabled. Enable the Starter staging feature only on the isolated candidate. A configured checkout price that differs from the access price now denies access. Existing hosted rehearsals are pinned to separate commits; no Render service was reconfigured by this update. Hosted acceptance and independent sandbox authorization remain outstanding.


## Hosted Starter acceptance — November 25, 2026 CT

**Accepted: isolated $9.99 synthetic subscription recovery and all four self-service features.** Render service nova-operations-checkout-sandbox deployed revision a0d53623fb112ec7d5fd018eca3f3f05b50ac88e, deployment dep-dc3s38rl550s73fefjg0. All four GitHub workflows passed; Operations run 45760092411, signed-starter-webhook job 139707805491: 40 payment/binding tests, one checkout guard and nine hosted recovery tests passed.

The owner confirmed a successful USD 999 test-mode payment and paid invoice in Stripe. The hosted recovery initially failed because the restricted test key lacked subscription read permission. Owner updated the existing sandbox key's permissions; no key rotation or production credential change. Render logs independently confirm HTTP 200 for:
- POST /sandbox/reconcile at 05:42:31 UTC November 26.
- GET /api/nova/starter/workspace at 05:43:33 UTC.
- POST /api/nova/starter/plan at 05:44:02 UTC.
- GET /api/nova/starter/templates at 05:44:18 UTC.
- GET /api/nova/starter/assistance at 05:44:36 UTC.

Owner screenshots confirm the $9.99 plan, zero managed tasks, unsaved checklist planning, three templates and static guidance (no external AI or managed execution). The rehearsal uses an owner token and exact test checkout recovery; it is not production customer authentication or durable production storage. New checkout is disabled. All four offer amounts have successful Stripe test-payment evidence; $49 private delivery and revocation previously passed, while hosted integrated $99/$299 fulfillment remains unverified.

**Do not repeat completed payments.** Legacy marketing webhook requests to the repurposed sandbox returned 404; the recovery path is direct read-only verification, not a webhook acceptance. Next work: isolated signed test webhook acceptance with exact event identity, durable idempotency and fresh provider evidence; verify production authentication, lifecycle and managed-task fulfillment; tax/terms and explicit production approval. Do not enable public checkout, live Stripe or real customer processing. No secrets or checkout session identifiers in this document.

## Owner commercial authorization and live catalog verification — November 26, 2026

Owner explicitly authorizes all four packages for commercial release together, including live payments once customer fulfillment works. Read-only live Stripe inspection confirmed all four active USD links each contain exactly one expected active live price, three monthly and one one-time. No live webhook endpoints or Stripe Tax registrations; automatic tax disabled. Existing $49 link is third-party application-created and carries 392 cents application fee, separate from processing fees; review before reuse. Do not charge a customer until the purchased service is actually available and applicable tax treatment is resolved. No real test charge needed.

Minnesota DOR guidance https://www.revenue.state.mn.us/guide/computer-software-and-digital-products explicitly treats remotely hosted software subscriptions without possession as nontaxable. Starter appears to fit this description; managed service bundles and other jurisdictions require separate review. Do not claim nationwide exemption or create a Stripe tax registration without actual government registration.

Website main commits 911c3c52cfa62dbf4b7ad9a3c4720d82fabcbf55 (plan selection), c3f5d25608190d731fd035870f0e15b3e51d8b5f (Operations page), cc19e992d3828e1bef82c6215572ea694c219877 (Pricing page) display all four offers with inquiry-only availability pending activation. Public GET of both pages still showed previous content November 26. Confirm Cloudflare production deployment separately; do not describe repository commits as live deployment. Owner approval is no longer the overall blocker; production authentication, payment binding, fulfillment and deployment remain technical blockers.
