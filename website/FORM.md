# Early Access form architecture (W5)

The public form does **not** contain SMTP passwords, API keys, or Stripe secrets.

## Current public behavior

`formEndpoint` is `/api/leads`.

1. Browser validates required fields, email format, and privacy consent.
2. Honeypot field `company_website` is not sent as a real lead.
3. A success message is shown only after `POST /api/leads` returns 2xx.
4. If delivery fails, the page says AMICOR did not receive the request and saves a local fallback.

## Destination

Validated leads are stored in the AMICOR Cloudflare KV namespace bound as `AMICOR_LEADS`. An optional `LEAD_WEBHOOK_URL` secret can later forward a copy to an inbox webhook. That secret is not set in W5.

List stored leads (owner only):

```powershell
wrangler kv key list --namespace-id <AMICOR_LEADS id> --remote
```
