# Nova Central staging: least-privilege PostgreSQL reader account

**Design only — not a migration, executable deployment command, grant execution, or approval to create accounts.**
Reviewed with isolated ASGI draft PR #554 and staging read-model draft #552. Applies only to a future, separately provisioned, disposable Nova Central staging database.

## Data boundary and separation of duties

- Proposed isolated database name: `nova_central_542_dispos` (name only; no actual resource exists).
- Proposed application reader role: `nova_central_542_reader` (name only; not yet provisioned).
- **Migration/fixture owner is a separate temporary identity**; web service must not receive its password, owner rights, schema creation rights, or any inherited admin grants.
- No connection or cross-database grants to `amicor-prod`, Studio SQLite, Growth `nova_ga_490_dispos`, Receptionist `nova_ga_receptionist_dispos`, or other AMICOR databases.
- Reader needs **CONNECT** on exactly the approved Nova Central DB, **USAGE** on the approved schema, and **SELECT** on the minimal identity table `platform_users` required by existing `get_current_user`, plus `nova_central_journey_read_model` only once its separate migration and preview are approved. Current isolated readiness endpoint does not mount or query the journey table.
- `platform_users` contains sensitive account material. The existing User ORM selects full model rows, so **column-limited grants are not safe to assert without a narrower auth query**. Before activating staging, either implement/test a minimal identity resolver with approved column-level SELECT grants or use a disposable staging-only users table with fictional records and audit full-row access. Never copy production accounts/password hashes.
- Reader must have **no** INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, CREATE, ALTER, DROP or ownership ability; no CREATEDB, CREATEROLE, SUPERUSER, BYPASSRLS, replication, inherited elevated roles, temporary table privileges, or access through functions that mutate data. Restrict default grants/future tables and review grants to PUBLIC and inherited roles.
- Use unique dedicated credentials generated at provisioning; never log secrets, share privileged credentials with the app, or allow normal service startup to seed accounts or run migrations.

## Review checklist for a separately approved provisioning change

1. Verify exact workspace, database instance ID, resource price/region and that the service uses the exact reviewed commit with auto-deploy OFF; fail on unexpected env/DB URL/role.
2. Record reader role membership, login attributes and effective privileges; test `current_database()`, `current_user`, `session_user`, TLS, schema/search_path and no inherited access to unrelated tables or databases. A URL username allowlist alone is **not proof of database privileges**.
3. In a dedicated, disposable Postgres instance, using fictional account and journey rows, prove approved SELECT succeeds while every mutating operation and unauthorized table access fails with permission denied. Test both direct SQL and the actual isolated ASGI application.
4. Establish DB/network access restrictions (including no unintended public ingress), credential rotation/revocation, clean shutdown and reconnect behavior. No external provider keys, customer imports or real communications.
5. Use explicit backup/restore verification and written rollback/teardown (including session termination and credential revocation). If retention, backups or audit logs are unavailable on the chosen plan, mark it **NO-GO** rather than assuming recoverability.
6. For eventual journey preview: separate schema migration and synthetic fixtures, authenticated tenant-bound SELECT, response field allowlist, read cap, expiry/retention, no-store cache headers, and both default-off gates with explicit time-limited owner approval.

## Important limitations

The 40 passing PR #554 focused tests use disposable SQLite and SQLAlchemy instrumentation. They verify code behavior in those tests, **not** PostgreSQL GRANT enforcement, resource/network isolation, or real agent orchestration. The broader backend diagnostic is an independent gate. No user action or financial commitment is authorized by this document.

**Go/no-go:** NO-GO for creating a database, granting credentials, migrating schema, deploying or enabling feature flags until specific owner approval identifies exact staging resource IDs, approved SHA, price, backup plan, dedicated reader credentials and the test window.
