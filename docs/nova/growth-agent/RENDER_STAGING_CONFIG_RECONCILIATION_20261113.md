# Render staging configuration — prepared replacement proposal (NOT applied)
Date: 2026-11-13. Related: PR #498; draft reconciliation PR #505; staging service `nova-growth-validation-490`.

**NO DEPLOY/MERGE AUTHORIZATION.** These commands are a review proposal only, contingent on a reconciled and passing **exact** candidate SHA. Do not copy into Render, trigger a deploy, modify the database, or activate a paid provider without separate owner approval.

## Proven source divergence / must preserve
The current staging SHA `1395f7e47f0f2e4a94473621374f9219e180ac6b` diverges from Workspace integration `956ed72b7af5985ac08df9bea28646cf961e9d73` (Workspace review branch: 98 ahead, one staging commit behind). Draft PR #505 attempts the missing staging commit into the integration review branch and is currently **not mergeable**. Do not force merge it.

The one staging-only commit fixes:
- `backend/app/core/nova/growth_agent/service.py`: queue mock reminder attempts at their `scheduled_for_utc` time instead of immediate `_now()`. Preserve newer approval, audit and replay guards as well as this change during manual conflict resolution.
- `backend/app/db/session.py`: block generic automatic creation of `nova_ga_*` tables in production.
- `backend/static/nova-growth/staging-journey.html`: synthetic website-chat fixture.
- `backend/tests/test_nova_growth_agent_postgres.py`: require actual Alembic migrations on a disposable database, no silent ORM schema fallback, tighten worker assertions.
- `backend/tests/test_nova_growth_agent_security.py`: production schema creation guard coverage.
- `backend/tests/test_nova_growth_agent_worker_retention.py`: test actual reminder due-time behavior, consent recheck and worker scheduling.

## Current Render configuration blockers
- Auto-deploy `no`; service branch `review/growth-agent-staging-corrections-20261112`; build/start commands pin `1395f7...`. Exact integration candidate SHA does **not** yet exist: do not substitute the current Workspace review head.
- Current start command runs `pytest tests/test_nova_growth_agent_postgres.py` on **persistent** staging DB each start; remove entirely.
- Current start runs `alembic upgrade` each startup. The last read-only inspection showed revision `20261112_nova_ga_retention`, but the deploy should independently **assert** the revision and fail closed, with any migration performed separately only after review/backup.
- Existing dedicated DB host: `dpg-dbqv7mmtlv9c73d7tnb0-a`, database `nova_ga_490_dispos`. No DB URL/password or signed export URLs may be committed to GitHub. Existing export `2026-11-13T03:55Z` archive readability checked (159,692 bytes) but restoration has NOT been proven.

## Proposed exact-SHA build command (template)
Substitute `<APPROVED_RECONCILED_SHA>` **only** after staging-only reconciliation PR and exact-head CI pass:

```sh
test "$RENDER_GIT_COMMIT" = "<APPROVED_RECONCILED_SHA>" && pip install -r backend/requirements.txt
```

## Proposed startup implementation
To avoid maintaining a fragile multi-line Python shell string in the Render dashboard, add a small, reviewed `backend/scripts/verify_growth_staging_start.py` on the **reconciled candidate branch**. That script must:
1. Read `RENDER_GIT_COMMIT`; compare to an explicitly configured `NOVA_GA_APPROVED_STAGING_SHA` with fail-closed missing/mismatch checks. No defaults and no production role escalation.
2. Normalize DB URL driver in memory only; parse its hostname and path and require the dedicated staging DB host/database above. Never print the URL or secrets. Refuse known production DB identity.
3. Connect read-only, verify `current_database()`, `alembic_version` revision `20261112_nova_ga_retention`, and required Growth tables. Do not create or modify schemas, data, migrations or backup state.
4. Enforce synthetic/mock-only staging flags, no paid providers or real email/SMS/calendar/payments, and the existing allowed staging origin. Fail closed on flags being unsafe.
5. On successful check, `os.execvp` uvicorn with the same single-worker address and `PORT`. **Do not run pytest, workers, or alembic upgrades in the service startup.**

Proposed Render start command after implementation and exact SHA review:

```sh
cd backend && python scripts/verify_growth_staging_start.py
```

Candidate build/run must retain source SHA pin; updating dashboard environment/build/start/branch separately risks startup failure or unintended version. Require a coordinated reviewed staging-only configuration change, **autoDeploy OFF** throughout, and no deployment until explicitly approved.

## Before staging approval: evidence packet
- Draft PR #505 conflict resolved manually; no forced merge.
- New candidate commit SHA and full file diff; exact-head CI: Growth Agent backend, Workspace Node, HTTP/auth, PostgreSQL tests on a separate disposable database; no environment test pointed at the persistent staging DB.
- Scripts tested in fail-closed cases (wrong SHA, wrong DB host/name, mismatched schema revision, unsafe live flags); no logs containing credentials.
- Export recovery feasibility verified without restoring over the existing staging DB; rollback to prior **application** SHA (with compatible DB schema), never Alembic downgrade of persistent staging.
- Owner shown SHA, command changes, rollback, any cost impacts, and gives separate staging-only approval.
- Post-release authenticated browser mobile + desktop synthetic journeys for CRM, review, approve-record-only, rejection, hold, audit, no outbound messages, source tracking and worker recovery.
- Separate explicit production launch approval required later.

**This proposal does not claim that a candidate is reconciled, tested, deployed or safe for production.**
