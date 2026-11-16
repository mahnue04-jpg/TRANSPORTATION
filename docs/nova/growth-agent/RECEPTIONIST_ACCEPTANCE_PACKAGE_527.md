# Acceptance package — Nova AI Receptionist pilot (#527)

**Draft PR:** https://github.com/mahnue04-jpg/TRANSPORTATION/pull/528  
**Issue:** https://github.com/mahnue04-jpg/TRANSPORTATION/issues/527  

## Tested commit

`65295ccf11240531d5dfe094ab7f0f16f6b107b5`

## What this package asks of the owner

Only **account authorization** and **release decisions**. Implementation and disposable verification are done in code.

1. Authorize a **dedicated test** Google Calendar (not production).  
2. Approve any temporary live-transport change-control (calendar write / one email / signed Twilio check).  
3. Run `RECEPTIONIST_REAL_ACCOUNT_ACCEPTANCE.md` and record pass/fail on #527.  
4. Decide whether to keep draft, merge after #526, or schedule staging.

Do **not** paste secrets into chat, screenshots, or issue comments.

## Completed in code (this pass)

| Area | Done |
|------|------|
| OAuth browser return + encrypted credentials + select calendar | Yes (live grant unverified) |
| Gated credential provider for sync transport | Yes (injected/hard-off) |
| External busy + book/reschedule/cancel/rebook paths | Yes (fake busy / mock sync) |
| Disposable Postgres Alembic rehearsal for all receptionist tables | Yes (skip-gated; CI postgres job) |
| Owner notification adapter + retries; provider_accepted ≠ receipt | Yes |
| Twilio signature + public URL behind proxies; unsigned sim blocked on public webhook | Yes |
| Owner readiness view (no secrets) | Yes |
| Real-account runbook | Yes |
| Chromium evidence in-repo | `docs/nova/growth-agent/screenshots/` |

## Assessment

| Claim | Status |
|-------|--------|
| Ready for **owner authorization** of a one-business pilot | **YES** (code + disposable tests) |
| Ready to claim **live pilot passed** | **NO** — awaiting authorized Google/Twilio/inbox evidence |

## Remaining real-account steps

See `RECEPTIONIST_REAL_ACCOUNT_ACCEPTANCE.md` checklist A–E.
