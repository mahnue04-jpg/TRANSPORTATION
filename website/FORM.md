# Early Access form architecture (W4)

The public form does **not** contain SMTP passwords, API keys, or Stripe secrets.

## Current public behavior

`formEndpoint` is empty because no `LEAD_WEBHOOK_URL` secret is configured on the Pages project.

1. Browser validates required fields, email format, and privacy consent.
2. Honeypot field `company_website` is ignored as spam.
3. The request is stored in `localStorage` only.
4. The success message states that no email was sent.

## Prepared backend

`POST /api/leads` is deployed as a Cloudflare Pages Function. Without `LEAD_WEBHOOK_URL` it returns `503 lead_delivery_disabled`. See `LEAD_ENDPOINT.md`.

Do not set `formEndpoint` to `/api/leads` until that secret exists. Otherwise the page would attempt live delivery that is still disabled.
