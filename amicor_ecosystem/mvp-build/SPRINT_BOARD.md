# Amicor Health ISF — Sprint Board (Execution Format)

**Version:** 1.0  
**Date:** May 2026  
**Scope:** MVP-only execution board aligned to `MVP_TASK_BREAKDOWN.md`

---

## Operating Rules

- Do not expand scope beyond EP-01 through EP-08.
- No advanced AI features in MVP sprints.
- No marketplace systems in MVP sprints.
- No sprint closes until sprint acceptance criteria pass.

---

## Owner Roles

| Code | Owner Role | Accountability |
|------|------------|----------------|
| PM | Product Manager | Scope, priority, story acceptance |
| BE | Backend Lead | API contracts, business logic, data integrity |
| FE | Frontend Lead | Provider, dispatcher, admin, and driver UI |
| QA | QA Lead | Test plans, regression, release sign-off |
| SEC | Security Owner | Auth, roles, session controls, audit checks |
| OPS | Operations Lead | Incident process, pilot readiness, runbooks |
| FIN | Finance Ops Owner | Payout workflow and reconciliation acceptance |

---

## Sprint 1 (Weeks 1-2) — Foundation

**Goal:** Role-based authentication and driver onboarding foundation is usable end-to-end.

| Work Item | Epic/Stories | Owner | Depends On |
|-----------|--------------|-------|------------|
| Auth login/session core | EP-01 / US-101, US-102, US-106 | BE, SEC | None |
| Admin role/account controls | EP-01 / US-103, US-105 | BE, FE, SEC | Auth login/session core |
| Password reset flow | EP-01 / US-104 | BE, FE | Auth login/session core |
| Driver application submit/review/activate | EP-03 / US-301, US-302, US-303 | BE, FE, QA | Auth + admin role/account controls |
| Sprint test + sign-off | EP-01, EP-03 | QA, PM | All Sprint 1 work items |

**Sprint Acceptance Criteria**

- Provider, driver, and admin can authenticate with role-scoped access.
- Admin can approve a driver and activated driver can sign in.
- Session timeout and secure reset flow are verified.
- Critical auth and onboarding test set passes.

---

## Sprint 2 (Weeks 3-4) — Request Lifecycle

**Goal:** Providers can create and manage requests while dispatch sees a working intake queue.

| Work Item | Epic/Stories | Owner | Depends On |
|-----------|--------------|-------|------------|
| Request submit + validate | EP-02 / US-201, US-206 | BE, FE | Sprint 1 auth |
| Provider active request view | EP-02 / US-202 | FE, BE | Request submit + validate |
| Request cancel + history | EP-02 / US-203, US-204 | BE, FE | Request submit + validate |
| Dispatcher intake queue | EP-02 / US-205 | FE, BE | Request submit + validate |
| Driver lifecycle controls | EP-03 / US-304, US-305 | BE, FE | Sprint 1 onboarding |
| Sprint test + sign-off | EP-02, EP-03 | QA, PM | All Sprint 2 work items |

**Sprint Acceptance Criteria**

- Provider can submit, track, cancel, and review request history.
- Dispatcher can view queue by urgency and appointment time.
- Incomplete/conflicting requests can be flagged for manual review.
- Driver inactive/availability controls are live and auditable.

---

## Sprint 3 (Weeks 5-6) — Assignment and Trip Tracking

**Goal:** Dispatcher assignment loop and live trip state tracking are operational.

| Work Item | Epic/Stories | Owner | Depends On |
|-----------|--------------|-------|------------|
| Assignment create/offer | EP-04 / US-401, US-402 | BE, FE | Sprint 2 requests + active drivers |
| SLA breach + reassignment | EP-04 / US-403, US-404 | BE, FE | Assignment create/offer |
| Exception coding on failures | EP-04 / US-405 | BE, FE | Assignment create/offer |
| Driver trip state updates | EP-05 / US-501 | FE, BE | Assignment create/offer |
| Provider live state visibility + event log | EP-05 / US-502, US-505 | FE, BE | Driver trip state updates |
| Sprint test + sign-off | EP-04, EP-05 | QA, PM, OPS | All Sprint 3 work items |

**Sprint Acceptance Criteria**

- Dispatcher can assign, detect timeout, and reassign rides.
- Driver can update state through completion with timestamps.
- Provider can observe state transitions in near real-time.
- Exception events are recorded and queryable.

---

## Sprint 4 (Weeks 7-8) — Notifications and Ops Dashboard

**Goal:** Critical events trigger notifications and are visible in an operational dashboard.

| Work Item | Epic/Stories | Owner | Depends On |
|-----------|--------------|-------|------------|
| Provider notification triggers | EP-06 / US-601, US-602, US-603 | BE, FE | Sprint 3 assignment/tracking events |
| Driver + dispatcher alerts | EP-06 / US-604, US-605 | BE, FE | Sprint 3 assignment/tracking events |
| Live queue dashboard | EP-07 / US-701 | FE, BE | Sprint 3 trip state events |
| Exceptions + availability panels | EP-07 / US-702, US-703 | FE, BE | Live queue dashboard |
| Active ride board + stall alerts | EP-05 / US-503, US-504 | FE, BE | Live queue dashboard |
| Sprint test + sign-off | EP-05, EP-06, EP-07 | QA, PM, OPS | All Sprint 4 work items |

**Sprint Acceptance Criteria**

- Critical notifications are sent for assignment, en-route, and cancellation/exception.
- Dispatcher receives SLA breach alerts.
- Admin/dispatcher can manage queue and exception panels from one dashboard.
- Stalled ride alerts surface with actionable context.

---

## Sprint 5 (Weeks 9-10) — Payout and Controls

**Goal:** Completed rides generate payout records and finance ops can review/reconcile.

| Work Item | Epic/Stories | Owner | Depends On |
|-----------|--------------|-------|------------|
| Auto payout record on completion | EP-08 / US-801 | BE | Sprint 3 completion event integrity |
| Payout review/approve/dispute | EP-08 / US-802, US-803 | FIN, BE, FE | Auto payout record on completion |
| Driver payout visibility | EP-08 / US-804 | FE, BE | Payout review/approve/dispute |
| Weekly reconciliation export | EP-08 / US-805 | FIN, BE | Payout review/approve/dispute |
| Finance dashboard + reporting/filtering | EP-07 / US-704, US-705, US-706 | FE, BE, FIN | Payout review/approve/dispute |
| SLA threshold config + notif audit view | EP-04 / US-406, EP-06 / US-606 | BE, FE, SEC | Sprint 4 notifications |
| Sprint test + sign-off | EP-07, EP-08 | QA, PM, FIN | All Sprint 5 work items |

**Sprint Acceptance Criteria**

- Every completed ride produces one payout record.
- Finance ops can approve, dispute, and export reconciliation data.
- Driver payout status is visible and consistent with finance view.
- Reporting and filtering support pilot operating cadence.

---

## Sprint 6 (Weeks 11-12) — Hardening and Pilot Launch

**Goal:** MVP is stable, operationally safe, and pilot ready.

| Work Item | Epic/Stories | Owner | Depends On |
|-----------|--------------|-------|------------|
| Critical defect burn-down | Cross-epic hardening | BE, FE, QA | Sprints 1-5 complete |
| Regression + performance sanity tests | Cross-epic hardening | QA | Critical defect burn-down |
| Pilot partner onboarding run | Launch readiness | OPS, PM | Regression + performance sanity tests |
| Pilot driver cohort activation | Launch readiness | OPS | Pilot partner onboarding run |
| Readiness review + scorecard sign-off | Launch readiness | PM, OPS, QA, SEC, FIN | All Sprint 6 work items |

**Sprint Acceptance Criteria**

- Zero open Sev-1 defects and no unresolved blocking defects.
- End-to-end pilot workflow passes with real operational users.
- Incident handling, escalation path, and daily operating cadence are confirmed.
- Launch scorecard is approved by PM, OPS, QA, and Security owner.

---

## Cross-Sprint Dependency Guardrails

- EP-01 and EP-03 must be stable before EP-04 assignment work begins.
- EP-04 must be stable before EP-05/EP-06 event-driven flows are accepted.
- EP-05 completion events must be stable before EP-08 payout automation is accepted.
- Any dependency breach moves the blocked story out of sprint scope.

---

## Weekly Cadence (Execution)

| Cadence Item | Owner | Frequency |
|--------------|-------|-----------|
| Sprint planning + dependency check | PM, BE, FE, QA | Start of sprint |
| Mid-sprint risk review | PM, OPS, QA, SEC | Weekly |
| Demo + acceptance review | PM, QA, Owner roles | End of sprint |
| Readiness scoreboard update | PM, OPS | Weekly |
