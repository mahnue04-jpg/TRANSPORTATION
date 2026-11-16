# Calendar connection: first implementation slice

This draft is stacked on Growth Agent PR #490, commit
`e4d0aec2e37af6b23e107c71c03eadf01d586287`. It must not be merged or deployed
as a live calendar connection. No existing staging service is changed.

## Implemented

The pure Google Calendar request planner prepares creation, time-only PATCH
rescheduling, and cancellation against a trusted organization/calendar binding.
Tenant and appointment determine a stable Google-compatible event ID; retries
prepare the same create request rather than generating another event ID.
Timezone-aware input is mandatory; event times are converted to UTC. Requests
omit attendees, contact details and credentials, with notifications disabled.
Tests cover the lifecycle, repeat requests, invalid times and identifiers,
tenant mismatch, and calendar path escaping. They use no Google account.

This code creates request descriptions only. It is not imported by the active
service, sends no network traffic and stores no data. The binding is not an
authorization token: never accept it from a caller as evidence of ownership.

## Remaining before a real customer pilot

1. Owner-authorized Google OAuth with least required scopes, encrypted server-side
   refresh-token storage, revoke/reconnect behavior and verified tenant ownership.
2. Trusted calendar selection and availability reads including events added
   outside Nova. Define conflict handling; checking availability alone does not
   atomically reserve an external calendar slot.
3. Durable sync/outbox records linking tenant, appointment, connection, calendar,
   event ID and operation version. Do not mark remote sync confirmed before
   provider acknowledgement; distinguish pending, failed and confirmed states.
4. A bounded dispatcher that handles timeouts, quotas, expired credentials,
   retryable failures, stale versions and ETag conflicts. Reconcile a create
   conflict by reading and validating the expected event; do not treat any 409
   as success. Reconcile missing events on cancellation without claiming an
   unrelated deletion. Order create/reschedule/cancel and prevent stale retries
   from restoring cancelled bookings. Cancel/rebook needs explicit lifecycle
   treatment because the internal service may reuse a cancelled appointment ID.
5. Integrate all three service operations with that outbox, owner status and
   recovery controls; test authorization through actual authenticated HTTP routes.
6. Separate owner notification delivery and evidence of actual receipt.
7. An explicitly approved test calendar lifecycle: book once, repeat safely,
   reschedule same event, cancel, restart recovery and disconnect. No paid voice,
   customer outreach, production migration or production deployment in this draft.

## Provider reference

- https://developers.google.com/workspace/calendar/api/v3/reference/events/insert
- https://developers.google.com/workspace/calendar/api/v3/reference/events/patch
- https://developers.google.com/workspace/calendar/api/v3/reference/events/delete

Stable IDs reduce accidental duplicates; this offline contract is not proof of
remote exactly-once delivery, conflict-free booking, or end-to-end acceptance.
