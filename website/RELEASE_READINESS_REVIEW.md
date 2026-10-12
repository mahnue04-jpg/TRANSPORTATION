# getamicor.com release-readiness review

This note is a review handoff. It is not a deployment authorization.

## What this package changes

The shared site navigation CTA is **Open Nova**, and it stays on `https://getamicor.com/nova-access/`. That page sends people to Nova screens that already exist on `amicor-health-isf-py.onrender.com`:

| Workspace | Public status on this page | Signed-in route |
| --- | --- | --- |
| Ask Nova | Account access | `/nova?signin=1` |
| Operations Agent | Supervised release | `/nova?signin=1`, plus the existing sandbox at `/nova/anonymous-agent` |
| Work & Revenue | Early access | `/nova/work` |
| Nova Today | Early access | `/nova/today` |
| Creative Studio | Supervised release | `/nova/creative` |

The sandbox copy says it does not send email, update a CRM, charge money, or submit work. Work & Revenue copy says external submission, client contact, and payment execution stay off.

`firstCustomerFunnel` is not set to true. `/start/` and `/guides/research-memo-setup/` are not in this package. Casting intake, public auditions, payment collection, and automatic applications are not linked.

## Do not do these things from this review

- Do not merge this pull request.
- Do not retarget it onto `main`.
- Do not push to `feature/amicor-public-website-w1`.
- Do not run `wrangler pages deploy`.
- Do not change Cloudflare or Render settings.
- Do not run a live migration.
- Do not turn on feature flags, spend, or send outreach.

## Cloudflare Pages

`website/DEPLOY.md` and `website/wrangler.toml` describe project `amicor-public`.

- Production branch recorded for Git deploys: `feature/amicor-public-website-w1`
- Root directory: `website`
- Build command: empty. Pages publishes the folder as-is.
- Manual production command, which this review must not run: `wrangler pages deploy . --project-name amicor-public`
- A push or merge into `feature/amicor-public-website-w1` is the Git trigger that publishes getamicor.com when that Pages project is connected.
- A push of this draft branch can create a Pages preview only if preview deployments are already enabled. That preview is not production, and it is not permission to promote the branch.

`website/scripts/build-production.mjs` is not in this package. The funnel gate that omits `/start/` lives on the separate draft funnel branch. Shipping the raw `website/` tree while that gate is unmerged can still serve unpublished funnel files if those files are present. They are not present here.

## Render

`render.yaml` defines web service `amicor-health-isf` with `releaseCommand` `alembic upgrade heads`. Render deploys that service from its connected branch. This package does not change `render.yaml`, the service name, or the hostname.

Merging website work into `main` would be a separate backend deploy. Do not merge this pull request into `main`.

## Netlify

Pull requests into `main` already open a deploy preview for `grand-beignet-6447ea`. This pull request targets `feature/amicor-public-website-w1` so it does not use that path. Do not retarget it.

## GitHub Actions

`.github/workflows/website-nova-access.yml` runs the Python route checks and the mobile/accessibility browser check. It does not deploy. The Jekyll workflow in this repo runs for `main` only.

## Rollback

Leave the pull request unmerged. getamicor.com stays on the current `feature/amicor-public-website-w1` revision. If a preview was created for this branch, discard that preview in Cloudflare. Do not roll production forward to this commit.
