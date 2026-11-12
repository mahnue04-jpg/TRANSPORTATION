# Self-audit matrix — Nova Growth Agent (Issue #485)

Legend: **IMPLEMENTED** / **TESTED SYNTHETICALLY** / **VERIFIED STAGING** / **VERIFIED LIVE** / **BLOCKED**

Verification pass date: **2026-11-12** (America/Chicago). Branch tip after worker/retention pass supersedes `3775b0cb`.

| Capability | Status | Evidence |
|------------|--------|----------|
| Tenant-scoped schema (`nova_ga_*`) | IMPLEMENTED | `models.py`, migrations `20261112_nova_growth_agent` + `20261112_nova_ga_worker` (prod DDL gated) |
| Deny-by-default org auth | IMPLEMENTED + TESTED SYNTHETICALLY | `tenant.py` `UserContext`; isolation + HTTP auth tests |
| Hashed contact identities | IMPLEMENTED + TESTED SYNTHETICALLY | `_hash_identity` digests |
| Setup wizard + activate checklist | IMPLEMENTED + TESTED SYNTHETICALLY | profile API + HTTP journey |
| Inbox AI/human + handoff + pause | IMPLEMENTED + TESTED SYNTHETICALLY | service + demo + UI |
| CRM states/search/notes | IMPLEMENTED + TESTED SYNTHETICALLY | leads PATCH + demo CRM edit |
| Analytics with denominators | IMPLEMENTED + TESTED SYNTHETICALLY | `confirmed`+`rescheduled` |
| Embeddable widget + signed token | IMPLEMENTED + TESTED SYNTHETICALLY | origin required; activation required |
| Shared atomic widget rate limit | IMPLEMENTED + TESTED SYNTHETICALLY | `rate_limit.py` durable counters; concurrent + restart tests |
| Appointment cancel → rebook + reschedule | IMPLEMENTED + TESTED SYNTHETICALLY | service + UI + demo |
| FAQ grounding / I-don't-know | IMPLEMENTED + TESTED SYNTHETICALLY | `faq_engine` tests |
| Consent + channel opt-out | IMPLEMENTED + TESTED SYNTHETICALLY | channel-correct; worker rechecks before send |
| Durable mock delivery worker | IMPLEMENTED + TESTED SYNTHETICALLY | `worker.py`; default-off via `NOVA_GROWTH_AGENT_BACKGROUND_WORKER`; atomic claim/lease/backoff/shutdown |
| Restart recovery (stale leases) | IMPLEMENTED + TESTED SYNTHETICALLY | reclaim expired `running` leases + recover endpoint |
| Retention dry-run + gated delete | IMPLEMENTED + TESTED SYNTHETICALLY | `retention.py`; delete requires `NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED` |
| Owner diagnostics | IMPLEMENTED + TESTED SYNTHETICALLY | `GET /diagnostics`; mock vs live clearly separated |
| Owner export | IMPLEMENTED + TESTED SYNTHETICALLY | appointments/consent/messages included |
| Calendar Google/Microsoft | IMPLEMENTED (mock) / BLOCKED live | `REAL_CALENDAR_WRITE=False` |
| AI provider live | IMPLEMENTED (mock) / BLOCKED live | `MockAIAdapter` |
| Email/SMS live | IMPLEMENTED (mock) / BLOCKED live | hard-off flags |
| Stripe subscriptions | IMPLEMENTED (catalog) / BLOCKED live | `launched=False` |
| Automatic retention purge cron | BLOCKED | Manual/API execute only; auto-delete remains off |
| Voice receptionist stretch | BLOCKED | `REAL_VOICE=False` |
| Staging verification | BLOCKED | Proposal only — see `STAGING_PROPOSAL.md` |
| Live/production verification | BLOCKED | Explicitly not authorized |
| Ops Agent #475/#477 untouched | IMPLEMENTED (isolation) | Change map; regressions green |
| Creative Studio #478 untouched | IMPLEMENTED (isolation) | Change map |

## Exact local verification results (this pass)

```text
Growth Agent suite: 42 passed
  tests/test_nova_growth_agent_unit.py
  tests/test_nova_growth_agent_integration.py
  tests/test_nova_growth_agent_security.py
  tests/test_nova_growth_agent_http.py
  tests/test_nova_growth_agent_worker_retention.py

Focused regressions (non-Growth): 69 passed
  tests/test_nova_casting_flags.py
  tests/test_nova_casting_preview.py
  tests/test_nova_work_revenue_labeling.py
  tests/test_nova_qualification_claim_scope.py
```

Evidence: `docs/nova/growth-agent/DEMO_EVIDENCE.json`.

## Remaining blockers (owner gates)

1. No merge / deploy / shared-DB migration / Render changes without explicit owner approval.
2. Live email/SMS/calendar/AI/Stripe remain hard-off.
3. Mock worker and retention delete remain **default-off** env flags.
4. Automatic retention cron not implemented.
5. Staging/live verification not performed (proposal drafted only).
6. SQLite same-process rate-limit gate supplements SQL atomics; Postgres multi-worker relies on SQL `UPDATE … WHERE count < limit`.

**Do not label this draft functionality live.**
