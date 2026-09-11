# AMICOR public website (Phase W4)

Static corporate and software-commercialization site for **AMICOR** / **AMICOR HEALTH ISF LLC** (Minnesota).

This folder is independent of Health ISF production code, Stripe, Delivery execution, Freight, Nova Core, Driver 001, and the Autonomous Operations Agent backend.

## Live preview

- Stable project URL: https://amicor-public.pages.dev
- Canonical / Open Graph / sitemap origin: `https://amicor-public.pages.dev`
- Unique per-deploy URLs (`https://<hash>.amicor-public.pages.dev`) also work

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
| This public website | LIVE PREVIEW on Cloudflare Pages |
| Autonomous Operations Agent | EARLY ACCESS / IN DEVELOPMENT |
| AMICOR Health | IN DEVELOPMENT |
| AMICOR Deliver | COMING SOON / IN DEVELOPMENT |
| Lifesaver AI Care Cloud | IN DEVELOPMENT |
| Home Hub | FUTURE HARDWARE / IN DEVELOPMENT |

Prices on the Operations Agent page are **preliminary pricing / subject to change**. There is no checkout.

## Early Access form

See `FORM.md` and `LEAD_ENDPOINT.md`. Live email intake is disabled. `formEndpoint` stays empty until `LEAD_WEBHOOK_URL` is set in the Cloudflare Pages dashboard.

## Legal drafts

`/privacy/`, `/terms/`, `/software-terms/`, and `/accessibility/` are business drafts. They are not attorney-approved.

## Hosting

Cloudflare Pages free tier. Estimated cost: **$0**. See `DEPLOY.md`.

## Paid dependencies

None.
