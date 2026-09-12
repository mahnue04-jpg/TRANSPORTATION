# Early Access form architecture (W9)

The public form does **not** contain SMTP passwords, API keys, Stripe secrets, or a private destination inbox.

## Current public behavior

`formEndpoint` is `/api/leads`. Public contact email is `info@getamicor.com`.

1. Browser validates required fields, email format, and privacy consent.
2. Honeypot field `company_website` is not sent as a real lead.
3. A success message is shown only after `POST /api/leads` returns 2xx.
4. If KV storage fails, the page says AMICOR did not receive the request and saves a local fallback.
5. Optional `LEAD_WEBHOOK_URL` notification is best-effort. Email Routing is not required for form success.

## Destination

Validated leads are stored in the AMICOR Cloudflare KV namespace bound as `AMICOR_LEADS`. That store is authoritative.

An optional `LEAD_WEBHOOK_URL` secret may later forward a copy to a private HTTPS endpoint. Set that secret only in the Cloudflare Pages dashboard. It is not set in W9.

Mailbox aliases info@getamicor.com and sales@getamicor.com are **ACTIVE and VERIFIED**. They are a separate channel from this form. See `EMAIL.md`.

List stored leads (owner only):

```powershell
wrangler kv key list --namespace-id aef188e1167a41c98ee81deabbbce50d --remote --prefix lead:
```
