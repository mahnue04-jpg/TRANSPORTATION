# Operational Truth Report

**Scope:** Amicor Health ISF platform operational readiness audit, Phase 1

**Rule:** Discover and document current truth only. No fixes, no refactors, no schema changes.

**Evidence used:**
- Frontend shell: `backend/static/ops-shell.js`
- Auth backend: `backend/app/auth.py`
- Health ISF API: `backend/app/modules/health_isf/routes.py`
- Health ISF service layer: `backend/app/modules/health_isf/service.py`
- Health ISF models: `backend/app/modules/health_isf/models.py`
- Nova ops backend: `backend/app/core/nova/operational_hydration_router.py`, `backend/app/core/nova/compliance_router.py`
- Authenticated runtime probe against `http://127.0.0.1:8011`

## Summary

- Authentication is operational.
- Trips, dispatch, driver operations, rider/customer workspace, Nova AI workspace loading, and operational recommendations are backed by live endpoints and real tables.
- Vehicles and billing are only partially or minimally implemented from a workflow perspective; several requested workflows have no dedicated endpoint or UI support.
- Some admin fallback views in the shell render placeholder data even though role-scoped workspaces can load live data.

## Audit Matrix

| Workflow | Status |
|---|---|
| Authentication | GREEN |
| Riders | YELLOW |
| Trips | GREEN |
| Drivers | YELLOW |
| Vehicles | RED |
| Dispatch | GREEN |
| Billing | YELLOW |
| Nova AI | GREEN |

---

## A. Authentication

### 1) Login

WORKFLOW: Login  
STATUS: GREEN  
FRONTEND: No dedicated login page in the ops shell; auth state is handled through token-bearing session state and activation/login assistance panels in `backend/static/ops-shell.js`.  
BACKEND: `POST /api/auth/login` in `backend/app/auth.py`.  
DATABASE: `platform_users`, `platform_refresh_tokens`  
BLOCKERS: None observed. Login returns access and refresh tokens and logs an operational event.  
RECOMMENDED NEXT STEP: Keep login as the canonical entry point; verify the browser session restore path continues to populate token state after page reloads.

### 2) Session validation

WORKFLOW: Session validation  
STATUS: GREEN  
FRONTEND: Auth diagnostics panels in the shell read token presence and session age; hydration is gated on token state.  
BACKEND: `GET /api/auth/me`, `POST /api/auth/refresh`, `POST /api/auth/logout` in `backend/app/auth.py`.  
DATABASE: `platform_users`, `platform_refresh_tokens`  
BLOCKERS: None observed. `require_auth` and `get_current_user` reject missing or invalid tokens with 401.  
RECOMMENDED NEXT STEP: Continue validating refresh-token expiry and revocation behavior under real browser sessions.

### 3) Role enforcement

WORKFLOW: Role enforcement  
STATUS: GREEN  
FRONTEND: Role-specific render paths in `backend/static/ops-shell.js` branch to admin, dispatcher, rider, driver, provider, supervisor, compliance, and support dashboards.  
BACKEND: Role gates are enforced by `require_any_role`, `require_health_isf_access`, `require_health_isf_write_access`, `require_dispatcher_workflow_access`, `require_ops_access`, and similar dependencies in `backend/app/auth.py`, `backend/app/modules/health_isf/routes.py`, and Nova routers.  
DATABASE: `platform_users` plus role-scoped operational tables; no separate role table was found.  
BLOCKERS: None observed. Unauthorized access is denied with 403.  
RECOMMENDED NEXT STEP: Keep validating role-scoped endpoints with representative tokens for each persona.

---

## B. Riders

### 1) Create rider

WORKFLOW: Create rider  
STATUS: GREEN  
FRONTEND: Rider/customer creation is exposed through rider/customer workspace flows in `backend/static/ops-shell.js`, primarily under `/app/riders` and `/app/patients` aliasing.  
BACKEND: `POST /api/health-isf/customer-requests` in `backend/app/modules/health_isf/routes.py`, which calls `create_customer_ride_request` in `backend/app/modules/health_isf/service.py`.  
DATABASE: `health_isf_customer_ride_requests`, `health_isf_rides`, `health_isf_organizations`, `platform_users`  
BLOCKERS: This is not a rider-profile CRUD model; it is customer ride-request creation.  
RECOMMENDED NEXT STEP: Treat this as the operational rider intake workflow, not a standalone profile object.

### 2) Edit rider

WORKFLOW: Edit rider  
STATUS: YELLOW  
FRONTEND: Rider/customer workspace exists, but there is no dedicated rider-profile editor in the shell.  
BACKEND: Partial support only. The backend exposes `PATCH /api/health-isf/customer-requests/{request_id}/status` and dispatcher/customer-request action routes, but no separate rider profile update endpoint was found.  
DATABASE: `health_isf_customer_ride_requests`, `health_isf_rides`, `health_isf_ride_status_history`, `health_isf_dispatch_logs`  
BLOCKERS: No dedicated rider profile table or rider-edit API was found. Only ride/request state can be changed.  
RECOMMENDED NEXT STEP: Document this as a request-state workflow, not rider profile editing.

### 3) View rider

WORKFLOW: View rider  
STATUS: GREEN  
FRONTEND: `/app/riders` and `/app/patients` in `backend/static/ops-shell.js`; the rider dashboard renders live panels when role-scoped hydration is present.  
BACKEND: `GET /api/health-isf/customers/workspace/history`, `GET /api/health-isf/customers/workspace/active`, and `GET /api/health-isf/customers/workspace/live-tracking` in `backend/app/modules/health_isf/routes.py`.  
DATABASE: `health_isf_customer_ride_requests`, `health_isf_rides`, `health_isf_ride_status_history`, `health_isf_realtime_events`, `health_isf_dispatch_logs`, `health_isf_ride_route_plans`  
BLOCKERS: Admin fallback can show an empty state when role-scoped hydration is absent.  
RECOMMENDED NEXT STEP: Keep the rider workspace tied to authenticated rider/customer context.

### 4) Search rider

WORKFLOW: Search rider  
STATUS: YELLOW  
FRONTEND: Search is indirect via rider workspace history/active tracking and dispatcher queue filtering in `backend/static/ops-shell.js`.  
BACKEND: `GET /api/health-isf/customers/workspace/history?rider_phone=...`, `GET /api/health-isf/customers/workspace/active?rider_phone=...`, `GET /api/health-isf/customers/workspace/live-tracking?rider_phone=...`, and dispatcher queue search by passenger name in `GET /api/health-isf/dispatcher/queues?search_query=...`.  
DATABASE: `health_isf_customer_ride_requests`, `health_isf_rides`, `health_isf_dispatcher_activity`, `health_isf_realtime_events`  
BLOCKERS: No dedicated rider search endpoint or rider directory table was found.  
RECOMMENDED NEXT STEP: Treat search as phone-based workspace lookup and passenger-name queue filtering.

---

## C. Trips

### 1) Create trip

WORKFLOW: Create trip  
STATUS: GREEN  
FRONTEND: Trip creation is represented in `/app/trips` and dispatch/customer-request flows in `backend/static/ops-shell.js`.  
BACKEND: `POST /api/health-isf/rides` and `POST /api/health-isf/customer-requests` in `backend/app/modules/health_isf/routes.py`; service methods include `create_ride` and `create_customer_ride_request`.  
DATABASE: `health_isf_rides`, `health_isf_customer_ride_requests`, `health_isf_ride_status_history`, `health_isf_organizations`, `health_isf_providers`, `health_isf_drivers`  
BLOCKERS: None observed.  
RECOMMENDED NEXT STEP: Keep using the ride/customer-request separation as the actual trip intake model.

### 2) Schedule trip

WORKFLOW: Schedule trip  
STATUS: GREEN  
FRONTEND: Scheduling is surfaced through trip/dispatch/rider workspaces and recurring schedule views in `backend/static/ops-shell.js`.  
BACKEND: Scheduling state is represented through `scheduled_time` on customer requests and ride workflow endpoints; relevant surfaces include `POST /api/health-isf/customer-requests`, `GET /api/health-isf/customers/workspace/active`, and `GET /api/health-isf/customers/workspace/history`.  
DATABASE: `health_isf_customer_ride_requests`, `health_isf_rides`, `health_isf_ride_route_plans`, `health_isf_ride_status_history`  
BLOCKERS: Scheduling is modeled through request and ride state, not a separate scheduler service.  
RECOMMENDED NEXT STEP: Continue treating scheduling as a first-class field on the ride request record.

### 3) Update trip

WORKFLOW: Update trip  
STATUS: GREEN  
FRONTEND: Trip lifecycle controls are exposed in the dispatcher and driver dashboards in `backend/static/ops-shell.js`.  
BACKEND: `PATCH /api/health-isf/rides/{ride_id}/status`, `PATCH /api/health-isf/rides/{ride_id}/assign-driver`, `PATCH /api/health-isf/dispatcher/rides/{ride_id}/reassign-driver`, plus dispatcher lifecycle actions such as `mark-arrived`, `mark-onboard`, and `complete`.  
DATABASE: `health_isf_rides`, `health_isf_ride_status_history`, `health_isf_dispatch_logs`, `health_isf_ride_execution_actions`, `health_isf_dispatch_assignments`  
BLOCKERS: None observed.  
RECOMMENDED NEXT STEP: Keep trip mutations constrained to the authenticated dispatcher/driver flows.

### 4) Cancel trip

WORKFLOW: Cancel trip  
STATUS: GREEN  
FRONTEND: Cancel actions exist in dispatcher and workflow surfaces.  
BACKEND: `PATCH /api/health-isf/dispatcher/rides/{ride_id}/cancel` and `PATCH /api/health-isf/customer-requests/{request_id}/status` for request-state cancellation.  
DATABASE: `health_isf_rides`, `health_isf_customer_ride_requests`, `health_isf_ride_status_history`, `health_isf_dispatch_logs`  
BLOCKERS: None observed.  
RECOMMENDED NEXT STEP: Preserve cancellation as a tracked state transition with history.

---

## D. Drivers

### 1) Create driver

WORKFLOW: Create driver  
STATUS: RED  
FRONTEND: There is no direct create-driver form in the main shell. Driver onboarding is represented by a driver-application flow, not driver creation.  
BACKEND: `POST /api/health-isf/driver-applications` exists, but no direct `POST /api/health-isf/drivers` create endpoint was found.  
DATABASE: `health_isf_driver_applications`, `health_isf_drivers`  
BLOCKERS: No direct driver creation API or route was found.  
RECOMMENDED NEXT STEP: Treat driver creation as missing and separate from application onboarding.

### 2) Edit driver

WORKFLOW: Edit driver  
STATUS: GREEN  
FRONTEND: Driver surfaces are available in `/app/drivers` and the driver dashboard when role-scoped.  
BACKEND: `PATCH /api/health-isf/drivers/{driver_id}` in `backend/app/modules/health_isf/routes.py`; service layer includes `update_driver`.  
DATABASE: `health_isf_drivers`, `health_isf_vehicles`, `health_isf_driver_sessions`, `health_isf_driver_location_pings`  
BLOCKERS: None observed.  
RECOMMENDED NEXT STEP: Keep driver edits tenant-scoped and session-aware.

### 3) Driver availability

WORKFLOW: Driver availability  
STATUS: GREEN  
FRONTEND: Driver mobile and driver dashboard surfaces expose availability state.  
BACKEND: `POST /api/health-isf/drivers/availability`, `POST /api/health-isf/drivers/heartbeat`, `POST /api/health-isf/drivers/login`, `POST /api/health-isf/drivers/logout`, plus driver runtime state endpoints.  
DATABASE: `health_isf_drivers`, `health_isf_driver_sessions`, `health_isf_driver_location_pings`, `health_isf_trips`  
BLOCKERS: None observed.  
RECOMMENDED NEXT STEP: Keep availability updates tied to authenticated driver sessions.

### 4) Driver assignment

WORKFLOW: Driver assignment  
STATUS: GREEN  
FRONTEND: Assignment controls exist in dispatcher and driver workflow views.  
BACKEND: `PATCH /api/health-isf/rides/{ride_id}/assign-driver`, `POST /api/health-isf/dispatch/auto-assign`, `POST /api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver`, `PATCH /api/health-isf/dispatcher/rides/{ride_id}/reassign-driver`.  
DATABASE: `health_isf_dispatch_assignments`, `health_isf_rides`, `health_isf_dispatch_logs`, `health_isf_ride_execution_actions`, `health_isf_assignment_locks`, `health_isf_drivers`  
BLOCKERS: None observed.  
RECOMMENDED NEXT STEP: Maintain assignment locking and audit logging around every dispatch decision.

---

## E. Vehicles

### 1) Create vehicle

WORKFLOW: Create vehicle  
STATUS: RED  
FRONTEND: `/app/vehicles` renders a static fleet view in the shell.  
BACKEND: No vehicle create endpoint was found.  
DATABASE: `health_isf_vehicles` exists, but no exposed create workflow was found.  
BLOCKERS: No route or service method for vehicle creation was found.  
RECOMMENDED NEXT STEP: Document vehicle creation as missing.

### 2) Edit vehicle

WORKFLOW: Edit vehicle  
STATUS: RED  
FRONTEND: `/app/vehicles` is a static table of three hardcoded vehicles.  
BACKEND: No vehicle update endpoint was found.  
DATABASE: `health_isf_vehicles`  
BLOCKERS: No vehicle edit API or service layer was found.  
RECOMMENDED NEXT STEP: Document vehicle editing as missing.

### 3) Assign vehicle

WORKFLOW: Assign vehicle  
STATUS: RED  
FRONTEND: The driver relationship is visible in the shell only as a static fleet concept.  
BACKEND: No direct vehicle assignment endpoint was found.  
DATABASE: `health_isf_vehicles`, `health_isf_drivers`  
BLOCKERS: The model relationship exists, but no exposed assignment workflow was found.  
RECOMMENDED NEXT STEP: Document vehicle assignment as missing.

---

## F. Dispatch

### 1) Assign trip

WORKFLOW: Assign trip  
STATUS: GREEN  
FRONTEND: `/app/dispatch` and dispatcher-related controls in `backend/static/ops-shell.js`.  
BACKEND: `POST /api/ops/workspace/action`, `POST /api/health-isf/dispatch/auto-assign`, `POST /api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver`, `PATCH /api/health-isf/rides/{ride_id}/assign-driver`.  
DATABASE: `health_isf_dispatch_assignments`, `health_isf_rides`, `health_isf_dispatch_logs`, `health_isf_ride_execution_actions`, `health_isf_assignment_locks`  
BLOCKERS: None observed.  
RECOMMENDED NEXT STEP: Keep assignment actions audited and tenant-scoped.

### 2) Route dispatch

WORKFLOW: Route dispatch  
STATUS: GREEN  
FRONTEND: Dispatch board and route/reassignment surfaces in `backend/static/ops-shell.js`.  
BACKEND: `GET /api/health-isf/dispatch/queue`, `GET /api/health-isf/dispatch/active-assignments`, `POST /api/health-isf/dispatcher/rides/{ride_id}/auto-assign`, `POST /api/health-isf/dispatcher/customer-requests/{request_id}/auto-dispatch`, `POST /api/health-isf/dispatcher/rides/{ride_id}/claim-ownership`, `POST /api/health-isf/dispatcher/rides/{ride_id}/handoff-ownership`.  
DATABASE: `health_isf_dispatch_assignments`, `health_isf_dispatch_logs`, `health_isf_realtime_events`, `health_isf_dispatcher_activity`, `health_isf_ride_execution_actions`  
BLOCKERS: None observed.  
RECOMMENDED NEXT STEP: Keep dispatch routing on the live queue/lock model.

### 3) Route status updates

WORKFLOW: Route status updates  
STATUS: GREEN  
FRONTEND: Driver and dispatcher dashboards expose status transitions and progress updates.  
BACKEND: `PATCH /api/health-isf/dispatcher/rides/{ride_id}/mark-arrived`, `PATCH /api/health-isf/dispatcher/rides/{ride_id}/mark-onboard`, `PATCH /api/health-isf/dispatcher/rides/{ride_id}/complete`, `PATCH /api/health-isf/dispatcher/rides/{ride_id}/cancel`, `POST /api/health-isf/drivers/{driver_id}/set-status`, `POST /api/health-isf/drivers/{driver_id}/accept-ride`, and related driver lifecycle endpoints.  
DATABASE: `health_isf_rides`, `health_isf_ride_status_history`, `health_isf_dispatch_logs`, `health_isf_ride_execution_actions`, `health_isf_drivers`, `health_isf_driver_sessions`  
BLOCKERS: None observed.  
RECOMMENDED NEXT STEP: Continue preserving status history for every route transition.

---

## G. Billing

### 1) Invoice generation

WORKFLOW: Invoice generation  
STATUS: RED  
FRONTEND: `/app/billing` shows a static claims view.  
BACKEND: No dedicated invoice-generation endpoint was found.  
DATABASE: `health_isf_payment_transactions`, `health_isf_settlement_ledger`, `health_isf_payouts`  
BLOCKERS: No invoice table or invoice workflow was found.  
RECOMMENDED NEXT STEP: Document invoice generation as missing.

### 2) Claims

WORKFLOW: Claims  
STATUS: RED  
FRONTEND: Billing page displays static counters only; no claims workflow UI was found.  
BACKEND: No dedicated claims API was found.  
DATABASE: `health_isf_payment_transactions`, `health_isf_settlement_ledger`, `health_isf_payouts`  
BLOCKERS: No claims service or claims table was found.  
RECOMMENDED NEXT STEP: Document claims as missing.

### 3) Payment tracking

WORKFLOW: Payment tracking  
STATUS: GREEN  
FRONTEND: Billing-related surfaces exist in `/app/billing` and related trip/dispatch views.  
BACKEND: `POST /api/health-isf/payments/intents`, `POST /api/health-isf/payments/capture`, `POST /api/health-isf/payments/settle`, `GET /api/health-isf/payments/rides/{ride_id}`.  
DATABASE: `health_isf_payment_transactions`, `health_isf_settlement_ledger`, `health_isf_payouts`, `health_isf_rides`, `health_isf_drivers`, `health_isf_providers`  
BLOCKERS: No invoice or claims layer accompanies the payment ledger.  
RECOMMENDED NEXT STEP: Keep payment tracking separate from the missing invoice/claims workflows.

---

## H. Nova AI

### 1) Workspace loading

WORKFLOW: Workspace loading  
STATUS: GREEN  
FRONTEND: Nova/ops workspace loading is driven by `backend/static/ops-shell.js`, which calls hydration and live-status endpoints and gates on token presence.  
BACKEND: `GET /api/ops/workspace/activation` in `backend/app/core/nova/operational_hydration_router.py`. Authenticated probe returned live `workspace_modules` data with 240 trips, 156 unassigned queue items, 74 active routes, and 9 drivers available.  
DATABASE: `platform_operations_tasks`, `platform_operations_assignment_events`, `platform_operations_notification_events`, `platform_operations_stream_cursors`, `platform_operations_replay_sessions`, plus health-isf operational tables used to assemble the workspace payload.  
BLOCKERS: Unauthenticated sessions fall back to demo or empty-state behavior.  
RECOMMENDED NEXT STEP: Keep workspace loading tied to authenticated session hydration.

### 2) Tool execution

WORKFLOW: Tool execution  
STATUS: GREEN  
FRONTEND: Workspace actions are routed through the shell action gateway.  
BACKEND: `POST /api/ops/workspace/action`, `POST /api/ops/predictive/*`, `POST /api/ops/governance/*`, and orchestration/federation/replay endpoints in `backend/app/core/nova/operational_hydration_router.py` and `backend/app/core/nova/compliance_router.py`.  
DATABASE: `platform_operations_governance_predictions`, `platform_operations_constraint_profiles`, `platform_operations_risk_forecasts`, `platform_operations_capacity_predictions`, `platform_operations_decision_provenance`, `platform_operations_governance_memory`, `platform_operations_advisory_reasoning_chains`, `platform_operations_governance_rationales`  
BLOCKERS: None observed.  
RECOMMENDED NEXT STEP: Keep tool execution role-scoped and audit-backed.

### 3) Operational recommendations

WORKFLOW: Operational recommendations  
STATUS: GREEN  
FRONTEND: Recommendation panels are rendered in the ops shell and updated from hydration payloads.  
BACKEND: `GET /api/ops/recommendations` in `backend/app/core/nova/operational_hydration_router.py`; authenticated runs return live recommendation payloads.  
DATABASE: `platform_operations_optimization_recommendations`, `platform_operations_governance_trends`, `platform_operations_governance_drift_events`, `platform_assistant_operational_events`  
BLOCKERS: Recommendations are only as complete as the current workspace hydration payload.  
RECOMMENDED NEXT STEP: Keep recommendations aligned with live ops and governance data.

---

## Truth Notes

- `backend/app/routes/ops_metrics.py` is empty.
- `backend/static/ops-shell.js` contains placeholder-driven admin fallback views for some workflows, especially vehicles, billing, and admin provider/driver surfaces.
- The health-isf backend is much more complete than the default unauthenticated shell experience suggests.
- A bearer token is required for the ops hydration and action endpoints.
- The live system contains real operational data in the dispatch/trip/driver/rider pathway, but not in the vehicle and billing workflows requested here.
