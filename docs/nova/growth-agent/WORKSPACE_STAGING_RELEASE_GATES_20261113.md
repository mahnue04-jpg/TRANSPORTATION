# Nova Growth Agent + Workspace — guarded staging release plan
Recorded: 2026-11-13. **This is a preflight/checklist, not deployment authorization.**

## Current source of truth

- Development integration: draft PR #498 on `review/growth-workspace-dashboard-497-20261112`; verified commit as of this plan: `64001d2da3cd6cb02f2ef43a508f6d582f938563`. Qualifying CI passed Workspace JS 30/30, Workspace Python 8/8, backend queue tests 9/9, HTTP security 6/6, Workspace HTTP 2/2; the *backend-diagnostic* job was still running when last inspected. Recheck exact SHA and workflow before release.
- Original Growth Agent PR #490 remains draft/unmerged with a different head. Do not assume either draft branch is already in production.
- Existing isolated Render service: `nova-growth-validation-490` (`srv-dbqv8ip5efls73dtpmo0`), branch `review/growth-agent-staging-corrections-20261112`, auto-deploy **OFF**, currently build/start pinned to `1395f7e47f0f2e4a94473621374f9219e180ac6b`.
- Comparison of current staging commit to Workspace review SHA reports **diverged** (review branch ahead 97, behind 1 at time of check). A build-time SHA edit alone cannot safely reconcile source or configuration.
- Current Render start command includes `alembic upgrade 20261112_nova_ga_retention` AND **runs `pytest tests/test_nova_growth_agent_postgres.py` against the persistent staging DB on each startup**. This is a release blocker: those tests can write or mutate data. Remove runtime pytest; execute integration checks only on an isolated disposable database before deployment.
- Dedicated staging Postgres database: `nova_ga_490_dispos` at `dpg-dbqv7mmtlv9c73d7tnb0-a`; last read-only inspection: 21 `nova_ga_*` tables, Alembic revision `20261112_nova_ga_retention`. Preserve data and do not widen external database IP access.
- Logical export made 2026-11-13 03:55 UTC. Owner checked downloaded archive readability in Windows PowerShell (`tar -tf` passed; 159,692 bytes). **Readable archive is NOT an independently proven restore.** Never paste signed backup download URLs, credentials, or database URLs into repository/PR logs.

## Preflight gates (in order)

1. Confirm no unexpected changes in current staging branch, migrations, production wiring, external worker toggles, or paid provider flags. Inventory differences between deployed SHA and candidate, including that one behind commit; reconcile with a new **staging-only** integration SHA under review, preserving all staging guards. Do not silently overwrite the deploy branch.
2. Verify data-preserving rollback with backup and restoration feasibility (test against an isolated **existing/disposable** DB only if allowed, avoid provisioning additional paid resources without owner approval); document app-version rollback compatibility with existing schema. **Never downgrade the persistent staging DB as a rollback method.**
3. Confirm the reviewed code has no migrations requiring unsafe changes to the staging database. Staging currently reports the latest Growth Agent retention revision, but verify exact target behavior.
4. Update Render build and start commands in a coordinated, reviewed change to pin **one approved candidate SHA** and preserve host/database assertion. Remove pytest from persistent staging startup entirely; if migration is retained, assert expected revision and database identity first. Do not apply the stale Render blueprint: it points at the wrong branch and may create a new billable database.
5. Keep auto-deploy OFF, workers and real email/SMS/calendar/payment transports OFF, Kling/paid providers OFF; do not change external IP allowlist. Ensure the staging version can be rolled back to a compatible known-good application commit without rolling back the DB.
6. Request explicit owner approval for the **exact staging candidate SHA and coordinated Render config edits** before any staging-only deploy. **Do not trigger `deploy latest` or merge draft PRs as a substitute.**
7. After staging-only release, run a real authenticated browser owner journey: sign in -> Workspace Growth Agent menu -> synthetic lead/chat -> human handoff -> preview queue -> View details -> Approve (record only), Reject, Hold -> verify precise audit rows and no execution, outbound messaging or charges. Test responsive mobile, permission denial, sign-out and tenant switch with pending requests, duplicate click and conflict/retry behavior.
8. Separately verify consent/opt-out, CRM, appointments, source attribution and mock worker recovery with synthetic data. UI must clearly distinguish synthetic demo, approval, mock attempt, and confirmed external delivery. No real customer traffic in staging.
9. Preserve logs, CI run IDs, exact SHA, backup identifier (NOT signed URL), migration status, smoke-test results and rollback instructions. Mark deficiencies as release blockers rather than pretending tests or UI are complete.
10. Production/site launch requires **separate** owner approval, live-service isolation and consent/privacy checks. Integrations with Creative Studio, Communications, Operations and real visitor acquisition are future acceptance gates, not verified by this staging plan.

## Current blockers and one next action

**Blockers:** (a) staging service pinned to different diverged branch/SHA, (b) persistent-DB-writing pytest in start command, (c) restore feasibility not proven, (d) real authenticated browser acceptance missing, (e) no production launch authorization.

**Next engineering action:** prepare a reconciled staging-only candidate SHA and a reviewed exact replacement for Render's build/start configuration, preserving data, secrets and all disabled live transports. Present **diff + candidate SHA + rollback procedure** for owner approval. Do not deploy.
