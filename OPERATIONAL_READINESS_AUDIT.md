# Operational Readiness Audit Report
**Date:** 2026-05-30  
**Backend:** FastAPI on `http://127.0.0.1:8011`  
**Frontend:** `backend/static/ops-shell.js` (monolithic SPA)  
**Method:** Static code analysis + Playwright network intercept + authenticated API probe  

---

## Methodology

1. **Playwright network intercept** — navigated to each workspace URL, captured all API requests/responses, enumerated action buttons and visible tables.
2. **Unauthenticated API probe** — confirmed HTTP status codes for all ops endpoints (401 = exists and auth-gated; 404 = missing).
3. **Authenticated API probe** — logged in as `admin@amicor.local` and called `/api/ops/workspace/activation` to see actual module contents.
4. **Static source analysis** — read `renderVehicles()`, `renderBilling()`, `renderDrivers()`, `renderProviders()` bodies to confirm hardcoded vs dynamic content.

---

## Summary Table

| WORKSPACE | API SOURCE | LIVE DATA? | PLACEHOLDER DATA? | ACTIONABLE? | READY FOR PRODUCTION? | STATUS |
|---|---|---|---|---|---|:---:|
| **Dispatch** | `/api/ops/workspace/activation` | ✅ YES — 156 unassigned trips, 74 active routes, 9 drivers, 7 reassignments (when authenticated) | Demo fallbacks active when unauthenticated | ✅ `/api/ops/workspace/action` implemented | Partial — needs auth session + populated org data | 🟡 YELLOW |
| **Drivers (admin role)** | `/api/system/supervision` only | ❌ NO — supervision event count signals only | ✅ YES — "Route Alpha / Beta / Gamma" hardcoded table, metrics show event keyword counts | ❌ No action buttons in admin view | Not ready | 🔴 RED |
| **Riders / Patients** | `/api/ops/workspace/activation` | ✅ YES — 240 trip entities, `patient_ride_coordination_queue` exists (when auth + rider role) | "Rider Workspace Unavailable" empty-state guard fires for admin role | ❌ No action buttons in admin/empty state | Role-dependent; empty for admin | 🟡 YELLOW |
| **Providers (admin role)** | `/api/system/supervision` only | ❌ NO — no live provider list | ✅ YES — "Provider Alpha / Beta / Gamma / Delta" (panel explicitly labeled "Placeholder Provider Table"); all metrics show "placeholder" literal | ❌ No action buttons | Not ready | 🔴 RED |
| **Vehicles** | `/api/system/health` + `/api/system/supervision` only | ❌ NO — no vehicle API, no vehicle DB table | ✅ YES — AMB-102 / SUV-219 / EV-044 hardcoded rows; "Vehicles Active: 18" is `Math.max(18, eventCount)` | ❌ No action buttons | Not ready | 🔴 RED |
| **Billing** | `/api/system/health` + `/api/system/supervision` only | ❌ NO — no billing API, no billing DB table | ✅ YES — Open Claims: 26, Approved: 14, Pending: 9, Rejected: 3 are hardcoded literals | ❌ No action buttons; links only | Not ready | 🔴 RED |
| **Mobile** | `/api/system/supervision` only | ❌ NO — no dedicated mobile API | ✅ YES — "Driver License / Medical Card / CPR Certificate / Insurance" compliance table is hardcoded with static expiry days | ❌ No action buttons | Not ready | 🔴 RED |

---

## Workspace-by-Workspace Detail

### 🟡 DISPATCH (`/app/dispatch`)

**API Calls Made (authenticated):**
- `GET /api/ops/workspace/activation` → `workspace_modules` populated with live DB data

**Live Data Available (confirmed via authenticated probe):**
| Module | Count |
|---|---|
| `trip_unassigned_queue` | 156 |
| `trip_active_routes` | 74 |
| `trip_driver_availability` | 9 |
| `trip_reassignment_queue` | 7 |
| `trip_operational_entities` | 240 |
| `trip_medicaid_nemt` | 227 |
| `escalation_review_panel` | 375 |
| `escalation_audit_timeline` | 18 |
| `trip_audit_review` | 80 |
| `trip_route_progress_tracking` | 74 |

**Unauthenticated fallback:** `buildDemoTransportRecords()`, `buildDemoDriverAvailability()`, `buildDemoEscalationSignals()`, `buildDemoReassignmentQueue()`, `buildDemoNoDriverRecovery()` — synthetic demo data.

**Action Endpoint:** `/api/ops/workspace/action` — **EXISTS** at `operational_hydration_router.py:2412`. Returns 401 without token. Functional when authenticated.

**Gaps:**
- Session must be active for any live data to load
- Unauthenticated visitors see entirely synthetic demo content
- Map panel renders as placeholder (no live geospatial feed)

---

### 🔴 DRIVERS (`/app/drivers`, admin role)

**API Calls Made:** `GET /api/system/health`, `GET /api/system/supervision` only.

**Hardcoded content (confirmed in `renderDrivers()`):**
```js
var routeRows = [
  { name: "Route Alpha", status: "active", eta: "12m", ... },
  { name: "Route Beta",  status: "boarding", eta: "19m", ... },
  { name: "Route Gamma", status: "handoff", eta: "27m", ... }
];
```
These 3 rows are the **only** content in the route/assignment table.

**Live signals used:** Supervision event keyword counts (`countEventsByKeyword(events, "driver")`) — these are real but represent system log events, not actual driver assignment records.

**Role exceptions:**
- `driver` role → `renderDriverDashboard(phase17)` — uses workspace_modules (live data)
- `driver_support` role → `renderDriverSupportDashboard(phase17)` — uses workspace_modules including `trip_active_routes` and `trip_driver_availability` (live data)
- `dispatcher` / `supervisor` → `renderDispatcherDashboard(phase17)` — live data

**Admin view is not connected to any driver DB table.** No backend `/api/drivers` or similar endpoint exists.

---

### 🟡 RIDERS / PATIENTS (`/app/riders`, `/app/patients`)

**API Calls Made:** `GET /api/system/health`, `GET /api/system/supervision` only (unauthenticated).

**Unauthenticated render:** Shows "Rider Workspace Unavailable" panel — explicit empty-state guard.

**Live data available (authenticated + rider role):** `trip_operational_entities: 240`, `patient_ride_coordination_queue`, `appointment_pickup_dropoff_risk: 53`, `recurring_medical_schedule`, `trip_medicaid_nemt: 227`.

**Rider role** → `renderRiderDashboard(phase17)` renders full ride request, live trip tracking, recurring schedule panels.

**Admin view gap:** Admin logging into `/app/riders` hits the `riderEmptyState` guard — no rider-specific data is surfaced even when authenticated, because admin role is not gated to rider module extraction.

---

### 🔴 PROVIDERS (`/app/providers`, admin role)

**API Calls Made:** `GET /api/system/health`, `GET /api/system/supervision` only.

**Hardcoded content (confirmed in `renderProviders()`):**
```js
var tableRows = [
  { name: "Provider Alpha", status: "verification_pending", ... },
  { name: "Provider Beta",  status: "onboarding", ... },
  { name: "Provider Gamma", status: "ready_placeholder", ... },
  { name: "Provider Delta", status: "verified_placeholder", ... }
];
```
Panel title is literally **"Placeholder Provider Table"**. Metric cards display the string `"placeholder"` verbatim.

**Role exceptions:**
- `provider` role → `renderProviderDashboard()` — role-specific dashboard
- `medical_coordinator`, `compliance_officer`, `supervisor` → their own role dashboards

**No backend `/api/providers` endpoint.** The workspace_modules `provider_sync_queue: 0` is empty in current DB state.

---

### 🔴 VEHICLES (`/app/vehicles`)

**API Calls Made:** `GET /api/system/health`, `GET /api/system/supervision` only.

**Hardcoded content (confirmed in `renderVehicles()`):**
```js
'<tr><td>AMB-102</td><td>Medical Van</td><td>Operational</td><td>Available</td></tr>'
'<tr><td>SUV-219</td><td>Assisted Ride</td><td>In Service</td><td>Assigned</td></tr>'
'<tr><td>EV-044</td><td>EV Shuttle</td><td>Charging</td><td>Standby</td></tr>'
```
Metrics use `Math.max(18, eventCount)` — floored to 18 regardless of real fleet count.

**No DB table, no API endpoint, no vehicle model.** This workspace has no backend foundation.

---

### 🔴 BILLING (`/app/billing`)

**API Calls Made:** `GET /api/system/health`, `GET /api/system/supervision` only.

**Hardcoded content (confirmed in `renderBilling()`):**
```js
renderMetric("Open Claims", "26")
renderMetric("Approved Today", "14")
renderMetric("Pending Review", "9")
renderMetric("Rejected", "3")
```
All four metrics are hardcoded string literals. No computation, no DB read.

**No billing table, no claims API endpoint.** Quick links navigate to other workspaces only.

---

### 🔴 MOBILE (`/app/mobile`)

**API Calls Made:** `GET /api/system/health`, `GET /api/system/supervision` only.

**Hardcoded content:** Driver compliance documents table (Driver License / Medical Card / CPR Certificate / Insurance with static expiry countdowns). App ecosystem tiles (Driver App, Rider App, Dispatch App, Provider App) are informational panels with no backend.

**Supervision events** are used for event-count signals (live but not meaningful for mobile operations).

**No dedicated mobile API.** Serves as an informational preview of the four app surfaces.

---

## Backend Endpoint Status

| Endpoint | Status | Notes |
|---|---|---|
| `GET /api/system/health` | ✅ 200 | Live — 395KB response, test pass counts, runtime telemetry |
| `GET /api/system/supervision` | ✅ 200 | Live — backend_status: green, uptime, event counts |
| `GET /api/ops/dashboard-summary` | ✅ 401 (auth-gated) | Implemented, requires Bearer token |
| `GET /api/ops/live-status` | ✅ 401 (auth-gated) | Implemented |
| `GET /api/ops/alerts` | ✅ 401 (auth-gated) | Implemented |
| `GET /api/ops/recommendations` | ✅ 401 (auth-gated) | Implemented |
| `GET /api/ops/workspace/activation` | ✅ 401 (auth-gated) | **Real data confirmed** — 240 trips, 156 unassigned, 74 active routes |
| `POST /api/ops/workspace/action` | ✅ 401 (auth-gated) | Implemented at `operational_hydration_router.py:2412` |
| `GET /api/ops/compliance/dashboard-summary` | ✅ 401 (auth-gated) | Implemented |
| `GET /api/ops/orchestration/*` | ✅ 401 (auth-gated) | Implemented |
| `/api/drivers` | ❌ Does not exist | No driver list API |
| `/api/providers` | ❌ Does not exist | No provider list API |
| `/api/vehicles` | ❌ Does not exist | No vehicle API |
| `/api/billing` | ❌ Does not exist | No billing/claims API |
| `backend/app/routes/ops_metrics.py` | ❌ EMPTY FILE | No routes implemented |

---

## Root Causes

### 1. Auth hydration not firing in Playwright (unauthenticated)
Every workspace only made `GET /api/system/health` and `GET /api/system/supervision`. The `loadBackendData()` call in `ops-shell.js` is gated on `state.token` — without a session, all 15+ ops API calls are skipped and workspaces render in degraded/demo mode.

### 2. Vehicles and Billing have no backend
These two workspaces are pure UI shells. No vehicle model, no billing model, no API endpoints. The static metrics (AMB-102, Open Claims: 26) appear to be design-time placeholder values that were never replaced.

### 3. Providers and Drivers (admin view) use explicit placeholders
The `renderProviders()` function has the comment-equivalent of "static table scaffold" in its panel titles and uses the literal string `"placeholder"` in metric values. The `renderDrivers()` admin view uses a hardcoded 3-row route table. Both functions are marked as non-actionable in their panel descriptions.

### 4. Role-gated workspaces work correctly
When the correct role is logged in (driver, driver_support, provider, dispatcher, supervisor, compliance_officer), these workspaces render from live `workspace_modules` data. The problem is the **admin fallback view** for Drivers and Providers shows no live data.

---

## Recommendations

| Priority | Action |
|---|---|
| 🔴 P1 | **Vehicles**: Create `HealthISFVehicle` model and `/api/ops/workspace/activation` vehicle modules — or remove workspace from nav until implemented |
| 🔴 P1 | **Billing**: Create billing/claims model and populate workspace module — or remove workspace from nav until implemented |
| 🟡 P2 | **Drivers (admin view)**: Replace hardcoded Route Alpha/Beta/Gamma with `trip_active_routes` from workspace_modules (already has 74 live items) |
| 🟡 P2 | **Providers (admin view)**: Remove "Placeholder Provider Table" — wire to compliance `profiles` array which already has 65 items with onboarding status |
| 🟡 P2 | **Riders (admin view)**: Admin role should see trip coordination summary from workspace_modules instead of empty state |
| 🟢 P3 | **Mobile**: Replace hardcoded compliance doc table with live data from `missing_document_support` and `driver_onboarding_queue` modules |
| 🟢 P3 | **Auth session persistence**: Ensure `loadBackendData()` retries after session restore so workspaces don't silently degrade after page reload |
