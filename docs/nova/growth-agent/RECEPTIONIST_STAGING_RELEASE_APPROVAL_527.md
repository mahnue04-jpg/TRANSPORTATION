# Staging-only release approval — Nova AI Receptionist (#527)

**Status:** Package corrected for owner approval. **Not provisioned. Not deployed. Not a live-accepted pilot.**

## Commit identity (do not conflate)

| Role | SHA | Notes |
|------|-----|-------|
| Reviewed prior head | `d588fc5d5bb28a8c9f9d3e509722b6d796622da5` | Green CI; voice mapping flake fixed |
| Base feature candidate preserved | `03befdea4685209dfdd63649372d688640d43f62` | Prior green Growth Agent CI |
| **Implementation tip** | `e5689d250f3189e790d684a10630a1f43d06ca1e` | Blueprint/start/readiness/empty-DB code + evidence |
| **Approval package / deploy tip** | `0dddb001ec30762c650a86af2e853c54a8adee3a` | Pilot + staging-release branches; require CI green on this tip before deploy |
| Staging-release branch | `cursor/nova-receptionist-staging-release-c9ac` | Must point at the approved tip; `autoDeployTrigger: off` |
| Prior green CI must not validate a newer tip | — | Re-run workflows on the deployment candidate before deploy |

## Owner approval statement (copy/paste)

> Approve isolated Render staging for Nova AI Receptionist using blueprint `docs/nova/growth-agent/render.nova-receptionist-staging.yaml` with `autoDeployTrigger: off`, free web plan, and startCommand `python scripts/receptionist_staging_start.py`. Do not modify `nova-growth-validation-490` / `nova_ga_490_dispos`. Because the workspace already uses its one free Postgres on that existing staging DB, there is **no $0 isolated database option** unless that free slot is freed first. If keeping 490’s free DB, separately approve paid Postgres **~$6/mo** (`0.1c-256mb`) before creating `nova-receptionist-staging-db`. Keep live calendar writes, live email, and live Twilio disabled. Deploy **only** the approved tip SHA (set `NOVA_GA_EXPECTED_GIT_COMMIT` to that SHA). Do not start Google consent until the service is live and the callback URL is verified.

## Recommended target (isolated — leave existing staging unchanged)

| Item | Value |
|------|-------|
| Web service (proposed) | `nova-receptionist-staging` |
| Plan | `free` web (`autoDeployTrigger: off`) |
| Expected origin | `https://nova-receptionist-staging.onrender.com` |
| Owner UI | `https://nova-receptionist-staging.onrender.com/nova/growth` |
| Health | `GET /api/health/readiness` → **200** (`traffic_ready: true`) |
| Database (proposed) | `nova-receptionist-staging-db` / DB name `nova_ga_receptionist_dispos` |
| Blueprint | `docs/nova/growth-agent/render.nova-receptionist-staging.yaml` |
| Build | `pip install --upgrade -r requirements.txt` (rootDir `backend`) |
| Start / migrate | `python scripts/receptionist_staging_start.py` (advisory-locked Alembic → `20261116_nova_ga_receptionist`, then uvicorn) |

### Existing staging (do not change)

| Item | Value |
|------|-------|
| Service | `nova-growth-validation-490` |
| Service ID | `srv-dbqv8ip5efls73dtpmo0` |
| Live commit (owner-reported) | `0ad5c5e178f260067e2a95447a01745ed2e09a8b` |
| Database | `nova_ga_490_dispos` (consumes the workspace **free** Postgres slot) |
| URL | `https://nova-growth-validation-490.onrender.com` |

**Why not reuse 490:** tip lacks website-inquiry / staging_preflight from the `0ad5c5e` lineage; 490 lacks receptionist tables/OAuth/voice. Replacing 490 would risk website-inquiry and safety gates.

## Cost / resource decision (read-only)

Render policy (docs, Nov 2026): **one active free Postgres per workspace**; free Postgres expires after 30 days; paid Basic-256mb Postgres **$6/mo**.

| Scenario | Incremental cost | Action |
|----------|------------------|--------|
| Free web hours available + free Postgres slot freed by owner | **$0** | Allowed only if owner explicitly frees/reassigns the free slot without harming 490 |
| Keep `nova_ga_490_dispos` on free + create isolated DB | **~$6/mo** Postgres | **STOP** until owner approves paid DB |
| Free web hours exhausted | **~$7/mo** web | **STOP** until owner approves paid web |

**Current package decision:** No zero-cost isolated database is available while `nova_ga_490_dispos` holds the free slot. This agent did **not** remove, reuse, or create any Render database. Owner must choose: (A) free the free slot, or (B) approve ~$6/mo paid Postgres.

## Exact deploy procedure (after approval)

1. Confirm tip SHA on `cursor/nova-receptionist-staging-release-c9ac` equals the approved deployment candidate.
2. Confirm CI green **on that tip** (do not reuse older green runs).
3. Apply blueprint in Render Dashboard (or create resources manually to match it). Do not enable auto-deploy.
4. Set secrets (names only below). Set `NOVA_GA_EXPECTED_GIT_COMMIT` to the approved full SHA.
5. Manual Deploy → that exact commit.
6. Startup script validates DB name `nova_ga_receptionist_dispos`, rejects SQLite/490/production hosts, acquires PG advisory lock, runs `alembic upgrade 20261116_nova_ga_receptionist`, verifies revision, execs uvicorn. Failure exits non-zero (deploy fails closed).
7. Accept only when `GET /api/health/readiness` returns **200** with `traffic_ready: true`. Missing Google/Twilio config must not 503 traffic readiness.

### Why startCommand migrate (not preDeploy / releaseCommand)

- `releaseCommand` is **not** in Render’s Blueprint JSON Schema (validation rejects it).
- `preDeployCommand` is paid-service only.
- Official free-plan pattern: idempotent migrate inside `startCommand` (see Render blueprint docs / free-plan guidance).
- Locking: `pg_try_advisory_lock` up to 120s; free web is single-instance but sleep/wake can overlap briefly.
- Duration: full empty-DB chain ~3s locally; expect longer on Render cold start. Failure does not fall back to SQLite or ORM `create_all`.

Blueprint validation evidence: `docs/nova/growth-agent/screenshots/receptionist_staging_blueprint_validation.json` (Draft 2020-12 schema; `valid: true`; negative control rejects `releaseCommand`).

## Readiness 503 root cause and fix

Prior evidence recorded `readiness_http: 503` while the journey still marked `passed: true`.

**Cause:** `/api/health/readiness` returned 200 only when `overall_status == "ready"` (full production-promotion gate). Staging runs without `APP_VERSION` (and with optional Google/Twilio unset) produced `not_ready` / 503 even when DB + auth secrets were healthy. The journey did not require HTTP 200.

**Fix:**
- Staging/test probes return 200 when infrastructure traffic gates pass (required auth secrets + reachable non-SQLite DB). Optional Google/Twilio do not block.
- Blueprint sets `APP_VERSION`.
- Owner journey now **fails** unless readiness HTTP is 200 and `traffic_ready` is true.

## Database evidence

### Empty first deploy (required)

Script: `backend/scripts/receptionist_staging_empty_db_rehearsal.py`  
Evidence: `docs/nova/growth-agent/screenshots/receptionist_staging_empty_db_rehearsal.json`

- Started from genuinely empty DB (`tables_before_migrate: []`)
- Exact procedure: `python scripts/receptionist_staging_start.py --migrate-only`
- No `stamp_parent`, no ORM `create_all`
- Parent marker tables + eight receptionist tables + constraints + revision `20261116_nova_ga_receptionist`
- App boot + `/api/health/readiness` → **200** (`traffic_ready: true`) with Google/Twilio secrets omitted

### Backup / restore preservation (retained)

Script: `backend/scripts/receptionist_staging_db_rehearsal.py`  
Evidence: `docs/nova/growth-agent/screenshots/receptionist_staging_db_rehearsal.json`

- Seed at parent → dump → restore → upgrade receptionist revision
- Pre-existing synthetic rows intact; receptionist tables additive

**Application rollback:** redeploy previous application SHA; leave additive receptionist tables. Do **not** default to `DROP TABLE`.

## Health & browser evidence

Evidence: `docs/nova/growth-agent/screenshots/receptionist_staging_owner_journey.json`  
Screenshot: `docs/nova/growth-agent/screenshots/receptionist_staging_readiness.png`

- `readiness_http: 200`, `traffic_ready: true`
- Login → synthetic demo → receptionist readiness shows Not connected (not a crash)
- Book / reschedule / cancel / rebook / notify tick / handoffs labeled SIMULATED
- Live transports remain hard-off

## OAuth / secrets (names only — never paste values)

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | App secret |
| `JWT_SECRET` | JWT signing |
| `AMICOR_SEED_PASSWORD` | Seeded owner login |
| `AMICOR_DEPLOYMENT_SYNC_KEY` | Deploy sync |
| `NOVA_GROWTH_AGENT_WIDGET_SECRET` | Widget HMAC |
| `NOVA_GA_GOOGLE_OAUTH_CLIENT_ID` | Google OAuth client |
| `NOVA_GA_GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth secret |
| `NOVA_GA_CREDENTIAL_ENCRYPTION_KEY` | Fernet key for tokens at rest |
| `NOVA_GA_EXPECTED_GIT_COMMIT` | Exact approved tip SHA (deploy guard) |
| `NOVA_GA_GOOGLE_OAUTH_HTTP_ENABLED` | Staging opt-in for token HTTP **without** calendar writes |

**Proposed redirect URI:**  
`https://nova-receptionist-staging.onrender.com/api/nova/growth-agent/calendar/oauth/callback`

## Remaining blockers (owner)

1. Choose database cost path: free the free Postgres slot **or** approve ~$6/mo paid Postgres.  
2. Set staging secrets in Render (names above) — no paste into chat.  
3. Deploy approved tip with `NOVA_GA_EXPECTED_GIT_COMMIT` set; verify readiness 200.  
4. Only then enable `NOVA_GA_GOOGLE_OAUTH_HTTP_ENABLED` and run real-account checklist.  
5. Live writes/email/Twilio remain a **separate** approval.

## Boundaries

No merge, deploy, provision, existing-DB migration, real OAuth consent, calendar writes, messages, calls, or spend performed by this preparation pass.
