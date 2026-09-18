# Lifesaver AI Care Cloud V1 — Staging Readiness

Prepared on the isolated branch after Phase 1 + Phase 2 local verification.
Phase 3A staging review updated this file for accuracy only.
This file does not authorize push, merge, Render changes, or production migration.

## 1. Current branch

`feature/lifesaver-ai-care-cloud-v1`

Local commits reviewed in Phase 3A:

- `8698c0054fedce4c03f1eefa115c3d76cf8136a5` — `feat(lifesaver): complete AI Care Cloud V1 phases 1 and 2`
- `de3df8f22a1538668d603f2b0c321c1842a1f720` — `chore(lifesaver): prepare staging migration and smoke checks`

Worktree: isolated Lifesaver checkout. Do not merge into production until Saye / Mrs. Nova approval.

Related review files:

- `docs/lifesaver/LIFESAVER_V1_STAGING_ENV_TEMPLATE.md`
- `docs/lifesaver/LIFESAVER_V1_STAGING_ROLLBACK.md`

## 2. Current V1 scope

Software-first care coordination for a member and an invited Care Circle.

In scope:

- Profile, consent, accessibility
- Today / Care surfaces (appointments, reminders, medications, wellness, journal, readings)
- Care Coordination with deterministic HIGH / MEDIUM / LOW cards
- Transportation coordination (simulated handoff only)
- Local notification outbox (simulated delivery only)
- Simulated device ingestion foundation
- Care Circle permissions and caregiver handoffs
- Administrative AI with clinical refusal
- SOS demonstration (no emergency-services call)

Out of scope for this V1 package: diagnosis, treatment, dosing, live dispatch, real email/SMS, real medical devices, 911, payments, Nova feature work, Delivery, Freight, Driver 001, Health ISF ride lifecycle.

## 3. Local URL

http://127.0.0.1:8031/lifesaver

Do not use the older 8030 process. It may be a pre-Phase 2 server.

## 4. Local DB

`backend/data/lifesaver_phase2_verify.db` (SQLite, local-only)

This file is gitignored. It is not a staging or production database.

## 5. Features completed

Phase 1:

- Tenant-scoped Lifesaver profiles and explicit consents (default denied)
- Today, Care, Circle, Privacy UI
- Appointments, reminders, medications, wellness, journal, user-entered readings
- Care Circle invite with least-privilege defaults
- Permission editor and caregiver handoffs
- Audit trail without journal bodies or reading values
- SOS demonstration with human confirmation

Phase 2:

- Care Coordination board and filters
- Transportation request / confirm / simulated handoff / cancel
- Notification queue / simulate-fail / retry / suppress / simulate-delivery
- Simulated device reading ingest; reserved external source blocked
- Lifesaver-owned AI adapter (no Nova Core import or writes)
- AI coordination summaries use the same live HIGH/MEDIUM/LOW/review counts as Coord

## 6. API routes completed

Prefix: `/api/lifesaver`

Public:

- `GET /health`

Authenticated:

- `GET|PATCH /me`
- `GET /today`
- `GET|POST /consents`
- `PUT /accessibility`
- `GET|POST /medications`, `DELETE /medications/{id}`
- `GET /reminders`, `POST /reminders/{id}/acknowledge`
- `GET|POST /appointments`
- `GET|POST /wellness`
- `GET|POST /journal`
- `GET|POST /readings`
- `POST /readings/simulated-device`
- `GET|POST /transport`
- `GET /sos`, `POST /sos/start`, `POST /sos/{id}/confirm`, `POST /sos/{id}/acknowledge`
- `GET /circle`, `GET /circle/caring-for`, `POST /circle/invite`
- `PATCH /circle/{id}/permissions`, `POST /circle/{id}/revoke`
- `GET /alerts`, `POST /alerts/{id}/acknowledge`
- `GET|POST /tasks`, `POST /tasks/{id}/complete`
- `GET|POST /handoffs`, `POST /handoffs/{id}/accept`, `POST /handoffs/{id}/decline`
- `GET /coordination`
- `POST /ai/converse`, `POST /ai/orchestrate`
- `GET|POST /transport/requests`
- `POST /transport/requests/{id}/confirm|handoff-simulated|cancel`
- `GET|POST /notifications`
- `POST /notifications/{id}/simulate-deliver|simulate-fail|suppress|retry`
- `GET /audit`

UI page:

- `GET /lifesaver` and `GET /lifesaver/{path}` serve `backend/static/lifesaver/index.html`

## 7. UI surfaces completed

- Login (localhost-only seed email hint; password never displayed or hardcoded)
- Today
- Care (appointments, medications, reminders, wellness, journal, readings, simulated device)
- Coord (priority cards, transportation coordination)
- Notify (local outbox)
- Circle (invite, permissions, alerts, tasks, handoffs)
- Privacy / More (consents, accessibility, AI conversation, audit)
- Bottom nav: Today, Care, Coord, Notify, Circle, More

## 8. Security model

- Existing platform JWT via `get_current_user_context`
- Tenant key: organization id, else organization name, else personal scope
- Profile ownership: one Lifesaver profile per org + user
- IDOR: member data is filtered by organization_id + profile_id; caregivers need an active circle link
- Least privilege: same-org users without a circle cannot read member health data
- Audit records action / resource / outcome only; blocked keys include body, reading values, password, token, secret, email, phone

## 9. Consent model

Consents start **false**. Features require the matching consent plus `care_cloud_use` where applicable.

Consent types:

- `care_cloud_use`
- `caregiver_sharing`
- `health_readings`
- `reminders`
- `wellness_checkins`
- `journal`
- `transport_status`
- `ai_conversation`
- `sos_demonstration`
- `audit_retention`
- `caregiver_notifications`
- `simulated_device_ingest`

Revocation immediately blocks later reads/writes for that feature.

## 10. Care Circle permissions

Invite defaults:

- `view_today`
- `receive_alerts`
- `acknowledge_alerts`

Never auto-grant `view_readings`. Extra permissions require an explicit save. Revoke removes future access.

## 11. Transportation simulation behavior

Statuses: `requested` → confirm → `ready_for_handoff` → `handed_off_simulated` or `cancelled`.

This path:

- does not create Health ISF rides
- does not call dispatch
- stores pickup/destination labels only
- has no FK to Health ISF

## 12. Notification simulation behavior

Local fake provider only. Statuses include `queued_local`, `failed_simulated`, `delivered_simulated`, `suppressed`.

Retry is local re-queue. No Twilio, SES, SendGrid, SMTP, or SMS send.

## 13. Simulated device behavior

`POST /readings/simulated-device` accepts labeled simulated readings.

`external_device_reserved` is rejected and does not ingest. No Apple Health, Fitbit, Bluetooth, or other external device call.

## 14. AI safety / refusal behavior

Lifesaver-owned adapter in `backend/app/modules/lifesaver/integrations/nova_adapter.py`.

- No `from app.core.nova`
- No Nova table writes
- Refuses diagnosis, treatment, dosing, and emergency determination
- Administrative / organizational answers only
- Coordination summaries use live Coord counts

## 15. Exact migration revision(s)

Prepared, **not applied** to staging or production:

1. `20260911_lifesaver_phase1_schema` — Phase 1 `lifesaver_*` tables
2. `20260911_lifesaver_phase2_schema` — transport requests, notification outbox, reading column additions

Two revisions exist because Phase 1 schema was never in Alembic history. Applying Phase 2 alone would be unsafe on a fresh staging database.

Local verify SQLite already has tables via `ensure_lifesaver_schema()`. Inspector guards make both upgrades no-ops if tables/columns already exist.

## 16. Required environment variables

Staging Lifesaver test (names only, no values):

- `DATABASE_URL` — staging Postgres URL, not production
- `JWT_SECRET` or `SECRET_KEY` — staging secret, not production
- `AMICOR_SEED_PASSWORD` — staging seed only, if seed users are enabled
- `AMICOR_RESTRICT_SEED_ACCOUNTS` — keep restricted unless a dedicated staging seed is approved
- `AMICOR_SKIP_WMI_PLATFORM_QUERY=1` on Windows local/staging jump hosts
- Smoke script: `LIFESAVER_SMOKE_BASE_URL`, `LIFESAVER_SMOKE_EMAIL`, `LIFESAVER_SMOKE_PASSWORD`

Runtime schema fallback remains `ensure_lifesaver_schema()` if migrations have not been applied yet.

## 17. Variables that must NOT use production values during staging test

- Production `DATABASE_URL`
- Production `JWT_SECRET` / `SECRET_KEY`
- Any `STRIPE_*` live key (`sk_live`, `rk_live`)
- Production Twilio / SES / SendGrid credentials
- Production Render hostname credentials for `amicor-health-isf`
- Production seed passwords used by live riders/drivers
- Any emergency-services or device-vendor API keys

## 18. Staging DB requirements

- Separate staging database
- Apply Lifesaver revisions only after explicit approval
- Additive only; no Health ISF ride table changes
- Confirm `lifesaver_*` tables exist after approved upgrade
- Do not point the local 8031 process at staging or production

## 19. Safe seed user strategy

- Use a dedicated staging test member, not a production rider
- Password from environment / secret store only
- Do not embed passwords in source, docs, or the smoke script
- Grant consents explicitly in the UI or a staging seed script after login
- Same-org caregiver accounts only if needed for Circle tests
- Never seed Driver 001 or production Health ISF rides

## 20. Staging smoke test steps

1. Confirm the target host is staging, not production.
2. Set smoke environment variables (no production password).
3. Run `python scripts/lifesaver_staging_smoke.py`.
4. Confirm `/lifesaver` loads and `/api/lifesaver/health` returns product identity.
5. Sign in with the staging test user only.
6. Confirm that user has granted the consents required by the authenticated GET routes (at least `care_cloud_use`, plus feature consents used by appointments / coordination / notifications / transport). Without those grants the smoke script correctly receives 403 and exits nonzero.
7. Hit appointments, coordination, notifications, and transport routes.
8. Confirm an AI diagnosis/treatment prompt is refused.
9. Confirm the script reports no external side-effect flags.
10. Optionally walk the UI checklist in a browser.
11. Stop. Do not promote to production from a green smoke run alone.

Local dry-run (public endpoints only):

```
LIFESAVER_SMOKE_BASE_URL=http://127.0.0.1:8031
LIFESAVER_SMOKE_DRY_RUN=1
python scripts/lifesaver_staging_smoke.py
```

## 21. Rollback plan

See `docs/lifesaver/LIFESAVER_V1_STAGING_ROLLBACK.md`.

Alembic `downgrade <rev>` means downgrade **to** that revision.

Staging DB only, after approval and backup:

1. Undo Phase 2: `alembic downgrade 20260911_lifesaver_phase1_schema`
2. Undo Phase 1: `alembic downgrade 20260909_nova_freight_settlement`

Do **not** run `alembic downgrade 20260911_lifesaver_phase2_schema` when already at Phase 2 head; that is a no-op.

Application: restore the previous staging image/build that does not serve Lifesaver, or revert only the Lifesaver router include and `/lifesaver` static route. Production is unaffected if staging DB and host stay isolated.

Local verify DB can be discarded; it is not production data.

## 22. Deployment order

1. Isolated code review of this branch
2. Staging environment variables (non-production)
3. Approved Alembic upgrade on staging only: Phase 1, then Phase 2
4. Deploy application build that includes Lifesaver routes
5. Seed or confirm the staging test user
6. Run `scripts/lifesaver_staging_smoke.py`
7. Manual UI smoke
8. Wait for Saye / Mrs. Nova before any production discussion

Do not start this sequence until staging review is approved.

## 23. What remains out of scope

- Real notification delivery
- Real ride dispatch or Health ISF write
- External medical device integrations
- Clinical decision support
- Payments / Stripe
- Nova V1/V2 feature work
- Delivery ops-shell changes
- Freight
- Driver 001 create/reset/replace
- Production Alembic apply
- Render hostname rename

## 24. Known pre-existing Health ISF issues

`backend/tests/test_health_isf_persistence.py` has documented pre-existing failures (including 401 and driver-assignment availability). Those failures are outside Lifesaver V1. Do not change Health ISF business logic to make this package look greener.

## 25. Isolation statement

Nova, Delivery, Freight, and Driver 001 remain isolated.

Lifesaver adds:

- `backend/app/modules/lifesaver/`
- `backend/static/lifesaver/`
- Lifesaver tests
- Additive `backend/app/main.py` router + static serve
- Additive Alembic include of `lifesaver_*` in `backend/migrations/env.py`

Lifesaver does not import Health ISF, Nova Core, Delivery, Stripe, Twilio, or SMTP. Transportation simulation does not create rides. Notification simulation does not send messages. Device ingest does not call external vendors.

## 26. Phase 3A go / no-go scorecard

| Area | Score | Note |
|---|---|---|
| A. Code readiness | GREEN | Phase 1+2 committed; AI counts match Coord |
| B. Test readiness | GREEN | 64 passed / 0 failed / 0 skipped in approved matrix |
| C. Migration readiness | GREEN | Two additive revisions reviewed; not applied |
| D. Auth readiness | GREEN | JWT + invalid login + logout verified locally |
| E. Security/privacy readiness | GREEN | Isolation, consent, redaction, no debug endpoint |
| F. Mobile readiness | GREEN | 390×844 local acceptance passed |
| G. Observability/logging readiness | YELLOW | Action/outcome audit only; no Lifesaver metrics board |
| H. Rollback readiness | GREEN | Plan and corrected Alembic downgrade order documented |
| I. Isolation readiness | GREEN | Frozen products untouched in Lifesaver commits |
| J. Known issues | YELLOW | Pre-existing Health ISF persistence failures; no staging host yet |

**Final Phase 3A status: READY FOR STAGING WITH CONDITIONS**

Conditions before any later staging deployment approval:

1. Dedicated staging database and secrets (never production).
2. Do not deploy onto production Render `amicor-health-isf`.
3. Backup staging DB, then apply Phase 1, then Phase 2.
4. Dedicated staging test user with explicit consents before authenticated smoke.
5. Keep real email/SMS/Stripe live/device/emergency keys unset.
6. Commit the Phase 3A review docs in a later isolated local commit if Saye / Mrs. Nova want them in the package.
