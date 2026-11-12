# Self-audit matrix — Nova Growth Agent (Issue #485)

Legend: **IMPLEMENTED** / **TESTED SYNTHETICALLY** / **VERIFIED STAGING** / **VERIFIED LIVE** / **BLOCKED**

| Capability | Status | Evidence |
|------------|--------|----------|
| Tenant-scoped schema (`nova_ga_*`) | IMPLEMENTED | `models.py`, migration `20261112_nova_growth_agent` (prod DDL gated) |
| Deny-by-default org auth | IMPLEMENTED + TESTED SYNTHETICALLY | `tenant.py`, integration isolation tests |
| Setup wizard + activate checklist | IMPLEMENTED | `/api/nova/growth-agent/profile`, owner UI |
| Inbox AI/human + handoff + pause | IMPLEMENTED + TESTED SYNTHETICALLY | service + demo + UI |
| CRM states/search | IMPLEMENTED + TESTED SYNTHETICALLY | leads API + owner UI PATCH + tests |
| Analytics with denominators | IMPLEMENTED + TESTED SYNTHETICALLY | `analytics()` + unit/integration |
| Embeddable widget + signed token | IMPLEMENTED + TESTED SYNTHETICALLY | `widget.js`, crypto + security tests; public chat gated by `NOVA_GROWTH_AGENT_WIDGET_ENABLED` |
| Appointment cancel → rebook + reschedule | IMPLEMENTED + TESTED SYNTHETICALLY | `book_appointment` slot reuse, `reschedule_appointment`, integration tests |
| FAQ grounding / I-don't-know | IMPLEMENTED + TESTED SYNTHETICALLY | `faq_engine` tests |
| Consent + STOP suppression | IMPLEMENTED + TESTED SYNTHETICALLY | consent/workflow tests |
| Workflow dry-run mock delivery | IMPLEMENTED + TESTED SYNTHETICALLY | workflows + demo |
| Appointment anti-double-book | IMPLEMENTED + TESTED SYNTHETICALLY | booking concurrency test |
| Calendar Google/Microsoft | IMPLEMENTED (mock adapter) / BLOCKED live | `MockCalendarAdapter`, `REAL_CALENDAR_WRITE=False` |
| AI provider live | IMPLEMENTED (mock FAQ AI) / BLOCKED live | `MockAIAdapter` |
| Email/SMS live | IMPLEMENTED (mock) / BLOCKED live | hard-off flags |
| Stripe subscriptions | IMPLEMENTED (catalog only) / BLOCKED live | `commercial.py` `launched=False` |
| Voice receptionist stretch | BLOCKED | Out of MVP; flag `REAL_VOICE=False` |
| Staging verification | BLOCKED | No staging deploy in this handoff |
| Live/production verification | BLOCKED | Explicitly not authorized |
| Ops Agent #475/#477 untouched | IMPLEMENTED (isolation) | Change map |
| Creative Studio #478 untouched | IMPLEMENTED (isolation) | Change map |

**Do not label this draft functionality live.**
