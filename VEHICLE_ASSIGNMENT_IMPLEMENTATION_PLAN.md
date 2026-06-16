# Vehicle Assignment Implementation Plan

## Goal
Add a real, writable trip-to-vehicle assignment contract to Health ISF so a ride can carry an assigned vehicle in the same way it already carries an assigned driver, without breaking dispatch, driver assignment, or existing ride lifecycle flows.

## Non-Goals
- Do not replace the current driver assignment flow.
- Do not redesign the ops shell layout or navigation structure.
- Do not change dispatch status semantics unless required to keep vehicle assignment consistent.
- Do not implement any billing, claims, or payment changes in this phase.

## Current Gap Summary
- `HealthISFVehicle` exists in `backend/app/modules/health_isf/models.py`, and `HealthISFDriver.vehicle_id` already points to it.
- `HealthISFRide` does not have a `vehicle_id` field yet.
- `RideResponse` in `backend/app/modules/health_isf/schemas.py` returns `provider_id`, `driver_id`, and ride status fields, but not assigned vehicle data.
- `assign_driver_to_ride()` in `backend/app/modules/health_isf/service.py` updates driver assignment and dispatch state, but does not assign a vehicle to the ride.
- `backend/static/ops-shell.js` still renders the vehicles surface as static content, so the UI has no live vehicle assignment workflow.

## Delivery Stages

### Stage 1: Data Model Contract
Exact files:
- `backend/app/modules/health_isf/models.py`
- `backend/migrations/versions/<new_revision>_health_isf_vehicle_assignment.py`
- `backend/tests/test_phase54_vehicle_assignment.py`

Exact model changes:
- Add `vehicle_id: Mapped[Optional[str]]` to `HealthISFRide`.
- Add a SQLAlchemy relationship from `HealthISFRide` to `HealthISFVehicle`.
- Keep `HealthISFDriver.vehicle_id` unchanged so driver-to-vehicle data still works independently.

Exact database fields:
- Add `health_isf_rides.vehicle_id` as a nullable foreign key to `health_isf_vehicles.id`.
- Add an index on `health_isf_rides.vehicle_id`.
- Keep the column nullable so existing rides remain valid before assignment is backfilled.

Independent test:
- A migration test or smoke check can create a ride without a vehicle, then assign a vehicle later without schema errors.
- Existing ride creation and retrieval tests must continue to pass unchanged.

### Stage 2: API Contract
Exact files:
- `backend/app/modules/health_isf/schemas.py`
- `backend/app/modules/health_isf/routes.py`

Exact API changes:
- Extend `RideResponse` to expose `vehicle_id`.
- Add a lightweight vehicle summary field to `RideResponse` only if the frontend needs it immediately; otherwise keep the response to `vehicle_id` first and hydrate the vehicle separately.
- Add a request schema such as `RideAssignVehicleRequest` with `vehicle_id: str`.
- Add a ride-scoped endpoint such as `PATCH /rides/{ride_id}/assign-vehicle`.
- Add the dispatcher-scoped equivalent such as `PATCH /dispatcher/rides/{ride_id}/assign-vehicle` if dispatcher workflows need the same action surface.
- Keep existing `PATCH /rides/{ride_id}/assign-driver` untouched.

Independent test:
- OpenAPI or route discovery should show the new vehicle assignment endpoint without changing the shape of existing ride endpoints.
- A ride fetched before and after assignment should now differ only by `vehicle_id` and not by unrelated fields.

### Stage 3: Service Logic
Exact files:
- `backend/app/modules/health_isf/service.py`
- `backend/app/modules/health_isf/routes.py`

Exact service methods:
- Add `assign_vehicle_to_ride(db, ride_id, vehicle_id, *, actor, source)` or an equivalent service function that mirrors the existing driver assignment pattern.
- Reuse the same transaction, audit, and history patterns used by `assign_driver_to_ride()`.
- Add a small resolver/helper for vehicle lookup and org scoping if the codebase already centralizes those checks.

Exact behavior rules:
- The selected vehicle must exist.
- The selected vehicle must belong to the same organization or provider scope as the ride, based on the repo’s existing tenant rules.
- The ride must not be in a terminal state when assignment occurs.
- If the ride already has a driver, the vehicle assignment must not silently detach the driver relationship.
- If the ride has a driver whose `vehicle_id` is set, the service should either validate compatibility or document an explicit override path.
- Reassigning the same vehicle should be idempotent.

Independent test:
- A unit test can assign a valid vehicle to an active ride and verify the ride record updates.
- A second call with the same vehicle should not create duplicate side effects.
- Terminal rides should reject assignment.

### Stage 4: Permissions And Safety
Exact files:
- `backend/app/modules/health_isf/routes.py`
- `backend/app/auth.py` if a new role dependency is required
- `backend/tests/test_phase54_vehicle_assignment.py`

Exact role permissions:
- Dispatcher and admin operators should be allowed to assign a vehicle to a ride.
- Drivers should be read-only for vehicle assignment.
- Any public or rider-facing route must not expose write access.
- If the existing codebase already distinguishes dispatcher and supervisor permissions, mirror that pattern instead of inventing a new role.

Exact validation rules:
- Reject blank or malformed vehicle IDs.
- Reject vehicle IDs that do not exist.
- Reject cross-organization assignment.
- Reject assignment when the vehicle is inactive, archived, or otherwise unavailable according to existing vehicle status semantics.
- Reject assignment if the ride is already completed, cancelled, or otherwise terminal.
- Preserve current dispatch behavior if the ride already has a dispatch record.

Independent test:
- Dispatcher/admin requests succeed with a valid vehicle.
- Driver-authenticated requests fail with 403 or the repo’s standard authorization response.
- Invalid vehicle IDs fail with the expected 404 or validation error.

### Stage 5: Frontend Control Surface
Exact files:
- `backend/static/ops-shell.js`

Exact frontend controls:
- Replace the static vehicles table in `renderVehicles()` with data loaded from the backend once the API supports it.
- Add a ride-level vehicle assignment action in the trip or dispatcher surface so an operator can bind a vehicle to a ride.
- Keep the current vehicle visualization fallback until the backend data is available, but mark it clearly as placeholder data if it remains.
- Prefer a small control near the ride card or ride detail row instead of a full UI rewrite.

Independent test:
- The ops shell should still load and render the current trip, driver, and dispatcher views.
- A mocked or seeded vehicle assignment response should populate the new control without breaking the existing static fallback.
- Existing non-vehicle tabs should remain unchanged.

### Stage 6: Dispatch Integration And History
Exact files:
- `backend/app/modules/health_isf/service.py`
- `backend/app/modules/health_isf/routes.py`
- `backend/app/modules/health_isf/models.py`

Exact integration points:
- Update any ride history or dispatch event payloads so vehicle assignment is visible in audit trails if the repo already records state transitions there.
- Keep the dispatch auto-assign and reassign flows intact so they continue to operate when a ride has an assigned vehicle.
- If dispatch logic uses vehicle availability, wire the new ride vehicle assignment into the same availability checks instead of creating a parallel rule set.

Independent test:
- Existing dispatch auto-assign tests should still pass.
- A ride with an assigned vehicle should still transition through accept, start, and complete flows.
- Dispatch history should preserve pre-existing events and add vehicle assignment only where intended.

## Migration Requirements
- Create one Alembic migration in `backend/migrations/versions/` for the new ride vehicle foreign key and index.
- Keep the migration additive and nullable so it does not require a data backfill before deployment.
- If backfill is needed later, do it in a separate migration or maintenance task after the contract is live.
- Avoid changing the existing `health_isf_drivers.vehicle_id` contract in the same migration unless a later test shows a hard coupling is required.

## Recommended Implementation Order
1. Add the ride vehicle column and migration.
2. Expose `vehicle_id` in the ride schema response.
3. Add the assign-vehicle request and endpoint.
4. Implement the service method and authorization checks.
5. Wire the frontend control to the new API.
6. Add regression tests for ride creation, driver assignment, vehicle assignment, and dispatch continuation.

## Acceptance Criteria
- A ride can be created without a vehicle and later assigned one.
- Existing driver assignment behavior still works unchanged.
- Dispatch and lifecycle transitions still work for rides with and without a vehicle.
- The ops shell can request and display live vehicle assignment data once the backend exposes it.
- The change is covered by independent tests at each stage, not only by one end-to-end test.

## Open Questions To Resolve During Build
- Should vehicle assignment be tied only to rides, or should driver and ride assignments be synchronized in both directions?
- Should a ride be allowed to have a vehicle without a driver, or must vehicle assignment require an assigned driver?
- Should the frontend show a vehicle picker from all vehicles or only from organization-scoped active vehicles?
- Should dispatch auto-assignment prefer a specific vehicle when the ride already has a preferred driver?

## Risk Controls
- Keep the ride vehicle field nullable until the workflow is fully adopted.
- Do not couple the new contract to billing or claims logic.
- Preserve all existing ride status transitions and dispatch status transitions.
- Add regression coverage for the driver assignment path so the new feature does not silently alter the current trip flow.
