# Nova Casting staging runbook

Safe-by-default runbook for the sandbox Casting pilot on branch `cursor/casting-auditions-pilot-e1ae` (pull request #339). This does not authorize a production deploy, a public audition form, or any outbound email, SMS, or WhatsApp.

Release recommendation: **hold**. Nothing in this runbook is live.

## What stays off

- `enabled`, `applications_enabled`, and `media_uploads_enabled` stay false on `GET /api/nova/casting/readiness`.
- Public intake, campaign publishing, and a public application URL stay off.
- Raw audition video is not stored. The pilot accepts an https link only. Unsafe schemes, credentials, IP hosts, and markup are rejected.
- Message rows cannot record a sent delivery. `delivery_state` is constrained to `not_sent`. Approval and retry do not open a mail transport.
- SMS and WhatsApp are rejected when `NOVA_CASTING_SMS_PROVIDER` or `NOVA_CASTING_WHATSAPP_PROVIDER` is empty. A configured name still stores `failed_closed` and `not_sent`.
- Applicants under 18 are rejected. Guardian fields and protected-trait fields are rejected and are not stored.
- A caller from another tenant, or a role that cannot perform the action, receives 404. Reviewers do not receive the contact email or the audition link.

## Before any staging process

1. Confirm the target is a disposable or owner-approved staging database. Do not point this at production.
2. Confirm `AMICOR_ENVIRONMENT`, `ENVIRONMENT`, and `APP_ENV` agree on one allowlisted non-production name: `development`, `dev`, `test`, `testing`, `local`, `staging`, or `disposable`.
3. If any of those names is `production` or `prod`, or the names disagree, leave the process alone. Routes stay at 503 and the pilot migration creates no tables.
4. Do not set Stripe live keys, a mail provider, an SMS provider, or a WhatsApp provider for this pilot.
5. Use an existing Nova user. Casting setup does not register accounts.

## Schema

On the disposable database only:

```bash
cd backend
alembic upgrade heads
```

- Production upgrade stamps revision `20261015_casting_journey` and does not create journey or pilot tables.
- If `platform_users`, `nova_casting_organizations`, `nova_casting_campaigns`, `nova_casting_roles`, `nova_casting_intakes`, or `nova_casting_pilot_messages` is missing, revision `20261015_casting_journey` returns without DDL.
- Downgrade of `20261015_casting_journey` drops only `nova_casting_invites`, `nova_casting_mock_attempts`, `nova_casting_mock_media`, and `nova_casting_journey_audit`.
- Downgrade of `20261014_casting_pilot` drops only the earlier pilot tables (`nova_casting_roles`, `nova_casting_intakes`, `nova_casting_rubrics`, `nova_casting_pilot_messages`, `nova_casting_suppressions`, `nova_casting_schedules`, `nova_casting_pilot_audit`). Do not downgrade either revision on a shared database.

## Enable the sandbox, then prove it is still closed

Set this only on the disposable process:

```bash
export NOVA_CASTING_STAGING_READS=true
```

Leave it unset everywhere else. Then sign in as the Nova user and open `/static/nova-creative/casting-sandbox.html`.

1. Create the sandbox organization and a draft campaign from that page. The campaign status stays `DRAFT`.
2. Choose **Load Harborlight sample**. The page must say the sample was saved for this sandbox organization and that nothing was sent.
3. Reload the browser and choose **Reload saved pilot**. The same three roles and the unsent confirmation must come back from the server. This is the persistent copy. The separate page `/static/nova-creative/casting-pilot-demo.html` is only a labeled preview and does not store the sample.
4. Save an adult intake with an `https://` link and consent. Submit it. Draft a callback email and approve it. The message must keep `Delivered: false`.
5. Negative path: enter age 16, or clear consent, and save. The page must reject it and must not show a receipt. Revoke consent on a saved intake and reload. The contact email and audition link must stay cleared.
6. A reviewer account in the same tenant can open the queue and must not see the email or the link. A reviewer cannot export. An account in another tenant receives "Application unavailable".
7. In **Authenticated sandbox journey**, issue an invitation, reload, and confirm the token comes back. Redeem it, save an https link, and submit. The receipt starts with `CA-`. Run mock transport only after the callback draft is approved. The status must include `mock_accepted` and `Real delivery: false`. Export the CSV and confirm it has no `https` link.
8. Choose **Try expired invitation**. The status must say the expired invitation stayed closed. Choose **Validate mock upload** only with a synthetic file. The result must not show a public URL. **Wipe mock memory** must clear the hold. Closing the campaign must reject a new invitation.

## Checks to run before calling staging usable

SQLite unit and authenticated HTTP tests do not need Postgres:

```bash
cd backend
python -m pytest -q tests/test_nova_casting_pilot.py tests/test_nova_casting_pilot_page.py tests/test_nova_casting_pilot_store.py tests/test_nova_casting_pilot_auth.py tests/test_nova_casting_journey.py
```

Postgres-gated migration and sandbox tests run when `CASTING_TEST_POSTGRES_URL` is set. They skip with a named reason when it is absent. Do not treat a skip as a pass. GitHub Actions job `casting-postgres-gated` runs them against the Postgres service and fails if any test is skipped.

```bash
export CASTING_TEST_POSTGRES_URL=postgresql+psycopg2://casting_test:casting_test@127.0.0.1:5432/casting_test
python -m pytest --noconftest -q \
  backend/tests/test_nova_casting_migration_execution.py \
  backend/tests/test_nova_casting_two_migrations.py \
  backend/tests/test_nova_casting_audit_consent.py \
  backend/tests/test_nova_casting_schema_repair.py \
  backend/tests/test_nova_casting_org_name_migration.py \
  backend/tests/test_nova_casting_journey.py
```

From `backend/` with the full dependency set and the same URL:

```bash
python -m pytest -q tests/test_nova_casting_db_reads_integration.py tests/test_nova_casting_router_http.py tests/test_nova_casting_sandbox_http.py tests/test_nova_casting_private_media_http.py tests/test_nova_casting_org_name_concurrency.py
```

Confirm zero sends in the pilot tables:

```sql
SELECT COUNT(*) FROM nova_casting_pilot_messages WHERE delivery_state <> 'not_sent';
```

That count must be 0. The check constraint rejects any other value.

Mock attempts are not deliveries:

```sql
SELECT COUNT(*) FROM nova_casting_mock_attempts WHERE provider <> 'disposable-mock';
SELECT COUNT(*) FROM nova_casting_mock_media WHERE public_url <> '';
```

Both counts must be 0. `nova_casting_mock_media` has no byte column. Delivery stays on `nova_casting_pilot_messages.delivery_state`.

## Rollback

1. Unset `NOVA_CASTING_STAGING_READS`. Pilot and sandbox routes return 503 and do not open a casting session.
2. On a disposable database only, `alembic downgrade 20261014_casting_pilot` drops the four journey tables and leaves the earlier pilot tables. `alembic downgrade 20261012_casting_org_name` then drops the pilot tables and leaves `platform_users`.
3. Delete that process's private media directory if one was created. It is not under `backend/static`.
4. Do not run this downgrade against a shared or production database.

## Still blocked

- No production host and no staging URL is approved by this runbook.
- Antivirus is structural-only unless ClamAV is installed on the disposable host. See `docs/nova-casting-clamav-runbook.md`.
- A real mail, SMS, or WhatsApp provider is out of scope. Do not buy one for this pilot.
- Public applicant intake remains an owner decision and is not enabled here.
