# Receptionist integration correction pass (#527)

**Branch:** `cursor/nova-receptionist-pilot-527-c9ac`  
**Base:** `feat/nova-calendar-boundary-20261116` (PR #526)  
**Date:** 2026-11-16 (America/Chicago)

## Priority 1 — fixed

| Gap | Fix |
|-----|-----|
| Browser OAuth completion | `GET .../calendar/oauth/callback` → **302** to `/nova/growth?calendar_oauth=1&state&code` (or `oauth_error`). SPA POSTs authenticated completion; strips query. No tokens in body. |
| Calendar status contract | Explicit `connected: true/false` on status + connect/disconnect. Covered: connected, disconnected, needs_reconnect (expired), revoked. |
| Voice simulator UI/API | Accepts `called_number`/`caller_number`/`intent`/`utterance`/`simulated` (and `script`). Maps intent → event; wires `ServiceBackedGrowthVoiceOps`. |
| Owner authorization | `require_growth_owner` = `ROLE_ADMIN` + `ROLE_SUPER_ADMIN_SUPPORT` same-tenant only. Support = same-tenant admin support. |
| External busy filtering | Wired into `list_availability` + `book_appointment` with states `disconnected` / `provider_unavailable` / `available`; conflict → `EXTERNAL_BUSY_CONFLICT`. |
| Stale UI after sign-out | `sessionGeneration` guards on refresh/actions; `clearState` on sign-out / token change. |

## Priority 2 — wired

- Simulator → real FAQ / lead / availability / book / reschedule / cancel / notify / handoff via injected/hard-off providers.
- Appointment change authz requires tenant appointment row + session authorized list or contact ownership (caller match alone insufficient).
- Public Twilio webhook keeps RejectOps / signature / dedupe; simulator shortcuts owner-only.

## Tests (disposable)

| Suite | Result |
|-------|--------|
| Growth Agent pytest (listed CI + owner_gate + busy_availability) | **121 passed, 1 skipped, 24 subtests** |
| `node --test static/nova-growth/receptionist.test.cjs` | **7 passed** |
| Alembic `upgrade heads` on disposable SQLite | **OK** — receptionist tables present without ORM create-all |
| Chromium Playwright acceptance | **OK** — login, activate, voice button POST 200, OAuth GET 302, sign-out clears |

### Browser evidence

- `/opt/cursor/artifacts/receptionist_after_login.png`
- `/opt/cursor/artifacts/receptionist_voice_simulator.png`
- `/opt/cursor/artifacts/receptionist_chromium_evidence.json`

## Honesty / readiness matrix

| Capability | Status |
|------------|--------|
| OAuth redirect + authenticated POST complete | **Implemented** (injected exchange in tests; no real Google grant) |
| `connected` status contract | **Implemented** |
| Voice UI button ↔ API | **Implemented** (Chromium verified; SIMULATED) |
| Owner gate roles | **Implemented** |
| External busy in avail/book | **Implemented** with fake busy provider; live freebusy hard-off → `provider_unavailable` |
| Appointment ownership authz | **Implemented** |
| Live Google OAuth / calendar write | **Not live-verified** — hard-off |
| Live Twilio / inbox receipt | **Not live-verified** — hard-off |
| Production DB migration | **Not run** (boundary) |

## Still needs real-account acceptance

1. Real Google OAuth grant + calendar selection against approved redirect.
2. Live freebusy → `available` state and conflict recovery under production clocks.
3. Live Twilio signed webhook + mapped number → tenant.
4. Owner notification delivery into a real inbox (provider_accepted ≠ receipt today).
5. End-to-end cancel/rebook with real Google event IDs.

## Boundaries observed

No merge, deploy, production migration, real OAuth grant, real calendar write, real messages/calls, or spend increase.
