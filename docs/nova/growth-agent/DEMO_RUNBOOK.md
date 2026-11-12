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
```

## Pytest synthetic scenario

```bash
cd backend
TESTING=true NOVA_GROWTH_AGENT_ENABLED=true \
  python -m pytest -q tests/test_nova_growth_agent_integration.py::test_synthetic_demo_end_to_end
```

## Full Growth Agent suite

```bash
cd backend
TESTING=true NOVA_GROWTH_AGENT_ENABLED=true \
  python -m pytest -q tests/test_nova_growth_agent_*.py
```

## Owner UI

1. Start backend as usual (uvicorn via existing docs).  
2. Open `/nova/growth`  
3. Sign in with an approved Nova seed/owner account  
4. Click **Run synthetic demo**  
5. Confirm inbox/CRM/analytics show **Synthetic** labels  

## Widget snippet (after installation create)

```html
<script src="/static/nova-growth/widget.js"
  data-amicor-growth-token="PASTE_TOKEN"
  async></script>
```

## What the demo proves

1. FAQ chat grounded answer + AI disclosure  
2. Consent required before storing contact  
3. Lead dedupe on duplicate email  
4. Appointment booking + idempotent replay  
5. Double-book blocked  
6. Reminder workflow dry-run mock delivery  
7. Human handoff  
8. Marketing opt-out suppression  
9. Audit + analytics with explicit denominators  

## Screenshots

Capture sanitized UI screenshots locally if needed; do not upload real customer data. Fixtures live under tests only.
