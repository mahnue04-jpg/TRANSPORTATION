# Transportation Coordination Workflow

## Workflow Stages

1. Intake: provider submits request with appointment and rider constraints.
2. Validation: serviceability, timing, and eligibility checks are applied.
3. Assignment: best-fit vetted driver is selected.
4. Execution: pickup, transit, and dropoff are tracked via ride states.
5. Completion: final status and ride record are confirmed.
6. Settlement: ride data is passed to payout tracking and reporting.

## Ride States (MVP)

- `requested`
- `queued`
- `assigned`
- `en_route_pickup`
- `in_transit`
- `completed`
- `cancelled`
- `exception`

## Exception Handling

- Driver cancellation or no-show
- Rider unavailable at pickup
- Timing conflict with appointment window
- Safety or compliance escalation
