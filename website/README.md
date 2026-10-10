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
| Car Hub | FUTURE HARDWARE / IN DEVELOPMENT |
| AMICOR Nova Work & Revenue | EARLY ACCESS / IN DEVELOPMENT |
| AMICOR Nova Today | EARLY ACCESS / IN DEVELOPMENT |
| AMICOR Nova Create | IN DEVELOPMENT |

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

## October 5 services refresh

Generate with `python website/_generate.py`; `_refresh.py` supplies the current services and Nova pages.

Public software links were observed in the live Nova app on October 5, 2026. The Operations Agent lists a seven-day no-card account trial and $49/$99/$299 starting options. Website links route into the app; no payment or authentication is implemented here. Creative Studio is described as a supervised release with media-provider and rendering limitations.

Business Services, Ask Nova, Nova Operations, Samples, and Company Profile are new public routes. Sample deliverables are fictional. The profile offers HTML download and browser print/PDF. The existing legal entity name is retained until documentary verification supports a correction.

Inquiry choices are validated by the existing lead endpoint. The frontend displays success only after a response confirms stored or notified delivery. Live KV storage and webhook notification require post-deploy verification.
