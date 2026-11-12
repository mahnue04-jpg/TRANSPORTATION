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
export SECRET_KEY=local
export JWT_SECRET=local
export DATABASE_URL=sqlite:///./growth_agent_demo.db
export APP_ENV=test
export AMICOR_ENVIRONMENT=test
```

## Pytest synthetic scenario

```bash
cd backend
TESTING=true NOVA_GROWTH_AGENT_ENABLED=true NOVA_GROWTH_AGENT_DEMO_MODE=true \
  python -m pytest -q tests/test_nova_growth_agent_integration.py::test_synthetic_demo_end_to_end
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

Expected (this verification pass): **35 passed**.

## Owner UI

1. Start backend as usual (uvicorn via existing docs).  
2. Open `/nova/growth`  
3. Sign in with an approved Nova seed/owner account  
4. Click **Run synthetic demo** (requires `NOVA_GROWTH_AGENT_DEMO_MODE=true`)  
5. Confirm inbox/CRM/analytics show **Synthetic** labels  
6. Optional: cancel / reschedule / marketing opt-out / recover pending deliveries from Booking panel  

## Widget snippet (after installation create)

```html
<script src="/static/nova-growth/widget.js"
  data-amicor-growth-token="PASTE_TOKEN"
  async></script>
```

Widget posts include `X-Amicor-Growth-Origin` so domain checks fail closed even when the browser omits `Origin`.

## What the demo proves

1. FAQ chat grounded answer + AI disclosure  
2. Consent required before storing contact  
3. Lead dedupe on duplicate email (hashed identity)  
4. CRM state/notes edit  
5. Appointment booking + idempotent replay  
6. Cancel → rebook same slot + reschedule  
7. Double-book blocked  
8. Reminder workflow dry-run mock delivery  
9. Restart recovery reclaim of queued mock delivery  
10. Human handoff  
11. Channel-correct marketing opt-out suppression (no blanket DNC for owner opt-out)  
12. Audit + analytics with explicit denominators (includes rescheduled bookings)  
13. Owner export includes appointments, consent, and conversation messages  

## Evidence artifact

Sanitized JSON from the last local synthetic run: `DEMO_EVIDENCE.json` in this folder.

## Screenshots

Capture sanitized UI screenshots locally if needed; do not upload real customer data. Fixtures live under tests only.
