# AMICOR website hosting preview (W3)

Preferred host: **Cloudflare Pages free tier**.  
Fallback: **GitHub Pages**.  
Cost: **$0**. Do not buy a domain in this phase.

W6 official domain: https://getamicor.com  
Cloudflare Pages project: `amicor-public`  
Underlying host only: https://amicor-public.pages.dev

Redeploy from this folder after website changes:

```powershell
cd website
wrangler pages deploy . --project-name amicor-public
```

Do not put secrets in this repo. If you later add optional lead notification, set `LEAD_WEBHOOK_URL` only in the Pages dashboard as a secret. Email Routing steps are in `EMAIL.md` and are owner-only.

## Exact owner step (required before a real preview URL exists)

Sign in to the AMICOR Cloudflare account (or create a free account), then either:

### A. Cloudflare Dashboard — Git connected (needs a push)

1. Push this branch only if you explicitly approve publishing the website commits:

```powershell
git push -u origin feature/amicor-public-website-w1
```

2. Cloudflare Dashboard → Workers & Pages → Create → Pages → Connect to Git.
3. Repository: `mahnue04-jpg/TRANSPORTATION` (or the AMICOR-approved fork).
4. Project name: `amicor-public`
5. Branch: `feature/amicor-public-website-w1`
6. Root directory: `website`
7. Build command: *(leave empty)*
8. Build output directory: `/` or `.`
9. Deploy. Copy the `*.pages.dev` URL.
10. Set `ORIGIN` in `_generate.py` and `siteOrigin` in `assets/js/site-config.js` to that URL (no trailing slash), regenerate, and commit.

### B. Cloudflare Dashboard — Direct upload (no git push)

1. Open a terminal in this repository.
2. Install and authenticate Wrangler with the owner Cloudflare login:

```powershell
npm install -g wrangler
wrangler login
cd website
wrangler pages deploy . --project-name amicor-public
```

3. Copy the printed `*.pages.dev` URL and update canonicals as in step A10.

### C. GitHub Pages fallback (also needs a push)

1. Push the branch if approved.
2. Repository Settings → Pages → Deploy from a branch.
3. Branch: `feature/amicor-public-website-w1`
4. Folder: `/website` if offered; otherwise copy `website/` to `/docs` on a dedicated pages branch.
5. Use the `*.github.io` URL as `ORIGIN`.

## After a preview URL exists

- Keep product status labels unchanged.
- `formEndpoint` is `/api/leads`. KV storage is required for a public success message. An optional webhook is not required. See `LEAD_ENDPOINT.md`.
- Official domain is already `getamicor.com`. Do not buy another domain.
