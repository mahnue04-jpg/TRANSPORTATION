# PHASE 46 - DISPATCH INTELLIGENCE + AUTO-ASSIGNMENT ENGINE

## Objective Outcome

Phase 46 is implemented as an additive, production-safe extension of Health ISF dispatch operations.

This phase advances dispatcher coordination from authenticated runtime infrastructure into deterministic auto-assignment orchestration with offer lifecycle control, reassignment flow, and realtime visibility.

## Preserved Systems Confirmation

The implementation preserves all prior foundations and introduces no rewrites.

- Phase 42 cognition architecture preserved.
- Phase 43 onboarding and grant proof systems preserved.
- Phase 44 customer request lifecycle preserved.
- Phase 45 driver auth/runtime systems preserved.
- Existing FastAPI structure preserved.
- Existing websocket coordination preserved and extended additively.
- Existing APIs remain backward compatible.

## Dispatch Engine Architecture

### New Persistence Layer

Added additive dispatch intelligence model:

- `HealthISFDispatchAssignment`
  - stores deterministic offer attempts and lifecycle progression
  - stores scoring traceability and timeout metadata
  - stores stage timestamps and reassignment context

Lifecycle state enum:

- `DispatchAssignmentState`
  - queued
  - searching
  - offered
  - assigned
  - accepted
  - en_route_pickup
  - pickup_complete
  - dropoff_complete
  - reassignment_pending

Timestamp coverage includes:

- queued_at
- search_started_at
- offered_at
- offer_expires_at
- assigned_at
- accepted_at
- en_route_pickup_at
- pickup_complete_at
- dropoff_complete_at
- reassignment_pending_at
- rejected_at
- expired_at

### Deterministic Service Orchestration

Added service-layer orchestration methods:

- `evaluate_available_drivers()`
- `reserve_driver_assignment()`
- `release_driver_assignment()`
- `auto_assign_request()`
- `reassign_expired_request()`

Supporting operations:

- `expire_stale_dispatch_offers()`
- `accept_assignment_offer()`
- `reject_assignment_offer()`
- `get_dispatch_queue()`
- `get_dispatch_active_assignments()`
- lifecycle timestamp updater for assignment state transitions

## Scoring Logic Summary

Deterministic score formula uses weighted signals:

- distance priority placeholder
- availability freshness
- heartbeat freshness
- acceptance history placeholder (rating proxy)
- active workload weighting

Deterministic tie-break sequence:

1. higher score
2. lower heartbeat age
3. stable lexical driver id ordering

Safety filters applied before scoring:

- organization scope match
- active driver only
- auth_state active
- is_online true
- availability_state available
- active-trip prevention (nonzero active ride workload excluded)

## Assignment Lifecycle Map

1. queued/searching:
   - dispatch search starts
2. offered:
   - top ranked driver receives timed offer
3. assigned/accepted:
   - offer acceptance drives assignment confirmation
4. en_route_pickup:
   - driver accepted ride transitions en route
5. pickup_complete:
   - pickup completion stage recorded
6. dropoff_complete:
   - completion stage recorded
7. reassignment_pending:
   - timeout/reject transitions request back to reassignment

## Websocket Events Added

Additive `dispatch_changed` event names introduced:

- `dispatch-search-started`
- `driver-offer-issued`
- `driver-offer-expired`
- `auto-assignment-completed`
- `reassignment-started`
- `reassignment-completed`

Phase 45 compatibility event remains active:

- `assignment-accepted`

## API Routes Added (Additive)

- `POST /api/health-isf/dispatch/auto-assign`
- `POST /api/health-isf/dispatch/reassign`
- `POST /api/health-isf/dispatch/offers/{offer_id}/accept`
- `POST /api/health-isf/dispatch/offers/{offer_id}/reject`
- `GET /api/health-isf/dispatch/queue`
- `GET /api/health-isf/dispatch/active-assignments`

No existing route paths were removed or changed.

## Admin Dispatch Visualization Additions

Dispatcher panel extension includes:

- dispatch intelligence queue panel
- active assignment panel
- assignment aging indicators
- reassignment visibility
- dispatch timeline panel
- controls for auto-assign, reassign, and intelligence refresh

## Driver Dashboard Extension Additions

Driver runtime panel extension includes:

- incoming assignment offer card
- countdown/expiry visibility
- accept offer action
- reject offer action
- refresh offer state action
- driver dispatch event stream panel

## Validation Results

### 1. py_compile validation

Executed `py_compile` for:

- `backend/app/modules/health_isf/models.py`
- `backend/app/modules/health_isf/service.py`
- `backend/app/modules/health_isf/schemas.py`
- `backend/app/modules/health_isf/routes.py`

Result: pass.

### 2. import smoke validation

Executed import smoke with `PYTHONPATH=backend` for modified Health ISF modules.

Result:

- `phase46_import_smoke_ok`

Observed existing environment warning (unchanged):

- `SECRET_KEY not set — using ephemeral key...`

### 3. websocket lifecycle verification

Verified route-level emits for all required Phase 46 event names plus prior compatibility markers.

Result: required lifecycle events present.

### 4. assignment-state verification

Verified lifecycle enum and dispatch assignment model fields include all requested states and stage timestamps.

Result: complete.

### 5. route conflict verification

Verified critical route registration and static-vs-dynamic ordering continuity:

- `/drivers/active` remains registered before `/drivers/{driver_id}`.
- all new `/dispatch/*` routes registered.

Result: no discovered path shadowing in touched route families.

### 6. regression validation (Phases 42-45)

Performed additive-safe regression checks:

- diagnostics clean on touched files
- backend compile + import smoke passes
- existing legacy/dispatcher routes preserved
- prior websocket emits and lifecycle pathways retained

Result: no regressions detected in static checks.

## Deployment Readiness Notes

Phase 46 is deployment-ready from an additive architecture perspective.

It introduces deterministic auto-assignment and reassignment orchestration while preserving established runtime stability, websocket integrity, and prior phase capabilities.
