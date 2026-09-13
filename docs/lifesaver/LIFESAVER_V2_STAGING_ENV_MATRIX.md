# Lifesaver V2 — Staging environment matrix

Variable **names** and safe patterns only. Do not put real keys, passwords, or production URLs in this file or in git.

Isolation is request-time. Production `app.main` stays unchanged unless `AMICOR_ENVIRONMENT=lifesaver_staging` or `AMICOR_LIFESAVER_STAGING_ISOLATED=1`.

| Variable | Required | Purpose | Safe staging pattern | Gras can generate | Owner input | Hostname-dependent |
|---|---|---|---|---|---|---|
| `DATABASE_URL` | Required | Dedicated Lifesaver staging database only | New Render Postgres URL **or** `sqlite:////data/lifesaver_staging.db` on a staging disk | No (needs provisioned DB) | Yes — create new DB, never reuse Health ISF | No |
| `JWT_SECRET` | Required | Access-token signing | `openssl rand -hex 32` stored only in Render | Yes, into Render secret store | Owner must paste into Render | No |
| `SECRET_KEY` | Required | App signing material; distinct from `JWT_SECRET` | `openssl rand -hex 32` stored only in Render | Yes, into Render secret store | Owner must paste into Render | No |
| `ALLOWED_ORIGINS` | Required | CORS allowlist; never `*` | `https://amicor-lifesaver-staging.onrender.com` | After hostname exists | Confirm final hostname | Yes |
| `AMICOR_PUBLIC_URL` | Required | Public origin identity | Same as the Render service URL | After hostname exists | Confirm final hostname | Yes |
| `APP_VERSION` | Required | Release label | `lifesaver-v2-staging.1` | Yes | Optional wording | No |
| `AMICOR_RESTRICT_SEED_ACCOUNTS` | Required | Keep seed accounts locked down | `1` | Yes | No | No |
| `AMICOR_ENVIRONMENT` | Required | Turns on isolated staging when set to `lifesaver_staging` | `lifesaver_staging` | Yes | Confirm before first deploy | No |
| `AMICOR_LIFESAVER_STAGING_ISOLATED` | Recommended | Explicit isolation flag if environment name is not used | `1` | Yes | No | No |
| `LOG_LEVEL` | Optional | Log verbosity | `INFO` | Yes | No | No |
| `AMICOR_SKIP_WMI_PLATFORM_QUERY` | Optional | Avoid a Windows WMI stall on jump hosts | `1` | Yes | No | No |
| `LIFESAVER_SMOKE_BASE_URL` | Smoke only | Smoke target | Final staging HTTPS URL | After hostname exists | Confirm | Yes |
| `LIFESAVER_SMOKE_EMAIL` | Smoke only | Dedicated staging member | `lifesaver.staging.member@example.com` | Can propose | Owner creates the user | No |
| `LIFESAVER_SMOKE_PASSWORD` | Smoke only | Staging member password | Secret store only | Yes, into secret store | Owner stores it | No |
| `LIFESAVER_SMOKE_DRY_RUN` | Smoke only | Public endpoints only until credentials exist | `1` until first authenticated smoke | Yes | No | No |

## Must remain unset

| Variable | Why |
|---|---|
| `STRIPE_*` | Lifesaver staging does not take payments |
| `TWILIO_*` | Notifications stay local/simulated |
| `SES*` / `SENDGRID*` / `SMTP*` | No real email |
| Device-vendor keys | Devices stay simulated |
| Emergency-service keys | SOS is demonstration only |
| Production `DATABASE_URL` | Dedicated staging DB only |
| Production `JWT_SECRET` / `SECRET_KEY` | Distinct signing material only |
| `LIFESAVER_SMOKE_ALLOW_PRODUCTION` | Smoke must refuse Health ISF / onrender production hosts |
| `TESTING` | Local pytest flag, not a staging runtime |

## Do not run

`alembic upgrade heads` — Lifesaver Phase 1 revises `20260909_nova_freight_settlement` and would walk Nova / Freight / Stripe / Driver history. Use `python scripts/lifesaver_staging_bootstrap.py` instead.
