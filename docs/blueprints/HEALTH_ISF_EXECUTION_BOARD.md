# AMICOR Health ISF Execution Board

Status: Active
Baseline: HEALTH_ISF_OPERATIONAL_BLUEPRINT.md v1.0 (Approved)
Backlog Source: HEALTH_ISF_IMPLEMENTATION_BACKLOG.md
Planning Horizon: Phase A, Phase B, Phase C

## 1) Ownership Model

| Workstream | Owner Role | Delivery Team |
|---|---|---|
| Intake and Rider Experience | Product + Rider Platform Lead | Frontend + Backend |
| Authorization and Provider Controls | Provider Integrations Lead | Backend + Policy |
| Dispatch and Assignment | Dispatch Systems Lead | Backend + Realtime |
| Driver Field Workflow | Driver Platform Lead | Frontend + Mobile + Backend |
| Billing and Claims | Revenue Systems Lead | Backend + Data |
| Reporting and Oversight | Operations Intelligence Lead | Data + Backend |
| Security and Governance | Security Lead | Platform + Backend |

## 2) Task Board (Lifecycle Mapped)

| Task ID | Lifecycle Step | Task | Owner | Depends On | Priority | Sprint | Exit Criteria |
|---|---|---|---|---|---|---|---|
| T1.1 | 1 Ride Request | Finalize rider request contract and validations | Rider Platform Lead | None | P0 | A1 | Request schema versioned and validated |
| T1.2 | 1 Ride Request | Implement request intake endpoint hardening | Backend Lead | T1.1 | P0 | A1 | POST request idempotent and audited |
| T1.3 | 1 Ride Request | Connect rider request UI to intake API | Frontend Lead | T1.2 | P0 | A1 | Request appears in dispatcher queue |
| T2.1 | 2 Eligibility | Build authorization decision service adapter | Provider Integrations Lead | T1.2 | P0 | A1 | Authorization state persisted per request |
| T2.2 | 2 Eligibility | Provider authorization worklist actions | Frontend Lead | T2.1 | P0 | A2 | Approve and deny actions complete with reason |
| T2.3 | 2 Eligibility | Enforce auth gate before dispatch assignment | Dispatch Systems Lead | T2.1 | P0 | A2 | Unauthorized requests blocked from assignment |
| T3.1 | 3 Dispatch | Implement queue prioritization rules engine | Dispatch Systems Lead | T1.2, T2.3 | P0 | A2 | Queue ranking deterministic and test-covered |
| T3.2 | 3 Dispatch | Dispatcher queue board lifecycle filters | Frontend Lead | T3.1 | P0 | A2 | Queue filter by auth, SLA, urgency |
| T3.3 | 3 Dispatch | Escalation endpoint and audit trail | Backend Lead | T3.1 | P0 | A3 | Escalations traceable by role and reason |
| T4.1 | 4 Driver Assignment | Assignment engine retries and timeout logic | Dispatch Systems Lead | T3.1 | P0 | A3 | Assignment attempts tracked with expiry |
| T4.2 | 4 Driver Assignment | Driver accept and decline mutation safeguards | Backend Lead | T4.1 | P0 | A3 | Assignment state transitions valid only |
| T4.3 | 4 Driver Assignment | Dispatcher assignment controls and candidate list | Frontend Lead | T4.1 | P0 | A3 | Assign and reassign paths operational |
| T5.1 | 5 Driver Arrival | Arrival transition API and evidence capture | Backend Lead | T4.2 | P0 | A4 | Arrival event includes actor and timestamp |
| T5.2 | 5 Driver Arrival | Driver arrival button enablement rules | Driver Platform Lead | T5.1 | P0 | A4 | Arrived enabled only for valid states |
| T5.3 | 5 Driver Arrival | Rider and dispatch arrival status propagation | Realtime Lead | T5.1 | P0 | A4 | Arrival reflected cross-surface within SLA |
| T6.1 | 6 Pickup | Pickup completion transition and guardrails | Backend Lead | T5.1 | P0 | A4 | Pickup cannot occur before arrival |
| T6.2 | 6 Pickup | Driver pickup workflow action integration | Driver Platform Lead | T6.1 | P0 | A4 | Pickup updates active trip state in UI |
| T6.3 | 6 Pickup | Rider pickup state update and notification | Frontend Lead | T6.1 | P0 | A4 | Rider sees pickup confirmed state |
| T7.1 | 7 Trip Execution | Route progress state machine validation | Backend Lead | T6.1 | P0 | A5 | In-transit progress valid across route states |
| T7.2 | 7 Trip Execution | Exception and incident escalation path | Dispatch Systems Lead | T7.1 | P0 | A5 | Incidents create escalation records |
| T7.3 | 7 Trip Execution | Driver in-trip controls and status updates | Driver Platform Lead | T7.1 | P0 | A5 | Driver can progress and report incident |
| T8.1 | 8 Completion | Trip completion endpoint and proof artifact | Backend Lead | T7.1 | P0 | A5 | Completion creates immutable artifact |
| T8.2 | 8 Completion | Driver complete trip workflow gate logic | Driver Platform Lead | T8.1 | P0 | A5 | Complete enabled only for valid in-progress trips |
| T8.3 | 8 Completion | Completion handoff to provider and billing queues | Backend Lead | T8.1 | P0 | A5 | Completed trips appear in downstream queues |
| T9.1 | 9 Billing | Claim generation from completed trip data | Revenue Systems Lead | T8.3 | P0 | B1 | Claim record created with line items |
| T9.2 | 9 Billing | Reconciliation mutation and denial workflow | Revenue Systems Lead | T9.1 | P0 | B1 | Reconcile actions audited and reversible by policy |
| T9.3 | 9 Billing | Billing UI queue and claim status board | Frontend Lead | T9.1 | P0 | B1 | Billing team can process all claim states |
| T10.1 | 10 Reporting | Operational lifecycle funnel dataset | Data Lead | T1.2..T9.2 | P1 | C1 | Funnel report reconciles with source events |
| T10.2 | 10 Reporting | Revenue reporting dataset and export APIs | Data Lead | T9.1 | P1 | C1 | Revenue metrics tie out to claims |
| T10.3 | 10 Reporting | Reporting screens by role | Frontend Lead | T10.1, T10.2 | P1 | C1 | Role-filtered reporting visible and accurate |
| T11.1 | 11 Provider Oversight | Oversight case object and lifecycle | Provider Integrations Lead | T8.3 | P1 | C2 | Case open-resolve-escalate supported |
| T11.2 | 11 Provider Oversight | Provider oversight board and actions | Frontend Lead | T11.1 | P1 | C2 | Providers can manage assigned cases |
| T11.3 | 11 Provider Oversight | Supervisor oversight escalation controls | Supervisor Tools Lead | T11.1 | P1 | C2 | Supervisor can resolve escalations with audit |

## 3) Cross-Cutting Mandatory Tasks

| Task ID | Domain | Task | Owner | Priority | Exit Criteria |
|---|---|---|---|---|---|
| X1 | Security | RBAC enforcement matrix across all lifecycle APIs | Security Lead | P0 | Unauthorized role calls blocked with tests |
| X2 | Governance | Append-only audit write for all critical transitions | Platform Lead | P0 | Every mutation emits an audit record |
| X3 | Reliability | Idempotency support for all mutation endpoints | Backend Lead | P0 | Duplicate requests do not duplicate side effects |
| X4 | Observability | Lifecycle KPI and error telemetry standards | Operations Intelligence Lead | P1 | Metrics and traces emitted for all key flows |
| X5 | Data Quality | Lifecycle completeness validator job | Data Lead | P1 | Daily validation report produced |

## 4) Integration Test Gates

| Gate | Scope | Required Tests | Pass Condition |
|---|---|---|---|
| G1 | Steps 1-2 | Request intake, auth approve or deny, gate enforcement | 100 percent critical path pass |
| G2 | Steps 3-4 | Dispatch ranking, assignment, accept or decline | No invalid assignment transitions |
| G3 | Steps 5-8 | Arrival, pickup, execution, completion transitions | No illegal lifecycle transitions |
| G4 | Step 9 | Claim generation and reconciliation | Claims tie to completion artifacts |
| G5 | Steps 10-11 | Reporting and oversight case workflows | Report numbers reconcile to source |
| G6 | Cross-cutting | RBAC, audit, idempotency, tenant scope | Zero critical security and data issues |

## 5) Dependency Notes

- Phase B requires all Phase A completion events to be stable and reconciled.
- Phase C requires validated billing outputs for revenue reporting.
- Provider Oversight depends on completion and billing event integrity.

## 6) Release Readiness Checklist

| Item | Status | Evidence |
|---|---|---|
| Lifecycle Steps 1-8 operational | Pending |  |
| Billing trip-to-cash operational | Pending |  |
| Reporting and oversight operational | Pending |  |
| Security and governance gates passed | Pending |  |
| Wireframe conformance validated | Pending |  |

## 7) Sprint A Run Plan

Detailed day-by-day Sprint A execution is documented in HEALTH_ISF_SPRINT_A_RUN_PLAN.md.
