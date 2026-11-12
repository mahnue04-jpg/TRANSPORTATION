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
| POST | `/widget/chat` | token | Public chat (signed token + origin) |
| GET | `/leads` | owner | CRM list/search |
| PATCH | `/leads/{id}` | owner | Lead state/notes |
| POST | `/consent` | owner | Record opt-in/out |
| GET | `/conversations` | owner | Inbox |
| GET | `/conversations/{id}` | owner | Transcript |
| POST | `/conversations/{id}/handoff` | owner | Human handoff |
| POST | `/workflows/preview` | owner | Dry-run preview + cost estimate |
| POST | `/workflows/execute` | owner | Approve mock delivery (default dry_run) |
| GET | `/availability` | owner | Slots for day/service |
| POST | `/appointments` | owner | Book (idempotent; reuses cancelled slot) |
| POST | `/appointments/{id}/cancel` | owner | Cancel |
| POST | `/appointments/{id}/reschedule` | owner | Reschedule (idempotent) |
| GET | `/analytics` | owner | Metrics with window denominators |
| GET | `/audit` | owner | Audit history |
| GET | `/export` | owner | Org-scoped export |
| POST | `/demo/synthetic` | owner | Full synthetic scenario |

UI: `GET /nova/growth` → `backend/static/nova-growth/`  
Widget assets: `/static/nova-growth/widget.js`, `widget.css`
