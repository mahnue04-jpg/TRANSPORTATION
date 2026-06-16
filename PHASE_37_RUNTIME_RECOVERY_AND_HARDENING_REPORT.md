# Phase 37 Runtime Recovery and Hardening Report

## Scope
This phase recovered the live canonical backend runtime, normalized assistant execution/event payload handling, and validated persistence and restart continuity without redesigning the orchestration layer.

No orchestration/runtime rewrite performed.

## Runtime Recovery
- Identified a stale Python listener on `127.0.0.1:8011` serving health endpoints but missing the Phase 36 assistant routes.
- Stopped the stale listener cleanly and verified the port was cleared.
- Started the canonical backend from `backend/` using the repo virtual environment on `127.0.0.1:8011`.
- Confirmed a healthy listener was present after restart.
- Repeated the clean restart once more after the code fix to verify continuity on a fresh process.

### Evidence Summary
- Canonical listener restarted on `8011` with a fresh Python process.
- Health endpoint returned `200` after restart.
- Assistant persistence remained readable after the second restart.

## Endpoint Validation Matrix
| Endpoint | Method | Result | Notes |
|---|---:|---:|---|
| `/api/assistant/executions` | GET | 200 | Authenticated access returns execution history. |
| `/api/assistant/memory` | GET | 200 | Authenticated access returns memory history. |
| `/api/assistant/events` | GET | 200 | New read route added for persisted assistant events. |
| `/api/assistant/events` | POST | 200 | Normalizes legacy payload shapes and logs events. |
| `/api/assistant/confirm` | POST | 200 | Accepts preview-emitted supervision classification object shape after normalization. |
| `/api/assistant/events` | GET unauthenticated | 401 | Auth protection preserved. |

## Payload Normalization
Two additive normalization fixes were applied:
- Assistant client events now accept legacy/camelCase payload keys and normalize them before persistence.
- Assistant confirmation now accepts the preview-emitted `supervision_classification` object shape and compares the normalized classification string against the stored preview record.

This removed the live 404/422/409 drift that came from stale runtime state and payload-shape mismatch.

## Execution Lifecycle Validation
Validated the preview/confirm workflow end to end on the live listener:
- `preview` returned a signed confirmation token.
- `confirm` accepted the preview-emitted supervision classification object and completed successfully.
- The returned workflow execution reached `completed`.
- Execution timestamps were populated.
- The execution history endpoint returned the persisted records.

Lifecycle states remain:
- `pending`
- `running`
- `completed`
- `failed`

## Persistence Validation
Persistence was verified in two ways:
- A posted assistant operational event was read back immediately through `GET /api/assistant/events`.
- After a clean backend restart, the same event was still present and readable.

Assistant execution and memory read routes also remained available after restart.

## Live UI Validation
Validated in the browser session:
- Authenticated shell access succeeded.
- Role-aware shell state rendered for the admin context.
- Assistant workspace loaded with read-only safety indicators and session state.
- A screenshot of the authenticated assistant shell was captured during validation.

Observed limitation:
- The browser shell can still fall back to a hydration/loading state during route transitions in this workspace, so the live execution form is not fully consistent on every refresh. Backend runtime and persistence are stable, but the UI hydration path still benefits from a manual refresh in some sessions.

## Known Remaining Defects
- The browser shell hydration path is still occasionally inconsistent on route transitions, even though the backend assistant routes are healthy.
- Existing Pydantic deprecation warnings remain in unrelated modules and were not part of this phase.
- The assistant UI audit panel currently depends on session rendering plus backend hydration; it is stable after refresh, but not fully deterministic during rapid navigation.

## Safe Next Priorities
1. Tighten the assistant UI hydration trigger so event, memory, and execution panels refresh immediately on assistant-route entry.
2. Reduce the remaining Pydantic deprecation warnings in unrelated modules.
3. Add one more browser-side regression check for the assistant route to guard against future stale-shell regressions.

## Verification Summary
- Backend compile checks passed for the touched modules.
- Targeted regression test passed for authenticated assistant event readback and payload normalization.
- Live backend confirm workflow completed successfully after restart.
- Restart continuity was verified with persisted assistant event data.
