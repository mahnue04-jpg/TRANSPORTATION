# Phase 38 - Runtime Schema Lock + Contract Enforcement Report

Date: 2026-05-22
Scope: Contract stabilization and runtime consistency enforcement for assistant preview/confirm/execution/memory/events paths.

## 1. Canonical Normalization Design

A shared normalization layer was enforced in `backend/app/core/nova/assistant_contract.py` and adopted by backend routes/services and frontend hydration.

### Canonical helpers introduced/expanded

- `normalize_optional_text`
- `normalize_optional_list`
- `normalize_optional_object`
- `normalize_supervision_details`
- `normalize_supervision_classification`
- `normalize_assistant_preview_payload`
- Existing record normalizers retained and aligned:
  - `normalize_client_event_payload`
  - `normalize_execution_record`
  - `normalize_memory_record`
  - `normalize_operational_event_record`

### Contract guarantees now centralized

- Supervision classification supports object and legacy string forms through one canonical path.
- Preview payload shape is normalized before hash generation, persistence, and response emission.
- Confirm flow re-normalizes persisted preview payload before validation, execution handoff, and response return.
- Event/memory/execution readback shapes are normalized at service boundaries.

## 2. Removed Duplicate Logic

### Backend

- Removed route-local event payload normalization in `backend/app/core/nova/assistant_execution_router.py`.
- Removed local `_normalize_supervision_classification` in `backend/app/main.py`.
- Replaced repeated JSON dict coercion patterns in `backend/app/core/nova/assistant_execution_service.py` with shared contract coercion.

### Frontend

- Added centralized hydration normalizers in `backend/static/ops-shell.js`:
  - `safeObject`
  - `normalizeSupervisionClassification`
  - `normalizeExecutionRecord`
  - `normalizeMemoryRecord`
  - `normalizeAuditRecord`
  - `normalizePreviewPayload`
- Replaced inline assumptions in:
  - preview card hydration
  - confirm request payload build
  - execution history push
  - persisted execution/memory/event refresh merge

## 3. Compatibility Guarantees Enforced

### Preview -> Confirm -> Persistence -> Hydration alignment

- Preview payload normalized before `preview_payload_hash` computation.
- Persisted `preview_payload_json` stores normalized shape.
- Confirm reads and normalizes persisted payload, then returns normalized shape.
- Frontend hydration normalizes backend records before rendering.

### Mixed supervision payload support

- Object-shaped input: accepted and normalized.
- Legacy string input: accepted and normalized.
- Internal comparisons use canonical classification extraction.

### Additive handling for partial/legacy records

- Optional objects/lists default safely.
- Missing optional fields no longer break hydration render paths.
- Event and memory render paths tolerate sparse payloads.

## 4. Regression Coverage Added

New test suite:
- `backend/tests/test_phase38_schema_contract_lock.py`

Covered scenarios:

- Preview -> Confirm lifecycle succeeds with object-shaped supervision payload.
- Preview -> Confirm lifecycle succeeds with legacy string supervision payload.
- Duplicate confirm submission is rejected.
- Execution readback continuity remains available after local replay cache reset.
- Event and memory readback remain available for validated sessions.

Existing targeted suites re-run:

- `backend/tests/test_assistant_events_live.py`
- `backend/tests/test_assistant_replay_fallback.py`

## 5. Validation Evidence

### Static/Syntax checks

- Python compile check passed for:
  - `backend/app/core/nova/assistant_contract.py`
  - `backend/app/core/nova/assistant_execution_router.py`
  - `backend/app/core/nova/assistant_execution_service.py`
  - `backend/app/main.py`
- JavaScript syntax check passed for:
  - `backend/static/ops-shell.js`

### Targeted test run

Command:

`python -m pytest -q backend/tests/test_assistant_events_live.py backend/tests/test_assistant_replay_fallback.py backend/tests/test_phase38_schema_contract_lock.py`

Result:

- `3 passed`
- No Phase 38 contract failures.

### Live runtime validation (`127.0.0.1:8011`)

Validated endpoints:

- `GET /api/assistant/executions`
- `GET /api/assistant/events`
- `GET /api/assistant/memory`
- `POST /api/assistant/events`
- `POST /api/assistant/confirm`

Observed evidence:

- Login: `200`
- Object supervision preview: `200`, supervision shape `dict`
- Object supervision confirm: `200`, verification `VERIFIED_PREVIEW`
- Duplicate confirm protection: `409` (`Confirmation token already consumed`)
- Legacy string supervision confirm: `200`, verification `VERIFIED_PREVIEW`
- Client event post (camelCase input): `200`, normalized event name persisted
- Readback:
  - Executions: `200`, count `7`
  - Events: `200`, count `4`
  - Memory: `200`, count `3`
- Fresh login continuity readback: executions `200`, count `7`

## 6. Operational Safety Assessment

No regressions observed in this phase for:

- Orchestration control path (still dry-run/supervised).
- Startup/runtime import paths for edited files.
- Auth protection on assistant endpoints.
- Runtime loop stability for assistant shell hydration.
- Persistence readback integrity for execution/memory/events.

## 7. Remaining Scoped Risks

- Existing broad workspace has unrelated in-flight modifications; this phase touched only contract enforcement paths listed above.
- Redis optional dependency remains fail-safe fallback based in this environment (observed in logs), but behavior remains guarded and tested.
- Pydantic deprecation warnings exist outside Phase 38 scope and were not changed.

## 8. Next Safe Priorities

1. Add contract snapshot tests that assert canonical key presence for preview/confirm payloads.
2. Add a lightweight backend endpoint-level schema checksum metric for early drift detection in production telemetry.
3. Add frontend smoke test asserting normalized hydration for sparse legacy records.
