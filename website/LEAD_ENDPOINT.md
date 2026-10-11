# Early Access lead endpoint (W9)

Live lead collection stores validated inquiries in the AMICOR-owned Cloudflare KV namespace `AMICOR_LEADS`. That store is **authoritative**. Inbox email and webhooks are optional and must not decide whether the public form succeeds.

The public form does not contain secrets. Do not commit `LEAD_WEBHOOK_URL`, `LEAD_WEBHOOK_TOKEN`, SMTP passwords, or a private destination inbox.

## Current public behavior

`assets/js/site-config.js` keeps:

```js
formEndpoint: "/api/leads"
```

1. The browser validates required fields, email format, and consent.
2. `POST /api/leads` writes the inquiry to KV when validation passes.
3. A success message is shown only after KV persistence returns a reference ID.
4. If KV is unavailable or the write fails, the page says AMICOR did not confirm that the request was saved and keeps a local fallback. A webhook alone is not confirmation.
5. Optional webhook notification, if later configured in the Pages dashboard, is best-effort. Webhook failure must not fail the form after KV write succeeds, and the page must not claim email delivery unless the webhook returned HTTP 2xx.

Email Routing for info@getamicor.com is **ACTIVE and VERIFIED**. It is a separate channel and is not required for form storage. See `EMAIL.md`.

## Contract

`POST /api/leads`  
Content-Type: `application/json`

The Cloudflare Pages Function in `functions/api/leads.js` implements this contract.

### Request

```json
{
  "receivedAt": "2026-09-11T21:00:00.000Z",
  "name": "Jordan Hale",
  "company": "North Star Transit",
  "email": "jordan@example.com",
  "phone": "",
  "industry": "NEMT",
  "companySize": "11-50",
  "product": "Autonomous Operations Agent",
  "message": "I would like a product demo.",
  "consent": true,
  "source": "amicor-public-website-w8"
}
```

Allowed `product` values:

- Autonomous Operations Agent
- AMICOR Health
- AMICOR Deliver
- Lifesaver AI Care Cloud
- Home Hub
- Partnership
- Other

Do not send medical records, diagnoses, insurance IDs, or other sensitive health information.

### Responses

| Status | Meaning |
|---|---|
| 202 | Saved. KV stored a new lead and returned `referenceId`. Email may still be unconfirmed. |
| 200 | Duplicate of a saved lead in the last 24 hours. Returns the original `referenceId`. |
| 204 | Honeypot trip. Nothing is stored. |
| 400 | Validation failed, including a message that is only the quote prompts |
| 405 | Not POST |
| 429 | Rate limited (about 5 requests / hour / IP) |
| 500 | KV write failed. Nothing was confirmed. |
| 503 | KV is not configured. A webhook alone cannot confirm the request. |

Success body:

```json
{
  "ok": true,
  "stored": true,
  "referenceId": "AMQ-1A2B3C4D",
  "duplicate": false,
  "notified": false,
  "emailNotification": { "attempted": false, "sent": false, "reason": "not_configured" }
}
```

`emailNotification.sent` is true only when the optional webhook returned HTTP 2xx. The form shows the reference ID after `stored` is true and does not claim email delivery otherwise.

### Sample error

```json
{ "ok": false, "error": "lead_delivery_disabled" }
```

## Server-side rules

- POST only
- Strip HTML and control characters
- Enforce field length limits
- Require consent
- Reject unknown products
- Ignore / no-op honeypot field `middle_name_confirm`
- No secret values in the function source
- KV write is required for 202. The response includes `referenceId`.
- The same email, product, and message within 24 hours returns the existing reference ID and does not write a second lead.
- Optional destination URL and bearer token come from Pages environment variables only:
  - `LEAD_WEBHOOK_URL`
  - `LEAD_WEBHOOK_TOKEN` (optional)

## Optional webhook later (do not do this in git)

Only after the owner has a private HTTPS endpoint they control (not a CRM purchase required by AMICOR):

1. Cloudflare Dashboard → Workers & Pages → **amicor-public** → Settings → Variables and Secrets.
2. Add `LEAD_WEBHOOK_URL` as a **secret** (Production). Paste the private HTTPS URL there only.
3. Optionally add `LEAD_WEBHOOK_TOKEN` as a secret if that endpoint requires a bearer token.
4. Do not put either value in this repo, in `_generate.py`, or in `site-config.js`.
5. If the endpoint is on another HTTPS host, add that host to `connect-src` only if the **browser** must call it. The Pages Function calls the webhook server-side, so `connect-src` usually stays unchanged.
6. Redeploy is not required for Pages secrets if the function already reads `env.LEAD_WEBHOOK_URL`. Confirm after saving.
7. Test that a valid form submit still returns 202 with a reference ID when the webhook is down. KV remains the source of truth. Email stays unconfirmed.

Until a webhook secret exists, the owner reviews leads with:

```powershell
cd website
npx wrangler kv key list --namespace-id aef188e1167a41c98ee81deabbbce50d --remote --prefix lead:
```

Do not implement a paid external CRM in this phase.
