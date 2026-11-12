# Change map — Nova Growth Agent MVP

## New modules (additive)

| Area | Path |
|------|------|
| Domain + flags + APIs | `backend/app/core/nova/growth_agent/**` |
| Owner dashboard + widget | `backend/static/nova-growth/**` |
| Alembic (prod-gated) | `backend/migrations/versions/20261112_nova_growth_agent.py` |
| Tests | `backend/tests/test_nova_growth_agent_*.py` |
| CI | `.github/workflows/nova-growth-agent.yml` |
| Docs | `docs/nova/growth-agent/**` |

## Touched shared files (minimal, append-only)

| File | Change |
|------|--------|
| `backend/app/main.py` | Import + `include_router` for growth agent; `/nova/growth` + widget static routes |

## Explicitly unchanged

- `ops-shell.*`, Driver 001, private-pay, Health ISF lifecycle
- `nova-work/**`, Work & Revenue CSV / ops modules (#475/#477)
- `nova-creative/**`, `creative_studio/**` (#478)
- `v3/growth/**` (existing synthetic lab left intact)
- Stripe LIVE paths, Render hostname, telecom keys

## Integration rules

1. Reuse auth/org scoping only.
2. Mock/default-off all outbound providers.
3. No merge/deploy/activation in this draft.
4. Do not contact Makkan, Botora, or AMICOR prospects.
