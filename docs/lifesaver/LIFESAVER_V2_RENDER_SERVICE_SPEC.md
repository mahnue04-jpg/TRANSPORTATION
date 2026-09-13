# Lifesaver V2 — Render service specification (prepare only)

Do not create this service, attach a database, or deploy until the owner explicitly approves spending and the first staging deploy.

Verified from this branch, not assumed from older notes:

| Setting | Value | Source |
|---|---|---|
| Service name | `amicor-lifesaver-staging` | Owner target; does not exist yet |
| Repository | `mahnue04-jpg/TRANSPORTATION` | Remote |
| Branch | `feature/lifesaver-ai-care-cloud-v2` | Remote branch |
| Root directory | `backend` | `render.yaml` Health ISF pattern and `app.main` location |
| Runtime | Python | `requirements.txt` + uvicorn |
| Build command | `pip install --upgrade -r requirements.txt` | `backend/requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` | Existing app entry; isolation is env-gated |
| Release / bootstrap | `python ../scripts/lifesaver_staging_bootstrap.py` | Creates `lifesaver_*` tables only. **Never** `alembic upgrade heads` |
| Health check | `/api/lifesaver/health` | `backend/app/modules/lifesaver/routes.py` |
| Auto-deploy | Off until first verified deploy | Avoid surprise public exposure |
| Instance size | Render Starter web (lowest paid that stays awake) or Free if sleep is acceptable | Owner cost choice |
| Disk | None if using dedicated Postgres; 1 GB at `/data` only if using staging SQLite | SQLite is the $0 option |
| Database attachment | **New** Render Postgres named `amicor-lifesaver-staging-db` | Never `amicor-health-isf-db` |
| Region | Same region as the owner later chooses for latency; isolation does not require sharing the Health ISF service | Owner choice |
| Expected URL pattern | `https://amicor-lifesaver-staging.onrender.com` | Render default; custom domain optional later |

## Isolation

Set `AMICOR_ENVIRONMENT=lifesaver_staging` and `AMICOR_LIFESAVER_STAGING_ISOLATED=1`. The shared `app.main:app` process then returns 404 for Nova, Health ISF, Delivery, payments, admin, and other non-Lifesaver HTML/API surfaces. Allowed: `/lifesaver`, `/api/lifesaver` (except local-only `/mock-pi`), `/api/auth`, Lifesaver static assets, and `/api/health/live`.

Do not add this service to the production `render.yaml` Health ISF block. Do not point `DATABASE_URL` at `amicor-health-isf-db`.

## Cost estimate (not a purchase)

Approximate incremental monthly cost if the owner later creates **new** resources:

- Starter web service: commonly about $7 / month
- Basic/Starter Postgres: commonly about $7 / month
- SQLite + 1 GB disk instead of Postgres: commonly about $0–$2 extra on a paid web instance; Free web sleeps
- No Stripe, Twilio, SES, device, or emergency vendors

Likely range: **$0 if Free + SQLite (sleeps)** or **about $14 / month for always-on Starter web + dedicated Postgres**. Confirm current Render pricing in the dashboard before approving.

## Home Hub

The Home Hub agent package stays on private LAN / loopback (`127.0.0.1:8041`). Do not publish it as the public web host. The in-process `/api/lifesaver/home-hub-agent` surface on staging requires a signed-in session except `GET .../health`.
