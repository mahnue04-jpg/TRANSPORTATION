# Early Access form architecture (W3)

The public form does **not** contain SMTP passwords, API keys, or Stripe secrets.

## Current public behavior

1. Browser validates required fields, email format, and privacy consent.
2. A hidden honeypot field (`company_website`) is a spam-protection placeholder.
3. `window.AMICOR_SITE.formEndpoint` is empty, so the request is stored in `localStorage` only.
4. No production email is sent. AMICOR does not receive the inquiry from this page.

## Prepared but disabled backend

`functions/api/leads.js` is a same-origin `POST /api/leads` receiver for Cloudflare Pages. It stays closed until `LEAD_WEBHOOK_URL` is set in the Pages dashboard. See `LEAD_ENDPOINT.md`.

## Connect a live intake channel later

Edit `website/assets/js/site-config.js` only after the Pages function is deployed and a destination secret exists:

```js
window.AMICOR_SITE = {
  siteOrigin: "https://YOUR-PAGES-HOST",
  formEndpoint: "/api/leads"
};
```

Do not put credentials in this file.

## Remaining requirement before live lead collection

1. A public host for `website/`.
2. `LEAD_WEBHOOK_URL` set to an approved HTTPS inbox webhook or AMICOR lead store.
3. `formEndpoint` set to `/api/leads`.
4. Privacy draft reviewed against the fields actually collected.
