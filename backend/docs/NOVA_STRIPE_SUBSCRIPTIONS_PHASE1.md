# AMICOR Nova Stripe subscriptions — Phase 1 (TEST foundation)

TEST MODE ONLY. Do not enable live Stripe. Do not invent plan prices.

## Environment (examples only — never commit real keys)

```
STRIPE_SECRET_KEY=sk_test_replace_me
STRIPE_WEBHOOK_SECRET=whsec_replace_me
STRIPE_NOVA_BILLING_WEBHOOK_SECRET=whsec_replace_me
NOVA_STRIPE_PRICE_STARTER=price_replace_me
NOVA_STRIPE_PRICE_PROFESSIONAL=price_replace_me
NOVA_STRIPE_PRICE_BUSINESS=price_replace_me
NOVA_FREE_TRIAL_DAYS=7
NOVA_SUBSCRIPTION_ENFORCEMENT=false
```

`NOVA_SUBSCRIPTION_ENFORCEMENT` must remain `false` in Phase 1.

## Endpoints

- `POST /api/nova/billing/checkout`
- `POST /api/nova/billing/portal`
- `POST /api/nova/billing/webhook`
- `GET /api/nova/billing/subscription`

Nova founding-customer signup (`/api/nova/signup`) is a separate TEST path and is unchanged.

Health ISF rider payments, Freight, Driver 001, and Stripe Connect are not part of this layer.
