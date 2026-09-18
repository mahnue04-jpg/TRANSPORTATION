# Lifesaver V1 — Staging infrastructure plan

Phase 3B planning document. **Do not provision, deploy, push, or spend.**

Prepared after local commit `5f0357f` (`docs(lifesaver): finalize staging readiness and rollback plan`).

Related files:

- `docs/lifesaver/LIFESAVER_V1_STAGING_READINESS.md`
- `docs/lifesaver/LIFESAVER_V1_STAGING_ENV_TEMPLATE.md`
- `docs/lifesaver/LIFESAVER_V1_STAGING_ROLLBACK.md`

## Recommendation (cheapest safe)

**Use local-only staging simulation.** Monthly cost **$0**. No new Render service. No new database. No production risk.

This is already running at http://127.0.0.1:8031/lifesaver with `backend/data/lifesaver_phase2_verify.db`.

**NEW PAID STAGING DB REQUIRED: NO**

Reason: Lifesaver V1 tables are additive `lifesaver_*` only. Runtime `ensure_lifesaver_schema()` and the two prepared Alembic revisions can be validated on a disposable local SQLite file. A managed Postgres is valuable later, not required to prove staging readiness without production risk. Attaching to the existing Health ISF database would put Lifesaver tables next to production ride data and is rejected.

## Host options

| Option | Monthly | One-time | Isolation | Prod Health ISF risk | Setup | Rollback | Real browser | Alembic validation | New paid resources |
|---|---|---|---|---|---|---|---|---|---|
| **C. Local-only staging simulation** | **$0** | $0 | Highest (this workstation only) | None | Already done | Discard local DB / stop 8031 | Yes, on 127.0.0.1 | Yes, local disposable DB | No |
| D. Existing repo “staging” pattern (`amicor-health-isf-py.onrender.com`) | $0 extra | $0 | **Unsafe** — that host is the current Health ISF Render service | **High** | Easy and wrong | Hard; mixes products | Yes | Would run against the live service DB | No, but unsafe |
| B. New Render web + existing non-prod DB | $0–$7 | $0 | Only safe if the DB is proven unused by production | High unless the DB is empty and unused | Medium | Medium | Yes | Yes | Maybe a paid web if free slot is used up |
| A. Separate Render web + separate Postgres | $0 if both Free; about **$13** if always-on Starter + Basic-256mb | $0 | High if names/secrets stay distinct | Low if production service is never edited | Higher | Easy (delete staging service/DB) | Yes | Yes | Free tier possible; paid if always-on |

Render list prices used for planning (Hobby workspace, 2026 public pricing; confirm before any later purchase):

- Free web: $0, spins down after ~15 minutes, 750 free hours/month
- Starter web: $7/month
- Free Postgres: $0, **expires in 30 days**, 1 GB cap
- Basic-256mb Postgres: $6/month

Do **not** create option A or B unless Saye / Mrs. Nova later reject local-only.

## Why the existing Render service is not “free staging”

`render.yaml` already defines:

- web: `amicor-health-isf` (Free)
- db: `amicor-health-isf-db` (Free)

Repo docs such as `backend/docs/RENDER_STAGING_DEPLOY_PHASE53.md` talk about “staging” on `https://amicor-health-isf-py.onrender.com`. That is the **current Health ISF production-facing service**, not a dedicated Lifesaver sandbox. Using it would:

- run Lifesaver on the frozen Health ISF host
- apply Lifesaver Alembic against the Health ISF database
- risk `alembic upgrade heads` touching that database during a shared release command

That option is documented only so it can be **rejected**.

## Local-only configuration (recommended path)

Placeholders only. Generate real secrets locally; do not commit them.

```
AMICOR_ENVIRONMENT=lifesaver_local_staging
APP_ENV=local
LOG_LEVEL=INFO
TESTING=0
AMICOR_RESTRICT_SEED_ACCOUNTS=1
AMICOR_SKIP_WMI_PLATFORM_QUERY=1
DATABASE_URL=sqlite:///C:/path/to/backend/data/lifesaver_phase2_verify.db
DB_FILENAME=C:/path/to/backend/data/lifesaver_phase2_verify.db
JWT_SECRET=<staging-only-random>
SECRET_KEY=<staging-only-random-different>
ALLOWED_ORIGINS=http://127.0.0.1:8031
AMICOR_PUBLIC_URL=http://127.0.0.1:8031
LIFESAVER_SMOKE_BASE_URL=http://127.0.0.1:8031
LIFESAVER_SMOKE_DRY_RUN=1
LIFESAVER_SMOKE_ALLOW_PRODUCTION=0
```

Do not set `STRIPE_*`, Twilio, SES, SendGrid, device-vendor, or emergency-services keys.

Product modes stay code-enforced: local notification fake, simulated devices, simulated transport, Lifesaver-owned AI.

### App start (already in use)

```
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8031
```

### Migration validation (local disposable only — do not point at production)

Syntax/import check is already in `backend/tests/test_lifesaver_migration.py`.

Optional later local upgrade against a **copy** of the verify DB or a throwaway file:

```
cd backend
set DATABASE_URL=sqlite:///C:/path/to/backend/data/lifesaver_alembic_throwaway.db
alembic upgrade 20260911_lifesaver_phase1_schema
alembic upgrade 20260911_lifesaver_phase2_schema
alembic current
alembic downgrade 20260911_lifesaver_phase1_schema
alembic downgrade 20260909_nova_freight_settlement
```

Do not run those commands against the Health ISF production `DATABASE_URL`.

### Smoke

```
set LIFESAVER_SMOKE_BASE_URL=http://127.0.0.1:8031
set LIFESAVER_SMOKE_DRY_RUN=1
python scripts/lifesaver_staging_smoke.py
```

Authenticated smoke needs `LIFESAVER_SMOKE_EMAIL` / `LIFESAVER_SMOKE_PASSWORD` from the local secret store and explicit consents.

## Render plan — prepare only, do not execute

Use this **only** if local-only is later rejected and a public URL is required.

| Item | Planned value | Forbidden value |
|---|---|---|
| Service name | `amicor-lifesaver-staging` | `amicor-health-isf` |
| Branch | `feature/lifesaver-ai-care-cloud-v1` after explicit push approval | `main` auto-deploy to production |
| Root directory | `backend` | — |
| Build | `pip install --upgrade -r requirements.txt` | — |
| Start | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` | — |
| Health check | `/api/lifesaver/health` (Lifesaver) and/or `/api/health/live` | Do not require production readiness gates that need live Stripe |
| Database | Prefer SQLite on that new service for a short demo, or a **new** Free Postgres named `amicor-lifesaver-staging-db` | `amicor-health-isf-db` or production `DATABASE_URL` |
| Release command | `alembic upgrade 20260911_lifesaver_phase1_schema && alembic upgrade 20260911_lifesaver_phase2_schema` | `alembic upgrade heads` on the Health ISF production service |

Environment on that future service (names only):

- Required staging-only: `DATABASE_URL`, `JWT_SECRET`, `SECRET_KEY`, `ALLOWED_ORIGINS`, `AMICOR_PUBLIC_URL`, `APP_VERSION`, `LOG_LEVEL=INFO`, `AMICOR_RESTRICT_SEED_ACCOUNTS=1`, `AMICOR_ENVIRONMENT=staging`
- Must remain unset: live `STRIPE_*`, Twilio, SES/SendGrid, device keys, `LIFESAVER_SMOKE_ALLOW_PRODUCTION`

Test-user procedure: create a staging-only member; grant consents in the UI; never use production riders/drivers/Driver 001.

Smoke: point `LIFESAVER_SMOKE_BASE_URL` at the new hostname only after confirming it is not `onrender.com` production Health ISF, or keep dry-run until that check is written into the approval.

Rollback: suspend/delete `amicor-lifesaver-staging` only; never edit `amicor-health-isf`. DB downgrade order is in `LIFESAVER_V1_STAGING_ROLLBACK.md`.

## Observability (no paid product)

Use what already exists:

1. `GET /api/lifesaver/health` — product identity
2. `GET /api/health/live` — process liveness
3. `LOG_LEVEL=INFO` — request tracing already in the app; Lifesaver audit logs `action`, `resource_type`, `outcome` only
4. `GET /api/lifesaver/audit` — safe operator visibility (no journal body, no reading values, no password)
5. `python scripts/lifesaver_staging_smoke.py` — pass/fail transcript
6. `cd backend && alembic current` — migration status on the DB actually in use

Do not enable Sentry for Lifesaver staging unless a DSN already exists and is confirmed non-production. Do not log request bodies, journal text, or reading values.

## Idempotency

Duplicate transport requests and notification queue rows create extra **local simulated** records. They do not send email/SMS, create Health ISF rides, or charge cards. Unexpected status transitions already return HTTP 409.

**IDEMPOTENCY BLOCKS STAGING: NO**

Fix after local/public staging if operators find duplicate cards noisy. Not a Phase 3B blocker.

## Decision table

| Option | Monthly cost | Safe? | Recommended? | Why |
|---|---|---|---|---|
| C. Local-only 8031 | $0 | Yes | **Yes — do this** | Lowest cost, no production risk, easy rollback, real browser, Alembic can be validated locally |
| A. New Render web + new Postgres | $0–$13 | Yes if names/secrets stay new | No, unless a public URL is later required | Costs money or consumes the Free Postgres 30-day slot |
| B. New web + existing DB | $0–$7 | Only if that DB is unused | No | Existing DBs are Health ISF-linked |
| D. Current Health ISF Render host | $0 extra | **No** | **No** | Touches production-facing Health ISF |

**One recommended path:** keep using local 8031 + local SQLite. Do not create paid services. Do not touch Render.
