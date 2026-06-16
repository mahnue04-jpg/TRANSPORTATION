# AMICOR HEALTH ISF OPERATIONAL WIRING SPRINT
**Status**: ACTIVE | **Start Date**: 2026-06-11 | **Target**: Full End-to-End Validation

---

## MASTER OBJECTIVE
Convert Amicor from a visually complete but functionally disconnected platform into a fully operational transportation system. Every workflow must pass a **5-Stage Verification Gate**:

1. **User Action** → Click button / Submit form
2. **API Call** → POST/PATCH to backend endpoint
3. **Database Write** → Record persisted to database
4. **Real-time Update** → Dispatch/other surfaces notified
5. **UI Refresh** → User surface reflects new state

**No workflow is complete until all five stages are verified.**

---

## PHASE ROADMAP

### PHASE 1: RIDER WORKFLOW [ACTIVE]
**Objective**: Convert Rider surface into fully operational transportation request system.

#### Workflows to Wire:
- [ ] **Request Ride Now** → Create Trip → Dispatch Queue → DB Write → UI Refresh
- [ ] **Schedule Recurring Ride** → Create Recurring Schedule → Future Trips Generate → DB Write → UI Refresh
- [ ] **Cancel Ride** → Update Trip Status → Dispatch Notification → DB Write → UI Refresh
- [ ] **Live Trip Tracking** → Real-time driver location, ETA, status updates
- [ ] **Rider Map** → Driver coordinates, route path, pickup/dropoff markers, ETA overlay

#### UI Conversions:
- Remove: "Awaiting Dispatch Update", "Sign-In Required", "Limited Visibility" (replace with live data)
- Replace: Rider Trip Map Placeholder with live map component
- Replace: "No trip history available" with actual trip history from DB
- Replace: Static "Scheduled" status with real-time trip state

#### Database Tables to Verify:
- `customer_ride_requests` (create records on "Request Ride Now")
- `rides` (update status on cancel/complete)
- `recurring_schedules` (create on "Schedule Recurring Ride")
- `ride_events` (append timeline events)

#### API Endpoints to Wire:
- `POST /api/health-isf/customer-requests` → Create request
- `POST /api/health-isf/customers/workspace/{request_id}/cancel` → Cancel request
- `GET /api/health-isf/customers/workspace/history` → Load history
- `GET /api/health-isf/customers/workspace/active` → Load active ride
- `GET /api/health-isf/operations/map-preview` → Live map data

---

### PHASE 2: DRIVER WORKFLOW
**Objective**: Convert Driver surface into real field operations application.

#### Workflows to Wire:
- [ ] **Accept Trip** → Update trip status → Dispatch notify → DB write → UI refresh
- [ ] **Arrive at Pickup** → Update location → Rider notify → DB write → UI refresh
- [ ] **Patient Onboard** → Record boarding → Start transport → DB write → UI refresh
- [ ] **Complete Trip** → Close trip → Generate payout → DB write → UI refresh + Billing update
- [ ] **Driver Map** → Current location, route guidance, pickup/destination, status overlay

#### UI Conversions:
- Replace: Disabled buttons (Arrived, Pickup, Complete Trip) → Enable on proper trip state
- Replace: Static route table → Live queue with real trips
- Replace: "Driver Signals: 0" → Real driver connection metrics
- Replace: Driver map placeholder → Live map with navigation

#### Database Tables:
- `rides` (status transitions)
- `ride_events` (append boarding, completion events)
- `payouts` (generate on completion)
- `driver_locations` (update on arrival/transport)

#### API Endpoints:
- `PATCH /api/health-isf/rides/{ride_id}/status` → Update status
- `POST /api/health-isf/drivers/{driver_id}/arrive-pickup` → Boarding
- `POST /api/health-isf/drivers/{driver_id}/complete-trip` → Trip completion
- `GET /api/health-isf/drivers/{driver_id}/active-trips` → Active trips
- `GET /api/health-isf/operations/map-preview` → Live driver location

---

### PHASE 3: DISPATCH WORKFLOW
**Objective**: Dispatch becomes system command center.

#### Workflows to Wire:
- [ ] **Create Trip** → Entry point for manual dispatch
- [ ] **Assign Driver** → Select driver → Update trip → Notify driver → DB write
- [ ] **Reassign Driver** → Unassign current → Assign new → Notify both → DB write
- [ ] **Cancel Trip** → Void trip → Notify rider/driver/provider → DB write
- [ ] **Monitor Route** → Live tracking of active trips

#### Database Tables:
- `rides` (assignment, status)
- `ride_assignments` (driver assignment history)
- `dispatch_events` (log assignments, reassignments, cancellations)

#### API Endpoints:
- `PATCH /api/health-isf/dispatcher/rides/{ride_id}/assign-driver`
- `PATCH /api/health-isf/dispatcher/rides/{ride_id}/reassign`
- `PATCH /api/health-isf/dispatcher/rides/{ride_id}/cancel`
- `GET /api/health-isf/operations/workflow-overview` → Dispatch summary

---

### PHASE 4: PROVIDER PORTAL
**Objective**: Provider portal creates real transportation requests.

#### Workflows to Wire:
- [ ] **Create Transportation Request** → Generate trip → Enter dispatch queue → DB write
- [ ] **Manage Patient Trips** → View active/scheduled trips from provider
- [ ] **Appointment Coordination** → Link appointment to transportation
- [ ] **Provider Notifications** → Receive trip updates

#### Database Tables:
- `customer_ride_requests` (create from provider UI)
- `providers` (track provider context)
- `ride_assignments` (view assignments)

---

### PHASE 5: BILLING WORKFLOW
**Objective**: Billing becomes fully operational.

#### Workflows to Wire:
- [ ] **Trip Complete** → Trigger billing workflow
- [ ] **Generate Invoice** → Create billing record
- [ ] **Generate Payout** → Calculate driver payout
- [ ] **Update Ledger** → Record revenue entry

#### Database Tables:
- `payouts` (generate on trip completion)
- `billing_records` (invoice generation)
- `revenue_ledger` (revenue tracking)

#### API Endpoints:
- `GET /api/health-isf/operations/revenue-workflow?window_hours=24` → Revenue summary

---

### PHASE 6: SUPPORT WORKFLOW
**Objective**: Create operational support system.

#### Workflows to Wire:
- [ ] **Create Ticket** → New support case → DB write
- [ ] **Assign Ticket** → Route to support team → DB write
- [ ] **Update Ticket** → Add notes/status → DB write
- [ ] **Resolve Ticket** → Close case → DB write

#### Database Tables:
- `support_tickets` (create table if missing)
- `support_assignments` (ticket routing)
- `support_notes` (ticket comments)

---

### PHASE 7: REPORTS
**Objective**: Connect backend analytics to UI.

#### Workflows to Wire:
- [ ] **Completed Trips Report** → Query `rides` table
- [ ] **Active Trips Report** → Real-time active trips
- [ ] **Revenue Report** → Query `revenue_ledger`
- [ ] **Driver Performance** → Query driver metrics
- [ ] **Provider Activity** → Query provider stats

#### API Endpoints:
- `GET /api/health-isf/operations/revenue-workflow` → Revenue data
- `GET /api/health-isf/operations/workflow-events` → Timeline events
- `GET /api/health-isf/analytics/*` → Analytics endpoints

---

### PHASE 8: BUTTON AUDIT
**Objective**: Verify every button executes complete 5-stage workflow.

#### Test Matrix:
For each visible button across all roles:
- [ ] Button click detected
- [ ] API endpoint called
- [ ] Database record created/modified
- [ ] Real-time notification sent
- [ ] UI surface refreshed with new state

#### Success Criteria:
- Zero disabled placeholder buttons
- 100% of enabled buttons execute 5-stage workflow
- All button clicks produce `changed=true` in UI

---

### PHASE 9: FINAL END-TO-END VALIDATION
**Objective**: Complete transportation workflow from request to completion.

#### Test Sequence:
1. Rider requests ride (Request Ride Now button)
2. Trip record created in database
3. Trip appears in Dispatch queue
4. Dispatcher assigns driver
5. Driver receives assignment in Driver app
6. Driver accepts trip
7. Driver navigates to pickup (map shows route)
8. Driver arrives at pickup
9. Driver records patient onboard
10. Driver completes trip
11. Trip marked complete
12. Billing record generated
13. Payout calculated
14. Provider sees completion
15. Reports updated with new trip data

#### Evidence Capture:
- Screenshot at each step
- API request/response log
- Database query results
- UI state before/after

---

## CURRENT STATUS

### Completed:
- ✅ Operational Surface Validation Report
- ✅ Button Audit across all roles
- ✅ API probe (operations endpoints return data)
- ✅ Gap identification (5-stage verification failures)

### In Progress:
- 🟡 Phase 1: Rider Workflow wiring

### Not Started:
- ⬜ Phases 2-9

---

## SUCCESS METRICS

| Phase | Workflow | Stage 1 | Stage 2 | Stage 3 | Stage 4 | Stage 5 | Status |
|-------|----------|--------|--------|--------|--------|--------|--------|
| 1 | Request Ride | ✓ | ✗ | ✗ | ✗ | ✗ | FAIL |
| 1 | Cancel Ride | ✓ | ✗ | ✗ | ✗ | ✗ | FAIL |
| 1 | Schedule Recurring | ✓ | ✗ | ✗ | ✗ | ✗ | FAIL |
| 1 | Live Tracking | ✓ | ✗ | ✗ | ✗ | ✗ | FAIL |
| 1 | Rider Map | ✗ | ✗ | ✗ | ✗ | ✗ | FAIL |

---

## CRITICAL NOTES

1. **No new features until Phase 9 passes.** The platform has enough UI. Focus is 100% on wiring.
2. **Every workflow must show `changed=true` in button audit.** Currently showing `changed=false`.
3. **Real-time updates are mandatory.** All surfaces must sync when any workflow updates.
4. **Database persistence is non-negotiable.** Every action must write to DB or it doesn't count.
5. **Map data is live data.** Map cannot be placeholder; it must pull from operations API.

---

## NEXT IMMEDIATE ACTION

**→ Execute Phase 1, Stage 1-5 for "Request Ride Now" button**
- Wire frontend click to backend API
- Verify API creates database record
- Verify dispatch queue updates
- Verify rider UI refreshes with new trip
- Capture evidence

**Target**: Rider can request ride and see it appear live in dispatch and on their own trip tracking screen.
