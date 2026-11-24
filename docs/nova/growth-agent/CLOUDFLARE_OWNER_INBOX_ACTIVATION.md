# AMICOR Nova Growth private inbox — owner activation checklist

Status: **NOT customer-data-ready** until Cloudflare Access is configured and acceptance is completed.

## Already deployed in website repository
- Public consultation form: `/early-access/?product=Nova%20Growth%20Agent&intent=quote`
- Owner UI: `/nova-growth/owner/`
- Read-only owner API: `/nova-growth/owner/api`
- Existing KV source: `AMICOR_LEADS` Cloudflare Pages binding
- API returns 503 if Access config is absent; returns 403 if a valid owner-signed assertion is missing or invalid.

## Required owner-only Cloudflare dashboard configuration

**Do not paste the application token, JWT, or secrets in GitHub, email, or ChatGPT.**

1. Sign in to the Cloudflare account hosting `getamicor.com`. Open **Zero Trust > Access > Applications**.
2. Create a **Self-hosted** application for **`getamicor.com/nova-growth/owner/*`**. Set session duration appropriately and restrict the **Allow** policy to the specific verified AMICOR owner identity. Do not use broad Everyone/All users, public email domains, or a bypass policy. Confirm that both `/nova-growth/owner/` and `/nova-growth/owner/api` are protected.
3. Use the application **AUD tag** shown by Cloudflare Access and your account's Access team domain. In **Workers & Pages > amicor-public > Settings > Variables and Secrets** for **Production**, set:
   - `GROWTH_ACCESS_DOMAIN` = `https://<your-team>.cloudflareaccess.com`
   - `GROWTH_ACCESS_AUD` = the exact Access **AUD tag**
   - `GROWTH_OWNER_EMAIL` = exact email permitted by the Access policy
   These are identity-verification configuration values. Keep all other production secrets private; do not put passwords or raw Access tokens in source.
4. Confirm the Pages project has the existing `AMICOR_LEADS` KV binding on production. Do not change or delete its namespace. Follow Cloudflare's prompt to deploy/redeploy after changing environment configuration if needed.

## Mandatory acceptance tests (no real customer data needed)

1. Open `https://getamicor.com/nova-growth/owner/` in a **signed-out/incognito** browser. The Cloudflare Access login/denial must appear *before the owner UI renders*. Confirm `/nova-growth/owner/api` also denies signed-out access. **This boundary is mandatory** even though the API independently checks Access JWTs.
2. Sign in with the authorized owner identity. Click **Refresh private inbox**. API returns `200` with `ok: true`. Owner-verified empty results are acceptable if no Growth lead exists.
3. From a separate test browser session, submit a **synthetic** Growth inquiry via the public form, with test contact data and explicit consent. Verify form returns a saved/delivered acknowledgement (not merely a local-only fallback).
4. Refresh owner inbox; verify the synthetic **Growth** inquiry is shown once, with correct product, consent, and source; no Operations or other AMICOR leads appear.
5. Sign out and verify the same private API no longer returns rows. Try a different unapproved account and verify denial.
6. Confirm no messages, calendar bookings, payment charges, or automated outreach were initiated. Leave Growth production message transports and Stripe disabled.

## Release separation
- This supervised inbox is a direct, read-only Cloudflare KV view, **not** a live Growth CRM synchronization or backend deployment. It does not mark leads processed or write to Growth Postgres.
- Do not merge Growth backend PR #586 as part of this activation.
- Do not modify production Render Postgres, Operations Agent, Creative Studio, or the site's lead POST handler as part of these steps.

## Quick troubleshooting
- **503 `private_inbox_not_configured`**: missing/invalid Access environment settings, or certs unavailable.
- **403 `access_denied`**: no valid Cloudflare Access JWT, identity mismatch, audience mismatch, or signature validation failure.
- **503 `lead_store_unavailable`**: Pages KV binding missing or KV read/list failed.
- **Empty inbox**: ensure the test lead was stored in production KV, is exactly `Nova Growth Agent`, and has consent `true`; the API intentionally excludes all other products.

### Evidence to record
Record only non-sensitive check results (HTTP status, date/time, redacted synthetic lead reference), not tokens or customer personal data.
