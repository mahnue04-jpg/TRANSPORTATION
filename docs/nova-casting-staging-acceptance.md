# Casting staging acceptance

Draft pull request #339. Nothing here merges, deploys production, opens public intake, sends a message, resets a password, or copies a connection string.

## Measured 2026-10-20 after the preview deploy

The owner deployed the preview around 13:17 CDT. This run measured `https://amicor-health-isf-pr-339.onrender.com` at `2026-10-20T18:32:12Z` and again at `2026-10-20T18:52:58Z` after the service had been idle. The second live request took 104 seconds, which is a new process. The deployed SHA stayed `500bb1f06c37adcef8b43666e4f71979bf7f80e2`.

| Check | Result |
| --- | --- |
| `GET /api/health/live` | 200. Branch `cursor/casting-auditions-pilot-e1ae`. The payload says environment `production` because an https service URL plus a non-SQLite database is inferred as production when `AMICOR_ENVIRONMENT` is unset. This was not a production deploy. |
| `GET /api/auth/deployment/seed-status` | 200. postgres, `durable` true, `location` postgres, `signing_key` env, `restart_observed` false. `owner_retry_allowed` false. Blocked because restart survival has not been observed on this store. `AMICOR_SEED_PASSWORD` is unset. |
| `GET /api/health/readiness` | 503. `overall_status` `not_ready`. `DATABASE_URL`, `SECRET_KEY`, and `JWT_SECRET` are present and the database is connected. The 503 is the promotion checklist: `ALLOWED_ORIGINS`, `AMICOR_PUBLIC_URL`, and `APP_VERSION` are unset. The route returns 503 for every status other than `ready`. |
| Synthetic account | Two new preview accounts signed up through the free path, with no checkout URL and no card. Each login returned 200. Logout returned 200 and revoked the refresh token with 401. The same account logged in again with the same user id and organization id. A second account received a different user id and organization id. Repeating the first email returned 409. A wrong password returned 401. |
| Saved token after the idle restart | The access token from before the idle period still returned 200 for `/api/auth/me`, with the same user id and organization id. Password login also returned the same ids. |
| Authenticated casting readiness | 200. `enabled`, `applications_enabled`, `media_uploads_enabled`, `staging_reads_enabled`, and `sandbox_writes_enabled` are false. Creating a sandbox organization returned 503. |
| Owner login | Still closed on this deploy. The idle wake was not a restart proof. The gate now opens for Postgres only after a later process finds a different instance id in `amicor_auth_restart_marker`. The first writer stays closed. That preview restart is not in this row yet. |

The synthetic password was not the owner password. It was not written to Slack, GitHub, or this file. Public intake, media uploads, email, SMS, and WhatsApp were not enabled. Production was not changed.

Measured on 2026-10-19 against `https://amicor-health-isf-pr-339.onrender.com` after the service woke. An earlier reading the same day was `26a57cd6`. This reading is the preview before the auth-control commit.

| Check | Result |
| --- | --- |
| `GET /api/health/live` | 200. `deploy_commit` `d0d4164e930f4b1774eff5085e3773d5e87dbd60`. Branch `cursor/casting-auditions-pilot-e1ae`. Runtime environment `development`. |
| `GET /api/auth/deployment/seed-status` | 200. sqlite, `durable` false, `location` `workspace`, `signing_key` `ephemeral`, `restart_observed` false. `owner_retry_allowed` false. Blocked because accounts are stored in ephemeral sqlite. `AMICOR_SEED_PASSWORD` is unset. Ten of ten seed rows are present. |
| `GET /api/health/readiness` | 503. `overall_status` `not_ready`. `DATABASE_URL`, `SECRET_KEY`, and `JWT_SECRET` are missing, along with `ALLOWED_ORIGINS`, `AMICOR_PUBLIC_URL`, and `APP_VERSION`. The nested `database.connected: true` is the workspace SQLite file, not a Postgres service. |
| `GET /api/nova/casting/readiness` | 401. Authentication required. The handler still returns `enabled`, `applications_enabled`, and `media_uploads_enabled` false for a signed-in caller. |
| Production `https://amicor-health-isf-py.onrender.com/api/health/readiness` | 200. `overall_status` `ready` and the database is connected. The values were not read, and that database was not attached to the preview. |
| Render `GET /v1/postgres/dpg-dbap057btjjs7381egmg-a` | 401 Unauthorized. This run has no Render credential. The injected secret is `FAL_KEY` only, and the Render CLI is not installed. Availability was not read from the API. |

## Owner-verified database

The owner approved one new empty Free Postgres for staging only. An owner-connected Render inspection on 2026-10-19 reports that the earlier `creating` state is cleared. This run did not create the database, did not read it through the API, and did not connect to it.

| Field | Owner-verified value |
| --- | --- |
| Name | `amicor-casting-staging-db` |
| ID | `dpg-dbap057btjjs7381egmg-a` |
| Plan | free |
| Region | virginia |
| Status | available |
| Expiry | 2026-11-18 UTC |
| Preview service | `srv-db7r3ke7bikc73ddosmg` (`amicor-health-isf-pr-339`) |
| Spend authorized | $0. No charge beyond free. |

The name is not `amicor-health-isf-db` or `amicor-nova-db`. No connection string was read, copied, or stored. The 2026-10-19 preview in the table above was ephemeral sqlite. The 2026-10-20 preview is Postgres.

## What was not done

No database was resumed, upgraded, restored, or copied. No connection string was written to Slack, GitHub, or this workspace. Production secrets, passwords, and rows were not read. `AMICOR_SEED_PASSWORD` was not set. Schema initialization and the synthetic sign-up, restart, and tenant-isolation proof did not run. `owner_retry_allowed` stays false. Public intake, uploads, and outbound delivery stay off. Nothing was merged and production was not deployed.

## Cost and safety

Checked against Render's pricing, free-plan, and disk pages on 2026-10-19.

| Choice | Monthly cost | Durable | Safe to do now |
| --- | --- | --- | --- |
| Leave the preview on ephemeral SQLite | $0 | No | Yes. This is the current state. The retry gate stays closed. |
| Look at the suspended database in the dashboard | $0 | No | Yes, if Resume, Upgrade, Restore, and Delete are not clicked and no connection string is copied. |
| Resume or upgrade that suspended database | $6 if it is an expired Free database that must be upgraded to be read. A suspended paid database starts billing again on resume. | Only after a paid action | No. Spending is not approved. Its rows are not copied. |
| New empty Free Postgres, only when the dashboard shows no active Free Postgres | $0 for 30 days, then inaccessible. Render deletes it 14 days after expiry unless a later paid upgrade is approved. | Until 2026-11-18 UTC | Owner verified `amicor-casting-staging-db` as Available, Free, and Virginia. Do not create a second one. Do not upgrade it. This run did not connect. |
| New Postgres plan `0.1c-256mb` | $6, 1 GB included | Yes | No. |
| Persistent disk | $7 web plan `0.5c-512mb` plus $0.25 per GB. Free web services cannot attach a disk. | Yes | No. The production disk is not reused. |

Attaching a Postgres URL and a new `JWT_SECRET` does not by itself open the retry gate. Postgres is durable, and the gate stays closed until a later process reads a different instance id from `amicor_auth_restart_marker`. The same id, including an idle wake, stays closed. A directory or Render disk marker still counts. A local test uses `127.0.0.1:1` and does not open a connection.

## Stages

The order is fixed in `ACCEPTANCE_STAGES` inside `backend/app/core/casting_staging_choice.py`. Only stage 0 runs without a new owner choice.

0. Ephemeral preview. Done above. No owner password retry.
1. Dashboard identification only. Record whether any Free Postgres is Available, plus the name, status, and plan of any suspended or expired database. Stop if the name is `amicor-health-isf-db` or `amicor-nova-db`.
2. Empty Free Postgres, only after stage 1 shows the free slot is empty. New name. No restore and no account copy. The owner verified `amicor-casting-staging-db` as Available. This run did not read that status from the API.
3. On preview service `srv-db7r3ke7bikc73ddosmg` only, save a secret reference to that database and generate new signing keys. This agent cannot store a Render secret reference. The owner-only dashboard step is below. Leave production unchanged. Do not deploy in this step. Do not set `AMICOR_SEED_PASSWORD`. The retry gate stays closed.
4. A later run signs up a synthetic account, restarts the preview, and signs in with that synthetic password. The owner password is not used. The gate stays closed until a separate change is reviewed after that proof.

## Owner decision

Choice C is approved: one new empty Free Postgres for the preview only. Spending beyond free is still unapproved. The owner does not retry the existing password. `owner_retry_allowed` stays false until a later reviewed change, and only after a synthetic account survives a preview restart.

## Wiring blocker

This agent cannot set the preview secrets. Render secret references are a dashboard or blueprint feature. This workspace has no Render credential, the Render CLI is not installed, and `GET /v1/postgres/dpg-dbap057btjjs7381egmg-a` returned 401. The only injected secret name is `FAL_KEY`. A pasted connection string in Slack or GitHub is not a substitute, and none was created.

`render.yaml` stays unchanged. Its `fromDatabase` entry points the production blueprint at `amicor-health-isf-db`. Blueprint `generateValue` is not used, because a blueprint sync is not limited to this preview.

## Owner-only dashboard step

Do this in the Render dashboard. The creating stop is cleared by the owner inspection above. This step stores variables. It does not deploy, migrate, or open the retry gate.

1. Search for database ID `dpg-dbap057btjjs7381egmg-a`. Continue only when the page shows name `amicor-casting-staging-db`, status Available, plan Free, region Virginia, and expiry 2026-11-18 UTC. If any field differs, stop. Do not click Connect, Resume, Upgrade, Restore, Delete, or a plan control. Do not copy an internal or external URL.
2. Search for service ID `srv-db7r3ke7bikc73ddosmg`. Continue only when the name is `amicor-health-isf-pr-339` and its region is Virginia. If the name is `amicor-health-isf`, `amicor-health-isf-py`, or anything else, stop. If the region is not Virginia, stop. Do not move the database or the service.
3. On that service, open Environment. Use **Add from database**. Select only `amicor-casting-staging-db`. Choose the internal connection string and store it as `DATABASE_URL`. Do not select `amicor-health-isf-db`, `amicor-nova-db`, or an external URL. Do not paste a value. If Add from database is not on the page, stop.
4. On that same Environment page, add `JWT_SECRET` and use Generate. Add `SECRET_KEY` and use Generate again, so the two values are independent. Do not reveal either value, do not copy one into the other, and do not copy production, Slack, or Git. If Generate is not on the row, stop. Do not set `AMICOR_SEED_PASSWORD`, `NOVA_CASTING_STAGING_READS`, `ALLOWED_ORIGINS`, `AMICOR_PUBLIC_URL`, or `APP_VERSION`.
5. Choose **Save only**. Do not choose Save and deploy, and do not choose Save, rebuild, and deploy. The blueprint release command runs `alembic upgrade heads`, and this preview's environment is `development`, so a deploy could initialize schema before the restart proof. Reply that the preview variables are saved. Do not include values.

Signing uses `JWT_SECRET` when both names are set. Readiness still requires both names. A difference between them logs a warning and does not open `owner_retry_allowed`.

After that reply, a later run can deploy the preview, initialize schema on this empty database, and prove a synthetic sign-up still logs in after a preview restart, including tenant isolation. Postgres stays durable in the gate, and `owner_retry_allowed` stays false until a separate change is reviewed after that proof.

## Local verification, not a live proof

Checked in this workspace on 2026-10-19: 18 passed and 1 skipped. The skip is the disposable Postgres migration, because `CASTING_TEST_POSTGRES_URL` was unset. Nothing used the staging database or a connection string.

- `tests/test_nova_casting_auth_restart.py` covers a durable directory login that survives a process restart, and the free-tier path where the account and saved token die on restart while `owner_retry_allowed` stays false.
- `tests/test_nova_casting_staging_choice.py` covers a Postgres URL with an environment signing key. The store is durable, `restart_observed` stays false, and `owner_retry_allowed` stays false. The same file refuses every other database, the production services, a paid plan, a deploy, and any supplied connection string.
- `tests/test_nova_casting_journey.py` covers tenant isolation: another tenant cannot redeem an invite, read the audit, or read the snapshot. The disposable Postgres migration test stays skipped unless `CASTING_TEST_POSTGRES_URL` points at a local database. It was not pointed at Render.
