# AMICOR website hosting preview (W3)

Preferred host: **Cloudflare Pages free tier**.  
Fallback: **GitHub Pages**.  
Cost: **$0**. Do not buy a domain in this phase.

W3 could not create a public preview from this environment:

- `wrangler` is not installed
- `CLOUDFLARE_API_TOKEN` is not set
- `gh` is not installed
- the website branch is **2 local commits ahead of `origin/main` and has not been pushed**

Do not treat localhost as a public preview.

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
- Leave `formEndpoint` empty until `LEAD_WEBHOOK_URL` is set. See `LEAD_ENDPOINT.md`.
- Do not attach a custom domain until a name is chosen and purchased in a later phase.
