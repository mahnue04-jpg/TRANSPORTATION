# Amicor Health ISF — MVP Task Breakdown

**Version:** 1.0  
**Date:** May 2026  
**Scope:** First operational MVP — pilot-ready, not full production scale

---

## Table of Contents

1. [Epics](#epics)
2. [User Stories](#user-stories)
3. [Sprint Backlog](#sprint-backlog)
4. [Priority Order](#priority-order)
5. [Technical Dependencies](#technical-dependencies)
6. [Definition of Done](#definition-of-done)
7. [Phased Execution Roadmap](#phased-execution-roadmap)

---

## Epics

| ID | Epic | Description |
|----|------|-------------|
| EP-01 | Authentication | Secure login, role-based session management, and account controls |
| EP-02 | Provider Requests | Full lifecycle for healthcare transportation request intake and tracking |
| EP-03 | Driver Onboarding | Vetting, activation, and readiness workflow for independent contractors |
| EP-04 | Ride Assignment | Dispatch queue, assignment, acceptance, reassignment, and exceptions |
| EP-05 | Trip Status Tracking | Ride state machine from pickup through completion |
| EP-06 | Notifications | Event-driven comms to providers, drivers, and admins at key state changes |
| EP-07 | Admin Dashboard | Operational visibility, queue management, exception controls |
| EP-08 | Payout Tracking | Completion-linked payout record stubs and reconciliation workflow |

---

## User Stories

### EP-01 · Authentication

**US-101** — As a provider, I can log in securely with email and password so I can access my organization's request portal.

**US-102** — As a driver, I can log in and see only my assignments and status tools.

**US-103** — As an admin, I can manage user accounts, roles, and access permissions.

**US-104** — As any user, I can reset my password through a secure email flow.

**US-105** — As an admin, I can deactivate user accounts immediately if needed.

**US-106** — As any user, my session expires after inactivity and I am prompted to re-authenticate.

---

### EP-02 · Provider Requests

**US-201** — As a provider, I can submit a transportation request with appointment time, pickup/dropoff addresses, and rider constraints.

**US-202** — As a provider, I can see the current status of all my active requests in one view.

**US-203** — As a provider, I can cancel a pending request before it is assigned.

**US-204** — As a provider, I can view the history of completed and cancelled requests with timestamps.

**US-205** — As a dispatcher, I can view all incoming requests sorted by urgency and appointment time.

**US-206** — As a dispatcher, I can flag a request for manual review if it contains incomplete or conflicting details.

---

### EP-03 · Driver Onboarding

**US-301** — As a driver applicant, I can submit my application with identity, vehicle, and insurance documents.

**US-302** — As an admin, I can review and approve or reject a driver application.

**US-303** — As an approved driver, I receive account activation with role-scoped access.

**US-304** — As an admin, I can mark a driver inactive for compliance, performance, or safety reasons.

**US-305** — As a driver, I can update my availability windows for scheduling purposes.

---

### EP-04 · Ride Assignment

**US-401** — As a dispatcher, I can assign a validated request to an available, active driver.

**US-402** — As a driver, I receive an assignment notification and can accept or decline within a defined window.

**US-403** — As a dispatcher, I am alerted when an assignment has not been accepted within the SLA window.

**US-404** — As a dispatcher, I can reassign a ride to a different driver after a cancellation or no-show.

**US-405** — As a dispatcher, I can log exception codes against a failed assignment for tracking purposes.

**US-406** — As an admin, I can configure SLA thresholds for assignment response windows.

---

### EP-05 · Trip Status Tracking

**US-501** — As a driver, I can update my ride state: en route to pickup, arrived, in transit, completed.

**US-502** — As a provider, I can see real-time state transitions for my active ride requests.

**US-503** — As an admin, I can view all active rides and their current states on a live board.

**US-504** — As a dispatcher, I am alerted when a ride is stalled in a state beyond the expected time threshold.

**US-505** — As any stakeholder, I can see a timestamped event log for every ride on record.

---

### EP-06 · Notifications

**US-601** — As a provider, I receive a notification when my request is assigned to a driver.

**US-602** — As a provider, I receive a notification when a driver is en route to pickup.

**US-603** — As a provider, I receive a notification if a ride is cancelled or an exception is raised.

**US-604** — As a driver, I receive an assignment offer notification with request details.

**US-605** — As a dispatcher, I receive escalation alerts for SLA breaches and unresolved exceptions.

**US-606** — As an admin, I can view notification delivery status per event for auditing.

---

### EP-07 · Admin Dashboard

**US-701** — As an admin or dispatcher, I can see a live request queue with status indicators and aging alerts.

**US-702** — As an admin, I can view an exceptions panel with open issues sorted by severity.

**US-703** — As an admin, I can view driver availability and assignment load for the current operating window.

**US-704** — As a finance ops user, I can view completed rides pending payout review.

**US-705** — As an admin, I can export daily and weekly operational summaries.

**US-706** — As an admin, I can filter all views by partner, region, date range, and status.

---

### EP-08 · Payout Tracking

**US-801** — As a system, I automatically create a payout record when a ride is marked completed.

**US-802** — As a finance ops user, I can review and approve payout records for settlement.

**US-803** — As a finance ops user, I can flag a payout record for dispute and add notes.

**US-804** — As a driver, I can view my completed ride history and the payout status of each record.

**US-805** — As an admin, I can generate a weekly payout reconciliation export for driver settlements.

---

## Sprint Backlog

### Sprint 1 — Foundation (Weeks 1–2)

| # | Story | Epic | Priority |
|---|-------|------|----------|
| 1 | US-101 | EP-01 | Critical |
| 2 | US-102 | EP-01 | Critical |
| 3 | US-103 | EP-01 | Critical |
| 4 | US-104 | EP-01 | High |
| 5 | US-105 | EP-01 | High |
| 6 | US-106 | EP-01 | High |
| 7 | US-301 | EP-03 | High |
| 8 | US-302 | EP-03 | High |
| 9 | US-303 | EP-03 | High |

**Sprint 1 Goal:** All roles can authenticate. Admin can onboard drivers. Core data model and API foundations are in place.

---

### Sprint 2 — Request Lifecycle (Weeks 3–4)

| # | Story | Epic | Priority |
|---|-------|------|----------|
| 1 | US-201 | EP-02 | Critical |
| 2 | US-202 | EP-02 | Critical |
| 3 | US-203 | EP-02 | High |
| 4 | US-205 | EP-02 | Critical |
| 5 | US-206 | EP-02 | Medium |
| 6 | US-304 | EP-03 | High |
| 7 | US-305 | EP-03 | Medium |
| 8 | US-204 | EP-02 | Medium |

**Sprint 2 Goal:** Providers can submit, track, and cancel requests. Dispatchers see the full intake queue.

---

### Sprint 3 — Assignment and Tracking (Weeks 5–6)

| # | Story | Epic | Priority |
|---|-------|------|----------|
| 1 | US-401 | EP-04 | Critical |
| 2 | US-402 | EP-04 | Critical |
| 3 | US-403 | EP-04 | High |
| 4 | US-404 | EP-04 | High |
| 5 | US-405 | EP-04 | Medium |
| 6 | US-501 | EP-05 | Critical |
| 7 | US-502 | EP-05 | Critical |
| 8 | US-505 | EP-05 | High |

**Sprint 3 Goal:** Dispatcher can assign rides. Drivers can accept and execute. Providers see live ride state.

---

### Sprint 4 — Notifications and Dashboard (Weeks 7–8)

| # | Story | Epic | Priority |
|---|-------|------|----------|
| 1 | US-601 | EP-06 | Critical |
| 2 | US-602 | EP-06 | Critical |
| 3 | US-603 | EP-06 | Critical |
| 4 | US-604 | EP-06 | Critical |
| 5 | US-605 | EP-06 | High |
| 6 | US-701 | EP-07 | Critical |
| 7 | US-702 | EP-07 | High |
| 8 | US-703 | EP-07 | High |
| 9 | US-503 | EP-05 | High |
| 10 | US-504 | EP-05 | High |

**Sprint 4 Goal:** All critical notifications are live. Admin and dispatch can manage operations from the dashboard.

---

### Sprint 5 — Payout, Controls, and Pilot Prep (Weeks 9–10)

| # | Story | Epic | Priority |
|---|-------|------|----------|
| 1 | US-801 | EP-08 | Critical |
| 2 | US-802 | EP-08 | High |
| 3 | US-803 | EP-08 | Medium |
| 4 | US-804 | EP-08 | Medium |
| 5 | US-805 | EP-08 | High |
| 6 | US-704 | EP-07 | High |
| 7 | US-705 | EP-07 | High |
| 8 | US-706 | EP-07 | Medium |
| 9 | US-406 | EP-04 | Medium |
| 10 | US-606 | EP-06 | Medium |

**Sprint 5 Goal:** Payout records are auto-created. Finance ops can review and export. Admin has reporting and filtering controls.

---

### Sprint 6 — Hardening and Launch Readiness (Weeks 11–12)

| # | Story | Epic | Priority |
|---|-------|------|----------|
| 1 | US-606 | EP-06 | Medium |
| 2 | US-406 | EP-04 | Medium |
| 3 | Bug fixes and QA hardening | All | Critical |
| 4 | Pilot partner onboarding | — | Critical |
| 5 | Pilot driver cohort activation | — | Critical |
| 6 | Operational readiness review | — | Critical |
| 7 | Launch scorecard sign-off | — | Critical |

**Sprint 6 Goal:** System is stable, fully exercised, and operationally validated with real users before full launch.

---

## Priority Order

| Priority | Epics |
|----------|-------|
| 1 — Blocking | EP-01 Authentication |
| 2 — Blocking | EP-03 Driver Onboarding |
| 3 — Blocking | EP-02 Provider Requests |
| 4 — Blocking | EP-04 Ride Assignment |
| 5 — Blocking | EP-05 Trip Status Tracking |
| 6 — Required | EP-06 Notifications |
| 7 — Required | EP-07 Admin Dashboard |
| 8 — Required | EP-08 Payout Tracking |

**Rule:** No sprint should be considered complete if its blocking epics have incomplete acceptance criteria. Payout tracking is required for pilot launch but is not a hard blocker on core ride operations.

---

## Technical Dependencies

```
EP-01 Authentication
    └─► EP-02 Provider Requests (requires authenticated provider session)
    └─► EP-03 Driver Onboarding (requires admin and driver role access)

EP-02 Provider Requests
    └─► EP-04 Ride Assignment (dispatcher needs validated request records)

EP-03 Driver Onboarding
    └─► EP-04 Ride Assignment (assignment requires active vetted driver pool)

EP-04 Ride Assignment
    └─► EP-05 Trip Status Tracking (tracking requires assigned ride records)
    └─► EP-06 Notifications (assignment events trigger first critical notifications)

EP-05 Trip Status Tracking
    └─► EP-06 Notifications (state transitions trigger provider/dispatcher notifications)
    └─► EP-07 Admin Dashboard (live queue depends on ride state events)
    └─► EP-08 Payout Tracking (completed ride event triggers payout record creation)

EP-06 Notifications
    └─► EP-07 Admin Dashboard (alert surfaces depend on notification event model)

EP-07 Admin Dashboard
    └─► EP-08 Payout Tracking (finance ops view lives inside dashboard)
```

**Key constraint:** The core data model (User, Request, Assignment, RideEvent, PayoutRecord) must be defined and migrated before Sprint 2 begins. API contracts for these objects must be locked at start of Sprint 1.

---

## Definition of Done

A story is complete when ALL of the following are true:

### Code Quality
- [ ] Feature code is reviewed and approved by at least one other team member
- [ ] No new linting or type-check errors introduced
- [ ] No hard-coded credentials, secrets, or environment-specific values in code

### Functionality
- [ ] Feature matches acceptance criteria in the user story
- [ ] Edge cases and failure paths are handled with appropriate error responses
- [ ] Role-based access controls are enforced (no unauthorized data exposure)

### Testing
- [ ] Unit tests cover core logic paths
- [ ] Manual QA walkthrough of the happy path completed
- [ ] Known exception and failure scenarios tested

### Data and Audit
- [ ] All state transitions are logged with timestamps and user identifiers
- [ ] No orphaned records possible from failed workflows

### Operational Readiness
- [ ] Feature is observable (logs emitted on key actions and errors)
- [ ] Any new configuration is documented in environment template
- [ ] Relevant runbook or escalation note updated if operational behavior changed

### Deployment
- [ ] Feature deployed to staging environment
- [ ] Staging walkthrough passes before marking done

---

## Phased Execution Roadmap

```
PHASE 0 — Design Lock (Pre-Sprint)
    ├─ Finalize data model and ride state machine
    ├─ Define and version API contracts
    ├─ Confirm role permission matrix
    └─ Complete compliance and legal checklist

PHASE 1 — Core Platform (Sprints 1–2, Weeks 1–4)
    ├─ Authentication and role-based access live
    ├─ Driver onboarding and activation flow live
    ├─ Provider request intake and queue live
    └─ Dispatcher request management live
    GATE: Dispatcher can receive, review, and manage requests

PHASE 2 — Operations Core (Sprint 3, Weeks 5–6)
    ├─ Ride assignment and acceptance workflow live
    ├─ Ride state machine and tracking live
    └─ Exception logging and reassignment live
    GATE: A ride can be assigned, accepted, executed, and completed end-to-end

PHASE 3 — Visibility and Control (Sprint 4, Weeks 7–8)
    ├─ All critical notifications live for providers, drivers, dispatchers
    ├─ Admin and dispatch dashboard live
    └─ Live queue and exceptions center live
    GATE: Operations team can manage the full queue from the dashboard

PHASE 4 — Financial and Reporting (Sprint 5, Weeks 9–10)
    ├─ Auto-payout records on ride completion live
    ├─ Finance ops review and export live
    ├─ Weekly reconciliation export live
    └─ Admin reporting and filtering live
    GATE: Finance can reconcile and export a complete week of payout activity

PHASE 5 — Pilot Launch (Sprint 6, Weeks 11–12)
    ├─ Hardening, bug resolution, and QA pass
    ├─ Pilot partner and driver cohort onboarded
    ├─ Operational readiness review complete
    └─ Launch scorecard signed off by operations, product, finance leads
    GATE: System passes end-to-end operational simulation with real users
```

---

## Notes for Development Team

- This breakdown is intentionally MVP-scoped. Do not add features not listed above without explicit backlog prioritization review.
- Each sprint goal is the primary acceptance criterion for the sprint — individual story completion supports the goal but the goal is what matters.
- The gate conditions at each phase are hard stops. Work does not advance to the next phase until the gate condition is met by a real walkthrough, not just code completion.
- AI dispatch optimization, marketplace features, and real-time GPS infrastructure are explicitly out of scope and will be planned post-pilot.
