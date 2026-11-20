# VoiceLedger Pro — isolated digital checkout prototype (TEST ONLY)

**Status:** code-review artifact only. Not mounted into AMICOR's production app. No Render backend deployment, Stripe live charges, live price/product, customer emails or real fulfillment.

## Architecture

- `flow.py`: a dedicated **test-key-only** Stripe Checkout client, verified webhook path, local SQLite order/event/entitlement/outbox tables, expiring download token checks.
- `api.py`: optional standalone FastAPI endpoint. It is not imported into the current AMICOR application. All routes requiring payment fail closed unless `VL_CHECKOUT_MODE=test` plus all mandatory settings are explicitly configured.
- `test_flow.py`: no-network offline test doubles for purchase validation, duplicate webhooks, wrong-price rejection, invalid webhook signatures and private-download limits.

## Required environment for a future *isolated* staging service

- `VL_CHECKOUT_MODE=test` (any other value disables checkout)
- `VL_STRIPE_TEST_SECRET=sk_test_...` (must be **test** key; never copy live key)
- `VL_STRIPE_WEBHOOK_SECRET=whsec_...` dedicated to test endpoint
- `VL_STRIPE_TEST_PRICE_ID=price_...` test-mode **one-time $39 USD** price created only after tax/pricing approval
- `VL_DATABASE_PATH=/persistent/private/orders.sqlite3` (requires persistent disk; ephemeral storage is not sufficient)
- `VL_PRIVATE_PACKAGE_PATH=/private/VoiceLedger-Pro-Licensed.zip` (must be inaccessible to public web serving, valid private licensed ZIP)
- `VL_CHECKOUT_SUCCESS_URL=https://<staging-domain>/success`
- `VL_CHECKOUT_CANCEL_URL=https://<staging-domain>/cancel`

This requires appropriate staging resources before deployment. **No resources, secrets, or Stripe test prices are created by this code.**

## Intended flow

1. Customer provides email; server starts Stripe **test** Checkout Session for the configured test Price ID.
2. Stripe redirects user back for informational status only. Success URL **does not** grant download.
3. Stripe signs webhook; server checks signature, event freshness, `livemode=false`, and retrieves Checkout Session from Stripe.
4. Server verifies `payment_status=paid`, status=complete, price ID, currency, amount, quantity, metadata and original order/email before committing a paid entitlement.
5. An outbox record is queued. **No email is sent automatically.** An authorized staging operator must inspect secure outbox and securely deliver the expiring token; do not expose the outbox on a public route.
6. Customer redemption is capped, token-checked, and private. Lost token / refunds / disputes / resend flows remain incomplete.

## Test checkout return experience

- Isolated API routes `GET /complete?session_id={CHECKOUT_SESSION_ID}` and `GET /cancel` provide clear mobile-friendly test-only status pages.
- The /complete page reads the existing test order status but never creates an entitlement. It does not grant access on URL alone, and never displays a private download token.
- When enabling an isolated test checkout service, use `https://<isolated-staging-domain>/complete?session_id={CHECKOUT_SESSION_ID}` as the success URL and `https://<isolated-staging-domain>/cancel` as the cancellation URL. Do not put these on the public AMICOR website before launch.
- Confirmation currently reports `paid` only after signed Stripe webhook processing and queueing. The fulfillment outbox is still a private manual staging workflow.
- This is **not a connected real test purchase** until the isolated Stripe test account/key, webhook signing secret, test price, durable database, and private licensed package are configured and independently verified.

## Known limitations before production

- The public VoiceLedger trial remains free and fully usable. A paid purchase currently **cannot** restrict use; a coherent product license / private delivery and customer access design is required before charging money.
- SQLite outbox tokens are stored as plaintext in the *private* database to allow fulfillment; lock down file access. No email service, outbox worker or access controls for support operators are implemented.
- A local SQLite database is not a multi-instance production entitlement store. Staging must use a persistent disk; production would need transactional durable storage, encrypted secret handling and backup strategy.
- No actual Stripe TEST account/price, webhook or package has been provisioned. No end-to-end paid checkout completed.
- Tax settings, registration obligations, licensing, refunds, chargebacks, customer support and proof of delivery need review. The $39 price is **proposed**, not approved.
- Do not include customer secrets, the SQLite DB, private ZIP, or Stripe keys in GitHub.
- CFSS Budget Co-Pilot is not included or available for purchase.

## Offline checks

```bash
python -m compileall -q voiceledger-commerce
python -m unittest discover -s voiceledger-commerce -p 'test_*.py' -v
```

Review-only PR: https://github.com/mahnue04-jpg/TRANSPORTATION/pull/562
