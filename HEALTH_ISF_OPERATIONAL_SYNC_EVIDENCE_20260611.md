# Health ISF Operational Sync Evidence

Generated at: 2026-06-11T21:47:21.9410545-05:00
Scope: Rider -> Dispatch -> Driver lifecycle synchronization proof for one pinned ride ID

## Evidence Target
- Ride ID: 6e23a054-89b2-4f7d-81b2-bf44a73557d0
- Passenger: UI Sync Rider
- Driver: 3467a045-f47d-4294-9def-a33cbec94cc4 (Workflow Driver 48337842)
- Organization: ca8d0c7c-1fff-4465-99d7-75a1fc51543e

## 5-Gate PASS Checklist (Same Ride ID)

1) User action visible in UI: PASS
- In-tab action: submitted rider intake form for UI Sync Rider.
- Same-tab queue rendered ride card with ID prefix 6e23a054 in Pending Queue.

2) API call returns success: PASS
- PATCH /api/health-isf/rides/{ride_id}/assign-driver -> accepted
- POST /api/health-isf/drivers/{driver_id}/accept-ride -> accepted
- POST /api/health-isf/drivers/{driver_id}/arrived-pickup -> accepted
- POST /api/health-isf/drivers/{driver_id}/pickup-complete -> in_transit
- POST /api/health-isf/drivers/{driver_id}/dropoff-complete -> completed

3) Database write confirmed: PASS
- GET /api/health-isf/rides/{ride_id} => status=completed, lifecycle_state=completed
- Status history rows persisted (7 total):
  - requested -> queued
  - queued -> assigned
  - assigned -> driver_en_route
  - driver_en_route -> arrived
  - arrived -> rider_onboard
  - rider_onboard -> in_progress
  - in_progress -> completed

4) Real-time/event update emitted: PASS
- Dispatch history rows persisted (10 total).
- Terminal event emission row:
  - action=dispatch_event_emitted
  - note=event=assignment-completed
  - emitted_event_name=assignment-completed
  - websocket_delivery_target=dispatcher_board,workflow_events,ride_updates,driver_dashboard

5) UI refresh shows new state in same tab: PASS
- Same-tab refresh rendered UI Sync Rider in Completed Rides with status completed and assigned driver Workflow Driver 48337842.

## Canonical API Snapshot
- Ride status: completed
- Ride timestamps:
  - requested_at: 2026-06-12T02:41:12.835808
  - assigned_at: 2026-06-12T02:44:46.296956
  - enroute_at: 2026-06-12T02:44:46.370169
  - arrived_at: 2026-06-12T02:44:46.419697
  - picked_up_at: 2026-06-12T02:44:46.511865
  - transporting_at: 2026-06-12T02:44:46.515993
  - completed_at: 2026-06-12T02:44:46.560740

## Full Transition Evidence (History)
1. 2026-06-12T02:41:12.837968 | requested -> queued | Ride created and queued for dispatch
2. 2026-06-12T02:44:46.296977 | queued -> assigned | Driver assigned
3. 2026-06-12T02:44:46.370210 | assigned -> driver_en_route | Driver accepted assignment
4. 2026-06-12T02:44:46.419723 | driver_en_route -> arrived | Driver arrived at pickup
5. 2026-06-12T02:44:46.511889 | arrived -> rider_onboard | Pickup completed
6. 2026-06-12T02:44:46.516042 | rider_onboard -> in_progress | Transport started after pickup completed
7. 2026-06-12T02:44:46.560768 | in_progress -> completed | Dropoff completed

## Event Emission Trail (Dispatch)
- 2026-06-12T02:41:12.908009 | dispatch_event_emitted | event=ride-created
- 2026-06-12T02:41:12.924031 | dispatch_event_emitted | event=provider-request-created
- 2026-06-12T02:44:46.578763 | dispatch_event_emitted | event=assignment-completed

## Notes
- The workflow-path endpoint currently returns ride_status=ridestatus.completed while canonical ride status endpoint returns status=completed. This does not affect lifecycle completion truth in rides/history/dispatch-history but should be normalized for strict proof consistency.
