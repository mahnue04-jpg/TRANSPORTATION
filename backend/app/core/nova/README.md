# Mr. Nova Core

Mr. Nova is an additive internal intelligence and orchestration layer for Amicor.

## Scope

- Explain system status
- Guide users step by step
- Recommend next build actions
- Summarize operational and dispatch health
- Review AI implementation reports
- Generate founder and business checklists
- Coordinate Amicor Core with Health ISF context

## Endpoints

- `GET /api/nova/status`
- `GET /api/nova/context`
- `POST /api/nova/ask`
- `POST /api/nova/summarize`
- `POST /api/nova/next-step`
- `POST /api/nova/review-report`

## Memory

Local structured memory is stored in `backend/data/nova_memory.json` and keyed by organization.

Tracked fields:

- current build phase
- active module
- last completed milestone
- next recommended step
- founder priorities
- business setup status
- deployment readiness status

## Design

- Additive implementation only
- Preserves existing Amicor assistant behavior
- Preserves Health ISF routes and workflows
- Enforces tenant-safe organization scope
