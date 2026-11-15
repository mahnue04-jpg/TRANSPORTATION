# PR #521 — isolated browser acceptance plan

## Verified environment facts (read-only, Nov 14/15 2026)
- Existing Render staging web service: `nova-growth-validation-490` (`srv-dbqv8ip5efls73dtpmo0`).
- Service branch: `review/growth-agent-staging-corrections-20261112`; last live deployed commit: `1395f7e47f0f2e4a94473621374f9219e180ac6b`.
- `autoDeploy=no`; PR previews disabled.
- Both **build and start commands explicitly assert the existing commit SHA**. The start script additionally asserts an isolated PostgreSQL hostname and `/nova_ga_490_dispos` database, and runs staging migrations/tests before startup.
- Therefore PR #521 cannot safely be deployed in place under existing owner-approved guardrails. Do not weaken, remove, or bypass that guard, and do not change the existing service branch, database, environment, or deployment settings.
- PR #521 is a synthetic-only preview; it does not connect to Cloudflare KV.

## Appropriate isolated preview (requires separate owner authorization)
1. Provision a **new, distinct, non-production Render preview service**, with a separate synthetic/disposable database and staging-only auth credentials. Do not reuse `nova-growth-validation-490`'s database or production services.
2. Pin builds to **the exact approved PR #521 commit SHA**, disable auto-deploy and PR automatic previews, disable all paid AI/video, Stripe, SMS, email, real calendar and live messaging integrations; no Cloudflare KV credentials, `LEAD_WEBHOOK_URL`, or production customer data.
3. Preserve the existing staging service, its database snapshots/backups and current pin untouched.
4. Verify setup only after `106` backend tests, `7` PostgreSQL tests, adapter tests and browser interaction checks succeed on the **exact deployed commit**.
5. In a real browser, sign in as staging owner, open `/nova/growth`, click **Load synthetic preview** and verify the marked example row appears once, with no real customer names, messages, charge buttons, or false live counts.
6. Check unauthenticated, nonowner and cross-tenant access; clear state after sign-out, refresh, and token expiration. Verify demo disabled shows explicit unavailable text rather than zero customers.
7. Capture screenshot/video evidence and include exact service name, revision, tests, and owner-screen observations. Keep separate formal approval gates for production Cloudflare KV read access and any merge or production deployment.

## Current disposition
No staging preview of PR #521 has been deployed or browser-verified. Existing `nova-growth-validation-490` remains on its pinned commit; **do not modify it**. All work remains draft and synthetic-only.
