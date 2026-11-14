# Nova Workspace / Growth Agent API discovery — 2026-11-14

Status: **read-only code inspection**; no integration, runtime tests, merge, or deployment. This is part of draft PR #516 and issues #496 / #497.

## Sources and pinned refs
- Growth Agent implementation: draft PR #490 head `e4d0aec2e37af6b23e107c71c03eadf01d586287`, `backend/app/core/nova/growth_agent/router.py` and `tenant.py`.
- Nova Workspace on `main` commit `f89a66efbd05fa641c6932d6dca917fbbb46252e`: `backend/app/core/nova/workspace/router.py` and `backend/static/nova-workspace/index.html`.
- Inspect both again before implementing because PR #490 is unmerged and branch heads can move. Do not claim Growth routes exist on `main`.

## Confirmed HTTP surfaces
| System | Prefix | Relevant code-declared routes |
|---|---|---|
| Growth | `/api/nova/growth-agent` | `GET /flags`, `GET /health`, `GET /profile`, `GET /leads`, `GET /conversations`, `GET /conversations/{conversation_id}`, `GET /appointments`, `GET /analytics`, `GET /audit`, `GET /diagnostics` |
| Growth owner writes | same | `PATCH /leads/{contact_id}`, `POST /conversations/{conversation_id}/handoff`, `POST /workflows/preview`, `POST /workflows/execute`, `POST /appointments`, `POST /appointments/{appointment_id}/reschedule`, `POST /appointments/{appointment_id}/cancel` |
| Growth public intake | same | `POST /widget/chat` (requires master and public widget flags; validated signed token/origin via service) |
| Nova Workspace | `/api/nova/workspace` | `GET /dashboard`, `GET /projects`, `GET /conversations`, `GET /search`, `POST /ask`; no Growth Agent-specific inbox, handoff or approval route found in this router |
| Workspace UI | `/nova/workspace` HTML served from `backend/static/nova-workspace/index.html` | Main nav has Nova destinations, but no visible Growth Agent entry in inspected HTML |

## Critical authorization findings
1. Growth uses `Depends(require_growth_owner)` on internal routes and `resolve_org()` delegates to `NovaCoreService.resolve_organization_scope`. Missing/global tenant scope is denied. The public widget endpoint is separately gated.
2. **Naming is not sufficient proof of ownership restriction.** The inspected `require_growth_owner` function checks `require_nova_access`, a user context, feature enablement and nonempty user/org fields; it does not visibly perform a distinct owner-role check. Confirm actual role semantics before exposing owner dashboard or approval actions. Introduce a verified permission dependency if needed.
3. Workspace router uses `Depends(require_nova_access)` globally and derives organization scope with `NovaCoreService.resolve_organization_scope`. Review permissions for agent-specific owner actions separately; do not treat any authenticated Workspace user as an owner.
4. Do not delegate cross-product operations by trusting `organization_id` supplied in frontend requests. Re-resolve tenant under authenticated server context, and authorize the target action independently.

## Implementation decisions, pending code review
- Reuse Growth's existing lead, conversation, appointment and audit storage rather than duplicating CRM tables in Workspace.
- Introduce a **read-only, feature-flagged Growth Agent panel** in Workspace first. It should use existing authenticated API calls with the same user session and expose true errors/unavailable states, never pretend a mock is live.
- Approval queue still needs evidence of persisted action-bound approvals, one-time decisions, expiry and revocation before adding active buttons. Existing Growth `POST /workflows/execute` is not evidence of a general cross-agent authorization contract.
- A Growth conversation `handoff` route exists, but it is not verified as an Operations Agent work-intake handoff. Inspect its service implementation and Operations API before wiring.
- Creative Studio links must remain **planned / disconnected** unless verified media identifiers and read permissions exist.
- A central knowledge/memory service must not be assumed from these routers. Document a bounded approved-FAQ read model before connecting any personal data.

## Minimal next code slice (separate draft PR)
1. Confirm owner role predicates and auth session behavior in `require_nova_access` / `UserContext`, Growth service queries, and Workspace frontend fetch wrapper.
2. Implement only an owner-authenticated read-only Growth panel, backed by `GET /health`, `GET /leads`, `GET /conversations`, `GET /appointments`, `GET /diagnostics`, and feature mode labels. If missing/disabled, show an honest unavailable message.
3. Add backend authorization tests (owner passes, non-owner denied, cross-tenant denied), UI empty/error/mobile tests, and synthetic fixtures. No live sends or database migrations.
4. Review test evidence before adding persisted owner approval and Operations dispatch in a later PR.

## Safety
No modification of PR #490/#515, Render staging, Studio SQLite, projects/media/backups, PostgreSQL/R2 migration, paid fal/Kling, production, customer outreach, public widgets, email/SMS, billing or credentials. All live transport features remain off.
