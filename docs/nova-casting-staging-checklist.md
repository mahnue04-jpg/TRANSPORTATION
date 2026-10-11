# Nova Casting staging checklist

Status: draft branch only. Do not merge, deploy, or collect real auditions from this checklist.

## What is enabled in a disposable test environment

- `GET /api/nova/casting/readiness` requires the existing Nova login. `enabled`, `applications_enabled`, and `media_uploads_enabled` stay false.
- Authenticated reads and disposable sandbox writes run only when `NOVA_CASTING_STAGING_READS` is true and `AMICOR_ENVIRONMENT`, `ENVIRONMENT`, and `APP_ENV` agree on one allowlisted non-production value (`development`, `dev`, `test`, `testing`, `local`, `staging`, or `disposable`). Absent, unknown, conflicting, and production values stay off.
- Sandbox routes can create and edit unpublished draft campaigns, save a consent-based test application, submit it, list status, withdraw a submitted application, record a review, shortlist, and store a human callback proposal. Nothing is emailed or texted.
- Media routes accept MIME type and byte size only. The row is quarantined. Playback returns no storage key and no signed URL.
- Audit rows record the allowlisted action, actor id, organization id, object id, and time. They do not store notes, emails, or storage keys.
- The fictional preview at `backend/static/nova-creative/casting-preview.html` still makes no network calls. The separate page `backend/static/nova-creative/casting-sandbox.html` calls the API with the existing Creative Studio Nova token and only after readiness reports `sandbox_writes_enabled`.

## What stays off

- Public intake, campaign publishing, file uploads, signed media URLs, and external delivery.
- `casting_db_models` is not imported by application startup, Creative Studio schema ensure, or Alembic autogenerate.
- `Base.metadata.create_all` omits `nova_casting_` tables, including Health ISF startup.
- Alembic revisions `20261010_casting_org_draft`, `20261010_casting_content_draft`, and `20261010_casting_audit_consent` return without DDL when the process is production. They still stamp the revision, so production `alembic upgrade heads` does not create casting tables.
- Forward-only revision `20261011_casting_schema_repair` creates any missing casting tables outside production and does nothing in production. Its downgrade does not drop tables.

## Disposable verification

From the repository root, with PostgreSQL available:

```bash
export CASTING_TEST_POSTGRES_URL=postgresql+psycopg2://casting_test:casting_test@127.0.0.1:5432/casting_test
python -m pytest --noconftest -q backend/tests/test_nova_casting_migration_execution.py backend/tests/test_nova_casting_two_migrations.py backend/tests/test_nova_casting_audit_consent.py backend/tests/test_nova_casting_schema_repair.py backend/tests/test_nova_casting_flags.py backend/tests/test_nova_casting_intake_schema.py backend/tests/test_nova_casting_schema_guard.py backend/tests/test_nova_casting_router_draft.py backend/tests/test_nova_casting_router_sandbox.py
```

From `backend/`, against a disposable database:

```bash
python -m pytest -q tests/test_nova_casting_db_reads_integration.py tests/test_nova_casting_router_http.py tests/test_nova_casting_sandbox_http.py
```

Local UI check, only with the flag and an allowlisted environment set on a disposable API:

1. Sign in through Creative Studio or the sandbox page. The token key is `amicor_nova_creative_token`.
2. Open `/static/nova-creative/casting-sandbox.html`.
3. If readiness reports sandbox writes off, the page stops and tells you nothing was submitted.
4. With writes on, an organizer creates a draft campaign and an applicant saves consent, submits, and can withdraw. The organizer reviews, shortlists, and records a callback. No message is sent.

## Known gaps

- No real video bytes, malware scan, or private playback URL. Clean-media authorization returns status only.
- Sandbox writes do not create casting organizations or memberships. Those rows must already exist in the disposable database.
- This is not launch-ready. Zeus is not a partner and is not connected.

## Approval gates still required

- Merge of PR #308.
- Any staging or production deployment, including Render.
- Running migrations against a non-disposable database.
- Setting `NOVA_CASTING_STAGING_READS` on a real host.
- Paid services, external integrations, or real applicant videos.
