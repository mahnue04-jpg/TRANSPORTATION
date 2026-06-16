# Health ISF Pilot Hardening Execution Plan

**Date:** 2026-06-03
**Purpose:** Move Health ISF from stabilization into pilot deployment readiness.
**Constraints:** No new features. No architecture redesign. No auth redesign. No role-system redesign.

## Execution Order

1. SQLite lock contention
2. WebSocket reliability
3. Dashboard refresh consistency
4. Driver dropdown staleness

## 1. SQLite Lock Contention

**Risk level:** Critical

**Root cause**

- The runtime-governor cleanup path calls `ConcurrentAssignmentService.cleanup_expired_locks(db)` against the SQLite-backed `health_isf_assignment_locks` table.
- Under current pilot-like runtime conditions, cleanup intermittently collides with live write activity and logs `database is locked` failures.
- The lock cleanup is background infrastructure, but it sits on the same SQLite database as live dispatch state, so contention can spill into operational reliability.

**Exact files involved**

- [backend/app/modules/health_isf/runtime_governor.py](backend/app/modules/health_isf/runtime_governor.py)
- [backend/app/modules/health_isf/realtime_service.py](backend/app/modules/health_isf/realtime_service.py)
- [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py)
- [backend/app/modules/health_isf/models.py](backend/app/modules/health_isf/models.py)
- [backend/app/modules/health_isf/operations.py](backend/app/modules/health_isf/operations.py)

**Fix approach**

- Harden the cleanup path so it is fail-safe under SQLite write pressure.
- Reduce or serialize cleanup frequency if it is competing with live assignment activity.
- Keep the current table and lock semantics intact; do not redesign the concurrency model.
- Make cleanup failures non-fatal to dispatcher operations while preserving cleanup visibility in logs.

**Test plan**

- Reproduce pilot-like concurrent assignment activity while cleanup is running.
- Verify no `database is locked` errors appear in the request path.
- Verify cleanup failures remain isolated to background diagnostics, not live assignment endpoints.
- Run the dispatcher end-to-end flow again and confirm ride assignment still succeeds.
- Inspect backend logs for at least one full pilot test window and confirm the lock cleanup path stays quiet.

## 2. WebSocket Reliability

**Risk level:** High

**Root cause**

- The frontend still relies on a mix of direct message mutations, an event allowlist, reconnect throttling, and follow-up refreshes.
- Some state changes are applied locally, but full convergence still depends on `scheduleRealtimeRefresh()` and the 20-second polling fallback.
- WebSocket recovery can be delayed by stale thresholds, auth-state checks, or tab lifecycle events, which is safe but not yet pilot-tight.

**Exact files involved**

- [backend/static/modules/health_isf/health-isf.js](backend/static/modules/health_isf/health-isf.js)
- [backend/app/modules/health_isf/ai_dispatch.py](backend/app/modules/health_isf/ai_dispatch.py)
- [backend/app/modules/health_isf/ai_operations_routes.py](backend/app/modules/health_isf/ai_operations_routes.py)
- [backend/app/modules/health_isf/realtime_service.py](backend/app/modules/health_isf/realtime_service.py)
- [backend/app/modules/health_isf/realtime.py](backend/app/modules/health_isf/realtime.py)

**Fix approach**

- Close the pilot-critical event coverage gaps in `applyRealtimeUpdate(...)` so core ride and driver changes converge without relying on the next refresh loop.
- Keep the reconnect/backoff design, but tighten recovery for silent socket degradation.
- Preserve the existing realtime architecture; improve event handling and recovery behavior only.
- Make the frontend treat websocket health as operationally relevant, not just informational.

**Test plan**

- Validate ride create, assign, accept, and status-change events while watching for immediate UI updates.
- Force socket disconnects and confirm the reconnect path restores live updates.
- Verify background-tab and foreground-tab transitions do not leave the board stale.
- Confirm no duplicate events are rendered after reconnect or refresh.
- Run browser console capture and network inspection to confirm no websocket-related JavaScript errors.

## 3. Dashboard Refresh Consistency

**Risk level:** High

**Root cause**

- Dashboard cards are assembled from multiple backend responses fetched in one `Promise.all(...)` bundle, but they do not all share one strict freshness boundary.
- Some dashboard metrics mix `state.enterpriseDashboard` and `state.dashboard` values in the same rendered surface.
- The current model still depends on periodic refresh and route-triggered hydration, which can leave adjacent KPIs slightly out of sync.

**Exact files involved**

- [backend/static/modules/health_isf/health-isf.js](backend/static/modules/health_isf/health-isf.js)
- [backend/app/modules/health_isf/ai_dispatch.py](backend/app/modules/health_isf/ai_dispatch.py)
- [backend/app/modules/health_isf/ai_operations_routes.py](backend/app/modules/health_isf/ai_operations_routes.py)

**Fix approach**

- Make pilot-critical dashboard cards use one authoritative freshness boundary per render.
- Keep the current dashboard layout and metric set intact.
- If a subset of supporting data is stale or unavailable, render a degraded state instead of mixing snapshots.
- Keep polling as a fallback, not as the primary consistency mechanism.

**Test plan**

- Refresh the dashboard after a ride assignment and verify all pilot-critical counters agree.
- Compare dashboard values immediately after a mutation and again after the next poll to confirm no visible drift.
- Navigate between dispatch, rides, and dashboard routes and verify the dashboard state is consistent on return.
- Validate dashboard cards against backend responses to ensure no mixed-snapshot values are rendered.

## 4. Driver Dropdown Staleness

**Risk level:** High

**Root cause**

- The dispatch worklist builds driver dropdown options from the current in-memory driver snapshot.
- The current filter includes drivers whose availability is `available` or `assigned`, which can surface a stale or misleading choice to the operator.
- The rides table uses a different assignability rule, so the same driver can appear eligible in one surface and ineligible in another.

**Exact files involved**

- [backend/static/modules/health_isf/health-isf.js](backend/static/modules/health_isf/health-isf.js)

**Fix approach**

- Make one canonical assignability rule for all pilot dispatch surfaces.
- Remove stale or misleading driver choices from the dropdowns.
- Revalidate driver eligibility at action time so a stale render cannot produce an invalid assignment choice.
- Keep the existing dispatch workflow and table layout unchanged.

**Test plan**

- Create a dispatch worklist with a mix of available, assigned, and unavailable drivers.
- Verify only truly assignable drivers appear as selectable options.
- Reassign or complete a ride, then refresh and confirm the dropdown updates immediately.
- Attempt an assignment with a stale selection and confirm the UI blocks the invalid choice before the backend rejection path.

## Pilot Deployment Exit Criteria

Pilot readiness is acceptable only when all of the following are true:

- SQLite lock cleanup runs without recurring `database is locked` failures.
- WebSocket-driven state updates converge without operator-visible stale windows in pilot flows.
- Dashboard refreshes show one consistent snapshot for pilot-critical KPIs.
- Driver dropdowns only expose valid, current assignment options.

## Notes

- This plan intentionally excludes feature work and architecture changes.
- All work here is stabilization-only and should be validated against the live dispatcher workflow before pilot rollout.