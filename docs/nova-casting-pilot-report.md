# Casting pilot report — issue #332

Earlier session `bc-8ffc6cff-a547-5d66-89a1-cd5d9350e1ae` opened this branch and was idle when the continuation started. Continuation session `bc-eb141276-1c6a-5237-a12f-31be865807b5` stays on branch `cursor/casting-auditions-pilot-e1ae`. This agent is not working on Work & Revenue #336, Synapse #311, website #329, or the Creative Studio video-rendering pipeline.

The GitHub token for this run cannot comment on issues (`403 Resource not accessible by integration`). The acknowledgement that belongs on issue #332 is in the draft pull request instead.

## State words

| Item | State |
| --- | --- |
| PR #308 sandbox casting | Merged on `main` (`d0a3f2b1`). Coded and tested before this branch. Not deployed. |
| PR #327 organization-name uniqueness | Merged on `main`. Not deployed. |
| This pilot | Coded and tested on the draft branch. Not merged. Not deployed. No staging URL. |
| Public intake, outbound email, SMS, WhatsApp, paid tools | Off. |

Readiness stays `enabled: false`, `applications_enabled: false`, and `media_uploads_enabled: false`. Sandbox routes still require `NOVA_CASTING_STAGING_READS` plus one shared non-production environment name.

## What works in this branch

- Organization-scoped roles with requirements, deadlines, eligibility questions, and an 18-year age floor. Campaigns remain `DRAFT`.
- Applicant draft, resume, and submit on an existing sandbox application. Consent version, retention window, receipt (`CA-` plus the application id), and https audition links. Unsafe schemes, credentials, IP hosts, and markup are rejected. No new public upload was added.
- Duplicate email detection, expired consent, revoked consent, and minimization that clears the name, email, link, and answers.
- Reviewer queue with search, status, shortlist filter, and pagination. Reviewers do not receive the contact email or the link. Rubric notes stay attributed to the reviewer and set `automatic_cast` false and `decision` to `human_required`.
- Organizer CSV export. Video links are rejected from the file. A reviewer cannot export.
- Email drafts with idempotency, a 20-draft daily cap, STOP and unsubscribe suppression, approval, and retry. `delivered` and `external_delivery` stay false. The database check allows only `delivery_state = 'not_sent'`.
- SMS and WhatsApp are rejected when `NOVA_CASTING_SMS_PROVIDER` or `NOVA_CASTING_WHATSAPP_PROVIDER` is empty. A configured name still does not send.
- Timezone call sheets. An expired schedule fails the invite closed. A participant who is not on that role cannot open the sheet.
- Fictional Harborlight sample stored for the sandbox organization. Reload reads the same roles and the unsent confirmation back from the server. The page at `/static/nova-creative/casting-pilot-demo.html` stays a labeled browser preview and does not fetch.

## Sample month

Harborlight is fictional. Day 1 opens three unpublished roles. Day 7 rejects a 17-year-old and a duplicate email, then accepts two adult drafts. Day 10 to 14 a person shortlists and approves a callback draft that is not delivered. Day 18 shows a call sheet in `America/New_York`. Day 21 revocation clears contact data and suppresses the reminder. Day 30 exports a minimized CSV. The sample offer is $2,400 USD for 30 days, marked as a sample and not a contract. No Zeus, Netflix, studio, or prior-customer relationship is claimed.

## Tests run here

First pass on 2026-10-14, before Postgres was available in that session:

`82 passed, 8 skipped`

The 8 skips are existing tests that wait for `CASTING_TEST_POSTGRES_URL`.

Continuation on the same branch, after a local Postgres 16 service was started for this worktree. Preview set from `.github/workflows/nova-casting-preview.yml`, with `CASTING_TEST_POSTGRES_URL` set:

`93 passed` and `0 skipped`

The same five files with that variable unset:

`10 passed, 8 skipped`

Skip reasons, from pytest:

- `test_nova_casting_migration_execution.py`: PostgreSQL CI service not configured
- `test_nova_casting_two_migrations.py`: Disposable PostgreSQL not configured
- `test_nova_casting_audit_consent.py`: PostgreSQL CI service not configured
- `test_nova_casting_schema_repair.py`: PostgreSQL CI service not configured (two tests)
- `test_nova_casting_org_name_migration.py`: Disposable PostgreSQL not configured (three tests)

With the URL set, that gated file set was `18 passed` and `0 skipped`. Job `casting-postgres-gated` runs those files in CI and fails if any test is skipped. This session did not observe the GitHub Actions run.

SQLite pilot, page, store, and authenticated HTTP tests:

`21 passed`

That includes cross-tenant denial, reviewer privacy, role denial, consent revocation, consent expiration, the 20-draft daily cap, under-18 rejection, and fake SMS or WhatsApp providers. Every message row stayed `delivery_state = not_sent`. The tests patch `smtplib.SMTP` and `SMTP_SSL` so an opened mail transport fails the test.

SQLite store round trip:

`1 passed` in `backend/tests/test_nova_casting_pilot_store.py`

That test saved a role and an intake, reloaded the role, stored a confirmation with `delivery_state = not_sent`, rejected SMS, and denied a different tenant.

Migration test: production environment creates no pilot tables; a disposable SQLite database creates them only after the parent tables exist; a `sent` delivery value is rejected; downgrade drops the pilot tables and leaves `platform_users`.

Browser check of the demo page, desktop 1280x900 and mobile 390x844: Play finished with "no message was sent". Age 16 returned "Applicant does not meet the minimum age". Missing consent and a `javascript:` link were rejected. A valid sample saved receipt `CA-JORDAN0001` in the tab only. Revocation cleared the sample contact. The only network requests were the page, CSS, and the logo. No API call and no outbound message. That page remains a labeled preview. It does not fetch.

The sandbox page is the persistent copy. A local disposable server, not a deployed host, signed in one test account, loaded Harborlight, and reloaded it. After reload the page read "Server copy reloaded. Published: false. Delivered: false. Roles: 3." Age 16 showed "Applicant does not meet the minimum age. Nothing was submitted." Revoke, then reload, showed "Consent is revoked on the server. Contact details stay cleared. Nothing was sent." The SQLite file for that run had three roles, one email row with `delivery_state = not_sent`, and the withdrawn intake had an empty email and an empty link. The 16-year-old was not stored. Screenshots are under `/opt/cursor/artifacts/casting/`.

## Documents

- Owner quick-start: `docs/nova-casting-quick-start.md`
- Staging procedure: `docs/nova-casting-staging-runbook.md`
- Launch checklist: `docs/nova-casting-staging-checklist.md`
- Producer sample offer: `docs/nova-casting-pilot-offer.md`

## Authenticated journey added 2026-10-15

Still sandbox-only. Campaigns stay `DRAFT` or `CLOSED`. A status other than those two is rejected with "Campaign cannot be published". A closed campaign cannot take a new invitation, a new role, or a redeem.

- Invitation tokens are issued inside the signed-in organizer session. Redeem creates or reuses one draft application for that campaign and applicant. An expired token stays closed. Another tenant receives "Application unavailable". The organizer snapshot includes the token so a reload can restore it. Reviewers and other applicants do not receive the token.
- Mock transport provider is `disposable-mock`. Outcomes are `mock_accepted`, `mock_failed`, `suppressed`, and `opted_out`. A mock receipt looks like `MOCK-` plus part of the message id. A later call with the same prior receipt returns that receipt and does not create a second delivery. Unsubscribe becomes `opted_out`. STOP, revoked consent, and an empty address become `suppressed`. `delivery_state` stays `not_sent`. `external_delivery`, `delivered`, and `real_delivery` stay false. The module does not import a mail, SMS, or HTTP client.
- Mock upload validates MIME and size, then runs the existing structural scan. A clean hold stays in process memory (cap 8) with an empty `public_url` and no byte column. Rejected bytes are not stored. The response sets `media_uploads_enabled` false and `bytes_released` false. Wipe clears that memory. Playback stays unavailable.
- Journey audit rows live in `nova_casting_journey_audit` (`invite.issued`, `invite.redeemed`, `invite.expired`, `mock.dispatched`, `upload.mock_recorded`). The older pilot audit check is unchanged.
- Migration `20261015_casting_journey` revises `20261014_casting_pilot`. Production names and missing parent tables return without DDL. Downgrade drops only `nova_casting_invites`, `nova_casting_mock_attempts`, `nova_casting_mock_media`, and `nova_casting_journey_audit`.

## Tests run on 2026-10-15

Local disposable Postgres 16, same URL the workflow uses (`postgresql+psycopg2://casting_test:casting_test@127.0.0.1:5432/casting_test`):

| Set | Result |
| --- | --- |
| `preview-regressions` file list, including `test_nova_casting_journey.py` | `101 passed` in 1.99s |
| `casting-postgres-gated` file list | `25 passed` in 1.15s, and the output does not contain `skipped` |
| `casting-db-integration` file list, from `backend/` | `32 passed` in 4.75s |
| Authenticated browser journey, desktop 1280x900 and iPhone 390x844 | `1 passed` in 11.03s |

The browser run signs in through a disposable login override, reloads the invitation from the server, redeems it, saves an https link and a `CA-` receipt, shortlists, approves a draft, runs mock transport with `Real delivery: false`, exports a CSV with no https link, and rejects an expired invitation. The iPhone viewport reloads the server copy and rejects the expired invitation. Screenshots from that run are `desktop-reloaded.png`, `desktop-receipt.png`, `desktop-call-sheet.png`, `desktop-expired.png`, `iphone-reloaded.png`, and `iphone-expired.png` under `/opt/cursor/artifacts/casting-journey/`. `smtplib` is patched to raise. This is not a deployed preview.

GitHub Actions counts for this continuation are recorded on the draft pull request after the push. Do not treat the local counts above as the GitHub run.

## Rollback

Turn `NOVA_CASTING_STAGING_READS` off. Routes return 503. On a disposable database, downgrade revision `20261015_casting_journey` drops only the four journey tables. Downgrade of `20261014_casting_pilot` then drops only the earlier pilot tables. Do not downgrade either revision on a shared database. Production upgrade stamps the revision and does not create tables.

## Blockers

- No issue comment was posted. The token cannot write to GitHub issues.
- No staging host is approved. The Netlify preview is the static site for the previous commit, not an approved Casting API. Local Postgres was used only for the gated tests above.
- GitHub Actions on commit `5a315388` already reported `casting-postgres-gated` at 18 passed. This continuation adds the journey file to that job. Counts for the new commit are filled in on the draft pull request after the push.
- Public applicant intake, real outbound messages, and a paid SMS or WhatsApp provider still need a separate owner decision.
- Antivirus remains structural-only unless ClamAV is installed on a disposable host. The mock upload gate uses that same structural scan. A clean result still does not release bytes or a public URL.
- Platform accounts are still required. Casting does not register users.
- Cloudflare Pages failed on commit `1fd90997` for project `amicor-public`. The check summary was "Build failed". The build log is only on the Cloudflare dashboard. This lane does not own the public site, so that build was not changed.
- Creative Studio video rendering was not modified. This pilot does not generate audition media.
