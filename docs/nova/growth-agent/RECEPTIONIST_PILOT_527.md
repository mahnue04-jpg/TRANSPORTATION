# Nova AI Receptionist pilot (#527)

Draft implementation on branch `cursor/nova-receptionist-pilot-527-c9ac`.

## Base

| Item | Value |
|------|-------|
| Base branch tip | PR #526 `db484ac6ef52a5937131937e9bb86b7adbbe964e` (`feat/nova-calendar-boundary-20261116`) |
| Growth Agent MVP | PR #490 `e4d0aec2` |
| Related drafts (not merged) | #517, #519, #521 (UI/campaign/KV — not required for this vertical slice) |

## Implemented (code complete; live transports off)

1. **Google Calendar OAuth** — owner-authorized start/callback/disconnect, PKCE, single-use session-bound state, approved redirect, Fernet-encrypted refresh/access tokens server-side. Missing config → **Not connected**.
2. **Durable calendar sync outbox** — create/reschedule/cancel with stable event IDs (from #526 planner), operation versions, leases, backoff, timeout-after-create recovery, stale-version suppression, cancel/rebook safety. Availability helpers honor America/Chicago DST + buffers. Internal booking ≠ external confirmation.
3. **Owner notifications** — transactional-only durable queue with idempotency; statuses `queued` / `provider_accepted` / `failed` (not inbox proof). Marketing purpose rejected.
4. **Handoff queue** — open → acknowledged → resolved for human escalation.
5. **Twilio inbound voice boundary** — chosen because Health ISF already uses Twilio SMS. Webhook HMAC signature, replay/dedupe ledger, server-side number→tenant mapping, session appointment authorization, kill switch + daily limits. Labeled **SIMULATED** helper only.
6. **Owner receptionist UI** — calendar status, sync errors, notifications, handoffs, simulated voice controls; sign-out clears state.

## Additive migration

`backend/migrations/versions/20261116_nova_ga_receptionist_pilot.py`  
Revises `20261112_nova_ga_retention`. Production-locked envs skip DDL. **Do not run against existing production DBs without separate owner approval.**

### Rollback

Downgrade drops only the new `nova_ga_*` receptionist tables listed in that revision. No Delivery / Creative Studio / Health ISF tables are touched.

## Configuration (local / disposable only)

```bash
export NOVA_GROWTH_AGENT_ENABLED=true
export NOVA_GROWTH_AGENT_DEMO_MODE=true
export NOVA_GROWTH_AGENT_WIDGET_ENABLED=true
export NOVA_GROWTH_AGENT_CALENDAR_SYNC_WORKER=true   # mock/injected transport
export NOVA_GROWTH_AGENT_OWNER_NOTIFY_WORKER=true    # mock email
export NOVA_GROWTH_AGENT_VOICE_SIMULATOR=true        # labeled simulator
export NOVA_GA_CREDENTIAL_ENCRYPTION_KEY=...        # Fernet key or high-entropy secret
# Optional for OAuth start URL generation (still no live Google grant in this draft):
export NOVA_GA_GOOGLE_OAUTH_CLIENT_ID=...
export NOVA_GA_GOOGLE_OAUTH_CLIENT_SECRET=...
export NOVA_GA_GOOGLE_OAUTH_REDIRECT_URI=https://<host>/api/nova/growth-agent/calendar/oauth/callback
```

Hard-off remains: `REAL_CALENDAR_WRITE`, `REAL_EMAIL_SEND`, `REAL_VOICE`, `REAL_SMS_SEND` are always `False` in code.

## Test commands (disposable)

```bash
cd backend
python -m pytest -q \
  tests/test_nova_growth_agent_calendar_requests.py \
  tests/test_nova_growth_agent_calendar_oauth.py \
  tests/test_nova_growth_agent_calendar_sync.py \
  tests/test_nova_growth_agent_notifications_handoff.py \
  tests/test_nova_growth_agent_voice.py \
  tests/test_nova_growth_agent_receptionist_http.py \
  tests/test_nova_growth_agent_unit.py \
  tests/test_nova_growth_agent_integration.py \
  tests/test_nova_growth_agent_security.py \
  tests/test_nova_growth_agent_http.py \
  tests/test_nova_growth_agent_worker_retention.py

node --test static/nova-growth/receptionist.test.cjs
```

## Honesty matrix

| Capability | Status |
|------------|--------|
| OAuth code path + encrypted storage | **Implemented** (injected exchange in tests) |
| Live Google OAuth grant / real calendar write | **Not live-verified** — hard-off |
| Sync outbox + conflict/restart recovery | **Implemented** with fake transport |
| Owner notifications delivery to inbox | **Simulated** (`provider_accepted` ≠ receipt) |
| Twilio webhook auth + session gates | **Implemented** (HMAC + dedupe); live calls **off** |
| Voice simulator | **Simulated only** — not proof of live phone |
| Browser DOM panel | **Implemented**; Chromium E2E against this tip pending CI |

## Remaining owner blockers

1. Provide real Google OAuth client + redirect + encryption key in a non-production env and approve a **test calendar** acceptance pass.
2. Separate approval before any migration on a shared/staging DB (never production without review).
3. Twilio number mapping + auth token for non-simulator webhook tests (still no paid calling).
4. Do not merge/deploy until owner review; keep `nova-growth-validation-490` pin unchanged.
