# AMICOR Health ISF Implementation Backlog

Status: Approved Execution Backlog
Baseline: HEALTH_ISF_OPERATIONAL_BLUEPRINT.md v1.0 (Approved)
Wireframes: HEALTH_ISF_ROLE_WIREFRAMES.md (Approved)
Objective: Deliver operational completion across the end-to-end healthcare transportation lifecycle.

## Execution Rules

- Every backlog item must map to one of the 11 lifecycle steps.
- No feature is valid without API, data, and UI ownership.
- No workflow transition is valid without acceptance criteria by role.
- No release is valid unless all critical lifecycle gates pass.

## Lifecycle Backlog Matrix

| Step | Epic | Primary Roles | Priority | Release Gate |
|---|---|---|---|---|
| 1 | Ride Request Intake | Rider, Dispatcher | P0 | Request persisted and visible in dispatch queue |
| 2 | Eligibility and Authorization | Provider, Supervisor, Dispatcher | P0 | Authorization state enforced before assignment |
| 3 | Dispatch Queue and Prioritization | Dispatcher, Supervisor | P0 | Queue SLA and triage rules active |
| 4 | Driver Assignment | Dispatcher, Driver | P0 | Assignment accepted or reassigned deterministically |
| 5 | Driver Arrival | Driver, Rider, Dispatcher | P0 | Arrival evidence captured |
| 6 | Passenger Pickup | Driver, Rider, Dispatcher | P0 | Pickup event recorded with timestamp |
| 7 | Trip Execution | Driver, Dispatcher | P0 | In-transit telemetry and exception handling active |
| 8 | Trip Completion | Driver, Provider, Dispatcher | P0 | Completion artifact created |
| 9 | Billing and Claims | Billing, Provider | P0 | Claim generated from completed trip |
| 10 | Reporting and Analytics | Operations, Billing, Supervisor | P1 | Operational and financial reports reconciled |
| 11 | Provider Oversight and Governance | Provider, Supervisor, Admin | P1 | Oversight review and escalation workflow active |

## Detailed Backlog by Lifecycle Step

## Step 1: Ride Request

### API
- POST /api/health-isf/customer-requests
- GET /api/health-isf/customer-requests/{request_id}
- GET /api/health-isf/customer-requests?status=pending

### Data Objects
- ride_requests
- rider_profiles
- request_audit_events

### UI Surfaces
- Rider Request screen
- Dispatcher intake queue (new requests)

### Acceptance Criteria by Role
- Rider: Can submit pickup, destination, schedule, and notes in one flow.
- Dispatcher: Sees new requests in queue within SLA refresh window.
- Supervisor: Can audit request creation history.

## Step 2: Eligibility / Authorization

### API
- POST /api/health-isf/authorizations/validate
- POST /api/health-isf/authorizations/{request_id}/approve
- POST /api/health-isf/authorizations/{request_id}/deny

### Data Objects
- ride_authorizations
- eligibility_rules
- authorization_decisions

### UI Surfaces
- Provider Authorization Worklist
- Dispatcher authorization status chips

### Acceptance Criteria by Role
- Provider: Can approve, deny, or request more information.
- Dispatcher: Cannot assign a driver when authorization is denied.
- Supervisor: Can override only with explicit reason and audit trail.

## Step 3: Dispatch

### API
- GET /api/health-isf/dispatch/queue
- POST /api/health-isf/dispatch/queue/{ride_id}/prioritize
- POST /api/health-isf/dispatch/queue/{ride_id}/escalate

### Data Objects
- dispatch_queue
- dispatch_priority_rules
- dispatch_escalations

### UI Surfaces
- Dispatcher queue board
- SLA breach and escalation panel

### Acceptance Criteria by Role
- Dispatcher: Can triage by urgency, schedule, and authorization.
- Supervisor: Can review and resolve escalations.
- Admin: Can configure queue policy safely.

## Step 4: Driver Assignment

### API
- POST /api/health-isf/dispatch/assign
- POST /api/health-isf/drivers/{driver_id}/accept-ride
- POST /api/health-isf/drivers/{driver_id}/decline-ride

### Data Objects
- driver_assignments
- assignment_attempts
- assignment_state_history

### UI Surfaces
- Dispatcher assignment controls
- Driver incoming assignment card

### Acceptance Criteria by Role
- Dispatcher: Can assign based on availability and policy.
- Driver: Can accept or decline within assignment timeout.
- Supervisor: Can intervene during repeated assignment failures.

## Step 5: Driver Arrival

### API
- POST /api/health-isf/drivers/{driver_id}/arrived-pickup
- GET /api/health-isf/rides/{ride_id}/arrival-status

### Data Objects
- trip_arrival_events
- geofence_arrival_proofs

### UI Surfaces
- Driver primary workflow action: Arrived
- Dispatcher live trip status

### Acceptance Criteria by Role
- Driver: Can mark arrived only for assigned active ride.
- Rider: Sees driver-arrived update in near real time.
- Dispatcher: Sees arrival timestamp and evidence marker.

## Step 6: Passenger Pickup

### API
- POST /api/health-isf/drivers/{driver_id}/pickup-complete
- GET /api/health-isf/rides/{ride_id}/pickup-status

### Data Objects
- trip_pickup_events
- rider_handoff_confirmations

### UI Surfaces
- Driver primary workflow action: Pickup
- Rider trip state view

### Acceptance Criteria by Role
- Driver: Can complete pickup from arrived state.
- Rider: Sees transition to in-progress.
- Dispatcher: Pickup state is reflected in active board.

## Step 7: Trip Execution

### API
- POST /api/health-isf/drivers/{driver_id}/route-progress
- GET /api/health-isf/rides/{ride_id}/live-status
- POST /api/health-isf/workflows/escalate

### Data Objects
- trip_progress_events
- trip_exception_events
- route_tracking_points

### UI Surfaces
- Driver trip-in-progress view
- Dispatcher exception handling feed

### Acceptance Criteria by Role
- Driver: Can progress route states and report incidents.
- Dispatcher: Can monitor and intervene on exceptions.
- Supervisor: Can review critical incidents and approvals.

## Step 8: Trip Completion

### API
- POST /api/health-isf/drivers/{driver_id}/dropoff-complete
- GET /api/health-isf/rides/{ride_id}/workflow-path

### Data Objects
- trip_completion_events
- completion_artifacts
- service_proof_records

### UI Surfaces
- Driver primary workflow action: Complete Trip
- Provider completion validation queue

### Acceptance Criteria by Role
- Driver: Can complete trip only from valid in-progress states.
- Provider: Can verify completion quality and flags.
- Dispatcher: Trip moves to completed and exits active board.

## Step 9: Billing

### API
- POST /api/health-isf/billing/claims
- GET /api/health-isf/billing/claims/{claim_id}
- POST /api/health-isf/billing/claims/{claim_id}/reconcile

### Data Objects
- billing_claims
- claim_line_items
- payout_reconciliation

### UI Surfaces
- Billing claim preparation queue
- Claim reconciliation workspace

### Acceptance Criteria by Role
- Billing: Can generate claim from completed trip artifact.
- Provider: Can review claim disputes.
- Supervisor: Can approve exceptional reconciliations.

## Step 10: Reporting

### API
- GET /api/health-isf/reports/operations
- GET /api/health-isf/reports/revenue
- GET /api/health-isf/reports/sla

### Data Objects
- operational_report_snapshots
- revenue_report_snapshots
- sla_report_snapshots

### UI Surfaces
- Operations reporting screen
- Billing and revenue reporting screen

### Acceptance Criteria by Role
- Operations: Can view trip lifecycle conversion funnel.
- Billing: Can view billed vs reconciled vs denied outcomes.
- Supervisor: Can view SLA compliance and escalation trends.

## Step 11: Provider Oversight

### API
- GET /api/health-isf/providers/oversight/cases
- POST /api/health-isf/providers/oversight/cases/{case_id}/resolve
- POST /api/health-isf/providers/oversight/cases/{case_id}/escalate

### Data Objects
- provider_oversight_cases
- provider_quality_reviews
- oversight_resolutions

### UI Surfaces
- Provider oversight board
- Supervisor governance and resolution panel

### Acceptance Criteria by Role
- Provider: Can open and resolve quality/authorization issues.
- Supervisor: Can escalate and close with audit history.
- Admin: Can inspect oversight trends and policy impact.

## Cross-Cutting Backlog (Mandatory)

## Security and Access
- Role-based access control enforcement on all lifecycle APIs.
- Tenant-scoped query enforcement on all list/detail endpoints.

## Audit and Governance
- Append-only audit events for every status transition.
- Override actions require actor, reason, and timestamp.

## Reliability and Continuity
- Idempotency keys for lifecycle mutation endpoints.
- Retry-safe event processing for queue and assignment actions.

## Data Quality and Observability
- Lifecycle completeness checks per trip.
- Dead-letter handling for failed transition events.

## Delivery Plan

## Phase A (P0 Core Operations)
- Steps 1 through 8 complete with role acceptance tests.

## Phase B (Trip-to-Cash)
- Step 9 billing completion and reconciliation.

## Phase C (Executive Visibility)
- Steps 10 and 11 reporting and oversight completion.

## Definition of Done

- All 11 steps implemented and acceptance criteria satisfied.
- Wireframe-to-implementation conformance validated by role.
- API contracts and lifecycle gates pass integration tests.
- No non-lifecycle UI components in production role workflows.

## Execution Board

Task-level sequencing, owners, dependencies, and gates are documented in HEALTH_ISF_EXECUTION_BOARD.md.
