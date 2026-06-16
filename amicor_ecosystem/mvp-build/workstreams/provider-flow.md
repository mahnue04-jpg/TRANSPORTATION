# Provider Flow (MVP)

## Objective

Define the provider user journey for request creation, visibility, and coordination.

## Provider Journey

1. Login and Access
- Provider user authenticates.
- Role-scoped portal loads only their organization data.

2. Request Creation
- Provider creates transportation request.
- Required fields: appointment time, pickup/dropoff, rider needs, notes.

3. Request Confirmation
- System confirms request receipt and status `queued`.
- Provider receives expected assignment timeline.

4. Tracking
- Provider sees status transitions (`assigned`, `en_route_pickup`, `in_transit`, `completed`).
- Exception notifications appear in near real time.

5. Exception Interaction
- Provider receives cancellation or delay notices.
- Provider can submit support/escalation input.

6. Closure
- Completed status and summary are available.
- Provider can access period reporting view.

## Provider MVP Requirements

- Fast request entry form with clear validation
- Transparent status timeline per request
- Notification preferences at organization/user level
- Audit-friendly request history

## Acceptance Criteria

- Providers can submit a request in under 2 minutes.
- Providers can always see current ride status for active requests.
- Escalation path is visible and actionable for exceptions.
