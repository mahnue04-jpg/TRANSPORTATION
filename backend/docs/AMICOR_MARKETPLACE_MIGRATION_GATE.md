# AMICOR Marketplace migration gate

This document is the launch gate for the Webflow-to-AMICOR digital marketplace migration.

## Current catalog

Five newer Webflow marketplace records are normalized in `backend/static/nova-marketplace/catalog.json`.

Each product remains `REVIEW_REQUIRED` and `BLOCKED` for checkout until all three conditions are true:

1. A verified digital deliverable file is available and owned/controlled by AMICOR.
2. A dedicated **one-time** marketplace Stripe Checkout path is implemented and tested.
3. A successful payment creates a durable entitlement and a controlled download/access path for the purchased product.

## Payment isolation

Do **not** route marketplace purchases through the existing Nova SaaS subscription checkout.

The existing Nova signup/billing Stripe clients are subscription-oriented and use `mode=subscription`. Marketplace products are currently exported as one-time purchases, so marketplace billing must have its own product/payment contract, webhook metadata, idempotency, and entitlement handling.

No live Stripe key, live charge, customer, subscription, invoice, or price is created by this migration branch.

## Source cleanup

The following Webflow fields are intentionally not trusted as customer actions:

- `example.com/demo`
- `example.com/docs`
- `example.com/get-access`
- the legacy Google Drive URL containing `YOURFILEID`

Webflow-hosted image URLs are retained temporarily for visual migration only. Before Webflow is retired, approved product images should be copied to AMICOR-controlled storage and catalog URLs updated.

## Legacy records

The eight older commerce rows remain reconciliation-only. They are not public checkout products. Trading-bot records require separate product/deliverable review before any publication.

## Next implementation gate

After the owner supplies or identifies the actual deliverable files:

- store each approved file in an AMICOR-controlled private location;
- map product slug -> immutable deliverable identifier/version;
- implement one-time Stripe Checkout in TEST mode only;
- process `checkout.session.completed` with product metadata and webhook idempotency;
- create purchase entitlement only after verified successful payment;
- issue a time-limited or authenticated download;
- test duplicate webhooks, failed payment, wrong product, unauthorized download, and repeat download behavior;
- only then consider a controlled live-payment test.
