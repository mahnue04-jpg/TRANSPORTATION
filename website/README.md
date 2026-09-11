# AMICOR public website (Phase W3)

Static corporate and software-commercialization site for **AMICOR** / **AMICOR HEALTH ISF LLC** (Minnesota).

This folder is independent of Health ISF production code, Stripe, Delivery execution, Freight, Nova Core, Driver 001, and the Autonomous Operations Agent backend.

## Local run

```bash
cd website
python -m http.server 4173
```

Open http://127.0.0.1:4173/

Regenerate HTML after editing `_generate.py`:

```bash
python website/_generate.py
```

## Canonical URL

Pages, `sitemap.xml`, and `robots.txt` still use the placeholder `https://amicor.local` because no public preview host exists yet.

When a `*.pages.dev` or `*.github.io` URL exists:

1. Set `ORIGIN` in `_generate.py` to that URL (no trailing slash).
2. Set `window.AMICOR_SITE.siteOrigin` in `assets/js/site-config.js`.
3. Run `python website/_generate.py`.

Do not purchase a domain in this phase. See `DOMAINS.md` and `DEPLOY.md`.

## Content-status matrix

| Surface | Status |
|---|---|
| This public website | READY TO HOST (not publicly deployed in W3) |
| Autonomous Operations Agent | EARLY ACCESS / IN DEVELOPMENT |
| AMICOR Health | IN DEVELOPMENT |
| AMICOR Deliver | COMING SOON / IN DEVELOPMENT |
| Lifesaver AI Care Cloud | IN DEVELOPMENT |
| Home Hub | FUTURE HARDWARE / IN DEVELOPMENT |

Prices on the Operations Agent page are **preliminary pricing / subject to change**. There is no checkout.

## Early Access form

See `FORM.md` and `LEAD_ENDPOINT.md`. Live email intake is disabled. `formEndpoint` stays empty until an approved destination secret exists.

## Legal drafts

`/privacy/`, `/terms/`, `/software-terms/`, and `/accessibility/` are business drafts with attorney-review notices. They are not certifications, HIPAA statements, SLAs, or executed contracts.

## Hosting

Preferred: Cloudflare Pages free tier. Fallback: GitHub Pages. Estimated cost: **$0**. Owner authentication is required before a preview URL can exist.

## Paid dependencies

None.
