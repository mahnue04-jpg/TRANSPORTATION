# AMICOR Health ISF Role Wireframes

Status: Approved
Dependency: HEALTH_ISF_OPERATIONAL_BLUEPRINT.md

## Approval Rule
Implementation must not continue until wireframes are approved.

## 1) Driver Wireframe (Field Workflow First)

Lifecycle Coverage: Steps 4, 5, 6, 7, 8

```text
+------------------------------------------------------------+
| Current Trip                                               |
| Rider Name: [Name]                                         |
| Pickup Address: [Address]                                  |
| Destination Address: [Address]                             |
| ETA: [Minutes]                                             |
|                                                            |
| [Call Rider] [Arrived] [No Show] [Pickup] [Complete Trip] |
+------------------------------------------------------------+
| Secondary Tabs: [Earnings] [Documents] [History]          |
+------------------------------------------------------------+
```

Required Data:
- Active assignment
- Rider contact
- Trip status and transition eligibility

## 2) Rider Wireframe

Lifecycle Coverage: Steps 1, 2, 3, 5, 8

```text
+------------------------------------------------------------+
| Request Ride                                               |
| Pickup: [Address]                                          |
| Destination: [Address]                                     |
| Appointment Window: [Time]                                 |
| [Submit Request]                                           |
+------------------------------------------------------------+
| Request Status                                              |
| Authorization: [Pending/Approved/Denied]                  |
| Dispatch: [Queued/Assigned]                                |
| Driver ETA: [Minutes]                                      |
| Trip: [In Progress/Completed]                              |
+------------------------------------------------------------+
```

## 3) Dispatcher Wireframe

Lifecycle Coverage: Steps 3, 4, 5, 6, 7

```text
+------------------------------------------------------------+
| Dispatch Queue                                              |
| [Ride ID] [Priority] [Auth] [Pickup] [Destination] [SLA]   |
| [Assign Driver] [Reassign] [Escalate]                      |
+------------------------------------------------------------+
| Assignment Board                                            |
| Driver Pool: [Available/Busy/Offline]                      |
| Active Trips: [Arrival/Pickup/In Transit]                  |
+------------------------------------------------------------+
```

## 4) Provider Wireframe

Lifecycle Coverage: Steps 2, 11

```text
+------------------------------------------------------------+
| Authorization Worklist                                      |
| [Request ID] [Patient] [Service Type] [Decision]            |
| [Approve] [Deny] [Request More Info]                        |
+------------------------------------------------------------+
| Oversight and Quality                                       |
| Completed Trips Requiring Review                            |
| Provider Disputes and Resolution Queue                      |
+------------------------------------------------------------+
```

## 5) Supervisor Wireframe

Lifecycle Coverage: Steps 3 through 11 (exception governance)

```text
+------------------------------------------------------------+
| Exception and Escalation Console                            |
| [Incident] [Policy Breach] [No Show] [Late Arrival]        |
| [Approve Override] [Reject Override] [Assign Resolution]    |
+------------------------------------------------------------+
| Governance Trail                                             |
| Decision History and Role Attribution                        |
| Compliance Checkpoint Status                                 |
+------------------------------------------------------------+
```

## 6) Billing Wireframe

Lifecycle Coverage: Steps 9, 10

```text
+------------------------------------------------------------+
| Claim Preparation Queue                                     |
| [Trip ID] [Completion Evidence] [Provider] [Claim Status]   |
| [Submit Claim] [Reconcile Denial]                           |
+------------------------------------------------------------+
| Revenue and Reporting                                       |
| Daily Claims, Payouts, Denials, Outstanding Receivables     |
| Export Financial and Operational Reports                    |
+------------------------------------------------------------+
```

## 7) Lifecycle-to-Screen Traceability

| Lifecycle Step | Primary Screen |
|---|---|
| 1 Ride Request | Rider Request Ride |
| 2 Eligibility / Authorization | Provider Authorization Worklist |
| 3 Dispatch | Dispatcher Dispatch Queue |
| 4 Driver Assignment | Dispatcher Assignment Board |
| 5 Driver Arrival | Driver Current Trip |
| 6 Passenger Pickup | Driver Current Trip |
| 7 Trip Execution | Driver Current Trip |
| 8 Trip Completion | Driver Current Trip |
| 9 Billing | Billing Claim Preparation Queue |
| 10 Reporting | Billing Revenue and Reporting |
| 11 Provider Oversight | Provider Oversight and Quality |

## 8) Wireframe Approval Log

| Role | Status | Approver | Date |
|---|---|---|---|
| Driver | Approved | AMICOR Health ISF Executive Directive | 2026-06-10 |
| Rider | Approved | AMICOR Health ISF Executive Directive | 2026-06-10 |
| Dispatcher | Approved | AMICOR Health ISF Executive Directive | 2026-06-10 |
| Provider | Approved | AMICOR Health ISF Executive Directive | 2026-06-10 |
| Supervisor | Approved | AMICOR Health ISF Executive Directive | 2026-06-10 |
| Billing | Approved | AMICOR Health ISF Executive Directive | 2026-06-10 |
