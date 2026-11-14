# Growth Agent staging safety gate — verified inventory, no deployment authorization

Date: 2026-11-14. Relates to draft PRs #490 and #517 and issues #496/#497.
This document records read-only evidence and **proposed** release gates. It does not authorize or execute Render changes.

## Current observed state (Render read-only)
- Confirmed Render workspace: **Saye's workspace** (`tea-d8oe81b7uimc739gujp0`).
- Existing isolated service: `nova-growth-validation-490` (`srv-dbqv8ip5efls73dtpmo0`), URL `https://nova-growth-validation-490.onrender.com`.
- Auto-deploy is **off**. Current branch: `review/growth-agent-staging-corrections-20261112`.
- Most recent **live** deployment: `dep-dbqv9l2fngtc73ee6420`, commit `1395f7e47f0f2e4a94473621374f9219e180ac6b`, completed November 12, 2026.
- The read-only Workspace panel under PR #517, commit `ff06a85b492e17f75c89208697ce66a9112e9538`, is **not deployed** on the above service. PR #517 is a draft against the PR #490 branch.
- The existing build and startup commands are pinned to the old exact SHA. Do not update one pin without the other and do not start a deployment that fails an exact-SHA guard.
- The service startup code runs `alembic upgrade 20261112_nova_ga_retention` and then `pytest -q --disable-warnings tests/test_nova_growth_agent_postgres.py` with `NOVA_GA_PG_TEST_URL` set to the persistent staging DATABASE_URL before starting uvicorn. **Treat those tests as potentially mutating**. Do not re-run them on the persistent database.
- The startup command checks the database hostname and path, expecting `/nova_ga_490_dispos`. Preserve this dedicated database identity; do not print or expose any connection credentials.
- Legacy documents `STAGING_PROPOSAL.md` and `RENDER_STAGING_OWNER_APPROVAL.md` still describe staging as not provisioned and different blueprint names. They predate this verified live service; **do not apply the obsolete blueprint** to provision a replacement or mutate the current service.

## Additional startup side-effect finding (2026-11-14)
Inspection of `backend/app/main.py` at PR #517 head shows `lifespan()` calls `init_db()`, `auth_module.ensure_auth_schema()`, `auth_module.seed_default_users()`, Health ISF schema ensure functions, Nova Today schema ensure, and schedules `run_deferred_platform_startup()`. When Growth Agent worker and retention flags are on, it can also start the mock worker and retention scheduler.

**This means `staging_start.py` is NOT a fully non-mutating application startup.** It removes direct `alembic` and `pytest` from the Render command and validates identifiers **before** launching uvicorn, but uvicorn triggers application lifespan initialization that may write to the connected database. Green unit tests only show that launcher argument generation is guarded; they do not prove database immutability, schema compatibility, or safe rollback. Current launcher is a proposed draft only and must not be substituted into Render yet.

**Added mandatory release gate:** audit startup, deferred initialization, and lifecycle worker behavior on the exact release candidate; disable optional worker/retention flags; verify in a disposable restored staging clone whether the full lifespan mutates schemas or records. If code changes are needed, review separately without weakening production startup. Establish an explicit, evidence-backed rollback plan. Until then, no service restart or deploy against the current persistent staging database.

## Deferred initialization verified in code (2026-11-14)

`backend/app/deployment/background_startup.py` confirms that `run_deferred_platform_startup()` invokes `Base.metadata.create_all`, payment table ensures, operational bootstrap, and `health_isf_service.init_sample_data(db)` when `runtime_environment` is anything other than `production` / `prod` (or the sample-data flag is enabled). **The proposed `APP_ENV=staging` configuration therefore does not prevent sample-data seeding or schema writes on a normal startup.** As of this review there is no verified no-write application-lifespan mode; do not claim one.

The isolated preflight now rejects enabled Growth mock worker and retention scheduler flags, but that only prevents those two optional components. It does not control platform initialization. A safe next engineering slice is an **isolated startup-mode design review** for the Growth-only staging service, with tests proving existing production behavior unchanged and no schema/bootstrap/sample seed calls on a restored disposable clone. Do not enable such a mode against the current staging DB until explicit owner review and approval.

## Proposed isolated lifespan gate (2026-11-14, not deployed)

PR #517 now includes an opt-in `NOVA_GA_ISOLATED_SKIP_DB_BOOTSTRAP=true` branch early in `app.main.lifespan`, guarded by the exact-SHA, staging-environment, dedicated-database and background-worker checks in `staging_preflight.validate`. In this mode it skips **the observed normal-lifespan** platform initialization and deferred startup scheduling. The proposed `staging_start.py` refuses to launch unless the mode is explicitly enabled; ordinary startup remains the default.

**Not a proof of all startup or runtime immutability:** module imports, middleware, per-request handlers, database session dependencies and other runtime code have not been verified for side effects. This opt-in mode is only a development candidate for isolated test environments. It may disable dependencies needed for the UI to function. Run it first against a separate, disposable restored database and verify both positive and negative browser/API behavior. Do not point it to the existing persistent staging database based solely on unit tests. Restore verification and explicit staging deployment approval are still outstanding.

## Blocking gates, in order
1. **Recoverability:** Confirm an export of the exact current database, safely stored and access-controlled; perform a *separate disposable restore* verification before any change that could touch persistent records. Evidence must include restored schema and a limited synthetic read/write/rollback check without sensitive data in the report. A valid archive listing alone is not a tested restoration.
2. **Non-mutating boot path:** Propose and review a start command that only performs startup validation against the existing persistent staging DB, **without schema migrations or tests that write data**. Run migration and PostgreSQL integration tests only in CI/disposable DB with unique synthetic credentials. Review exact SHA and DB identity assertions.
3. **Authorization/compatibility:** PR #517 limits management APIs to admin-level sessions. Verify the existing Growth dashboard and workflows still work for the intended role, and that staff/dispatcher/driver/unauthenticated/cross-tenant access fails closed. Avoid a claim that role name alone proves business ownership; confirm product policy.
4. **Immutable candidate:** Freeze an exact reviewed commit integrating the necessary changes, dependency and static asset routes. Ensure branch/tag, Render service and expected SHA agree. Confirm rollback procedure to last known-good commit without automatic DB downgrade.
5. **Cost and action boundary:** Record current service plan/cost implications, feature flags and secret exposure checks. **Request explicit separate owner staging-only authorization** before modifying service settings or deploying. Auto-deploy must remain off; never touch production or Creative Studio.
6. **Staging browser acceptance after an approved deploy:** Owner login in `/nova/workspace`, four authenticated GETs from manual Growth panel, truthful 'returned records' labels, no customer PII rendered, empty/offline/403/404/503/expired role states, keyboard/mobile accessibility and same-tenant scoping. Check no new POST/paid calls or background live transports.

## Evidence already verified in GitHub CI (not Render)
At PR #517 commit `ff06a85b492e17f75c89208697ce66a9112e9538`: Growth Python **59 passed**, disposable PostgreSQL **6 passed**, Workspace simulated interaction **8 passed**, and backend diagnostic/qualification regression/Cloudflare checks succeeded. **73 counted tests passed, 0 failed.** They do not establish that the new branch is on the existing Render service.

## Release/rollback principle
Preserve current staging database and last known-good deployment; perform no automatic schema downgrade. If a newly approved deployment fails, stop traffic to the new candidate, return to verified known-good application code and retain records. Record diagnostics and escalate if schema changes occurred rather than improvising a rollback.

## Explicitly not approved
No deploy/restart/merge, no service or DB provision/delete, no staging or production data migration, no env or IP allowlist edits, no external outreach/SMS/email, no paid AI/video/provider, no R2 or Creative Studio SQLite/media/backups changes. No live customer claims or use of simulated tests as production acceptance.
