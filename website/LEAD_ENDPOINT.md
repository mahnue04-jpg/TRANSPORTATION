# Early Access lead endpoint (W3)

Live lead collection stores validated inquiries in the AMICOR-owned Cloudflare KV namespace `AMICOR_LEADS`. Inbox webhook forwarding is optional and is not configured in W5. The public form does not contain secrets.

## Current public behavior

`assets/js/site-config.js` keeps:

```js
formEndpoint: ""
```

Empty means the browser validates the request and stores it in `localStorage` only. No email is sent.

## Contract

`POST /api/leads`  
Content-Type: `application/json`

The Cloudflare Pages Function in `functions/api/leads.js` implements this contract after the `website/` folder is hosted as a Pages project.

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
  "company_website": "",
  "source": "amicor-public-website-w3"
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
| 202 | Accepted and forwarded to the approved destination |
| 204 | Honeypot trip; pretend success |
| 400 | Validation failed |
| 405 | Not POST |
| 429 | Rate limited (about 5 requests / hour / IP) |
| 502 | Destination rejected the payload |
| 503 | `LEAD_WEBHOOK_URL` is not set; delivery disabled |

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
- Ignore / no-op honeypot field `company_website`
- No secret values in the function source
- Destination URL and optional bearer token come from Pages environment variables only:
  - `LEAD_WEBHOOK_URL`
  - `LEAD_WEBHOOK_TOKEN` (optional)

## Enabling live delivery later

1. Deploy the `website/` folder to Cloudflare Pages.
2. In the Pages project → Settings → Environment variables, add `LEAD_WEBHOOK_URL` pointing to an approved AMICOR inbox webhook, serverless mailer, or admin lead store. Do not put SMTP passwords in the website repo.
3. Set `formEndpoint` in `assets/js/site-config.js` to the same-origin path `/api/leads`.
4. If the endpoint is on another HTTPS host, also add that host to `connect-src` in `_headers`.
5. Confirm the Privacy Policy draft still matches what is collected.

Until those steps are done, the form must keep the local fallback and must not claim that AMICOR received the inquiry.
