# Self-audit matrix — Nova Growth Agent (Issue #485)

Legend: **IMPLEMENTED** / **TESTED SYNTHETICALLY** / **VERIFIED LOCAL DISPOSABLE PG** / **VERIFIED STAGING** / **VERIFIED LIVE** / **BLOCKED**

Verification pass date: **2026-11-12** (America/Chicago). Branch tip after scheduled-retention + disposable PG + owner UI evidence package.

| Capability | Status | Evidence |
|------------|--------|----------|
| Tenant-scoped schema (`nova_ga_*`) | IMPLEMENTED + VERIFIED LOCAL DISPOSABLE PG | Migrations `20261112_nova_growth_agent` → `_worker` → `_retention`; alembic upgrade OK on `nova_ga_dispos_mig` |
| Deny-by-default org auth | IMPLEMENTED + TESTED SYNTHETICALLY | `tenant.py`; isolation + HTTP auth tests |
| Hashed contact identities | IMPLEMENTED + TESTED SYNTHETICALLY | `_hash_identity` digests |
| Setup wizard + activate checklist | IMPLEMENTED + TESTED SYNTHETICALLY | profile API + authenticated UI screenshots |
| Inbox AI/human + handoff + pause | IMPLEMENTED + TESTED SYNTHETICALLY | service + demo + UI |
| CRM states/search/notes | IMPLEMENTED + TESTED SYNTHETICALLY | leads PATCH + UI CRM screenshot |
| Analytics with denominators | IMPLEMENTED + TESTED SYNTHETICALLY | `confirmed`+`rescheduled` |
| Embeddable widget + signed token | IMPLEMENTED + TESTED SYNTHETICALLY | origin required; activation required |
| Shared atomic widget rate limit | IMPLEMENTED + TESTED SYNTHETICALLY + VERIFIED LOCAL DISPOSABLE PG | concurrent PG test exact limit |
| Appointment cancel → rebook + reschedule | IMPLEMENTED + TESTED SYNTHETICALLY | service + UI + demo |
| FAQ grounding / I-don't-know | IMPLEMENTED + TESTED SYNTHETICALLY | `faq_engine` tests |
| Consent + channel opt-out | IMPLEMENTED + TESTED SYNTHETICALLY | channel-correct; worker rechecks before send |
| Durable mock delivery worker | IMPLEMENTED + TESTED SYNTHETICALLY + VERIFIED LOCAL DISPOSABLE PG | claim/lease/backoff; concurrent PG claims |
| Restart recovery (stale leases) | IMPLEMENTED + TESTED SYNTHETICALLY + VERIFIED LOCAL DISPOSABLE PG | reclaim expired `running` leases |
| Retention dry-run + gated delete | IMPLEMENTED + TESTED SYNTHETICALLY | `retention.py`; delete requires separate flag |
| **Scheduled retention processor** | **IMPLEMENTED + TESTED SYNTHETICALLY + VERIFIED LOCAL DISPOSABLE PG** | `retention_schedule.py`; default-off; dry-run default; durable org+window rows; lease reclaim; delete separately gated |
| Owner diagnostics | IMPLEMENTED + TESTED SYNTHETICALLY | `GET /diagnostics` + UI flag strip (`live_delivery=false`, `retention_mode=dry_run`) |
| Owner export | IMPLEMENTED + TESTED SYNTHETICALLY | appointments/consent/messages included |
| Calendar Google/Microsoft | IMPLEMENTED (mock) / BLOCKED live | `REAL_CALENDAR_WRITE=False` |
| AI provider live | IMPLEMENTED (mock) / BLOCKED live | `MockAIAdapter` |
| Email/SMS live | IMPLEMENTED (mock) / BLOCKED live | hard-off flags |
| Stripe subscriptions | IMPLEMENTED (catalog) / BLOCKED live | `launched=False` |
| Voice receptionist stretch | BLOCKED | `REAL_VOICE=False` |
| Staging verification | BLOCKED | Executable proposal only — `STAGING_PROPOSAL.md` |
| CI (Growth Agent sqlite + disposable Postgres) | **CI VERIFIED** | Run https://github.com/mahnue04-jpg/TRANSPORTATION/actions/runs/43255525824 on `5e78296f` — growth-agent-tests + growth-agent-postgres-dispos pass |
| Live/production verification | BLOCKED | Explicitly not authorized |
| Ops Agent #475/#477 untouched | IMPLEMENTED (isolation) | Change map; regressions green |
| Creative Studio #478 untouched | IMPLEMENTED (isolation) | Change map |

## Exact local verification results (this pass)

```text
Growth Agent suite (sqlite): 45 passed
  tests/test_nova_growth_agent_unit.py
  tests/test_nova_growth_agent_integration.py
  tests/test_nova_growth_agent_security.py
  tests/test_nova_growth_agent_http.py
  tests/test_nova_growth_agent_worker_retention.py

Disposable PostgreSQL (nova_ga_dispos_test / nova_ga_dispos_mig): 6 passed + alembic upgrade OK
  tests/test_nova_growth_agent_postgres.py
  alembic upgrade 20261112_nova_ga_retention → ALEMBIC_OK

Focused regressions (non-Growth): 69 passed
  tests/test_nova_casting_flags.py
  tests/test_nova_casting_preview.py
  tests/test_nova_work_revenue_labeling.py
  tests/test_nova_qualification_claim_scope.py

Owner UI synthetic walkthrough (Playwright, local uvicorn :8765):
  screenshots: docs/nova/growth-agent/screenshots/01..10-*.png
  artifacts: /opt/cursor/artifacts/nova-growth-ui/
  flags observed: live_delivery=false · mock_worker=on · retention_schedule=on · retention_mode=dry_run · retention_delete=off
```

Evidence: `docs/nova/growth-agent/DEMO_EVIDENCE.json`, `docs/nova/growth-agent/screenshots/`, `docs/nova/growth-agent/STAGING_PROPOSAL.md`.

## Remaining blockers (owner gates)

1. No merge / deploy / shared-DB migration / Render changes without explicit owner approval.
2. Live email/SMS/calendar/AI/Stripe remain hard-off.
3. Mock worker, retention schedule, and retention delete remain **default-off** env flags (delete separately gated).
4. Staging/live verification not performed (executable proposal drafted only).
5. ~~CI disposable Postgres job pending~~ **CI verified** on tip `5e78296f` (growth-agent-tests + growth-agent-postgres-dispos passed). Staging still not verified.

**Do not label this draft functionality live.**
