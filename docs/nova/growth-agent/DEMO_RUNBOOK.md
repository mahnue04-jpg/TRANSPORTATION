# Synthetic demo runbook

Fictitious business: **Cedar Ridge Home Services (SYNTHETIC DEMO)**.  
No real customers. No outbound live messages.

## Prerequisites

```bash
cd backend
python -m pip install -r requirements.txt pytest
export TESTING=true
export NOVA_GROWTH_AGENT_ENABLED=true
export NOVA_GROWTH_AGENT_DEMO_MODE=true
export NOVA_GROWTH_AGENT_WIDGET_ENABLED=true
export NOVA_GROWTH_AGENT_WIDGET_SECRET=local-dev-only
# Optional mock worker (still never live-sends):
# export NOVA_GROWTH_AGENT_BACKGROUND_WORKER=true
# Retention delete stays off unless explicitly testing gated delete:
# export NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED=false
export SECRET_KEY=local
export JWT_SECRET=local
export DATABASE_URL=sqlite:///./growth_agent_demo.db
export APP_ENV=test
export AMICOR_ENVIRONMENT=test
```

## Full Growth Agent suite

```bash
cd backend
TESTING=true NOVA_GROWTH_AGENT_ENABLED=true \
  NOVA_GROWTH_AGENT_DEMO_MODE=true \
  NOVA_GROWTH_AGENT_WIDGET_ENABLED=true \
  NOVA_GROWTH_AGENT_WIDGET_SECRET=ci-widget-secret \
  SECRET_KEY=ci-only-placeholder \
  JWT_SECRET=ci-only-placeholder \
  DATABASE_URL=sqlite:///./test_nova_growth_agent_ci.db \
  APP_ENV=test \
  AMICOR_ENVIRONMENT=test \
  python -m pytest -q tests/test_nova_growth_agent_*.py
```

Expected (this verification pass): **42 passed**.

Worker/retention/rate-limit focused module: `tests/test_nova_growth_agent_worker_retention.py`.

## Owner UI

1. Start backend (uvicorn via existing docs).  
2. Open `/nova/growth`  
3. Sign in with an approved Nova seed/owner account  
4. Click **Run synthetic demo** (requires `NOVA_GROWTH_AGENT_DEMO_MODE=true`)  
5. Use Diagnostics: refresh diagnostics, retention dry-run, mock worker tick (worker flag required)  
6. Optional booking: cancel / reschedule / marketing opt-out / recover pending  

## What the demo proves

1. FAQ chat grounded answer + AI disclosure  
2. Consent required before storing contact  
3. Lead dedupe on duplicate email (hashed identity)  
4. CRM state/notes edit  
5. Appointment booking + idempotent replay  
6. Cancel → rebook same slot + reschedule  
7. Double-book blocked  
8. Reminder workflow mock delivery (inline or deferred to mock worker)  
9. Restart recovery / stale lease reclaim  
10. Human handoff  
11. Channel-correct marketing opt-out suppression  
12. Shared atomic rate limiting (multi-worker safe)  
13. Retention dry-run with consent retained; delete gated off by default  
14. Diagnostics distinguish mock processing from real delivery  
15. Audit + analytics with explicit denominators  

## Evidence artifact

`DEMO_EVIDENCE.json` in this folder. Staging proposal: `STAGING_PROPOSAL.md`.
