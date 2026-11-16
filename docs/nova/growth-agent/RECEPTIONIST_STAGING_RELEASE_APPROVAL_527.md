# Staging-only release approval — Nova AI Receptionist (#527)

**Status:** Prepared only. **Not provisioned. Not deployed.**  
**Package tip (this branch):** see git HEAD / PR update.  
**Base candidate preserved:** `03befdea4685209dfdd63649372d688640d43f62`

## Owner approval statement (copy/paste)

> Approve creating isolated Render staging for Nova AI Receptionist using blueprint `docs/nova/growth-agent/render.nova-receptionist-staging.yaml` on free plan only. Do not modify `nova-growth-validation-490` / `nova_ga_490_dispos`. If free Postgres is unavailable because the workspace already has a free DB, stop and report paid Postgres cost (~$6/mo) before creating any paid resource. Keep live calendar writes, live email, and live Twilio disabled. Deploy only after CI is green on the approved tip. Do not start Google consent until the service is live and the callback URL is verified.

## Recommended target (isolated — leave existing staging unchanged)

| Item | Value |
|------|-------|
| Web service (proposed) | `nova-receptionist-staging` |
| Expected origin | `https://nova-receptionist-staging.onrender.com` |
| Owner UI | `https://nova-receptionist-staging.onrender.com/nova/growth` |
| Health | `GET /api/health/readiness` |
| Database (proposed) | `nova-receptionist-staging-db` / DB name `nova_ga_receptionist_dispos` |
| Blueprint | `docs/nova/growth-agent/render.nova-receptionist-staging.yaml` |
| Build | `pip install --upgrade -r requirements.txt` (rootDir `backend`) |
| Release | `alembic upgrade 20261116_nova_ga_receptionist` |
| Start | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

### Existing staging (do not change)

| Item | Value |
|------|-------|
| Service | `nova-growth-validation-490` |
| Service ID | `srv-dbqv8ip5efls73dtpmo0` |
| Live commit (owner-reported) | `0ad5c5e178f260067e2a95447a01745ed2e09a8b` |
| Older documented pin | `1395f7e47f0f2e4a94473621374f9219e180ac6b` (do not assume current) |
| Database | `nova_ga_490_dispos` |
| URL | `https://nova-growth-validation-490.onrender.com` |

**Why not reuse 490:** tip lacks website-inquiry / staging_preflight from the `0ad5c5e` lineage; 490 lacks receptionist tables/OAuth/voice. Replacing 490 would risk website-inquiry and safety gates. Isolated service keeps both validation tracks.

## Cost / resource limits

| Scenario | Est. cost |
|----------|-----------|
| Free web + free Postgres slots available | **$0** incremental |
| Free Postgres slot already used by `nova_ga_490_dispos` (Render: **one free Postgres per workspace**) | Stop — paid Basic Postgres **~$6/mo** needs separate approval |
| Free web hours exhausted (750 hrs/workspace/mo) | Stop — paid web **~$7/mo** needs separate approval |
| Live Google writes / email / Twilio | **$0** in this release — hard-off; OAuth HTTP flag separate |

## Candidate & CI

| Item | Value |
|------|-------|
| Base candidate | `03befdea4685209dfdd63649372d688640d43f62` |
| Staging-prep branch | `cursor/nova-receptionist-staging-release-c9ac` |
| Parent migration | `20261112_nova_ga_retention` |
| Target migration | `20261116_nova_ga_receptionist` (8 tables) |
| Prior green CI on base | [Growth Agent run 43873277046](https://github.com/mahnue04-jpg/TRANSPORTATION/actions/runs/43873277046): backend 131 passed / 1 skipped / 24 subtests; Postgres 13; UI 13 |
| Diagnostic | [43873277138](https://github.com/mahnue04-jpg/TRANSPORTATION/actions/runs/43873277138) success (not a Render deploy) |
| Casting | [43873277073](https://github.com/mahnue04-jpg/TRANSPORTATION/actions/runs/43873277073) success |

## Database safety rehearsal (disposable only)

Script: `backend/scripts/receptionist_staging_db_rehearsal.py`  
Evidence: `docs/nova/growth-agent/screenshots/receptionist_staging_db_rehearsal.json`

Verified on local disposable DBs `nova_ga_receptionist_src` → dump/restore → `nova_ga_receptionist_restore`:

- Seeded synthetic profile/contact/appointment at parent revision
- Backup + restore into second disposable DB
- Alembic upgrade to `20261116_nova_ga_receptionist` (**no ORM create_all for receptionist tables**)
- All eight tables present; pre-existing rows intact
- Exercised connection, sync job, notification, handoff, voice mapping rows

**Application rollback:** redeploy previous application SHA; leave additive receptionist tables in place. Do **not** default to `DROP TABLE`. Alembic downgrade only with separate owner approval.

## OAuth configuration (names only — never paste values)

| Variable | Purpose |
|----------|---------|
| `NOVA_GA_GOOGLE_OAUTH_CLIENT_ID` | Google OAuth client |
| `NOVA_GA_GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth secret |
| `NOVA_GA_GOOGLE_OAUTH_REDIRECT_URI` | Exact callback |
| `NOVA_GA_CREDENTIAL_ENCRYPTION_KEY` | Fernet key for tokens at rest |
| `NOVA_GA_GOOGLE_OAUTH_HTTP_ENABLED` | Staging opt-in for token exchange/refresh **without** calendar writes |
| `AMICOR_PUBLIC_URL` | Public HTTPS origin |

**Proposed redirect URI (exact):**  
`https://nova-receptionist-staging.onrender.com/api/nova/growth-agent/calendar/oauth/callback`

**Secure setup (owner):** create a dedicated Google Cloud OAuth client for this staging origin; generate a new Fernet key for staging only; set secrets in the Render dashboard sync fields. Do **not** paste values into issues/chat. Do **not** start Google consent until the candidate is deployed and the callback route returns the expected 302/HTML.

**OAuth while writes stay off:** Yes after this package’s gate fix. Token HTTP is gated by `NOVA_GA_GOOGLE_OAUTH_HTTP_ENABLED` (default false), independent of hard-off `REAL_CALENDAR_WRITE` / `REAL_EMAIL_SEND` / `REAL_VOICE`. Calendar API writes remain disabled.

## Default-off integrations on this staging target

- `REAL_CALENDAR_WRITE` / `REAL_EMAIL_SEND` / `REAL_VOICE` / Stripe live: hard-coded False
- `NOVA_GA_GOOGLE_OAUTH_HTTP_ENABLED=false` until owner enables after deploy+callback verify
- Retention delete off; voice simulator may be on (labeled SIMULATED)

## Health & browser acceptance checks (post-deploy)

1. `GET /api/health/readiness` → 200  
2. Owner login → `/nova/growth` receptionist readiness shows Not configured / Not connected (not a crash)  
3. Simulated provider paths labeled SIMULATED  
4. After OAuth HTTP enabled + consent: connected + select calendar  
5. Availability → book → reschedule → cancel/rebook (internal; sync may suppress while writes off)  
6. Notification tick → `provider_accepted` ≠ inbox receipt  
7. Handoff list; voice simulator only  

Local Chromium evidence (GitHub-accessible): `docs/nova/growth-agent/screenshots/`

## Remaining blockers (owner)

1. Approve isolated provision (and paid Postgres if free slot exhausted).  
2. Set staging secrets (names above) in Render — no paste into chat.  
3. Deploy approved tip; verify readiness + OAuth callback.  
4. Only then enable `NOVA_GA_GOOGLE_OAUTH_HTTP_ENABLED` and run real-account checklist.  
5. Live writes/email/Twilio remain a **separate** approval.

## Boundaries

No merge, deploy, provision, existing-DB migration, real OAuth consent, calendar writes, messages, calls, or spend performed by this preparation pass.
