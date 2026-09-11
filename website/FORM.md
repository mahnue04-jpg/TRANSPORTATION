# Early Access form architecture (W2)

The public form does **not** contain SMTP passwords, API keys, or Stripe secrets.

## Current W2 behavior

1. Browser validates required fields, email format, and privacy consent.
2. A hidden honeypot field (`company_website`) is a spam-protection placeholder.
3. If `window.AMICOR_SITE.formEndpoint` is empty, the request is stored in `localStorage` only.
4. If an approved HTTPS endpoint is later set, the page POSTs JSON to that endpoint and still keeps a local fallback if the request fails.

## Connect a live intake channel later

Edit `website/assets/js/site-config.js`:

```js
window.AMICOR_SITE = {
  siteOrigin: "https://YOUR-PAGES-HOST",
  formEndpoint: "https://YOUR-APPROVED-ENDPOINT"
};
```

Use only an already approved serverless function or AMICOR backend route. Do not put credentials in this file.

Suggested JSON body:

```json
{
  "receivedAt": "ISO-8601",
  "name": "",
  "company": "",
  "email": "",
  "phone": "",
  "industry": "",
  "companySize": "",
  "product": "",
  "message": "",
  "consent": true,
  "source": "amicor-public-website-w2"
}
```

## Remaining requirement before live lead collection

An approved backend or serverless receiver must exist, `formEndpoint` must be set to that HTTPS URL, and privacy text must be reviewed. Until then, submissions stay on the visitor’s device.
