# Nova Casting launch checklist

Draft pull request #308 only. Do not merge. Do not deploy. Nothing in this checklist is live on a real host.

`GET /api/nova/casting/readiness` keeps `enabled`, `applications_enabled`, and `media_uploads_enabled` false. Sandbox routes open only when `NOVA_CASTING_STAGING_READS` is true and `AMICOR_ENVIRONMENT`, `ENVIRONMENT`, and `APP_ENV` agree on one allowlisted non-production value. Absent, unknown, conflicting, and production values stay off.

## Requirement status

| Requirement | Implemented | Tested | Live | Blocked by |
| --- | --- | --- | --- | --- |
| Authenticated organizer and applicant journey: create and edit a draft, consent, save, resume, submit, review, shortlist, callback, withdraw, and delete private media | Yes, on the sandbox page | Desktop 1280x800 and mobile 390x844 browser runs on a disposable API | No | Owner approval before any real host |
| Same-tenant wrong-organization denial | Yes. Setup binds the organization to the caller tenant. Another account's organization returns 404 for management and for the other organization's application id | PostgreSQL HTTP test and both browser runs | No | Owner approval |
| Sandbox organization and reviewer membership without hand-seeded casting rows | Yes. The signed-in account creates its own organization. Only `reviewer` can be granted, and only to another active user in the same tenant | PostgreSQL HTTP test and browser setup | No | Platform login still requires an existing Nova user. This does not create Nova accounts |
| Private video upload, one byte range, withdrawal cleanup, failed-commit cleanup, orphan cleanup | Yes | Disposable PostgreSQL media test | No | Owner approval. `media_uploads_enabled` stays false |
| Structural scan separated from antivirus readiness | Yes. Default mode is structural-only | Unit tests and browser banner | No | A structural pass is not maintained antivirus |
| Maintained ClamAV on disposable infrastructure | Yes, as an opt-in. See `docs/nova-casting-clamav-runbook.md` | ClamAV 1.5.4 with fresh `daily.cvd` 28150, `main.cvd` 63, and `bytecode.cvd` 339 accepted a synthetic MP4 and detected EICAR directly | No | Not installed on any real host. `clamd` is not started |
| Fresh and older disposable PostgreSQL history, repair, and rollback | Yes. Production stamps create no tables. Repair is idempotent and its downgrade keeps tables. An older organization-only schema accepts later revisions and can roll back to no casting tables | `CASTING_TEST_POSTGRES_URL` tests for repair, history, two revisions, and migration execution | No | Do not run `alembic upgrade heads` against a non-disposable database |
| Environment gates | Yes. Default deny | Flag tests for absent, unknown, conflicting, and production values | No | Do not set the flag on a real host without approval |

The safe staging procedure is `docs/nova-casting-staging-runbook.md`. The producer-facing sample, with no partnership and no return claim, is `docs/nova-casting-pilot-offer.md`.

## Pilot extension on draft branch `cursor/casting-auditions-pilot-e1ae`

Coded in the existing sandbox, not merged and not deployed. Public intake stays off. Message rows are constrained to `not_sent`.

| Requirement | Implemented | Tested | Live | Blocked by |
| --- | --- | --- | --- | --- |
| Roles, eligibility, https audition links, consent retention, revocation, dedupe, receipts | Yes, sandbox pilot routes | Unit tests in `test_nova_casting_pilot.py` | No | Owner approval before any real host or public form |
| Human shortlist, rubric notes, reviewer-minimized queue, CSV export without links | Yes | Unit tests | No | Owner approval |
| Approval-gated email drafts, STOP suppression, retry that does not send | Yes | Unit tests | No | No email provider is configured, and none should be enabled for this pilot |
| Timezone call sheet and fictional Harborlight demo | Yes. The sandbox organization stores the sample and reloads it. The demo HTML page is a labeled preview | Page source test and authenticated SQLite HTTP test | No | Not a staging deploy |
| SMS and WhatsApp | Rejected unless a provider name is configured, and still not sent | Unit tests | No | Do not buy a provider for this pilot |
| Authenticated invitation, redeem, refresh persistence, expired invite | Yes. Token stays in the organizer snapshot. Redeem reuses one draft application. Expired and closed-campaign invites stay closed | `test_nova_casting_journey.py` and the browser journey at 1280x900 and 390x844 | No | Invitations are not public links |
| Mock transport receipts, retry, opt-out, and failure | Yes. Provider `disposable-mock`. `delivery_state` stays `not_sent` and `real_delivery` stays false | HTTP journey test and browser journey | No | Do not connect a real mail transport |
| Disposable mock upload with MIME, size, and malware-review gate | Yes. Clean bytes stay in process memory. No public URL and no byte column. Wipe clears the hold | Unit and HTTP tests | No | `media_uploads_enabled` stays false. Do not enable public media upload |
| Journey migration reversibility and tenant isolation | Yes. Revision `20261015_casting_journey`. Downgrade drops four tables. A mismatched tenant cannot read the snapshot or the journey audit. Wipe removes mock metadata so a new database session does not restore it | Postgres-gated file list, `26 passed`, output has no `skipped`, measured 2026-10-18 on disposable Postgres 16 | No | Do not run the downgrade on a shared database |
| Fictional subscriber FAQ with human escalation | Yes, signed-in sandbox only. Listed Harborlight answers are canned. Unlisted, ticket, and billing questions wait for a person. A reviewer acknowledge does not send. Card numbers are redacted. Public `/casting/` has no form | `test_nova_casting_subscriber_faq.py` | No | No billing credentials, no public intake, and no outbound message |

## Preview build (2026-10-18)

On commit `e1d30c2a`, before this follow-up, these public URLs returned **200**:

- `https://deploy-preview-339--grand-beignet-6447ea.netlify.app/`
- `https://deploy-preview-339--grand-beignet-6447ea.netlify.app/casting/`
- `https://cursor-casting-auditions-pil.amicor-public.pages.dev/casting/`

`/static/nova-creative/casting-sandbox.html` on that Netlify host returned **404**. That host publishes the public site only. The page now says the signed-in sandbox is not hosted there. It still has no application form, no fetch, and `noindex`. Public intake stays off. The authenticated sandbox remains on the Nova app, which is not this public preview.

## Explicitly unavailable

- Public intake, campaign publishing, and a public application form. Campaign status cannot leave `DRAFT` or `CLOSED`.
- Real media upload and playback of applicant video. Mock upload metadata is not a released file.
- Signed media URLs, public file hosting, and playback without the Nova session.
- Email, SMS, and external delivery of callbacks.
- Real applicant videos, names, or contact details. Tests use synthetic bytes and `.invalid` addresses.
- Paid scanners, paid signature feeds, and third-party contact.
- Casting tables on production startup or in production `alembic upgrade heads`.
- Zeus or any other partner connection.
- Website and Creative Studio diagnostic changes. Those belong to the revenue work.

## Remaining dependencies

- Owner approval to merge pull request #308.
- Owner approval before any Render or other real-host deployment.
- The owner approved one new empty Free Postgres. An owner-connected inspection reports `amicor-casting-staging-db` (`dpg-dbap057btjjs7381egmg-a`, plan free, region virginia, status available, expiry 2026-11-18 UTC). The live preview at `d0d4164e930f4b1774eff5085e3773d5e87dbd60` still uses ephemeral sqlite and an ephemeral signing key. This workspace cannot set a Render secret reference. The owner-only save-only step for service `srv-db7r3ke7bikc73ddosmg` is in `docs/nova-casting-staging-acceptance.md`. Do not attach `amicor-health-isf-db` or `amicor-nova-db`, do not copy production secrets or rows, and do not paste a connection string. Paid Postgres and a disk stay unapproved. `owner_retry_allowed` stays false.
- Owner approval before a migration against a database that is not disposable.
- A Nova user account for each person in a sandbox demo. Casting setup does not register users.
- If antivirus readiness is required on a future disposable host, install the free ClamAV packages from the OS archive and run `freshclam` into `NOVA_CASTING_CLAMAV_DB`. Do not treat structural mode as that install.

## Rollout, only after those approvals

1. Confirm the target is not production and that `AMICOR_ENVIRONMENT`, `ENVIRONMENT`, and `APP_ENV` agree on one allowlisted name.
2. Run `alembic upgrade heads` only against a database the owner has named for this purpose. Production skips casting DDL. A database that already stamped the earlier casting revisions without tables needs the forward repair revision `20261011_casting_schema_repair`.
3. Set `NOVA_CASTING_STAGING_READS` only on that disposable or approved staging process.
4. Leave `media_uploads_enabled` false. It is a fixed response field, not an upload switch.
5. Optional: set `NOVA_CASTING_SCANNER=clamav` and `NOVA_CASTING_CLAMAV_DB` after `freshclam` succeeds. Otherwise the page stays on structural-only wording.

## Rollback

- Turn `NOVA_CASTING_STAGING_READS` off. Routes return 503 and do not open a casting session.
- Repair revision `20261011_casting_schema_repair` downgrade does not drop tables.
- On a disposable database, the earlier casting revisions can downgrade and drop the casting tables. Do not do that on a shared or production database.
- Delete the private media directory for that disposable process. It is not under `backend/static`.

## Disposable verification

```bash
export CASTING_TEST_POSTGRES_URL=postgresql+psycopg2://casting_test:casting_test@127.0.0.1:5432/casting_test
python -m pytest --noconftest -q backend/tests/test_nova_casting_migration_execution.py backend/tests/test_nova_casting_two_migrations.py backend/tests/test_nova_casting_audit_consent.py backend/tests/test_nova_casting_schema_repair.py backend/tests/test_nova_casting_flags.py backend/tests/test_nova_casting_intake_schema.py backend/tests/test_nova_casting_schema_guard.py backend/tests/test_nova_casting_router_draft.py backend/tests/test_nova_casting_router_sandbox.py backend/tests/test_nova_casting_media_scan.py
```

From `backend/`:

```bash
python -m pytest -q tests/test_nova_casting_db_reads_integration.py tests/test_nova_casting_router_http.py tests/test_nova_casting_sandbox_http.py tests/test_nova_casting_private_media_http.py
```
