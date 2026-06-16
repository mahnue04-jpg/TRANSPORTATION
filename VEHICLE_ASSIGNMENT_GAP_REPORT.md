# Vehicle Assignment Gap Report

**Mission:** Determine whether Amicor Health ISF can currently perform:

Trip -> Driver Assignment -> Vehicle Assignment -> Dispatch

**Verdict:** **No**. The platform can assign drivers to trips and dispatch trips, but it cannot currently assign a real vehicle to a real trip as an operational workflow.

**Overall classification:**
- Trip -> Driver Assignment: WORKING
- Vehicle Assignment: MISSING / STUBBED
- Dispatch: WORKING

---

## Executive Answer

**Can a dispatcher currently assign a real vehicle to a real trip?**

**No.**

### Exact blocker

There is **no trip-scoped vehicle assignment workflow** in the backend. The only vehicle relation in the data model is `HealthISFDriver.vehicle_id`, and even that relation is **not writable through the exposed driver update API**. The driver update schema and service layer explicitly exclude `vehicle_id`, and the frontend vehicle page is static/hardcoded.

### Operational impact

Trips can be assigned to drivers and moved through dispatch lifecycle states, but the system cannot bind a real vehicle to the trip in an exposed, repeatable, audited way. That means fleet coordination remains incomplete and the revenue chain cannot be treated as a real transportation operation.

---

## Ranked Findings

### 1) Vehicle Assignment Workflow Missing

**Rank:** CRITICAL  
**Current Status:** MISSING  
**Impact on Operations:** The platform cannot attach a specific fleet asset to an operational trip. This breaks the trip -> driver -> vehicle -> dispatch chain.  
**Exact Files Involved:**
- [backend/static/ops-shell.js](backend/static/ops-shell.js)
- [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py)
- [backend/app/modules/health_isf/service.py](backend/app/modules/health_isf/service.py)
- [backend/app/modules/health_isf/models.py](backend/app/modules/health_isf/models.py)
- [backend/app/modules/health_isf/schemas.py](backend/app/modules/health_isf/schemas.py)
  
**Exact APIs Involved:**
- None for vehicle create/edit/assign
- `PATCH /api/health-isf/drivers/{driver_id}` exists, but does not accept `vehicle_id`
- `PATCH /api/health-isf/rides/{ride_id}/assign-driver` exists, but only assigns drivers
  
**Exact Database Tables Involved:**
- `health_isf_vehicles`
- `health_isf_drivers`
- `health_isf_rides`
- `health_isf_dispatch_assignments`
- `health_isf_dispatch_logs`
  
**Exact Models Involved:**
- `HealthISFVehicle`
- `HealthISFDriver`
- `HealthISFRide`
- `HealthISFDispatchAssignment`
  
**Validation Rules:**
- `DriverUpdate` only allows `name`, `phone`, `status`, `is_active`, and `rating`
- `vehicle_id` is not allowed in the exposed driver update payload
- `assign_driver_to_ride()` enforces driver assignment only; it never writes a vehicle to the ride
  
**Role Permissions:**
- `require_health_isf_write_access` protects driver mutations
- `require_dispatcher_workflow_access` protects dispatch assignment routes
- No role permission exists for vehicle assignment because no vehicle assignment route exists
  
**Current Operational Status:**
- Frontend page: STUBBED
- UI components: STUBBED
- Backend routes: MISSING
- Service methods: MISSING
- Database tables: PARTIAL
- Models: PARTIAL
- Validation rules: WORKING for driver updates, but vehicle assignment fields are excluded
- Role permissions: PARTIAL
- API calls: MISSING
- Current operational status: MISSING
  
**Estimated Implementation Effort:** Medium  
**Reasoning:** The model exists, but the full operational contract does not.

---

### 2) Vehicle Page Is Static Shell Only

**Rank:** HIGH  
**Current Status:** STUBBED  
**Impact on Operations:** Dispatchers can see a fleet page, but it does not control real fleet assets or assignment state.  
**Exact Files Involved:**
- [backend/static/ops-shell.js](backend/static/ops-shell.js)
  
**Exact APIs Involved:**
- None
  
**Exact Database Tables Involved:**
- None directly used by the page
  
**Exact Models Involved:**
- None directly used by the page
  
**Validation Rules:**
- None
  
**Role Permissions:**
- Route is available to admin, dispatcher, compliance_officer, and supervisor in the shell navigation, but that is only page visibility
  
**Current Operational Status:**
- Frontend page: WORKING as a page, but STUBBED operationally
- UI components: STUBBED
- Backend routes: MISSING
- Service methods: MISSING
- Database tables: MISSING in usage
- Models: PARTIAL
- Validation rules: MISSING
- Role permissions: PARTIAL
- API calls: MISSING
- Current operational status: STUBBED
  
**Evidence:** `renderVehicles()` is hardcoded with `AMB-102`, `SUV-219`, and `EV-044`, and uses `Math.max(18, countEventsByKeyword(events, "vehicle"))` for metrics.

---

### 3) Driver Update Contract Excludes Vehicle Binding

**Rank:** HIGH  
**Current Status:** WORKING for driver edits, but vehicle binding is excluded  
**Impact on Operations:** The only exposed path that could have been used for vehicle assignment does not accept vehicle assignment data.  
**Exact Files Involved:**
- [backend/app/modules/health_isf/schemas.py](backend/app/modules/health_isf/schemas.py)
- [backend/app/modules/health_isf/service.py](backend/app/modules/health_isf/service.py)
- [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py)
  
**Exact APIs Involved:**
- `PATCH /api/health-isf/drivers/{driver_id}`
  
**Exact Database Tables Involved:**
- `health_isf_drivers`
- `health_isf_vehicles`
  
**Exact Models Involved:**
- `DriverUpdate`
- `HealthISFDriver`
- `HealthISFVehicle`
  
**Validation Rules:**
- `DriverUpdate` schema does not include `vehicle_id`
- `update_driver()` only permits `name`, `phone`, `status`, `is_active`, `rating`
  
**Role Permissions:**
- `require_health_isf_write_access`
  
**Current Operational Status:**
- Frontend page: PARTIAL
- UI components: PARTIAL
- Backend routes: WORKING for driver edits, but not vehicle assignment
- Service methods: WORKING for driver edits, but not vehicle assignment
- Database tables: PARTIAL
- Models: PARTIAL
- Validation rules: WORKING, but exclusionary
- Role permissions: WORKING
- API calls: WORKING for driver edits only
- Current operational status: PARTIAL

---

### 4) Trip Assignment Works, But Vehicle Is Never Bound

**Rank:** CRITICAL  
**Current Status:** PARTIAL  
**Impact on Operations:** Dispatch can assign a driver and advance ride state, but the trip never receives a vehicle assignment.  
**Exact Files Involved:**
- [backend/app/modules/health_isf/service.py](backend/app/modules/health_isf/service.py)
- [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py)
- [backend/app/modules/health_isf/models.py](backend/app/modules/health_isf/models.py)
  
**Exact APIs Involved:**
- `PATCH /api/health-isf/rides/{ride_id}/assign-driver`
- `POST /api/health-isf/dispatch/auto-assign`
- `PATCH /api/health-isf/dispatcher/rides/{ride_id}/reassign-driver`
  
**Exact Database Tables Involved:**
- `health_isf_rides`
- `health_isf_dispatch_assignments`
- `health_isf_dispatch_logs`
- `health_isf_ride_execution_actions`
- `health_isf_drivers`
- `health_isf_vehicles`
  
**Exact Models Involved:**
- `HealthISFRide`
- `HealthISFDispatchAssignment`
- `HealthISFDriver`
- `HealthISFVehicle`
  
**Validation Rules:**
- `assign_driver_to_ride()` requires a valid active driver in the same organization
- The function sets `ride.driver_id` and records dispatch assignments
- The function never sets `ride.vehicle_id` because no such field exists on the ride model
  
**Role Permissions:**
- `require_health_isf_write_access`
- `require_dispatcher_workflow_access`
  
**Current Operational Status:**
- Frontend page: WORKING for dispatching
- UI components: WORKING for driver assignment
- Backend routes: WORKING for driver assignment
- Service methods: WORKING for driver assignment
- Database tables: PARTIAL
- Models: PARTIAL
- Validation rules: WORKING for driver assignment only
- Role permissions: WORKING
- API calls: WORKING for driver assignment only
- Current operational status: PARTIAL

---

## Detailed Workflow Truth

### Trip -> Driver Assignment

**Status:** WORKING  
**Why:** The backend supports driver assignment to rides and dispatch state progression. The dispatch assignment table persists the assignment lifecycle.

### Driver -> Vehicle Assignment

**Status:** MISSING  
**Why:** The only vehicle relationship is `HealthISFDriver.vehicle_id`, but no exposed route or service method writes it. The driver update payload cannot carry it.

### Vehicle -> Trip Assignment

**Status:** MISSING  
**Why:** The ride model has no `vehicle_id`, and no route/service exposes a trip-scoped vehicle binding.

### Dispatch

**Status:** WORKING  
**Why:** Dispatch queue, auto-assign, reassign, and ride status transitions exist and are persisted.

---

## Exact Blocker

The exact blocker is the absence of a writable vehicle-assignment contract.

Specifically:
- No route exists to assign a vehicle to a ride
- No ride field exists to store a vehicle on the trip itself
- The driver update schema excludes `vehicle_id`
- The driver update service excludes `vehicle_id`
- The vehicle page is static and does not call backend APIs

This means a dispatcher can assign a driver, but cannot complete a real vehicle assignment workflow for a trip.

---

## Exact Files Involved

- [backend/static/ops-shell.js](backend/static/ops-shell.js)
- [backend/app/modules/health_isf/routes.py](backend/app/modules/health_isf/routes.py)
- [backend/app/modules/health_isf/service.py](backend/app/modules/health_isf/service.py)
- [backend/app/modules/health_isf/models.py](backend/app/modules/health_isf/models.py)
- [backend/app/modules/health_isf/schemas.py](backend/app/modules/health_isf/schemas.py)

---

## Exact Implementation Required

Truth only, no implementation:
- A writable vehicle-assignment path does not exist.
- The platform would need a real assignment contract that binds a specific vehicle to a real trip or driver in the backend.
- That contract would need route, service, and validation support, plus a UI action that invokes it.

---

## Operational Impact Ranking

1. **CRITICAL**: Vehicle assignment missing
2. **CRITICAL**: Trip has no vehicle binding even after driver assignment
3. **HIGH**: Vehicle page is static shell only
4. **HIGH**: Driver update contract excludes vehicle binding

---

## Final Verdict

A dispatcher **cannot currently assign a real vehicle to a real trip**.

The platform can assign drivers and dispatch trips, but vehicle assignment is not operationally implemented. The blocker is not just missing UI; it is the absence of a writable trip/vehicle assignment contract in the backend.
