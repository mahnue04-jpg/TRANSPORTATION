# End-to-End Transportation Workflow Lifecycle Report

Generated: 2026-06-10T03:42:46.383279+00:00
Runtime: http://127.0.0.1:8010
Ride ID: 28177374-8d16-454a-89ef-0769518dedb5
Request ID: 7272bb8e-2965-4e14-b61c-5d909fb43cae
Driver ID: 2434bc0c-13d8-4cb3-b2c0-284ef44c859d

## Final Verdict
- Overall: PASS
- Passed steps: 11/11

## Step 1: Provider requests ride
- PASS/FAIL: PASS
- Screenshot: evidence/workflow_11step/step_01.png
- API Evidence:
  - Method: POST
  - Path: /api/health-isf/customer-requests
  - Status: 201
  - Response Summary: {"id": "7272bb8e-2965-4e14-b61c-5d909fb43cae", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "dispatch_status": "pending"}
- Database Evidence:
  - customer_request.dispatch_status: pending
  - ride.status: pending
  - ride.lifecycle_state: queued
  - ride.driver_id: None
  - assignments(latest up to 3): []

## Step 2: Ride appears in dispatch queue
- PASS/FAIL: PASS
- Screenshot: evidence/workflow_11step/step_02.png
- API Evidence:
  - Method: GET
  - Path: /api/health-isf/dispatch/queue?limit=100
  - Status: 200
  - Response Summary: {"queue_match": {"ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "passenger_name": "Provider Requested Rider", "requested_at": "2026-06-10T03:42:44.675009", "ride_status": "RideStatus.PENDING", "assignment_state": "pending_assignment", "dispatcher_message": "No available driver", "attempt_index": 0, "offered_driver_id": null, "offer_expires_at": null, "score": null, "queued_at": "2026-06-10T03:42:44.675009", "search_started_at": null, "offered_at": null, "assigned_at": null, "accepted_at": null, "reassignment_pending_at": null, "reassignment_started_at": null, "reassignment_completed_at": null, "reassignment_attempt_count": 0, "reassignment_reason": null, "reassignment_chain_id": null}, "count": 56}
- Database Evidence:
  - customer_request.dispatch_status: pending
  - ride.status: pending
  - ride.lifecycle_state: queued
  - ride.driver_id: None
  - assignments(latest up to 3): []

## Step 3: Automatic driver assignment executes
- PASS/FAIL: PASS
- Screenshot: evidence/workflow_11step/step_03.png
- API Evidence:
  - Method: POST
  - Path: /api/health-isf/dispatcher/rides/28177374-8d16-454a-89ef-0769518dedb5/auto-assign
  - Status: 200
  - Response Summary: {"approve_status": 200, "approve_response": {"offer": null, "request": {"id": "7272bb8e-2965-4e14-b61c-5d909fb43cae", "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "rider_name": "Provider Requested Rider", "rider_phone": "+15559296731", "pickup_address": "111 Provider Clinic Way", "dropoff_address": "222 Care Center Ave", "scheduled_time": null, "ride_type": "healthcare", "recurring": false, "recurring_pattern": null, "notes": "Step1 provider request", "dispatch_status": "approved", "pending_at": "2026-06-10T03:42:44.731350", "broadcasted_at": "2026-06-10T03:42:44.837057", "accepted_at": null, "assigned_at": null, "in_progress_at": null, "completed_at": null, "cancelled_at": null, "created_at": "2026-06-10T03:42:44.731351", "updated_at": "2026-06-10T03:42:44.837108"}, "ride": {"passenger_name": "Provider Requested Rider", "passenger_phone": "+15559296731", "pickup_address": "111 Provider Clinic Way", "dropoff_address": "222 Care Center Ave", "service_type": "medical_transport", "notes": "Step1 provider request", "id": "28177374-8d16-454a-89ef-0769518dedb5", "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e", "provider_id": "6e0c86e1-fce3-4ac6-ba56-b55717e84cb2", "driver_id": null, "vehicle_id": null, "status": "pending", "lifecycle_state": "queued", "estimated_distance_miles": null, "estimated_duration_minutes": null, "priority_score": null, "priority_tag": null, "is_emergency": false, "appointment_time": null, "recurring_trip_pattern": null, "recurring_schedule_id": null, "recurring_instance_date": null, "ai_dispatch_context": null, "requested_at": "2026-06-10T03:42:44.675009", "assigned_at": null, "enroute_at": null, "arrived_at": null, "picked_up_at": null, "transporting_at": null, "accepted_at": null, "completed_at": null}, "message": "Customer request approved for dispatch workflow."}, "auto_assign_response": {"id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "status": "accepted", "lifecycle_state": "assigned"}}
- Database Evidence:
  - customer_request.dispatch_status: assigned
  - ride.status: accepted
  - ride.lifecycle_state: assigned
  - ride.driver_id: 2434bc0c-13d8-4cb3-b2c0-284ef44c859d
  - assignments(latest up to 3): [{"id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "assignment_state": "offered", "offered_at": null, "assigned_at": null, "accepted_at": null, "pickup_complete_at": null, "dropoff_complete_at": null, "updated_at": "2026-06-10 03:42:45.020791"}]

## Step 4: Driver sees ride
- PASS/FAIL: PASS
- Screenshot: evidence/workflow_11step/step_04.png
- API Evidence:
  - Method: GET
  - Path: /api/health-isf/drivers/2434bc0c-13d8-4cb3-b2c0-284ef44c859d/active-offer
  - Status: 200
  - Response Summary: {"driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "offer": {"id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "offer_id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "assignment_state": "offered", "attempt_index": 1, "score": null, "score_breakdown": {}, "timeout_seconds": 90, "queued_at": "2026-06-10T03:42:45.020791", "search_started_at": "2026-06-10T03:42:45.020791", "offered_at": null, "offer_expires_at": null, "assigned_at": null, "accepted_at": null, "en_route_pickup_at": null, "pickup_complete_at": null, "dropoff_complete_at": null, "reassignment_pending_at": null, "reassignment_started_at": null, "reassignment_completed_at": null, "reassignment_attempt_count": 0, "reassignment_reason": null, "reassignment_chain_id": "17cfeda4-1f13-4ad2-bfc0-2aa98f5bb2f6", "rejected_at": null, "expired_at": null, "closed_reason": null}}
- Database Evidence:
  - customer_request.dispatch_status: assigned
  - ride.status: accepted
  - ride.lifecycle_state: assigned
  - ride.driver_id: 2434bc0c-13d8-4cb3-b2c0-284ef44c859d
  - assignments(latest up to 3): [{"id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "assignment_state": "offered", "offered_at": null, "assigned_at": null, "accepted_at": null, "pickup_complete_at": null, "dropoff_complete_at": null, "updated_at": "2026-06-10 03:42:45.020791"}]

## Step 5: Driver accepts ride
- PASS/FAIL: PASS
- Screenshot: evidence/workflow_11step/step_05.png
- API Evidence:
  - Method: POST
  - Path: /api/health-isf/dispatch/offers/2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb/accept
  - Status: 200
  - Response Summary: {"id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "assignment_state": "accepted"}
- Database Evidence:
  - customer_request.dispatch_status: assigned
  - ride.status: accepted
  - ride.lifecycle_state: assigned
  - ride.driver_id: 2434bc0c-13d8-4cb3-b2c0-284ef44c859d
  - assignments(latest up to 3): [{"id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "assignment_state": "accepted", "offered_at": null, "assigned_at": "2026-06-10 03:42:45.103830", "accepted_at": "2026-06-10 03:42:45.114536", "pickup_complete_at": null, "dropoff_complete_at": null, "updated_at": "2026-06-10 03:42:45.114536"}]

## Step 6: Dispatcher sees accepted ride
- PASS/FAIL: PASS
- Screenshot: evidence/workflow_11step/step_06.png
- API Evidence:
  - Method: GET
  - Path: /api/health-isf/dispatch/active-assignments?limit=100
  - Status: 200
  - Response Summary: {"match": {"offer_id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "driver_name": "Revenue Driver 1c4700", "assignment_state": "accepted", "attempt_index": 1, "offered_at": null, "offer_expires_at": null, "assigned_at": "2026-06-10T03:42:45.103830", "accepted_at": "2026-06-10T03:42:45.114536", "en_route_pickup_at": null, "pickup_complete_at": null, "dropoff_complete_at": null, "reassignment_pending_at": null, "reassignment_started_at": null, "reassignment_completed_at": null, "reassignment_attempt_count": 0, "reassignment_reason": null, "reassignment_chain_id": "17cfeda4-1f13-4ad2-bfc0-2aa98f5bb2f6", "score": null, "passenger_name": "Provider Requested Rider", "ride_status": "RideStatus.ACCEPTED", "ownership_locked": false, "ownership_locked_by_user_id": null, "ownership_locked_at": null, "ownership_lock_expires_at": null, "ownership_is_current_user": false}}
- Database Evidence:
  - customer_request.dispatch_status: assigned
  - ride.status: accepted
  - ride.lifecycle_state: assigned
  - ride.driver_id: 2434bc0c-13d8-4cb3-b2c0-284ef44c859d
  - assignments(latest up to 3): [{"id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "assignment_state": "accepted", "offered_at": null, "assigned_at": "2026-06-10 03:42:45.103830", "accepted_at": "2026-06-10 03:42:45.114536", "pickup_complete_at": null, "dropoff_complete_at": null, "updated_at": "2026-06-10 03:42:45.114536"}]

## Step 7: Driver marks en route
- PASS/FAIL: PASS
- Screenshot: evidence/workflow_11step/step_07.png
- API Evidence:
  - Method: POST
  - Path: /api/health-isf/drivers/2434bc0c-13d8-4cb3-b2c0-284ef44c859d/accept-ride
  - Status: 200
  - Response Summary: {"id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "status": "accepted", "lifecycle_state": "driver_en_route"}
- Database Evidence:
  - customer_request.dispatch_status: assigned
  - ride.status: accepted
  - ride.lifecycle_state: driver_en_route
  - ride.driver_id: 2434bc0c-13d8-4cb3-b2c0-284ef44c859d
  - assignments(latest up to 3): [{"id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "assignment_state": "en_route_pickup", "offered_at": null, "assigned_at": "2026-06-10 03:42:45.103830", "accepted_at": "2026-06-10 03:42:45.114536", "pickup_complete_at": null, "dropoff_complete_at": null, "updated_at": "2026-06-10 03:42:45.296644"}]

## Step 8: Driver marks arrived
- PASS/FAIL: PASS
- Screenshot: evidence/workflow_11step/step_08.png
- API Evidence:
  - Method: POST
  - Path: /api/health-isf/drivers/2434bc0c-13d8-4cb3-b2c0-284ef44c859d/arrived-pickup
  - Status: 200
  - Response Summary: {"id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "status": "accepted", "lifecycle_state": "arrived"}
- Database Evidence:
  - customer_request.dispatch_status: assigned
  - ride.status: accepted
  - ride.lifecycle_state: arrived
  - ride.driver_id: 2434bc0c-13d8-4cb3-b2c0-284ef44c859d
  - assignments(latest up to 3): [{"id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "assignment_state": "en_route_pickup", "offered_at": null, "assigned_at": "2026-06-10 03:42:45.103830", "accepted_at": "2026-06-10 03:42:45.114536", "pickup_complete_at": null, "dropoff_complete_at": null, "updated_at": "2026-06-10 03:42:45.347415"}]

## Step 9: Driver marks pickup complete
- PASS/FAIL: PASS
- Screenshot: evidence/workflow_11step/step_09.png
- API Evidence:
  - Method: POST
  - Path: /api/health-isf/drivers/2434bc0c-13d8-4cb3-b2c0-284ef44c859d/pickup-complete
  - Status: 200
  - Response Summary: {"id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "status": "in_transit", "lifecycle_state": "in_progress"}
- Database Evidence:
  - customer_request.dispatch_status: in_progress
  - ride.status: in_transit
  - ride.lifecycle_state: in_progress
  - ride.driver_id: 2434bc0c-13d8-4cb3-b2c0-284ef44c859d
  - assignments(latest up to 3): [{"id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "assignment_state": "pickup_complete", "offered_at": null, "assigned_at": "2026-06-10 03:42:45.103830", "accepted_at": "2026-06-10 03:42:45.114536", "pickup_complete_at": "2026-06-10 03:42:45.387245", "dropoff_complete_at": null, "updated_at": "2026-06-10 03:42:45.387245"}]

## Step 10: Driver marks dropoff complete
- PASS/FAIL: PASS
- Screenshot: evidence/workflow_11step/step_10.png
- API Evidence:
  - Method: POST
  - Path: /api/health-isf/drivers/2434bc0c-13d8-4cb3-b2c0-284ef44c859d/dropoff-complete
  - Status: 200
  - Response Summary: {"id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "status": "completed", "lifecycle_state": "completed"}
- Database Evidence:
  - customer_request.dispatch_status: completed
  - ride.status: completed
  - ride.lifecycle_state: completed
  - ride.driver_id: 2434bc0c-13d8-4cb3-b2c0-284ef44c859d
  - assignments(latest up to 3): [{"id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "assignment_state": "dropoff_complete", "offered_at": null, "assigned_at": "2026-06-10 03:42:45.103830", "accepted_at": "2026-06-10 03:42:45.114536", "pickup_complete_at": "2026-06-10 03:42:45.387245", "dropoff_complete_at": "2026-06-10 03:42:45.444745", "updated_at": "2026-06-10 03:42:45.444745"}]

## Step 11: Ride status becomes completed
- PASS/FAIL: PASS
- Screenshot: evidence/workflow_11step/step_11.png
- API Evidence:
  - Method: GET
  - Path: /api/health-isf/rides/28177374-8d16-454a-89ef-0769518dedb5
  - Status: 200
  - Response Summary: {"ride": {"id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "status": "completed", "lifecycle_state": "completed"}}
- Database Evidence:
  - customer_request.dispatch_status: completed
  - ride.status: completed
  - ride.lifecycle_state: completed
  - ride.driver_id: 2434bc0c-13d8-4cb3-b2c0-284ef44c859d
  - assignments(latest up to 3): [{"id": "2a11c5a5-cf11-4ec8-9f0f-14aa03a445eb", "ride_id": "28177374-8d16-454a-89ef-0769518dedb5", "driver_id": "2434bc0c-13d8-4cb3-b2c0-284ef44c859d", "assignment_state": "dropoff_complete", "offered_at": null, "assigned_at": "2026-06-10 03:42:45.103830", "accepted_at": "2026-06-10 03:42:45.114536", "pickup_complete_at": "2026-06-10 03:42:45.387245", "dropoff_complete_at": "2026-06-10 03:42:45.444745", "updated_at": "2026-06-10 03:42:45.444745"}]

## Evidence Files
- JSON results: evidence/workflow_11step/workflow_11step_results.json
- Screenshots: evidence/workflow_11step/step_01.png through step_11.png