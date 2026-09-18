# AMICOR Nova Stripe subscriptions — live-readiness runbook

Nova billing supports Stripe test mode and an explicitly gated live mode. Live mode is fail-closed unless `NOVA_STRIPE_LIVE_ENABLED=true`.

## Safety rule

Keep `NOVA_STRIPE_LIVE_ENABLED=false` until all owner-controlled Stripe setup is complete. Do not commit real keys or webhook secrets.

## Required production environment variables

```
STRIPE_SECRET_KEY=
STRIPE_PUBLISHABLE_KEY=
STRIPE_NOVA_SAAS_WEBHOOK_SECRET=
STRIPE_NOVA_BILLING_WEBHOOK_SECRET=
NOVA_STRIPE_PRICE_STARTER=
NOVA_STRIPE_PRICE_PROFESSIONAL=
NOVA_STRIPE_PRICE_BUSINESS=
NOVA_FREE_TRIAL_DAYS=7
NOVA_SUBSCRIPTION_ENFORCEMENT=false
NOVA_SUBSCRIPTION_PAST_DUE_ACCESS=false
NOVA_STRIPE_LIVE_ENABLED=false
```

The two Nova webhook secrets should come from the corresponding Stripe live webhook endpoints. Do not reuse the Connect or rider-payment webhook destination unless Stripe is deliberately configured that way.

## Nova billing endpoints

- `POST /api/nova/billing/checkout`
- `POST /api/nova/billing/portal`
- `POST /api/nova/billing/webhook`
- `GET /api/nova/billing/subscription`

Nova signup has a separate webhook route:

- `POST /api/nova/signup/stripe/webhook`

## Billing events currently handled

The Nova billing webhook handles:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`
- `charge.refunded`

Paid invoices and refunds are written to the Nova billing revenue-event ledger with duplicate Stripe event IDs rejected by the existing webhook-event idempotency path.

## Seven-day trial

`NOVA_FREE_TRIAL_DAYS=7` is the current default. The tenant billing path applies the trial only when that tenant has not already used or started a trial.

## Owner-controlled live activation checklist

1. Complete Stripe account/business verification.
2. Add and verify AMICOR's payout bank account in Stripe.
3. Switch the Stripe Dashboard to live mode.
4. Create or verify the live Nova subscription products/prices and copy the live `price_` IDs into the three `NOVA_STRIPE_PRICE_*` variables.
5. Create the live signup webhook endpoint for `/api/nova/signup/stripe/webhook` and store its signing secret in `STRIPE_NOVA_SAAS_WEBHOOK_SECRET`.
6. Create the live billing webhook endpoint for `/api/nova/billing/webhook` and store its signing secret in `STRIPE_NOVA_BILLING_WEBHOOK_SECRET`.
7. Put the live secret and publishable keys into the production environment.
8. Leave `NOVA_STRIPE_LIVE_ENABLED=false` while checking startup, health, and configuration.
9. Enable `NOVA_STRIPE_LIVE_ENABLED=true` only for the controlled live-payment test.
10. Run one controlled live subscription test, then verify Checkout, subscription state, webhook idempotency, invoice revenue persistence, cancellation/failure behavior, and refund persistence before broad customer launch.

Health ISF rider payments, Freight, Driver payouts, and Stripe Connect are separate payment layers and are not enabled by `NOVA_STRIPE_LIVE_ENABLED`.
