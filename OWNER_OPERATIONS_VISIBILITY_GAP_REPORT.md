# Owner Operations Visibility Audit - Gap Report

Generated: 2026-06-09
Scope: mapping only (no build changes)
Owner persona: admin/owner command center

## Evidence Basis
- Owner role context and route model in [backend/static/ops-shell.js](backend/static/ops-shell.js#L97).
- Owner dispatch surface in [backend/static/ops-shell.js](backend/static/ops-shell.js#L6162).
- Owner trip lifecycle monitor in [backend/static/ops-shell.js](backend/static/ops-shell.js#L6167).
- Dispatcher queue lifecycle bucketing in [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py#L9214).
- Lifecycle states and timestamps in [backend/app/modules/health_isf/models.py](backend/app/modules/health_isf/models.py#L324).
- Dispatch assignment timestamps available in [backend/app/modules/health_isf/schemas.py](backend/app/modules/health_isf/schemas.py#L471).

## Executive Summary
- Owner can see lifecycle progress primarily on /app/dispatch and /app/trips.
- Several requested states are not first-class owner views; they are merged into broad buckets (active/delayed/completed).
- Critical timestamps and reasons exist in backend models/schemas but are not fully surfaced in owner UI tables.
- Largest visibility gaps: driver accepted, driver rejected reasoning, pickup-complete, and dropoff-complete as explicit owner states.

## State-by-State Mapping

| State | 1) Current Screen | 2) Missing Screen | 3) Missing Data | 4) Recommended Improvement |
|---|---|---|---|---|
| New rides | /app/dispatch: Active Trip Queue + Pending Intake metric (Trip Progress Visibility). See [backend/static/ops-shell.js](backend/static/ops-shell.js#L5199). | No dedicated "New Intake" owner drill-down screen with sortable SLA columns. | No explicit intake ownership, retry count, or intake validation failures in owner table rows. | Add owner "New Ride Intake" board with filters by wait time/SLA/risk and row-level ownership.
| Assigned rides | /app/dispatch: Assigned metric + queue stage badges. See [backend/static/ops-shell.js](backend/static/ops-shell.js#L5199). | No dedicated "Assigned Awaiting Driver Action" queue page. | Assignment offer lifecycle timestamps (offered_at, assigned_at) not visible in owner queue rows though available in API schema. | Add assigned queue tab showing offer age, assigned_at, driver ETA, reassignment attempt count.
| Driver accepted rides | Partially visible as "active" or as progress movement after acceptance; backend groups accepted into active. See [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py#L9256). | Missing explicit "Driver Accepted" owner state/screen. | accepted_at is available in backend assignment schema but not surfaced as a dedicated owner KPI/table column. | Add explicit "Accepted" bucket and KPI card with acceptance latency and acceptance rate.
| Driver rejected rides | /app/dispatch: Reassignment Workflow Queue and delayed/escalation indications. See [backend/static/ops-shell.js](backend/static/ops-shell.js#L5199). | Missing dedicated "Rejected Offers" owner panel. | Rejection reason taxonomy and closed_reason not consistently visible to owner; rejected vs expired are merged operationally. | Add rejected-offer queue with reason, driver, attempt_index, auto-recovery outcome.
| En route rides | /app/dispatch: Driver En Route and In Transit metrics; active trip table route status. See [backend/static/ops-shell.js](backend/static/ops-shell.js#L5199). | No separate map-first en-route owner screen. | enroute_at timestamp and route progress percent are not consistently exposed in owner rows. | Add en-route live map/list view with enroute_at, ETA drift, and geofence status.
| Arrived rides | /app/dispatch shows arrived-related labels through route status mapping; also lifecycle grouped in active. | No explicit "Arrived at Pickup" owner queue separate from arrived-at-facility labeling. | Ambiguity between arrived_pickup and arrived_facility states; arrival proof metadata not consistently surfaced to owner. | Split arrival into pickup-arrived and destination-arrived with distinct badges and timestamps.
| Pickup completed rides | Indirectly represented as patient onboard / in-progress flow in dispatch metrics. See [backend/static/ops-shell.js](backend/static/ops-shell.js#L5199). | Missing explicit "Pickup Complete" owner state screen. | pickup_complete_at exists in assignment schema but is not visible in owner command center tables. | Add pickup-complete stage card + table with pickup_complete_at and handoff verification fields.
| Dropoff completed rides | Not represented as a distinct owner stage; effectively transitions to completed. | Missing explicit "Dropoff Complete" pre-close state screen. | dropoff_complete_at exists in assignment schema but is not shown separately before final completion KPI. | Add dropoff-complete stage with closure checklist (proof, note, exceptions) before completed ledger.
| Completed rides | /app/dispatch completed metric + /app/trips completed metric and timeline. See [backend/static/ops-shell.js](backend/static/ops-shell.js#L6167). | No dedicated owner "Completed Ride Ledger" operational screen with reconciliation view. | Completion evidence bundle (arrival/pickup/dropoff timestamps, actor IDs, exception flags) not unified in one owner view. | Add completed ledger with export, reconciliation filters, and full lifecycle evidence columns.

## Cross-Cutting Gaps
1. State granularity mismatch
- Owner UI aggregates multiple lifecycle states into broad buckets, while backend tracks finer states.

2. Timestamp visibility gap
- Backend stores/schemas include rich timestamps, but owner tables expose only a subset.

3. Rejection observability gap
- Rejected and expired offers are not a first-class owner workflow with reason analytics.

4. Completion evidence gap
- Completed counts exist, but owner lacks a single authoritative evidence ledger for operational audit.

## Prioritized Recommendations (Mapping Phase)
1. Add a dedicated owner lifecycle board with one column per requested state.
2. Surface assignment and ride timestamps (assigned_at, accepted_at, enroute_at, pickup_complete_at, dropoff_complete_at, completed_at) in owner tables.
3. Split rejected/expired/timeout outcomes into distinct owner views with reasons and recovery status.
4. Add a completed-ride evidence ledger for operational and audit traceability.

## Mapping Verdict
- Owner visibility is partially present but not state-complete for the requested lifecycle audit.
- Requested states fully visible as first-class owner screens: New, Assigned, Completed (partial).
- Requested states missing explicit owner-first views: Driver Accepted, Driver Rejected, Pickup Completed, Dropoff Completed.
