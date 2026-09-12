# AMICOR public website (Phase W9)

Static corporate and software-commercialization site for **AMICOR** / **AMICOR HEALTH ISF LLC** (Minnesota).

This folder is independent of Health ISF production code, Stripe, Delivery execution, Freight, Nova Core, Driver 001, and the Autonomous Operations Agent backend.

## Official public URL

- **Official domain:** https://getamicor.com
- Canonical / Open Graph / sitemap origin: `https://getamicor.com`
- Underlying Cloudflare Pages host (not customer-facing): https://amicor-public.pages.dev

## Local run

```bash
cd website
python -m http.server 4173
```

Regenerate HTML after editing `_generate.py`:

```bash
python website/_generate.py
```

## Content-status matrix

| Surface | Status |
|---|---|
| This public website | LIVE at getamicor.com |
| Autonomous Operations Agent | EARLY ACCESS / IN DEVELOPMENT |
| AMICOR Health | IN DEVELOPMENT |
| AMICOR Deliver | COMING SOON / IN DEVELOPMENT |
| Lifesaver AI Care Cloud | IN DEVELOPMENT |
| Home Hub | FUTURE HARDWARE / IN DEVELOPMENT |

Prices on the Operations Agent page are **preliminary pricing / subject to change**. There is no checkout.

## Early Access form

See `FORM.md` and `LEAD_ENDPOINT.md`. `formEndpoint` is `/api/leads`. Validated inquiries are stored in an AMICOR Cloudflare KV lead store. That store remains authoritative if mailbox forwarding or an optional webhook is missing.

Public contact address: `info@getamicor.com`. Cloudflare Email Routing is **ACTIVE and VERIFIED** for info@ and sales@. Catch-all is off. Do not put the private destination inbox in this folder. See `EMAIL.md`.

Internal outreach plan: `FIRST_CUSTOMER_PREP.md`. Do not treat that file as a public offer.

## Legal drafts

`/privacy/`, `/terms/`, `/software-terms/`, and `/accessibility/` are business drafts. They are not attorney-approved.

## Hosting

Cloudflare Pages free tier plus the owner-purchased `getamicor.com` domain. See `DEPLOY.md`.

## Paid dependencies

None in the website codebase. Domain registration is paid separately by the owner.
