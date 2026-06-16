# Amicor Health ISF Operational MVP Plan

## 1. Plan Purpose

This plan defines the first operational MVP build for Amicor Health ISF, focused on healthcare transportation coordination in rural and behavioral health contexts.

This is a launch-focused plan, not a full enterprise rollout.

## 2. Operational Outcomes (MVP)

By MVP launch, the platform must:

- Allow providers to submit and track ride requests.
- Allow dispatch/admin teams to assign vetted drivers quickly.
- Allow drivers to accept, execute, and complete rides with status updates.
- Trigger notifications at critical ride state changes.
- Provide basic payout tracking and reconciliation visibility.
- Produce operational and partner-ready reporting.

## 3. MVP Scope Boundaries

### In Scope

- Authentication and role-based access
- Provider request intake and request lifecycle management
- Driver assignment and reassignment workflows
- Ride tracking state machine
- Notifications (in-app first, SMS/email adapter-ready)
- Admin dashboard operations center
- Payout tracking and weekly reconciliation exports
- Reporting baseline for operations and grants

### Out of Scope (Phase 1)

- Real-time GPS precision tracking stack
- Full claims adjudication and reimbursement automation
- Advanced AI dispatch optimization in production
- Deep EMR/EHR integrations

## 4. Workstream Breakdown

1. Workflow Planning: map end-to-end request-to-payout lifecycle with SLA checkpoints.
2. Dashboard Planning: define operational dashboard views, alerts, and controls.
3. Provider Flow: define provider portal journey from onboarding to request completion.
4. Driver Flow: define independent driver onboarding and ride execution lifecycle.
5. Operational Execution: define runbooks, staffing model, cadence, and incident handling.

Detailed artifacts are in `workstreams/`.

## 5. Role Model and Ownership

- `admin`: system governance, user management, configuration control
- `dispatcher`: assignment, reassignments, exception handling
- `provider`: request creation, tracking, cancellation requests
- `partner_staff`: operational visibility and service coordination
- `driver`: assignment acceptance and ride execution
- `finance_ops`: payout review, settlement, reconciliation

## 6. 12-Week Operational Build Timeline

## Weeks 1-2: Foundation and Alignment

- Finalize lifecycle states and exception taxonomy
- Confirm role permissions and data visibility rules
- Agree SLA targets for assignment and completion
- Lock API contracts for requests, assignments, and statuses

## Weeks 3-6: Core Workflow Build

- Implement provider request intake and validation
- Implement dispatch queue and driver assignment workflow
- Implement ride state transitions and event logging
- Enable critical notifications for all key ride events

## Weeks 7-9: Control and Financial Layer

- Implement admin dashboard MVP views
- Implement payout tracking and dispute flags
- Implement baseline reporting views and exports
- Implement escalation pathways for exceptions

## Weeks 10-12: Pilot and Stabilization

- Execute pilot with selected providers and driver cohort
- Run operational readiness drills and incident playbooks
- Tune assignment SLAs and workflow bottlenecks
- Finalize launch scorecard and go-live readiness decision

## 7. MVP KPI Scorecard

Track weekly and cumulatively:

- Request volume by provider/region
- Time to first assignment
- Assignment acceptance rate
- Ride completion rate
- Cancellation and no-show rates
- Exception resolution time
- Payout cycle time
- Provider satisfaction signal
- Driver reliability score

## 8. Core Operational Cadence

- Daily dispatch standup (exceptions, staffing, backlog)
- Weekly operations review (KPIs, partner issues, payout reconciliation)
- Biweekly product-ops planning (workflow adjustments, backlog priorities)
- Monthly leadership review (growth, risk, funding/reporting outcomes)

## 9. Risks and Controls

- Driver availability gaps in rural windows: maintain reserve driver pool.
- Late reassignment due to cancellations: enforce rapid fallback rules.
- Incomplete ride status updates: require state confirmation checkpoints.
- Payout disputes: maintain auditable event and completion records.
- Partner confidence risk: publish transparent weekly operational reporting.

## 10. Launch Readiness Gate

MVP is launch-ready when:

- End-to-end request-to-payout flow passes operational simulation.
- Dashboard shows live queue, exceptions, and settlement visibility.
- Provider and driver pilot users can complete journeys without manual workaround.
- Weekly reporting supports partner and grant reporting obligations.
