# AMICOR public website (Phase W2)

Static corporate and software-commercialization site for **AMICOR** / **AMICOR HEALTH ISF LLC**.

This folder is independent of Health ISF production code, Stripe, Delivery execution, Freight, Nova Core, Driver 001, and the Autonomous Operations Agent backend.

## Local run

From the repository root:

```bash
cd website
python -m http.server 4173
```

Open http://127.0.0.1:4173/

Regenerate HTML after editing `_generate.py`:

```bash
python website/_generate.py
```

No Node packages, accounts, or paid tools are required.

## Canonical URL

Generated pages, `sitemap.xml`, and `robots.txt` use the placeholder origin `https://amicor.local`.

When a public host exists:

1. Set `ORIGIN` in `_generate.py` to that URL (no trailing slash).
2. Set `window.AMICOR_SITE.siteOrigin` in `assets/js/site-config.js` to the same URL.
3. Run `python website/_generate.py`.

Do not purchase a domain in this phase.

## Content-status matrix

| Surface | Status |
|---|---|
| This public website | LIVE (when you later host it) |
| Autonomous Operations Agent | EARLY ACCESS / IN DEVELOPMENT |
| AMICOR Health | IN DEVELOPMENT |
| AMICOR Deliver | COMING SOON / IN DEVELOPMENT |
| Lifesaver AI Care Cloud | IN DEVELOPMENT |
| Home Hub | FUTURE HARDWARE / IN DEVELOPMENT |

Prices on the Operations Agent page are **preliminary pricing / subject to change before commercial launch**. There is no checkout.

## Routes

- `/`
- `/health/`
- `/deliver/`
- `/technologies/`
- `/technologies/autonomous-operations-agent/`
- `/lifesaver/`
- `/home-hub/`
- `/about/`
- `/early-access/`
- `/contact/`
- `/privacy/`
- `/terms/`
- `/software-terms/`
- `/accessibility/`

## Early Access form

See `FORM.md`. Default behavior is validated localStorage fallback. A live POST happens only if `formEndpoint` is set to an approved HTTPS URL. Secrets must not be placed in frontend files.

## Deployment (do not do this until approved)

### Cloudflare Pages (preferred)

1. Create a free Cloudflare account.
2. Pages → Create project → connect this GitHub repository when you are ready to publish.
3. Project settings:
   - Build command: *(leave empty)*
   - Build output directory: `website`
4. After the first preview URL exists, replace `https://amicor.local` as described under Canonical URL.

Estimated recurring hosting cost: **$0** on the Cloudflare Pages free tier.

### GitHub Pages

1. Repository Settings → Pages.
2. Source: Deploy from a branch.
3. Folder: `/website` if GitHub allows a subfolder; otherwise copy `website/` contents to `/docs` or a `gh-pages` branch.
4. Update sitemap/canonical URLs to the `*.github.io` address.

Estimated recurring hosting cost: **$0** on GitHub Pages for a public or qualifying repo.

## Domain connection (later)

Do **not** buy a domain for this phase.

When a domain exists:

1. Cloudflare: Pages project → Custom domains → add the hostname.
2. At the registrar, point the domain to Cloudflare nameservers or add the CNAME Cloudflare shows.
3. GitHub Pages: add the same hostname under Pages → Custom domain, then create the DNS records GitHub shows.

## Paid dependencies

None. No website builder, no paid font service, no paid form vendor.

## Security

Do not add Stripe keys, API secrets, SMTP passwords, database URLs, or customer data to this folder.
