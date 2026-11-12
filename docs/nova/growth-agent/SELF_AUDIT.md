# Self-audit matrix — Nova Growth Agent (Issue #485)

Legend: **IMPLEMENTED** / **TESTED SYNTHETICALLY** / **VERIFIED STAGING** / **VERIFIED LIVE** / **BLOCKED**

Verification pass date: **2026-11-12** (America/Chicago). Branch tip after this pass supersedes `a7cebd48`.

| Capability | Status | Evidence |
|------------|--------|----------|
| Tenant-scoped schema (`nova_ga_*`) | IMPLEMENTED | `models.py`, migration `20261112_nova_growth_agent` (prod DDL gated) |
| Deny-by-default org auth | IMPLEMENTED + TESTED SYNTHETICALLY | `tenant.py` now returns `UserContext`; isolation + HTTP auth tests |
| Hashed contact identities | IMPLEMENTED + TESTED SYNTHETICALLY | `_hash_identity` digests in `service.py`; export hints redacted |
| Setup wizard + activate checklist | IMPLEMENTED + TESTED SYNTHETICALLY | profile API + HTTP journey activate; owner UI |
| Inbox AI/human + handoff + pause | IMPLEMENTED + TESTED SYNTHETICALLY | service + demo + UI |
| CRM states/search/notes | IMPLEMENTED + TESTED SYNTHETICALLY | leads PATCH + owner UI Save + demo CRM edit |
| Analytics with denominators | IMPLEMENTED + TESTED SYNTHETICALLY | `analytics()` counts `confirmed`+`rescheduled`; demo evidence |
| Embeddable widget + signed token | IMPLEMENTED + TESTED SYNTHETICALLY | origin required (fail-closed); activation required; `X-Amicor-Growth-Origin` |
| Appointment cancel → rebook + reschedule | IMPLEMENTED + TESTED SYNTHETICALLY | service + owner UI + synthetic demo |
| FAQ grounding / I-don't-know | IMPLEMENTED + TESTED SYNTHETICALLY | `faq_engine` tests |
| Consent + channel opt-out | IMPLEMENTED + TESTED SYNTHETICALLY | email marketing opt-out without blanket DNC; STOP still DNC |
| Workflow dry-run mock delivery | IMPLEMENTED + TESTED SYNTHETICALLY | workflows + demo |
| Restart recovery (queued deliveries) | IMPLEMENTED + TESTED SYNTHETICALLY | `recover_pending_deliveries` + `POST /workflows/recover` + demo |
| Appointment anti-double-book | IMPLEMENTED + TESTED SYNTHETICALLY | multi-session concurrency test + unique slot |
| Durable widget rate limit | IMPLEMENTED + TESTED SYNTHETICALLY | visitor-message count + process burst brake |
| Owner export (consent/appts/messages) | IMPLEMENTED + TESTED SYNTHETICALLY | `export_org` expanded; demo `export_includes` |
| Calendar Google/Microsoft | IMPLEMENTED (mock adapter) / BLOCKED live | `MockCalendarAdapter`, `REAL_CALENDAR_WRITE=False` |
| AI provider live | IMPLEMENTED (mock FAQ AI) / BLOCKED live | `MockAIAdapter` |
| Email/SMS live | IMPLEMENTED (mock) / BLOCKED live | hard-off flags |
| Stripe subscriptions | IMPLEMENTED (catalog only) / BLOCKED live | `commercial.py` `launched=False` |
| Background worker continuous drain | BLOCKED | Manual recover path only; `BACKGROUND_WORKER_ENABLED=False` |
| Retention purge job | BLOCKED | Policy documented; no auto-purge runner |
| Voice receptionist stretch | BLOCKED | Out of MVP; flag `REAL_VOICE=False` |
| Staging verification | BLOCKED | No staging deploy in this handoff |
| Live/production verification | BLOCKED | Explicitly not authorized |
| Ops Agent #475/#477 untouched | IMPLEMENTED (isolation) | Change map; casting/work-revenue regressions green locally |
| Creative Studio #478 untouched | IMPLEMENTED (isolation) | Change map |

## Exact local verification results (this pass)

```text
Growth Agent suite: 35 passed
  tests/test_nova_growth_agent_unit.py
  tests/test_nova_growth_agent_integration.py
  tests/test_nova_growth_agent_security.py
  tests/test_nova_growth_agent_http.py

Focused regressions (non-Growth): 69 passed
  tests/test_nova_casting_flags.py
  tests/test_nova_casting_preview.py
  tests/test_nova_work_revenue_labeling.py
  tests/test_nova_qualification_claim_scope.py
```

Sanitized synthetic journey evidence: `docs/nova/growth-agent/DEMO_EVIDENCE.json` (also `/opt/cursor/artifacts/growth_agent_synthetic_demo_evidence.json` in the verification environment).

Demonstrated behaviors in evidence: setup+activate, grounded FAQ chat, consent lead capture, duplicate contact reuse, CRM edit, booking + idempotent replay, cancel→rebook, reschedule, mock reminder, restart reclaim of queued delivery, human handoff, channel marketing opt-out suppression, double-book block, analytics denominators, export completeness, all live messaging flags false.

## Remaining blockers (owner gates)

1. No merge / deploy / migration apply / Render hostname changes without explicit owner approval.
2. Live email/SMS/calendar/AI/Stripe remain hard-off pending legal/compliance and paid-provider review.
3. Continuous background delivery worker not enabled (recover endpoint is the reclaim path).
4. Automated retention purge not implemented (policy + export only).
5. Staging and live verification not performed.
6. Multi-worker rate limiting still relies on DB message counts (good) plus an in-process burst brake (not cross-process).

**Do not label this draft functionality live.**
