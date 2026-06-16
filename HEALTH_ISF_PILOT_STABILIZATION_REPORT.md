# Health ISF Pilot Stabilization Report

**Date:** 2026-06-03
**Status:** Dispatcher workflow passed end-to-end; stabilization work remains before pilot deployment.
**Scope:** Stabilization only. No new features. No auth redesign. No role-system redesign.

## Executive Summary

The dispatcher workflow is now operational end-to-end, including ride creation, driver assignment, ride state persistence, dashboard navigation, and post-fix JavaScript validation. The remaining work is not feature work. It is stabilization work required to reduce operator confusion, prevent stale operational state, and harden runtime behavior under pilot load.

The highest-risk open items are:

1. SQLite lock contention in runtime-governor assignment-lock cleanup.
2. Websocket state convergence still depending on a fixed event allowlist plus 20-second polling.
3. Dispatch assignment UI still exposing drivers that are not truly assignable at the moment of action.

## Evidence Base

- End-to-end dispatcher workflow passed in the live UI on June 3, 2026.
- Backend log review found no request-path 500s during the tested dispatcher flow.
- Backend log review did find repeated background errors for assignment-lock cleanup.
- Current report is grounded in the active implementation under `backend/static/modules/health_isf/health-isf.js`, `backend/static/ops-shell.js`, and `backend/app/modules/health_isf/runtime_governor.py`.

## 1. Remaining UI Issues

| Severity | Issue | Evidence | Pilot Risk | Stabilization Task |
|---|---|---|---|---|
| High | Dispatch worklist still exposes drivers with `availability === assigned` as selectable assignment targets. | `backend/static/modules/health_isf/health-isf.js` in the dispatch worklist includes `return availability === 'available' || availability === 'assigned';` before building the assignment dropdown. | Operators can select a driver that appears assignable in the UI but is already committed elsewhere, producing avoidable rejection noise during live dispatch. | Restrict assignment controls to truly assignable drivers only and keep disabled/unavailable states explicit in the existing control. |
| Medium | Assignment validation and assignment failure still use blocking `window.alert(...)` dialogs in the rides table and dispatch worklist. | `backend/static/modules/health_isf/health-isf.js` uses blocking alerts for missing-driver validation and assignment failure in the click handlers around the rides table and dispatch worklist. | Blocking modal dialogs interrupt operator flow and provide poor recovery guidance during rapid multi-ride dispatching. | Replace alert-based operator interruption with the module's existing non-blocking error surface and keep the current behavior model unchanged. |
| Low | The outer ops shell and the embedded Health ISF workspace persist different session/runtime state keys and can present conflicting role/session cues. | `backend/static/ops-shell.js` uses `amicor_shell_session_v1`; `backend/static/modules/health_isf/health-isf.js` uses `amicor_health_isf_runtime_state_v1` and `amicor_health_isf_shell_role_override_v1`. | Pilot operators and support staff can misread the active role/session when diagnosing access or refresh behavior. | Align displayed session/role cues so the shell and Health ISF workspace do not present contradictory operator context. |

## 2. Remaining Dashboard Refresh Issues

| Severity | Issue | Evidence | Pilot Risk | Stabilization Task |
|---|---|---|---|---|
| High | Dashboard freshness still depends on a combination of websocket-triggered refreshes and a 20-second polling loop. | `backend/static/modules/health_isf/health-isf.js` schedules a refresh for only selected realtime events and also runs `refreshData()` every 20 seconds in `startAutoRefresh()`. | If a relevant runtime change is not captured by the websocket refresh allowlist, dashboard metrics can remain stale until the next polling interval, focus event, or visibility event. | Make dashboard convergence deterministic for core ride/driver/dispatch state changes without relying on the next poll window. |
| Medium | Dashboard aggregate cards mix data from separate endpoints in the same rendered summary. | The aggregate summaries pull fields from both `state.enterpriseDashboard` and `state.dashboard` in the same objects, including `completed_rides` / `total_trips_completed` from one source and queue/utilization data from another. | Adjacent dashboard cards can show internally inconsistent snapshots after refresh skew or partial endpoint lag, reducing operator trust in the board. | Normalize dashboard card construction so a single rendered snapshot uses one authoritative freshness boundary for pilot-critical KPIs. |
| Low | Advanced dashboard intelligence is route-gated and only fetched when the active route is `dashboard` or `analytics`. | `refreshData()` conditionally fetches enterprise, AI, governance, runtime-state, and replay data only when `wantsDashboardIntelligence` is true. | Operators who stay on dispatch for long periods can land on a dashboard that is fresh only after a subsequent route-triggered refresh cycle. | Ensure route changes into dashboard views force an immediate authoritative refresh for all dashboard intelligence dependencies. |

## 3. Remaining Websocket Issues

| Severity | Issue | Evidence | Pilot Risk | Stabilization Task |
|---|---|---|---|---|
| High | Websocket updates are only authoritative for the event types explicitly handled and refresh-triggered in the frontend allowlist. | `backend/static/modules/health_isf/health-isf.js` applies local mutations in `applyRealtimeUpdate(...)`, but only a fixed set of normalized event types triggers `scheduleRealtimeRefresh()`. | New, renamed, or partially-modeled events can update one local surface while leaving dependent surfaces stale until the next full refresh. | Tighten realtime event handling so pilot-critical ride and driver state transitions always converge across dispatch, rides, drivers, and dashboard surfaces. |
| Medium | Silent websocket degradation can persist for up to 45 seconds before stale-socket reconnect logic forces recovery. | `REALTIME_STALE_THRESHOLD_MS` is `45000`, and reconnect-on-stale only occurs when the connection is open but considered inactive long enough. | An operator can sit on a seemingly healthy page while live state is already behind, especially during lower-volume windows. | Reduce stale-detection exposure for pilot-critical routes and verify reconnect behavior under low-volume and intermittent-loss conditions. |
| Medium | Reconnect recovery is guarded by throttling, backoff, and auth-state checks that can intentionally suppress reconnect attempts. | `canReconnectRealtime(...)` suppresses duplicate reconnects, and `scheduleRealtimeReconnect(...)` can halt into `auth_required` when token recovery is unavailable. | Recovery behavior is safe, but if session/token drift occurs during pilot operations the module can stay degraded longer than the operator expects. | Validate reconnect and token-recovery behavior under forced socket close, token expiry, and tab-suspension scenarios before pilot cutover. |

## 4. Remaining Stale Data Issues

| Severity | Issue | Evidence | Pilot Risk | Stabilization Task |
|---|---|---|---|---|
| High | Driver availability shown in assignment controls is snapshot-based and currently permits stale or already-assigned drivers to appear selectable. | Dispatch worklist option generation uses `driver.availability || driver.status`, and the current filter explicitly includes `assigned` drivers in the selectable set. | Operators can make assignment decisions from stale availability labels and only learn the truth after a backend rejection. | Make assignment surfaces consume one authoritative assignability rule and refresh that rule immediately after state-changing events. |
| Medium | Different surfaces use different availability fields for the same fleet state. | Dispatch-load messaging counts only `driver.status === 'available'`, while dispatch assignment options label availability using `driver.availability || driver.status`. | The same driver pool can appear "stable" in one surface and effectively unavailable in another, creating avoidable dispatch hesitation. | Normalize pilot-critical availability logic so every dispatch-facing surface uses the same assignability semantics. |
| Medium | Assignment controls in the rides table are generated from the current `state.drivers` snapshot and remain valid until the next refresh cycle. | The rides-table assignment control builds dropdown options from the current `state.drivers` array, while refresh is still poll/hydration/realtime dependent. | A driver can change state after render but before click, especially with multiple operators or driver workflow changes in progress. | Revalidate assignability at action time and refresh the affected row state immediately after every assignment-related transition. |

## 5. Remaining Production Blockers

| Severity | Blocker | Evidence | Why It Blocks Pilot Readiness | Required Stabilization Outcome |
|---|---|---|---|---|
| Critical | SQLite lock contention is already occurring in assignment-lock cleanup. | `backend/app/modules/health_isf/runtime_governor.py` logs `runtime_governor_lock_cleanup_failed` when `ConcurrentAssignmentService.cleanup_expired_locks(db)` raises; backend log review shows repeated `database is locked` failures against `health_isf_assignment_locks`. | Pilot dispatch is a concurrency-heavy workflow. Repeated lock contention in the realtime assignment-lock subsystem is an operational risk, even if the current failures are background-only during test traffic. | Eliminate recurring assignment-lock cleanup failures under expected pilot concurrency, or move the lock path onto infrastructure that supports the expected write pattern. |
| High | Realtime board convergence is not yet robust enough to rely on websocket delivery alone. | Frontend convergence still depends on partial local mutation, allowlisted refresh triggers, and a 20-second polling fallback. | Pilot operators need the dispatch board to be trustable under multi-actor changes. A missed or unmapped event can leave the board temporarily wrong. | Demonstrate deterministic convergence for core ride/driver state changes across websocket, refresh, and reconnect paths. |
| High | Assignment UI can still invite invalid operator actions that the backend later rejects. | Dispatch worklist currently offers drivers with `availability === assigned` as selectable options. | This is not a data-integrity failure because the backend rejects invalid assignments, but it is still a pilot blocker because it creates operator confusion and false-negative workflow noise. | Bring UI assignability in line with backend rules before pilot users rely on the workflow. |

## Recommended Stabilization Order

1. Fix assignment-lock contention and prove the cleanup path is quiet under pilot-like concurrency.
2. Make assignability rules authoritative and consistent across dispatch UI surfaces.
3. Tighten websocket-to-refresh convergence for ride and driver state transitions.
4. Remove mixed-snapshot dashboard rendering for pilot-critical KPIs.
5. Remove blocking alert dialogs and resolve split session/role presentation.

## Pilot Readiness Position

The dispatcher workflow itself is functional. Pilot deployment should be treated as **conditional** rather than fully clear. The system is past the feature-completeness barrier, but not yet past the runtime-hardening barrier. The pilot should not proceed until the critical blocker around assignment-lock cleanup is resolved and the high-severity board/assignability consistency issues are closed.