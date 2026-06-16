# AMICOR Health ISF Sprint A Run Plan

Status: Ready for Execution
Source: HEALTH_ISF_EXECUTION_BOARD.md
Scope: Phase A (Lifecycle Steps 1 through 8)
Execution Mode: API-first, then role workflow UI integration, then end-to-end validation

## 1) Sprint A Goals

- Deliver lifecycle steps 1 through 8 as a single operational chain.
- Enforce transition legality, authorization gates, and auditability.
- Validate role workflows for Rider, Dispatcher, Driver, Provider, Supervisor.

## 2) API-First Implementation Order

1. Step 1 Ride Request endpoints and request audit events.
2. Step 2 Authorization validation and decision endpoints.
3. Step 3 Dispatch queue, prioritization, and escalation endpoints.
4. Step 4 Assignment accept and decline endpoints and timeout behavior.
5. Step 5 Arrival endpoint and arrival evidence artifact.
6. Step 6 Pickup endpoint and pickup legality checks.
7. Step 7 Route progress and in-trip escalation endpoints.
8. Step 8 Completion endpoint and completion artifact handoff.

## 3) Day-by-Day Delivery Plan

## Day 1: Intake and Authorization Contracts

Tasks:
- T1.1, T1.2, T2.1

Deliverables:
- Request schema contract finalized.
- Intake endpoint hardening complete.
- Authorization decision service adapter operational.

Test Commands:
```powershell
& ".venv\Scripts\python.exe" -m pytest backend/tests -k "ride_request or authorization" -q
& ".venv\Scripts\python.exe" -m pytest backend/tests/test_ride_flow.py -q
```

Exit Gate:
- New request can be created, fetched, and linked to authorization state.

## Day 2: Dispatch and Assignment Core

Tasks:
- T2.3, T3.1, T3.3, T4.1

Deliverables:
- Unauthorized requests blocked from assignment.
- Queue prioritization deterministic.
- Escalation path writes full audit events.
- Assignment retry and timeout logic functional.

Test Commands:
```powershell
& ".venv\Scripts\python.exe" -m pytest backend/tests -k "dispatch or assignment or escalation" -q
& ".venv\Scripts\python.exe" -m pytest test_websocket_events.py -q
```

Exit Gate:
- Dispatcher queue can prioritize, assign, and escalate with policy enforcement.

## Day 3: Driver Arrival and Pickup Transitions

Tasks:
- T4.2, T5.1, T5.3, T6.1

Deliverables:
- Accept and decline transition safeguards complete.
- Arrival transition emits evidence event.
- Cross-surface arrival propagation active.
- Pickup transition legal only from valid prior states.

Test Commands:
```powershell
& ".venv\Scripts\python.exe" -m pytest backend/tests -k "arrival or pickup or transition" -q
& ".venv\Scripts\python.exe" -m pytest test_ride_flow.py -q
```

Exit Gate:
- Trip state cannot bypass arrival or pickup legality.

## Day 4: Trip Execution and Completion Chain

Tasks:
- T7.1, T7.2, T8.1, T8.3

Deliverables:
- Route progress state machine validated.
- In-trip exception escalation operational.
- Completion endpoint creates immutable artifact.
- Completion handoff to provider and billing queues active.

Test Commands:
```powershell
& ".venv\Scripts\python.exe" -m pytest backend/tests -k "route_progress or completion or workflow_path" -q
& ".venv\Scripts\python.exe" -m pytest backend/tests -k "billing and completed" -q
```

Exit Gate:
- Assigned ride can progress from assignment to completion with artifact creation.

## Day 5: Role UI Integration and Acceptance Validation

Tasks:
- T1.3, T2.2, T3.2, T4.3, T5.2, T6.2, T6.3, T7.3, T8.2

Deliverables:
- Role wireframe-conformant screens wired to API chain.
- Driver primary workflow actions match approved baseline.
- Dispatcher and provider actions reflect lifecycle states.

Test Commands:
```powershell
& ".venv\Scripts\python.exe" -m pytest test_phase3_ui_handlers.py -q
& ".venv\Scripts\python.exe" -m pytest backend/tests -k "driver or rider or dispatcher" -q
```

Exit Gate:
- Role acceptance criteria pass for Steps 1 through 8.

## Day 6: Cross-Cutting Controls and Hardening

Tasks:
- X1, X2, X3, X4, X5

Deliverables:
- RBAC and tenant-scoped enforcement validated.
- Append-only audit events verified for all mutations.
- Idempotency behavior validated for mutation retries.
- Lifecycle telemetry and data completeness checks enabled.

Test Commands:
```powershell
& ".venv\Scripts\python.exe" -m pytest backend/tests -k "rbac or tenant or audit or idempotency" -q
& ".venv\Scripts\python.exe" -m pytest final_checkpoint_test.py -q
```

Exit Gate:
- Security and governance controls pass without critical findings.

## Day 7: Integration Gates and Go-No-Go

Tasks:
- G1, G2, G3, G6

Deliverables:
- End-to-end phase A validation report.
- Open defects triaged by severity and owner.
- Go-no-go recommendation for Phase B.

Test Commands:
```powershell
& ".venv\Scripts\python.exe" -m pytest backend/tests -q
& ".venv\Scripts\python.exe" -m pytest test_ride_flow.py test_websocket_events.py final_checkpoint_test.py -q
```

Exit Gate:
- Lifecycle steps 1 through 8 confirmed operational in integrated flow.

## 4) Daily Standup Template

```text
Yesterday:
- Completed tasks (Task IDs):
- Test pass summary:

Today:
- Planned tasks (Task IDs):
- Risks and blockers:

Metrics:
- Open P0 defects:
- Gate status (G1-G6):
```

## 5) Risk and Rollback Plan

- If transition legality fails, freeze new UI actions and run API-only replay checks.
- If assignment churn spikes, switch to conservative dispatch retry policy.
- If audit writes degrade performance, keep mutation path active and queue async audit replay with alerting.

## 6) Sprint A Completion Criteria

- Steps 1 through 8 pass role acceptance criteria.
- Illegal state transitions are blocked and audited.
- Cross-role status propagation is operational.
- Execution evidence published and linked to G1, G2, G3, G6.
