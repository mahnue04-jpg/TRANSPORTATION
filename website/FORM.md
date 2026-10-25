# Early Access form architecture (W9)

The public form does **not** contain SMTP passwords, API keys, Stripe secrets, or a private destination inbox.

## Current public behavior

`formEndpoint` is `/api/leads`. Public contact email is `info@getamicor.com`.

1. Browser validates required fields, email format, and privacy consent.
2. Honeypot field `middle_name_confirm` is not sent as a real lead.
3. A success message, including a reference ID, is shown only after `POST /api/leads` confirms KV persistence.
4. If KV storage fails, the page says AMICOR did not confirm that the request was saved and keeps a local fallback.
5. Optional `LEAD_WEBHOOK_URL` notification is best-effort. The page does not claim email delivery unless that webhook succeeds. Email Routing is not required for form success.

## Destination

Validated leads are stored in the AMICOR Cloudflare KV namespace bound as `AMICOR_LEADS`. That store is authoritative.

An optional `LEAD_WEBHOOK_URL` secret may later forward a copy to a private HTTPS endpoint. Set that secret only in the Cloudflare Pages dashboard. It is not set in W9.

Mailbox aliases info@getamicor.com and sales@getamicor.com are **ACTIVE and VERIFIED**. They are a separate channel from this form. See `EMAIL.md`.

List stored leads (owner only):

```powershell
wrangler kv key list --namespace-id aef188e1167a41c98ee81deabbbce50d --remote --prefix lead:
```
