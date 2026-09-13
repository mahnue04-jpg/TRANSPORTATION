# Lifesaver V2 — Staging isolation

The shared process is still `uvicorn app.main:app`. Isolation is **not** a second application. It is a request-time gate that is a no-op unless:

- `AMICOR_ENVIRONMENT=lifesaver_staging` (or `lifesaver_isolated_staging`), or
- `AMICOR_LIFESAVER_STAGING_ISOLATED=1`

Local verify servers that use `lifesaver_local_v2` / `lifesaver_local_staging` stay on the full app so existing local checks keep working.

## Allowed on an isolated hostname

- `/lifesaver` and `/lifesaver/*` UI
- `/api/lifesaver/*` except `/api/lifesaver/mock-pi/*`
- `/api/auth/*`
- `/static/lifesaver/*`, `/static/ux/*`, `/static/branding/*`
- `/api/health/live`
- `/` redirects to `/lifesaver`

## Blocked (404)

Nova, Health ISF, Delivery, Freight, payments, marketing, admin, platform-ops, workspace, and other shared HTML/API prefixes.

## Extra staging guards

- Dedicated `DATABASE_URL` must not look like Health ISF production
- `JWT_SECRET` or `SECRET_KEY` required (no ephemeral fallback for public staging)
- `ALLOWED_ORIGINS` must not be `*`
- Stripe / Twilio / SES / SendGrid / SMTP keys must stay unset
- Hardware mode forced to `mock`
- Home Hub agent mutating/status routes require `Authorization: Bearer`
- Mock Pi stays local-only
- Schema init: `python scripts/lifesaver_staging_bootstrap.py` — never `alembic upgrade heads`
