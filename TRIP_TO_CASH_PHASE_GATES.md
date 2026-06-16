# Trip-to-Cash Phase Gates

## Mission Lock
This checklist governs delivery decisions for Amicor Health ISF as a healthcare transportation operation.

Primary success path:
Rider -> Trip -> Driver -> Vehicle -> Dispatch -> Ride Completion -> Invoice -> Payment -> Revenue

A feature is in scope only if it increases reliability, auditability, or throughput of this path.

## Gate Model
- Gate status values: PASS, FAIL, BLOCKED.
- A gate passes only when all pass tests succeed in production-like conditions.
- Any fail condition is an immediate gate FAIL.
- Downstream gates may not be marked PASS if an upstream gate is FAIL or BLOCKED.

## Hard Gate Checklist

### Gate G1: Rider Intake Integrity
Operational objective: A real rider request is created with enough data to dispatch a real trip.

Pass tests:
1. Create customer ride request through operational API and persist rider contact plus pickup/dropoff details.
2. Retrieve rider workspace history and active ride context for that rider.
3. Confirm tenant scope correctness for the request owner organization.

Fail conditions:
1. Request cannot be created from authenticated workflow.
2. Rider lookup returns empty or wrong-tenant data for newly created request.
3. Required intake fields are optional in runtime behavior.

Evidence:
- API: POST /api/health-isf/customer-requests
- API: GET /api/health-isf/customers/workspace/history
- API: GET /api/health-isf/customers/workspace/active
- Tables: health_isf_customer_ride_requests, health_isf_rides

### Gate G2: Trip Contract Integrity
Operational objective: A trip record exists and can move through lifecycle states with full history.

Pass tests:
1. Create ride and verify persisted trip identity and status baseline.
2. Transition ride status through expected non-terminal states.
3. Confirm status history events are written for each transition.

Fail conditions:
1. Ride state can change without audit/history event.
2. Invalid status transitions are accepted.
3. Trip retrieval omits lifecycle-critical fields.

Evidence:
- API: POST /api/health-isf/rides
- API: PATCH /api/health-isf/rides/{ride_id}/status
- Tables: health_isf_rides, health_isf_ride_status_history

### Gate G3: Driver Assignment Reliability
Operational objective: Dispatcher can assign and reassign a qualified driver to a live trip.

Pass tests:
1. Assign driver to ride and verify ride.driver_id is persisted.
2. Reassign driver and verify assignment event history is preserved.
3. Confirm same-organization enforcement for ride and driver.

Fail conditions:
1. Assignment succeeds for inactive or wrong-tenant driver.
2. Assignment writes without dispatch audit record.
3. Reassignment corrupts ride state or drops lifecycle continuity.

Evidence:
- API: PATCH /api/health-isf/rides/{ride_id}/assign-driver
- API: PATCH /api/health-isf/dispatcher/rides/{ride_id}/reassign-driver
- Tables: health_isf_dispatch_assignments, health_isf_dispatch_logs, health_isf_rides

### Gate G4: Vehicle Assignment Reliability
Operational objective: Dispatcher can assign a real fleet vehicle to a live trip.

Pass tests:
1. Assign vehicle to ride through authenticated dispatcher/admin workflow.
2. Retrieve ride and confirm vehicle_id is present and tenant-valid.
3. Confirm idempotent behavior for repeated assignment of same vehicle.
4. Confirm terminal rides reject assignment.

Fail conditions:
1. No writable ride-to-vehicle contract exists.
2. Vehicle assignment accepts wrong-tenant or inactive vehicle.
3. Driver assignment workflow regresses after vehicle assignment rollout.

Evidence:
- API target: PATCH /api/health-isf/rides/{ride_id}/assign-vehicle
- API target: PATCH /api/health-isf/dispatcher/rides/{ride_id}/assign-vehicle
- Tables target: health_isf_rides.vehicle_id, health_isf_vehicles
- Current state: FAIL (missing operational contract)

### Gate G5: Dispatch Execution Continuity
Operational objective: Dispatch board can execute assignment, ownership, lifecycle progression, and exception handling.

Pass tests:
1. Auto-assign or manual assign creates active dispatch assignment record.
2. Ownership claim/handoff works without assignment loss.
3. Queue and active assignment views reflect runtime state in near real time.

Fail conditions:
1. Board action succeeds in API but not in persisted assignment state.
2. Locking/ownership conflicts produce silent data loss.
3. Dispatcher view falls back to synthetic data during valid authenticated sessions.

Evidence:
- API: POST /api/health-isf/dispatch/auto-assign
- API: GET /api/health-isf/dispatch/queue
- API: GET /api/health-isf/dispatch/active-assignments
- API: POST /api/health-isf/dispatcher/rides/{ride_id}/claim-ownership
- Tables: health_isf_dispatch_assignments, health_isf_assignment_locks, health_isf_dispatch_logs

### Gate G6: Ride Completion Evidence
Operational objective: Completed rides are auditable, finalizable, and ready for billing conversion.

Pass tests:
1. Complete ride through dispatcher or driver lifecycle endpoint.
2. Confirm terminal completed status with immutable completion timestamp/event.
3. Confirm trip output fields needed for billing are present.

Fail conditions:
1. Completed rides can regress to active states without controlled override.
2. Completion event does not include billable ride identity context.
3. Completion path bypasses dispatch history/audit.

Evidence:
- API: PATCH /api/health-isf/dispatcher/rides/{ride_id}/complete
- API: POST /api/health-isf/drivers/{driver_id}/dropoff-complete
- Tables: health_isf_rides, health_isf_ride_status_history, health_isf_dispatch_logs

### Gate G7: Invoice Generation Readiness
Operational objective: Completed rides produce invoice records with deterministic totals and payer context.

Pass tests:
1. Generate invoice from completed ride with line-level fare components.
2. Retrieve invoice by ride and by payer/customer context.
3. Confirm invoice amount reconciles with ride facts and pricing logic.

Fail conditions:
1. No invoice object or API exists for completed rides.
2. Invoice generation requires manual data patching.
3. Invoice total is non-deterministic for the same ride data.

Evidence target:
- API target: invoice create/read endpoints
- Tables target: invoice and invoice_line tables (currently not established in truth reports)
- Current state: FAIL (missing operational workflow)

### Gate G8: Payment Capture And Settlement
Operational objective: Invoices can be paid and settlement is auditable.

Pass tests:
1. Payment intent and capture are tied to invoice or completed ride identity.
2. Settlement entries are generated and queryable.
3. Payment state transitions are idempotent and auditable.

Fail conditions:
1. Payment flow is disconnected from invoice or ride finalization.
2. Settlements cannot be traced back to original trip and payer.
3. Duplicate capture is possible without replay protection.

Evidence:
- API: POST /api/health-isf/payments/intents
- API: POST /api/health-isf/payments/capture
- API: POST /api/health-isf/payments/settle
- API: GET /api/health-isf/payments/rides/{ride_id}
- Tables: health_isf_payment_transactions, health_isf_settlement_ledger, health_isf_payouts

### Gate G9: Revenue Reconciliation Visibility
Operational objective: The business can measure recognized revenue from completed and paid rides.

Pass tests:
1. Report paid amount by day, payer, and organization from canonical ledger tables.
2. Reconcile ride completion counts against invoice counts and payment counts.
3. Surface unresolved exceptions (completed-not-invoiced, invoiced-not-paid).

Fail conditions:
1. Revenue cannot be reproduced from persisted transactional data.
2. Operational dashboard presents hardcoded revenue metrics.
3. Reconciliation exceptions are not detectable.

Evidence target:
- Reporting endpoints or SQL views for reconciliation
- Canonical sources: health_isf_rides, invoice tables, payment/settlement tables
- Current state: BLOCKED by G7 incompleteness

## Active Work Item To Gate Mapping

| Work Item | Current State | Primary Gate | Pass Criteria For Item | Blocking Gate Dependency |
|---|---|---|---|---|
| WI-01 Vehicle assignment contract (ride vehicle_id, assign endpoint, service validation, permissions, UI action) | Planned | G4 | Dispatcher assigns vehicle to ride and retrieval shows tenant-valid vehicle_id with no G3 regression | G3 must remain PASS |
| WI-02 Vehicle create/edit operational workflow | Not started | G4 | Fleet assets can be created/updated and used in assignment picker with tenant and active-state validation | G1, G2, G3 must remain PASS |
| WI-03 Invoice generation workflow | Not started | G7 | Completed ride can produce deterministic invoice record and retrieval APIs | G6 must be PASS |
| WI-04 Claims workflow | Not started | G7 | Claim can be generated/tracked from invoice-ready ride for payer reimbursement path | G7 base invoice contract |
| WI-05 Driver direct creation workflow | Gap identified | G3 | Dispatcher/admin can create operational driver record directly without app pipeline dependency | G1, G2 must remain PASS |
| WI-06 Rider profile/search master workflow | Gap identified | G1 | Rider records are searchable/editable as first-class operational entities | None, but must preserve tenant isolation |

## Immediate Priority Sequence
1. Close WI-01 to move G4 from FAIL to PASS.
2. Close WI-03 to move G7 from FAIL to PASS.
3. Add payment-to-invoice linkage controls under WI-03 so G8 is fully auditable.
4. Build reconciliation outputs for G9 from canonical tables only.

## Release Gate Rule
No release is operationally accepted unless G1 through G8 are PASS and G9 is at least PASS for core daily reconciliation.

## Verification Cadence
- Run gate verification at the end of each implementation stage.
- Any FAIL reopens the owning work item and blocks downstream gates.
- Record gate status snapshots per build candidate in a dated release note.
