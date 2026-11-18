# Nova Central isolated startup — design and acceptance contract (#542)

**Status: proposal only. No executable entrypoint, migration, deployment or production change in this PR.**

## Finding and threat model

The ordinary `backend/app/main.py` FastAPI lifespan invokes shared platform recovery, authentication schema ensuring and default-user seeding, then schedules deferred platform startup. `backend/app/db/session.py:init_platform_db` also uses `Base.metadata.create_all` for many non-Central tables. Therefore `uvicorn app.main:app` is **not** a zero-write startup for a proposed dedicated Nova Central staging environment. Even with Nova journey flags disabled, starting the shared app may create/modify unrelated tables or accounts. Never point it at production, Studio, Growth or Receptionist databases for this exercise.

## Proposed next implementation slice (separate draft PR)

Implement a minimal **Nova Central-only ASGI factory or entrypoint** in its own module, without importing `app.main`, `app.startup`, seed routines, generic app lifespan, or any background worker. Preserve the existing production app unchanged. Expose only liveness/readiness and the one protected read-only Central journey view. Reuse the actual authentication and persisted user lookup dependencies, including active role/grants, account revocation, tenant membership and signed tenant matching; **do not** replace those with synthetic overrides outside disposable tests. Staging auth tables/identities must be provisioned separately and explicitly approved, not auto-seeded.

### Fail-closed configuration (validate before app initialization)

- Exact approved commit SHA and separately verified `RENDER_GIT_COMMIT`; abort on mismatch.
- `AMICOR_ENVIRONMENT=staging` and `APP_ENV=staging` required. Production, missing or conflicting values abort.
- Expected **new** isolated database host and exact DB name supplied through separate allowlist variables; parse the configured database URL and abort if absent, malformed, mismatched or pointing to the existing production/Growth/Receptionist databases. Do not print connection credentials.
- Default both `NOVA_CENTRAL_JOURNEY_READONLY_ENABLED` and `NOVA_CENTRAL_JOURNEY_DATA_READ_ENABLED` to false and require separately approved short-lived enablement.
- Disable shared seed/init/migration hooks, deferred tasks, auto-dispatchers, paid providers, externally directed transport, and outgoing customer messages. No migration runs at boot.
- Ensure no shared Render environment group/secret reference is silently inherited. Keep auto-deploy disabled and do not use real customer identities for acceptance.

### Proposed read-only behavior

- Anonymous or invalid token: 401; role revoked, staff/support, no tenant, global or mismatched JWT/persisted tenant: 403 (subject to existing auth semantics).
- Feature disabled: 404 or empty `not_connected` readiness as defined by the existing gate. Missing staging read-model table: 503, not table creation.
- Enabled synthetic preview: SQL tenant filter from authenticated persisted user only; 20-row bounded deterministic status projection, five allowed non-PII fields, no write endpoints or task execution; `Cache-Control: private, no-store` and `Vary: Authorization, Cookie`.
- No customer journey data until separately approved durable source-of-truth projection and retention/audit policy.

## Required no-cost proof before provisioning

1. Use disposable SQLite or ephemeral test Postgres with DDL/DML instrumentation. Snapshot tables/rows and assert that **ASGI import + lifespan + requests** cannot create, seed, update or delete unrelated data.
2. Assert the entrypoint does **not** invoke `app.main`, `app.startup`, `init_platform_db`, `ensure_auth_schema`, `seed_default_users`, Alembic, deferred startup, external communications, job workers or paid providers.
3. Test missing/foreign database host/name, mismatched SHA, missing/conflicting environments, both flags, wrong credentials, expired/revoked role and account, token org transfer, bearer/cookie precedence, missing table, database read error, startup/restart and no caching.
4. Test two fictional organizations sharing the same journey correlation ID and prove no cross-tenant data appears. Ensure only explicitly provisioned disposable accounts can authenticate.
5. Report exact runner/head SHA, test counts, startup command, dependency tree and whether memory/build constraints permit the intended Render tier. Do not claim CI covers an actual Render runtime until a separately authorized staging deployment succeeds.

## Deployment gate (NOT authorized)

Before any new resource creation or deployment, provide exact service and database IDs **after separate owner approval**, plan/region/monthly cost, source SHA, disabled auto-deploy, separate credentials, backup/restore drill, teardown and retention plan, and a hard refusal on existing AMICOR DBs or Studio SQLite. Staging migration/fictional record insertion and temporary flag enablement require their own approvals. PRs #547–#552 remain draft and should not be merged automatically.

**Acceptance objective:** a demonstrably isolated, zero-unapproved-write Central staging process. This is not yet a working agent dispatcher, real customer dashboard, or permission to spend.
