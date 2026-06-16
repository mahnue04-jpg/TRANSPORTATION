# Workflow Planning (MVP)

## Objective

Define the production-intent operational workflow from provider request through driver payout tracking.

## End-to-End Workflow

1. Request Intake
- Provider submits request with appointment details and constraints.
- System validates required fields and serviceability.

2. Queueing and Prioritization
- Valid requests move to dispatch queue.
- Priority determined by time-to-appointment and critical constraints.

3. Assignment
- Dispatcher assigns available vetted driver.
- Driver receives assignment and accepts/declines in defined SLA window.

4. Execution and Tracking
- Driver updates ride states: `en_route_pickup`, `in_transit`, `completed`.
- System logs all state changes and timestamps.

5. Exception Handling
- Exceptions are classified and routed (cancellation, no-show, delay, safety).
- Reassignment logic triggers where applicable.

6. Completion and Settlement Inputs
- Completed ride data is validated.
- Records flow to payout tracking and reporting.

## SLA Targets (MVP Baseline)

- Time to first assignment: <= 20 minutes (standard), <= 10 minutes (high-priority windows)
- Driver response to assignment: <= 5 minutes
- Exception triage start: <= 10 minutes

## Required Data Objects

- Request
- Assignment
- RideEvent
- ExceptionCase
- PayoutRecord

## Acceptance Criteria

- Full request lifecycle works without manual state editing.
- Reassignment path exists for failed assignments.
- Every completed ride has a complete event trail.
