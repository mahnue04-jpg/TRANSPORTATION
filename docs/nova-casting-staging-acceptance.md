# Casting staging acceptance

Draft pull request #339. The live preview is head `26a57cd6`. Nothing here merges, deploys production, opens public intake, sends a message, resets a password, or copies a connection string.

Measured again on 2026-10-19 against `https://amicor-health-isf-pr-339.onrender.com`:

| Check | Result |
| --- | --- |
| `GET /api/health/live` | 200. `deploy_commit` `26a57cd648798ec1283cbabf7fa61788d80ecdad`. Branch `cursor/casting-auditions-pilot-e1ae`. Runtime environment `development`. |
| `GET /api/auth/deployment/seed-status` | 200. sqlite, `durable` false, `location` `workspace`, `signing_key` `ephemeral`, `restart_observed` false. `owner_retry_allowed` false. Blocked because accounts are stored in ephemeral sqlite. `AMICOR_SEED_PASSWORD` is unset. Ten of ten seed rows are present. |
| `GET /api/health/readiness` | 503. `overall_status` `not_ready`. `DATABASE_URL`, `SECRET_KEY`, and `JWT_SECRET` are missing, along with `ALLOWED_ORIGINS`, `AMICOR_PUBLIC_URL`, and `APP_VERSION`. The nested `database.connected: true` is the workspace SQLite file, not a Postgres service. |
| `GET /api/nova/casting/readiness` | 401. Authentication required. The handler still returns `enabled`, `applications_enabled`, and `media_uploads_enabled` false for a signed-in caller. |
| Production `https://amicor-health-isf-py.onrender.com/api/health/readiness` | 200. `overall_status` `ready` and the database is connected. The values were not read, and that database was not attached to the preview. |
| Render `GET /v1/postgres/dpg-dbap057btjjs7381egmg-a` | 401 Unauthorized. This run has no Render credential, so availability, plan, and region were not confirmed. |

## Owner-reported database

The owner approved one new empty Free Postgres for staging only and reported that Render created it. This run did not create it and did not connect to it.

| Field | Reported value |
| --- | --- |
| Name | `amicor-casting-staging-db` |
| ID | `dpg-dbap057btjjs7381egmg-a` |
| Plan | free |
| Region | virginia |
| Status when reported | creating |
| Expiry | 2026-11-18 UTC |
| Spend authorized | $0. No charge beyond free. |

The name is not `amicor-health-isf-db` or `amicor-nova-db`. Because the status was still `creating`, and this run could not read Render, the database was not treated as available. No connection string was read, copied, or stored.

## What was not done

No database was resumed, upgraded, restored, or copied. No connection string was written to Slack, GitHub, or this workspace. Production secrets, passwords, and rows were not read. `AMICOR_SEED_PASSWORD` was not set. Schema initialization and the synthetic sign-up, restart, and tenant-isolation proof did not run. `owner_retry_allowed` stays false. Public intake, uploads, and outbound delivery stay off. Nothing was merged and production was not deployed.

## Cost and safety

Checked against Render's pricing, free-plan, and disk pages on 2026-10-19.

| Choice | Monthly cost | Durable | Safe to do now |
| --- | --- | --- | --- |
| Leave the preview on ephemeral SQLite | $0 | No | Yes. This is the current state. The retry gate stays closed. |
| Look at the suspended database in the dashboard | $0 | No | Yes, if Resume, Upgrade, Restore, and Delete are not clicked and no connection string is copied. |
| Resume or upgrade that suspended database | $6 if it is an expired Free database that must be upgraded to be read. A suspended paid database starts billing again on resume. | Only after a paid action | No. Spending is not approved. Its rows are not copied. |
| New empty Free Postgres, only when the dashboard shows no active Free Postgres | $0 for 30 days, then inaccessible. Render deletes it 14 days after expiry unless a later paid upgrade is approved. | Until day 30 | Owner reported `amicor-casting-staging-db` as created and still creating. This run did not verify the free slot or connect. Do not create a second one. |
| New Postgres plan `0.1c-256mb` | $6, 1 GB included | Yes | No. |
| Persistent disk | $7 web plan `0.5c-512mb` plus $0.25 per GB. Free web services cannot attach a disk. | Yes | No. The production disk is not reused. |

Attaching a Postgres URL and a new `JWT_SECRET` does not open the retry gate. The gate still requires a durable directory or Render disk, a stable signing key, and a restart marker. Postgres is recorded as durable, and `owner_retry_allowed` stays false. A local test uses `127.0.0.1:1` and does not open a connection.

## Stages

The order is fixed in `ACCEPTANCE_STAGES` inside `backend/app/core/casting_staging_choice.py`. Only stage 0 runs without a new owner choice.

0. Ephemeral preview. Done above. No owner password retry.
1. Dashboard identification only. Record whether any Free Postgres is Available, plus the name, status, and plan of any suspended or expired database. Stop if the name is `amicor-health-isf-db` or `amicor-nova-db`.
2. Empty Free Postgres, only after stage 1 shows the free slot is empty. New name. No restore and no account copy. The owner reported this database. This run did not verify it.
3. On preview service `amicor-health-isf-pr-339` only, set `DATABASE_URL` from that new database and generate a new `JWT_SECRET`. This agent cannot do that without a Render credential. The owner-only dashboard step is below. Leave production unchanged. Do not set `AMICOR_SEED_PASSWORD`. The retry gate stays closed.
4. A later run signs up a synthetic account, restarts the preview, and signs in with that synthetic password. The owner password is not used. The gate stays closed until a separate change is reviewed after that proof.

## Owner decision

Choice C is approved: one new empty Free Postgres for the preview only. Spending beyond free is still unapproved. The owner does not retry the existing password. `owner_retry_allowed` stays false until a later reviewed change, and only after a synthetic account survives a preview restart.

## Wiring blocker

This agent cannot set the preview secrets. The only injected secret name is `FAL_KEY`. The Render CLI is not installed, GitHub Actions secrets are not readable by this integration, and the Render API returned 401. A dashboard paste of the connection string into Slack or GitHub is not an acceptable substitute.

Owner-only step, in the Render dashboard, after the database status is Available:

1. Open database `amicor-casting-staging-db` (`dpg-dbap057btjjs7381egmg-a`). Continue only if the status is Available, the plan is Free, and the region is Virginia. If it is still creating, or the plan is not Free, stop. Do not resume, upgrade, restore, or delete anything. Do not open or copy a connection string.
2. Open only the preview web service `amicor-health-isf-pr-339`. Do not open production `amicor-health-isf` or `amicor-health-isf-py`. Do not change `render.yaml`; its `fromDatabase` entry points the production blueprint at `amicor-health-isf-db`.
3. On that preview service, add `DATABASE_URL` with **Add from database**. Choose `amicor-casting-staging-db` and the internal connection string. That stores a secret reference on the preview service. Do not paste the value anywhere else.
4. On that same preview service, use Render's Generate control for a new `JWT_SECRET`, then set `SECRET_KEY` to that same generated value inside the service environment editor. Do not copy either value from production, Slack, or Git. Do not set `AMICOR_SEED_PASSWORD`. Do not set `NOVA_CASTING_STAGING_READS`.
5. Save so only the preview redeploys. Reply that the database is Available and the preview variables are saved. Do not include values.

After that reply, a later run can initialize the schema and prove a synthetic sign-up still logs in after a preview restart, including tenant isolation. The current gate still returns `owner_retry_allowed` false for Postgres until a separate change is reviewed after that proof.
