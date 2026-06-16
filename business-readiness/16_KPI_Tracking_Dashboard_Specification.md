# KPI Tracking Dashboard Specification

## Purpose
Define the minimum KPI dashboard required to manage pilot performance, partner confidence, first revenue, and grant evidence production.

## Owner
Operations Owner (primary), Grant Director (evidence alignment), Finance Owner (revenue metrics).

## When Used
Daily operations monitoring, weekly partner reviews, monthly grant reporting, and launch governance.

## Final Specification Content

### 1. Dashboard Audiences
- Operations team
- Partnership team
- Finance team
- Grant team
- Executive leadership

### 2. KPI Categories
Operational reliability:
- Request-to-queue turnaround
- Queue-to-assignment turnaround
- On-time pickup rate
- Completion rate
- Exception rate
- Exception resolution time

Partnership performance:
- Active partner count
- Weekly rides per partner
- Partner response timeliness
- Partner satisfaction signal (if captured)

Revenue performance:
- Completed rides billed
- Weekly invoice amount
- Collection status
- Driver payout amount
- Gross margin and margin percent

Grant performance:
- Monthly ride counts for target population
- Coverage footprint
- No-show and cancellation trends
- Outcome trend narratives

### 2A. KPI Dictionary (Approved)
| KPI | Definition | Formula | Target | Owner |
|---|---|---|---|---|
| Request-to-Queue Turnaround | Time from provider request submission to queued/rejected decision | avg(decision_timestamp - request_timestamp) | <=15 minutes | Operations Lead |
| Queue-to-Assignment Turnaround | Time from queued state to assigned state | avg(assigned_timestamp - queued_timestamp) | <=90 minutes | Dispatch Supervisor |
| On-Time Pickup Rate | Share of completed rides where pickup occurs within scheduled window | on_time_pickups / completed_rides | >=92% | Operations Lead |
| Completion Rate | Share of non-cancelled requests that complete | completed_rides / (total_requests - cancelled_requests) | >=95% | COO |
| Cancellation Rate | Share of requests cancelled before completion | cancelled_requests / total_requests | <=8% | Partnership Director |
| Exception Rate | Share of rides entering exception state | exception_rides / total_requests | <=6% | Operations Lead |
| Exception Resolution Time | Time from exception open to closure | avg(exception_closed_at - exception_opened_at) | <=20 minutes | Dispatch Supervisor |
| Invoice Realization Rate | Billed amount realized as collectible invoice amount | invoiced_amount / expected_billable_amount | >=98% | Finance Lead |
| Collection Cycle Time | Time from invoice issue to payment receipt | avg(payment_received_at - invoice_issued_at) | <=21 days | Finance Lead |
| Gross Margin Percent | Margin after direct driver payout | (billed_amount - driver_payout_amount) / billed_amount | >=25% | CFO |

### 3. Required Filters
- Date range
- Partner organization
- Service area
- Ride type/accessibility type
- Status/exception type

### 4. Data Refresh Cadence
- Operations metrics: near real-time or hourly
- Revenue metrics: daily and weekly close
- Grant evidence metrics: weekly and monthly snapshots

Operational alert thresholds:
- On-time pickup rate below 90% in any rolling 7-day window -> Sev 2 escalation
- Completion rate below 93% in any rolling 7-day window -> Sev 2 escalation
- Exception resolution time above 25 minutes in any rolling 7-day window -> Sev 2 escalation
- Collection cycle time above 30 days on any invoice -> CFO escalation

### 5. Reporting Outputs
- Weekly operations report export
- Weekly billing/payout summary export
- Monthly grant evidence export
- Partner-specific performance summary

### 6. Governance Rules
- Metric definitions version-controlled
- Owner per KPI assigned
- Any KPI definition change requires COO approval

## Missing Information Required from Amicor
- Dashboard tool choice and access roles
- Partner-facing vs internal-only metric visibility rules
