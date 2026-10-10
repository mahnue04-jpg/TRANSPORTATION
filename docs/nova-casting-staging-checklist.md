# Nova Casting staging checklist

Status: draft branch only. Do not merge, deploy, or collect real auditions from this checklist.

## What is enabled

- `GET /api/nova/casting/readiness` requires the existing Nova login and always reports intake as off.
- `GET /api/nova/casting/organizations/{organization_id}/applications/{application_id}` and `GET /api/nova/casting/organizations/{organization_id}/campaigns/{campaign_id}` are mounted on the existing API.
- Reads run only when `NOVA_CASTING_STAGING_READS` is `true` and `AMICOR_ENVIRONMENT`, `ENVIRONMENT`, and `APP_ENV` are not `production` or `prod`.
- The caller identity is the authenticated Nova user. Path organization ids select a record; they do not grant membership.

## What stays off

- `enabled`, `applications_enabled`, and `media_uploads_enabled` stay false.
- No POST routes, file uploads, signed media URLs, campaign publishing, or external delivery.
- No facial, appearance, or protected-trait scoring.
- `casting_db_models` is not imported by application startup, Creative Studio schema ensure, or Alembic autogenerate.
- `Base.metadata.create_all` omits `nova_casting_` tables, including Health ISF startup.
- Alembic revisions `20261010_casting_org_draft`, `20261010_casting_content_draft`, and `20261010_casting_audit_consent` return without DDL when the process is production. They still stamp the revision, so production `alembic upgrade heads` does not create casting tables. Applying those tables later needs a new approved revision.

## Disposable verification

From the repository root, with PostgreSQL available:

```bash
export CASTING_TEST_POSTGRES_URL=postgresql+psycopg2://casting_test:casting_test@127.0.0.1:5432/casting_test
python -m pytest --noconftest -q backend/tests/test_nova_casting_migration_execution.py backend/tests/test_nova_casting_two_migrations.py backend/tests/test_nova_casting_audit_consent.py backend/tests/test_nova_casting_flags.py backend/tests/test_nova_casting_intake_schema.py backend/tests/test_nova_casting_schema_guard.py backend/tests/test_nova_casting_router_draft.py
```

From `backend/`, against a disposable database:

```bash
python -m pytest -q tests/test_nova_casting_db_reads_integration.py tests/test_nova_casting_router_http.py
```

## Approval gates still required

- Merge of PR #308.
- Any staging or production deployment, including Render.
- Running migrations against a non-disposable database.
- Setting `NOVA_CASTING_STAGING_READS` on a real host.
- Paid services, external integrations, or real applicant videos.

Zeus is not a partner and is not connected.
