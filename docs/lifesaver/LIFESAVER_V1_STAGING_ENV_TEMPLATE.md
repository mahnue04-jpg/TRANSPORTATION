# Lifesaver V1 — Staging environment template

Variable **names** and safe placeholders only. Do not put real keys or passwords in this file.

Use a dedicated staging secret store. Never copy production values into staging.

| Variable | Classification | Safe placeholder | Purpose |
|---|---|---|---|
| `DATABASE_URL` | Required; **must be staging-only** | `postgresql://lifesaver_staging:***@staging-db.example.internal:5432/lifesaver_staging` | Staging Postgres. Never production. |
| `JWT_SECRET` | Required; **must be staging-only** | `openssl rand -hex 32` output | Access-token signing. Distinct from production and from `SECRET_KEY`. |
| `SECRET_KEY` | Required; **must be staging-only** | `openssl rand -hex 32` output | App signing material. Distinct from `JWT_SECRET`. |
| `ALLOWED_ORIGINS` | Required if any cross-origin client is used | `https://lifesaver-staging.example.com` | CORS allowlist. Same-origin `/lifesaver` does not need `*`. |
| `AMICOR_PUBLIC_URL` | Required for host identity | `https://lifesaver-staging.example.com` | Public origin. Not the production Health ISF host. |
| `APP_VERSION` | Required | `lifesaver-v1-staging.1` | Release label. |
| `LOG_LEVEL` | Optional | `INFO` | Prefer `INFO`. Do not use `DEBUG` if it can emit request bodies. |
| `AMICOR_SKIP_WMI_PLATFORM_QUERY` | Optional (Windows jump hosts) | `1` | Avoids a Windows WMI stall. Harmless elsewhere. |
| `LIFESAVER_SMOKE_BASE_URL` | Required for smoke | `https://lifesaver-staging.example.com` | Smoke target. Must not be production. |
| `LIFESAVER_SMOKE_EMAIL` | Required for authenticated smoke | `lifesaver.staging.member@example.com` | Dedicated staging test member. |
| `LIFESAVER_SMOKE_PASSWORD` | Required for authenticated smoke; **must be staging-only** | *(secret store only)* | Never embed in git or chat. |
| `LIFESAVER_SMOKE_DRY_RUN` | Optional | `1` | Public endpoints only. Use `1` until staging credentials exist. |
| `LIFESAVER_SMOKE_ALLOW_PRODUCTION` | **Must remain disabled in staging** | unset / `0` | Do not set to `1`. |
| `AMICOR_ENVIRONMENT` | Required for isolated public staging | `lifesaver_staging` | Enables Lifesaver-only hostname isolation. Do not set this on Health ISF production. |
| `AMICOR_LIFESAVER_STAGING_ISOLATED` | Recommended on the staging service | `1` | Explicit isolation flag. No-op when unset. |
| `AMICOR_RESTRICT_SEED_ACCOUNTS` | Required unless a dedicated seed is approved | `1` | Keep restricted. Do not open production seed accounts on staging. |
| `AMICOR_SEED_PASSWORD` | Optional; **must be staging-only** if used | *(secret store only)* | Only for a dedicated staging seed. Never the production rider/driver seed. |
| `TESTING` | **Must remain disabled in staging** | unset / `0` | Local/test isolation flag. Not for staging. |
| `STRIPE_SECRET_KEY` | **Production-only / forbidden in staging for Lifesaver** | unset | Lifesaver does not take payments. Do not introduce live keys. |
| `STRIPE_PUBLISHABLE_KEY` | **Forbidden for Lifesaver staging** | unset | Same. |
| `TWILIO_*` / SMS provider keys | **Must remain disabled in staging** | unset | Notifications are local simulation only. |
| `SES_*` / `SENDGRID_*` / SMTP credentials | **Must remain disabled in staging** | unset | No real email. |
| `APPLE_HEALTH_*` / `FITBIT_*` / device vendor keys | **Must remain disabled in staging** | unset | Devices stay simulated. |
| Any emergency-services API key | **Forbidden** | unset | SOS is demonstration only. |
| Production `DATABASE_URL` | **Forbidden in staging** | — | Do not reuse. |
| Production `JWT_SECRET` / `SECRET_KEY` | **Forbidden in staging** | — | Do not reuse. |
| Production Render `amicor-health-isf` credentials | **Forbidden in staging** | — | Do not point Lifesaver staging at production. |

## Product modes (not separate env vars)

These are code-enforced in V1. Staging must keep them as implemented:

- Notification provider: local fake outbox only
- Device ingest: simulated only; `external_device_reserved` rejected
- Transport: coordination simulation only; no Health ISF ride create
- AI: Lifesaver-owned adapter; no Nova Core import or writes

There is no Lifesaver feature flag to “turn on” real email, SMS, dispatch, devices, or clinical AI. Do not add one during staging.

## Seed-user strategy

1. Create a dedicated staging member in the staging auth database.
2. Store the password only in the staging secret store.
3. After first login, grant consents explicitly in the UI (they start false).
4. Authenticated smoke requires those consents or it will exit nonzero on 403.
5. Do not reuse production rider, driver, or Driver 001 accounts.
