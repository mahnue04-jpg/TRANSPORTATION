# Dashboard Planning (MVP)

## Objective

Design an operations-first dashboard for dispatch, visibility, and exception management.

## Primary Dashboard Views

1. Live Queue View
- New requests
- Unassigned requests
- Aging request indicators

2. Assignment Board
- Assigned rides by state
- Driver status and capacity snapshot
- Reassignment actions

3. Exception Center
- Active exceptions by severity
- SLA breach risk indicators
- Escalation and resolution actions

4. Financial Snapshot
- Completed rides pending payout review
- Disputed rides
- Weekly settlement status

5. Reporting Panel
- Daily/weekly KPI summary
- Partner and provider filters
- Export actions

## Alerting Rules (MVP)

- Unassigned request nearing SLA threshold
- Driver cancellation after acceptance
- Ride stalled in state beyond threshold
- Payout exceptions requiring finance review

## MVP UX Principles

- Operational clarity over visual complexity
- One-click access to escalation actions
- Time-based indicators for all active workflows

## Acceptance Criteria

- Dispatch can identify and act on critical items in under 60 seconds.
- Exceptions are discoverable without navigating across multiple modules.
- Operations leadership can run daily performance review from dashboard data.
