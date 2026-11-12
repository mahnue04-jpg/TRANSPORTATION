# Growth Agent API schema (draft)

Base: `/api/nova/growth-agent`  
Gate: `NOVA_GROWTH_AGENT_ENABLED=true` (else 404). Live send flags hard-off.

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/flags` | owner | Capability flags |
| GET | `/health` | owner | Diagnostics + kill-switch hint |
| GET | `/plans` | owner | Starter/Growth/Pro catalog (unlaunched) |
| GET | `/retention` | owner | Retention/deletion/export policy |
| GET/POST | `/profile` | owner | Setup wizard get/upsert/activate |
| POST | `/agent` | owner | Pause/disable kill switch |
| POST | `/widget/installations` | owner | Mint signed install token |
| POST | `/widget/chat` | token | Public chat (signed token + Origin/Referer/`X-Amicor-Growth-Origin`; profile must be activated; widget flag required) |
| GET | `/leads` | owner | CRM list/search |
| PATCH | `/leads/{id}` | owner | Lead state/notes |
| POST | `/consent` | owner | Record opt-in/out |
| GET | `/conversations` | owner | Inbox |
| GET | `/conversations/{id}` | owner | Transcript |
| POST | `/conversations/{id}/handoff` | owner | Human handoff |
| POST | `/workflows/preview` | owner | Dry-run preview + cost estimate |
| POST | `/workflows/execute` | owner | Approve mock delivery (default dry_run; queues then sends mock) |
| POST | `/workflows/recover` | owner | Reclaim queued/retrying mock deliveries after restart |
| POST | `/workflows/worker/tick` | owner | One mock-worker batch (requires `NOVA_GROWTH_AGENT_BACKGROUND_WORKER=true`; never live) |
| GET | `/diagnostics` | owner | Worker status, pending/failed jobs, retention preview + schedule status; mock vs live labeled |
| POST | `/retention/preview` | owner | Dry-run retention counts (no delete) |
| POST | `/retention/execute` | owner | Bounded delete when `NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED=true` |
| POST | `/retention/schedule/tick` | owner | One scheduled-retention batch (requires `NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED=true`; dry-run unless delete also enabled) |
| GET | `/availability` | owner | Slots for day/service |
| GET | `/appointments` | owner | List appointments |
| POST | `/appointments` | owner | Book (idempotent; reuses cancelled slot) |
| POST | `/appointments/{id}/cancel` | owner | Cancel |
| POST | `/appointments/{id}/reschedule` | owner | Reschedule (idempotent) |
| GET | `/analytics` | owner | Metrics with window denominators (`confirmed`+`rescheduled`) |
| GET | `/audit` | owner | Audit history |
| GET | `/export` | owner | Org-scoped export (leads, conversations+messages, consent, appointments) |
| POST | `/demo/synthetic` | owner | Full synthetic scenario (requires `NOVA_GROWTH_AGENT_DEMO_MODE=true`) |

UI: `GET /nova/growth` → `backend/static/nova-growth/`  
Widget assets: `/static/nova-growth/widget.js`, `widget.css`
