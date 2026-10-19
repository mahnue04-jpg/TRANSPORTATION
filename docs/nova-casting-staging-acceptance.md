# Casting staging acceptance

Draft pull request #339. Head `235c4ef3` is the live preview. Nothing here merges, deploys production, opens public intake, sends a message, resets a password, or provisions a resource.

Measured on 2026-10-19 against `https://amicor-health-isf-pr-339.onrender.com` after the free service woke:

| Check | Result |
| --- | --- |
| `GET /api/health/live` | 200. `deploy_commit` `235c4ef326b8c3451df5ea7ce386debcd08feb27`. Branch `cursor/casting-auditions-pilot-e1ae`. |
| `GET /api/auth/deployment/seed-status` | 200. sqlite, `durable` false, `location` `workspace`, `signing_key` `ephemeral`, `restart_observed` false. `owner_retry_allowed` false. Blocked because accounts are stored in ephemeral sqlite. `AMICOR_SEED_PASSWORD` is unset. |
| `GET /api/health/readiness` | 503. `DATABASE_URL`, `SECRET_KEY`, and `JWT_SECRET` are missing. The nested `database.connected: true` is the workspace SQLite file, not a Postgres service. |
| Production `https://amicor-health-isf-py.onrender.com/api/health/readiness` | 200. The database is connected. The values were not read, and that database was not attached to the preview. |

## What was not done

This environment has no Render API key, so the live database list was not read. No database was created, resumed, upgraded, or restored. No connection string was copied. `amicor-health-isf-db` and `amicor-nova-db` stay unattached. The suspended free staging database was not found by name in this repository, in pull request #339, or in the prior staging transcript. It was not activated.

## Cost and safety

Checked against Render's pricing, free-plan, and disk pages on 2026-10-19.

| Choice | Monthly cost | Durable | Safe to do now |
| --- | --- | --- | --- |
| Leave the preview on ephemeral SQLite | $0 | No | Yes. This is the current state. The retry gate stays closed. |
| Look at the suspended database in the dashboard | $0 | No | Yes, if Resume, Upgrade, Restore, and Delete are not clicked and no connection string is copied. |
| Resume or upgrade that suspended database | $6 if it is an expired Free database that must be upgraded to be read. A suspended paid database starts billing again on resume. | Only after a paid action | No. Spending is not approved. Its rows are not copied. |
| New empty Free Postgres, only when the dashboard shows no active Free Postgres | $0 for 30 days, then inaccessible. Render deletes it 14 days after expiry unless a later paid upgrade is approved. | Until day 30 | Not yet. The free slot has not been verified empty. One active Free Postgres blocks a second one. An expired Free database does not have to be upgraded before a new empty one is created. |
| New Postgres plan `0.1c-256mb` | $6, 1 GB included | Yes | No. |
| Persistent disk | $7 web plan `0.5c-512mb` plus $0.25 per GB. Free web services cannot attach a disk. | Yes | No. The production disk is not reused. |

Attaching a Postgres URL and a new `JWT_SECRET` does not open the retry gate. The gate still requires a durable directory or Render disk, a stable signing key, and a restart marker. Postgres is recorded as durable, and `owner_retry_allowed` stays false. A local test uses `127.0.0.1:1` and does not open a connection.

## Stages

The order is fixed in `ACCEPTANCE_STAGES` inside `backend/app/core/casting_staging_choice.py`. Only stage 0 runs without a new owner choice.

0. Ephemeral preview. Done above. No owner password retry.
1. Dashboard identification only. Record whether any Free Postgres is Available, plus the name, status, and plan of any suspended or expired database. Stop if the name is `amicor-health-isf-db` or `amicor-nova-db`.
2. Empty Free Postgres, only after stage 1 shows the free slot is empty. New name. No restore and no account copy.
3. On preview service `amicor-health-isf-pr-339` only, set `DATABASE_URL` from that new database and generate a new `JWT_SECRET`. Leave production unchanged. Do not set `AMICOR_SEED_PASSWORD`. The retry gate stays closed.
4. A later run signs up a synthetic account, restarts the preview, and signs in with that synthetic password. The owner password is not used. The gate stays closed until a separate change is reviewed after that proof.

## Owner decision

Reply with one of these. Spending stays unapproved until a later message names a dollar amount.

- **A.** Stay on the ephemeral preview. Do nothing in Render.
- **B.** Look only, then reply with whether any Free Postgres is Available and with the suspended database's name, status, and plan. Do not paste a connection string.
- **C.** Only after B shows zero Available Free Postgres databases: approve a new empty Free Postgres for the preview service alone.

Until that reply, do not retry the existing password.
