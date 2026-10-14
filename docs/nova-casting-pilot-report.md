# Casting pilot report — issue #332

Session `bc-8ffc6cff-a547-5d66-89a1-cd5d9350e1ae`. Branch `cursor/casting-auditions-pilot-e1ae`. This agent is not working on Work & Revenue #336, Synapse #311, website #329, or unrelated Creative Studio changes.

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
- Fictional Harborlight sample on the sandbox route, and a browser-only 30-day demo at `/static/nova-creative/casting-pilot-demo.html`.

## Sample month

Harborlight is fictional. Day 1 opens three unpublished roles. Day 7 rejects a 17-year-old and a duplicate email, then accepts two adult drafts. Day 10 to 14 a person shortlists and approves a callback draft that is not delivered. Day 18 shows a call sheet in `America/New_York`. Day 21 revocation clears contact data and suppresses the reminder. Day 30 exports a minimized CSV. The sample offer is $2,400 USD for 30 days, marked as a sample and not a contract. No Zeus, Netflix, studio, or prior-customer relationship is claimed.

## Tests run here

Casting preview set, including the new pilot tests, on 2026-10-14:

`82 passed, 8 skipped`

The 8 skips are existing tests that wait for `CASTING_TEST_POSTGRES_URL`. Postgres was not running in this session, so the older sandbox HTTP and private-media tests were not re-executed here. They remain in `.github/workflows/nova-casting-preview.yml`.

SQLite store round trip:

`1 passed` in `backend/tests/test_nova_casting_pilot_store.py`

That test saved a role and an intake, reloaded the role, stored a confirmation with `delivery_state = not_sent`, rejected SMS, and denied a different tenant.

Migration test: production environment creates no pilot tables; a disposable SQLite database creates them only after the parent tables exist; a `sent` delivery value is rejected; downgrade drops the pilot tables and leaves `platform_users`.

Browser check of the demo page, desktop 1280x900 and mobile 390x844: Play finished with "no message was sent". Age 16 returned "Applicant does not meet the minimum age". Missing consent and a `javascript:` link were rejected. A valid sample saved receipt `CA-JORDAN0001` in the tab only. Revocation cleared the sample contact. The only network requests were the page, CSS, and the logo. No API call and no outbound message.

## Rollback

Turn `NOVA_CASTING_STAGING_READS` off. Routes return 503. On a disposable database, downgrade revision `20261014_casting_pilot` drops only the pilot tables. Do not downgrade it on a shared database. Production upgrade stamps the revision and does not create tables.

## Blockers

- No issue comment was posted. The token cannot write to GitHub issues.
- No staging host, Nova login, or disposable Postgres was available here, so there is no deployed preview URL.
- Public applicant intake, real outbound messages, and a paid SMS or WhatsApp provider still need a separate owner decision.
- Antivirus remains structural-only unless ClamAV is installed on a disposable host. This pilot does not add a scanner.
- Platform accounts are still required. Casting does not register users.
