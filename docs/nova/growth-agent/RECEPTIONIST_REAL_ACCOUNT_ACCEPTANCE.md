# Real-account acceptance runbook — Nova receptionist pilot (#527)

**Audience:** AMICOR owner only.  
**Purpose:** Authorize one dedicated test calendar and one signed Twilio check.  
**This document never asks for secret values in chat, screenshots, or issue comments.**

## Current status (code)

Pilot code can complete OAuth (injected tests), select a calendar, sync via durable outbox, notify via mock email, and validate Twilio signatures. **Live Google writes, live email, and live voice remain hard-off** until the owner explicitly changes hard-off flags in a separate controlled release (not this draft).

| Gate | Owner decision required |
|------|-------------------------|
| Authorize Google test calendar | Yes |
| Temporarily allow live calendar/email/voice for acceptance | Separate release approval (not implied by this PR) |
| Spend / Twilio trial charges | Yes — see costs |

## Exact credentials & permissions (names only — do not paste values)

| Item | Where to set (env / console) | Scope |
|------|------------------------------|--------|
| `NOVA_GA_GOOGLE_OAUTH_CLIENT_ID` | Staging secrets | Google Cloud OAuth client |
| `NOVA_GA_GOOGLE_OAUTH_CLIENT_SECRET` | Staging secrets | Same client |
| `NOVA_GA_GOOGLE_OAUTH_REDIRECT_URI` | Must match Google console + app | Exact callback URL |
| `NOVA_GA_CREDENTIAL_ENCRYPTION_KEY` | Staging secrets (Fernet) | Encrypts refresh/access at rest |
| Google OAuth scopes | Calendar events + readonly | Least privilege for booking |
| Dedicated **test** Google Calendar | Owner Google account | Not production business calendar |
| Owner inbox for transactional mail | Business owner mailbox | Receipt check only |
| `TWILIO_AUTH_TOKEN` | Staging secrets | Signature validation |
| `AMICOR_PUBLIC_URL` | Staging public HTTPS origin | Signature URL + webhook |
| Twilio number → `nova_ga_voice_agent_mappings` | DB row / owner tooling | Trusted mapping only |

**Approvals required (separate checkboxes):**

1. [ ] Use dedicated **test** Google calendar (not the production clinic calendar).  
2. [ ] Temporarily enable live calendar write path for acceptance only (hard-off change — separate change control).  
3. [ ] Temporarily enable live transactional email for one owner message (hard-off change).  
4. [ ] Temporarily enable signed Twilio webhook against staging public URL (hard-off / network allowlist).  
5. [ ] Accept Twilio trial / message / voice minute costs (estimate below).  
6. [ ] Disconnect and restore hard-off after the run.

## Expected costs (order-of-magnitude)

| Activity | Approx. cost |
|----------|----------------|
| Google OAuth + Calendar API (test event create/patch/delete) | Usually $0 on Google free tier for light use |
| One transactional email | $0 with mock; provider fee if live SMTP/API enabled |
| One signed Twilio webhook validation | $0 |
| Optional short Twilio test call / SMS | Twilio trial rates (often cents; confirm in Twilio console) |

No purchases or plan upgrades are required for the checklist below if live transports stay off (steps marked *blocked until approval*).

## Checklist

### A. Calendar authorization

1. Confirm staging has OAuth env vars set (names above) — **do not paste values**.  
2. Sign in as Growth owner (`ROLE_ADMIN`) on `/nova/growth`.  
3. Open **Receptionist readiness** — expect OAuth configured or Not connected.  
4. Click **Connect Google Calendar** → complete Google consent for the **test** calendar account.  
5. Confirm redirect lands on `/nova/growth?calendar_oauth=1&state&code` and panel shows `connected: true`.  
6. Select the dedicated test calendar via **Select calendar** (or API `POST /calendar/select`).  
7. Confirm readiness shows selected calendar id/summary and credential health `healthy` (no tokens visible).

### B. Availability + one test appointment (*live writes need approval*)

1. With connection healthy, load availability for a weekday (`America/Chicago`).  
2. Create **one** test appointment for a synthetic contact.  
3. Confirm internal booking `confirmed` and sync job `pending`/`confirmed` (or `suppressed` if live still off).  
4. Reschedule **that same** appointment (same event id path).  
5. Cancel, then rebook the same slot.  
6. Confirm sync outbox versions, stale suppression, and timeout-after-create recovery in sync errors panel.

### C. Owner notification (*live inbox needs approval*)

1. After booking, run notification tick (owner API or worker).  
2. With mock adapter: status `provider_accepted` — **not** inbox proof.  
3. With approved live adapter: confirm **one** message in the owner inbox, then disable live send.

### D. Twilio signed request (*live voice stays off*)

1. Ensure `AMICOR_PUBLIC_URL` matches the public HTTPS URL Twilio calls.  
2. Ensure number→tenant mapping exists for the org.  
3. Send a **signed** validation request (Twilio console or signed test tool) to `/api/nova/growth-agent/voice/twilio/webhook`.  
4. Confirm signature acceptance / reject for forged signatures.  
5. Confirm unsigned `simulated=true` on the public webhook is rejected.  
6. Do **not** place customer calls.

### E. Disconnect & restore

1. Disconnect Google Calendar from the panel.  
2. Confirm readiness shows Not connected and credentials cleared.  
3. Restore hard-off flags / kill switches / staging secrets rotation as needed.  
4. Record results on issue #527 (pass/fail per step — no secrets).

## Ready / not-ready rule

- **Code-ready for owner authorization:** OAuth/select/sync/notify/voice boundaries implemented; disposable tests green.  
- **Not live-pilot-ready:** until checklist A–E succeed with authorized accounts and any temporary live flags are restored to hard-off.

## Boundaries

No merge, production migration, or spend increase without the approvals above. Preserve Creative Studio data and pinned `nova-growth-validation-490` settings.
