# Ride Lifecycle Evidence Report

Source file: scripts/workflow_evidence_run2.json

## Workflow Status
- [x] create_patient (status 201)
- [x] create_driver (status 201)
- [x] create_vehicle (status 201)
- [x] create_ride (status 201)
- [x] assign_driver (status 200)
- [x] dispatch_ride (status 200)
- [x] start_trip (status 200)
- [x] complete_trip (status 200)

## Auto Seed Result
- patients: 5
- drivers: 5
- vehicles: 5
- rides: 5

## Browser Network Trace: Create Patient Button
Request URL: http://127.0.0.1:8011/api/health-isf/customer-requests?organization_id=ca8d0c7c-1fff-4465-99d7-75a1fc51543e
Headers:
```json
{
  "accept": "application/json",
  "authorization": "Bearer eyJhbGciOiAiSFMyNTYiLCAidHlwIjogIkpXVCJ9.eyJzdWIiOiAiZTY2NzUyNjYtM2UxMy00MDhhLThkYmMtMmZiMzE2NTFjYzlkIiwgImVtYWlsIjogImRpc3BhdGNoZXJAYW1pY29yLmxvY2FsIiwgInJvbGUiOiAiZGlzcGF0Y2hlciIsICJvcmdhbml6YXRpb25faWQiOiAiY2E4ZDBjN2MtMWZmZi00NDY1LTk5ZDctNzVhMWZjNTE1NDNlIiwgImV4cCI6IDE3ODA5ODY1OTMuNDc1OTMwN30.ZrK_RfYYFsKFUgRtWfkhUyGED-IVCIqZOzjz8jDc1-I",
  "content-type": "application/json",
  "referer": "http://127.0.0.1:8011/app/dispatch"
}
```
Response body:
```json
{
  "status": 201,
  "body": {
    "id": "a732f701-126a-4b44-85bd-4eea25a63c28",
    "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
    "ride_id": "9aa70d63-9db8-4cd1-a8c4-eaebe67e8d6a",
    "rider_name": "Browser Final Patient",
    "rider_phone": "+15550999901",
    "pickup_address": "901 Browser Ln",
    "dropoff_address": "902 Browser Ln",
    "scheduled_time": null,
    "ride_type": "healthcare",
    "recurring": false,
    "recurring_pattern": null,
    "notes": null,
    "dispatch_status": "pending",
    "pending_at": "2026-06-09T05:33:10.653147",
    "broadcasted_at": null,
    "accepted_at": null,
    "assigned_at": null,
    "in_progress_at": null,
    "completed_at": null,
    "cancelled_at": null,
    "created_at": "2026-06-09T05:33:10.653149",
    "updated_at": "2026-06-09T05:33:10.653150"
  }
}
```

## create_patient
1. Request payload
```json
{
  "method": "POST",
  "url": "http://127.0.0.1:8011/api/health-isf/customer-requests?organization_id=ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
  "headers": {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": "Bearer <dispatcher_token>"
  },
  "payload": {
    "rider_name": "WF2 Patient 1",
    "rider_phone": "+1555505001",
    "pickup_address": "501 Seed St",
    "dropoff_address": "601 Seed Ave",
    "ride_type": "healthcare",
    "recurring": false
  }
}
```
2. Response payload
```json
{
  "status": 201,
  "body": {
    "id": "d0dc188e-dc7d-4376-897d-00fb15fe3282",
    "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
    "ride_id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
    "rider_name": "WF2 Patient 1",
    "rider_phone": "+1555505001",
    "pickup_address": "501 Seed St",
    "dropoff_address": "601 Seed Ave",
    "scheduled_time": null,
    "ride_type": "healthcare",
    "recurring": false,
    "recurring_pattern": null,
    "notes": null,
    "dispatch_status": "pending",
    "pending_at": "2026-06-09T05:29:42.445552",
    "broadcasted_at": null,
    "accepted_at": null,
    "assigned_at": null,
    "in_progress_at": null,
    "completed_at": null,
    "cancelled_at": null,
    "created_at": "2026-06-09T05:29:42.445554",
    "updated_at": "2026-06-09T05:29:42.445554"
  }
}
```
3. Database record created
```json
{
  "id": "d0dc188e-dc7d-4376-897d-00fb15fe3282",
  "ride_id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
  "rider_name": "WF2 Patient 1",
  "rider_phone": "+1555505001",
  "dispatch_status": "completed",
  "pending_at": "2026-06-09 05:29:42.445552",
  "accepted_at": null,
  "assigned_at": "2026-06-09 05:29:43.066038",
  "in_progress_at": "2026-06-09 05:29:43.286301",
  "completed_at": "2026-06-09 05:29:43.347736",
  "updated_at": "2026-06-09 05:29:43.347765"
}
```
4. Screenshot
- scripts/evidence_screens/create_patient.png
- scripts/evidence_screens/create_patient_live_success.png

## create_driver
1. Request payload
```json
{
  "method": "POST",
  "url": "http://127.0.0.1:8011/api/health-isf/drivers",
  "headers": {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": "Bearer <dispatcher_token>"
  },
  "payload": {
    "name": "WF2 Driver 1",
    "phone": "+1555404001",
    "vehicle_type": "medical_van",
    "vehicle_plate": "WF2DRV01"
  }
}
```
2. Response payload
```json
{
  "status": 201,
  "body": {
    "name": "WF2 Driver 1",
    "phone": "+1555404001",
    "vehicle_type": "medical_van",
    "vehicle_plate": "WF2DRV01",
    "id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993",
    "status": "offline",
    "is_active": true,
    "total_trips": 0,
    "rating": 5.0,
    "created_at": "2026-06-09T05:29:42.344973",
    "updated_at": "2026-06-09T05:29:42.344976"
  }
}
```
3. Database record created
```json
{
  "id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993",
  "name": "WF2 Driver 1",
  "phone": "+1555404001",
  "vehicle_type": "medical_van",
  "vehicle_plate": "WF2DRV01",
  "status": "completed",
  "availability_state": "available",
  "total_trips": 1,
  "updated_at": "2026-06-09 05:29:43.330175"
}
```
4. Screenshot
- scripts/evidence_screens/create_driver.png

## create_vehicle
1. Request payload
```json
{
  "method": "POST",
  "url": "http://127.0.0.1:8011/api/health-isf/vehicles",
  "headers": {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": "Bearer <dispatcher_token>"
  },
  "payload": {
    "vehicle_type": "medical_van",
    "vehicle_plate": "WF2VEH01",
    "capacity": 2
  }
}
```
2. Response payload
```json
{
  "status": 201,
  "body": {
    "id": "43370392-544e-4d12-ab54-6df1bc3b928d",
    "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
    "vehicle_type": "medical_van",
    "vehicle_plate": "WF2VEH01",
    "capacity": 2,
    "is_active": true,
    "created_at": "2026-06-09T05:29:42.391233",
    "updated_at": "2026-06-09T05:29:42.391237"
  }
}
```
3. Database record created
```json
{
  "id": "43370392-544e-4d12-ab54-6df1bc3b928d",
  "vehicle_type": "medical_van",
  "vehicle_plate": "WF2VEH01",
  "capacity": 2,
  "is_active": 1,
  "created_at": "2026-06-09 05:29:42.391233",
  "updated_at": "2026-06-09 05:29:42.391237"
}
```
4. Screenshot
- scripts/evidence_screens/create_vehicle.png

## create_ride
1. Request payload
```json
{
  "method": "POST",
  "url": "http://127.0.0.1:8011/api/health-isf/customer-requests?organization_id=ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
  "headers": {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": "Bearer <dispatcher_token>"
  },
  "payload": {
    "rider_name": "WF2 Patient 1",
    "rider_phone": "+1555505001",
    "pickup_address": "501 Seed St",
    "dropoff_address": "601 Seed Ave",
    "ride_type": "healthcare",
    "recurring": false
  }
}
```
2. Response payload
```json
{
  "status": 201,
  "body": {
    "id": "d0dc188e-dc7d-4376-897d-00fb15fe3282",
    "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
    "ride_id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
    "rider_name": "WF2 Patient 1",
    "rider_phone": "+1555505001",
    "pickup_address": "501 Seed St",
    "dropoff_address": "601 Seed Ave",
    "scheduled_time": null,
    "ride_type": "healthcare",
    "recurring": false,
    "recurring_pattern": null,
    "notes": null,
    "dispatch_status": "pending",
    "pending_at": "2026-06-09T05:29:42.445552",
    "broadcasted_at": null,
    "accepted_at": null,
    "assigned_at": null,
    "in_progress_at": null,
    "completed_at": null,
    "cancelled_at": null,
    "created_at": "2026-06-09T05:29:42.445554",
    "updated_at": "2026-06-09T05:29:42.445554"
  }
}
```
3. Database record created
```json
{
  "id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
  "status": "completed",
  "lifecycle_state": "completed",
  "driver_id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993",
  "requested_at": "2026-06-09 05:29:42.436957",
  "accepted_at": "2026-06-09 05:29:43.052856",
  "picked_up_at": "2026-06-09 05:29:43.272406",
  "transporting_at": "2026-06-09 05:29:43.275111",
  "completed_at": "2026-06-09 05:29:43.336942",
  "updated_at": "2026-06-09 05:29:43.336930"
}
```
4. Screenshot
- scripts/evidence_screens/create_ride.png

## assign_driver
1. Request payload
```json
{
  "method": "POST",
  "url": "http://127.0.0.1:8011/api/health-isf/dispatcher/customer-requests/d0dc188e-dc7d-4376-897d-00fb15fe3282/assign-driver",
  "headers": {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": "Bearer <dispatcher_token>"
  },
  "payload": {
    "driver_id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993"
  }
}
```
2. Response payload
```json
{
  "status": 200,
  "body": {
    "request": {
      "id": "d0dc188e-dc7d-4376-897d-00fb15fe3282",
      "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
      "ride_id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
      "rider_name": "WF2 Patient 1",
      "rider_phone": "+1555505001",
      "pickup_address": "501 Seed St",
      "dropoff_address": "601 Seed Ave",
      "scheduled_time": null,
      "ride_type": "healthcare",
      "recurring": false,
      "recurring_pattern": null,
      "notes": null,
      "dispatch_status": "assigned",
      "pending_at": "2026-06-09T05:29:42.445552",
      "broadcasted_at": "2026-06-09T05:29:43.018264",
      "accepted_at": null,
      "assigned_at": "2026-06-09T05:29:43.066038",
      "in_progress_at": null,
      "completed_at": null,
      "cancelled_at": null,
      "created_at": "2026-06-09T05:29:42.445554",
      "updated_at": "2026-06-09T05:29:43.068381"
    },
    "ride": {
      "passenger_name": "WF2 Patient 1",
      "passenger_phone": "+1555505001",
      "pickup_address": "501 Seed St",
      "dropoff_address": "601 Seed Ave",
      "service_type": "medical_transport",
      "notes": null,
      "id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
      "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
      "provider_id": "6e0c86e1-fce3-4ac6-ba56-b55717e84cb2",
      "driver_id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993",
      "vehicle_id": null,
      "status": "accepted",
      "lifecycle_state": "assigned",
      "estimated_distance_miles": null,
      "estimated_duration_minutes": null,
      "priority_score": null,
      "priority_tag": null,
      "is_emergency": false,
      "appointment_time": null,
      "recurring_trip_pattern": null,
      "recurring_schedule_id": null,
      "recurring_instance_date": null,
      "ai_dispatch_context": null,
      "requested_at": "2026-06-09T05:29:42.436957",
      "assigned_at": "2026-06-09T05:29:43.052850",
      "enroute_at": null,
      "arrived_at": null,
      "picked_up_at": null,
      "transporting_at": null,
      "accepted_at": "2026-06-09T05:29:43.052856",
      "completed_at": null
    },
    "offer": null,
    "message": "Driver assigned from dispatcher customer-request workflow."
  }
}
```
3. Database record created
```json
{
  "id": "5b977bf7-6d0a-4e75-8ecf-989f81ca922a",
  "ride_id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
  "driver_id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993",
  "assignment_state": "dropoff_complete",
  "attempt_index": 1,
  "offered_at": null,
  "assigned_at": "2026-06-09 05:29:43.181318",
  "accepted_at": "2026-06-09 05:29:43.186332",
  "pickup_complete_at": "2026-06-09 05:29:43.275721",
  "dropoff_complete_at": "2026-06-09 05:29:43.343639",
  "updated_at": "2026-06-09 05:29:43.343639"
}
```
4. Screenshot
- scripts/evidence_screens/assign_driver.png

## dispatch_ride
1. Request payload
```json
{
  "method": "POST",
  "url": "http://127.0.0.1:8011/api/health-isf/dispatch/offers/5b977bf7-6d0a-4e75-8ecf-989f81ca922a/accept",
  "headers": {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": "Bearer <dispatcher_token>"
  },
  "payload": null
}
```
2. Response payload
```json
{
  "status": 200,
  "body": {
    "id": "5b977bf7-6d0a-4e75-8ecf-989f81ca922a",
    "offer_id": "5b977bf7-6d0a-4e75-8ecf-989f81ca922a",
    "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
    "ride_id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
    "driver_id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993",
    "assignment_state": "accepted",
    "attempt_index": 1,
    "score": null,
    "score_breakdown": {},
    "timeout_seconds": 90,
    "queued_at": "2026-06-09T05:29:43.052397",
    "search_started_at": "2026-06-09T05:29:43.052397",
    "offered_at": null,
    "offer_expires_at": null,
    "assigned_at": "2026-06-09T05:29:43.181318",
    "accepted_at": "2026-06-09T05:29:43.186332",
    "en_route_pickup_at": null,
    "pickup_complete_at": null,
    "dropoff_complete_at": null,
    "reassignment_pending_at": null,
    "reassignment_started_at": null,
    "reassignment_completed_at": null,
    "reassignment_attempt_count": 0,
    "reassignment_reason": null,
    "reassignment_chain_id": "f1b7109e-01d3-43a6-9d3b-bb4f6cf35db5",
    "rejected_at": null,
    "expired_at": null,
    "closed_reason": null
  }
}
```
3. Database record created
```json
{
  "id": "5b977bf7-6d0a-4e75-8ecf-989f81ca922a",
  "ride_id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
  "driver_id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993",
  "assignment_state": "dropoff_complete",
  "attempt_index": 1,
  "offered_at": null,
  "assigned_at": "2026-06-09 05:29:43.181318",
  "accepted_at": "2026-06-09 05:29:43.186332",
  "pickup_complete_at": "2026-06-09 05:29:43.275721",
  "dropoff_complete_at": "2026-06-09 05:29:43.343639",
  "updated_at": "2026-06-09 05:29:43.343639"
}
```
4. Screenshot
- scripts/evidence_screens/dispatch_ride.png

## start_trip
1. Request payload
```json
{
  "method": "POST",
  "url": "http://127.0.0.1:8011/api/health-isf/drivers/0c15dbd0-06f4-4c5c-8f76-24ee091ff993/pickup-complete",
  "headers": {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": "Bearer <dispatcher_token>"
  },
  "payload": {
    "ride_id": "824036b4-cba9-4cd8-b95d-f649afcc45be"
  },
  "prereq": {
    "arrived_pickup_status": 200,
    "arrived_pickup_body": {
      "passenger_name": "WF2 Patient 1",
      "passenger_phone": "+1555505001",
      "pickup_address": "501 Seed St",
      "dropoff_address": "601 Seed Ave",
      "service_type": "medical_transport",
      "notes": null,
      "id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
      "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
      "provider_id": "6e0c86e1-fce3-4ac6-ba56-b55717e84cb2",
      "driver_id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993",
      "vehicle_id": null,
      "status": "accepted",
      "lifecycle_state": "arrived",
      "estimated_distance_miles": null,
      "estimated_duration_minutes": null,
      "priority_score": null,
      "priority_tag": null,
      "is_emergency": false,
      "appointment_time": null,
      "recurring_trip_pattern": null,
      "recurring_schedule_id": null,
      "recurring_instance_date": null,
      "ai_dispatch_context": null,
      "requested_at": "2026-06-09T05:29:42.436957",
      "assigned_at": "2026-06-09T05:29:43.052850",
      "enroute_at": null,
      "arrived_at": "2026-06-09T05:29:43.228032",
      "picked_up_at": null,
      "transporting_at": null,
      "accepted_at": "2026-06-09T05:29:43.052856",
      "completed_at": null
    }
  }
}
```
2. Response payload
```json
{
  "status": 200,
  "body": {
    "passenger_name": "WF2 Patient 1",
    "passenger_phone": "+1555505001",
    "pickup_address": "501 Seed St",
    "dropoff_address": "601 Seed Ave",
    "service_type": "medical_transport",
    "notes": null,
    "id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
    "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
    "provider_id": "6e0c86e1-fce3-4ac6-ba56-b55717e84cb2",
    "driver_id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993",
    "vehicle_id": null,
    "status": "in_transit",
    "lifecycle_state": "in_progress",
    "estimated_distance_miles": null,
    "estimated_duration_minutes": null,
    "priority_score": null,
    "priority_tag": null,
    "is_emergency": false,
    "appointment_time": null,
    "recurring_trip_pattern": null,
    "recurring_schedule_id": null,
    "recurring_instance_date": null,
    "ai_dispatch_context": null,
    "requested_at": "2026-06-09T05:29:42.436957",
    "assigned_at": "2026-06-09T05:29:43.052850",
    "enroute_at": null,
    "arrived_at": "2026-06-09T05:29:43.228032",
    "picked_up_at": "2026-06-09T05:29:43.272406",
    "transporting_at": "2026-06-09T05:29:43.275111",
    "accepted_at": "2026-06-09T05:29:43.052856",
    "completed_at": null
  }
}
```
3. Database record created
```json
{
  "id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
  "status": "completed",
  "lifecycle_state": "completed",
  "driver_id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993",
  "requested_at": "2026-06-09 05:29:42.436957",
  "accepted_at": "2026-06-09 05:29:43.052856",
  "picked_up_at": "2026-06-09 05:29:43.272406",
  "transporting_at": "2026-06-09 05:29:43.275111",
  "completed_at": "2026-06-09 05:29:43.336942",
  "updated_at": "2026-06-09 05:29:43.336930"
}
```
4. Screenshot
- scripts/evidence_screens/start_trip.png

## complete_trip
1. Request payload
```json
{
  "method": "POST",
  "url": "http://127.0.0.1:8011/api/health-isf/drivers/0c15dbd0-06f4-4c5c-8f76-24ee091ff993/dropoff-complete",
  "headers": {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": "Bearer <dispatcher_token>"
  },
  "payload": {
    "ride_id": "824036b4-cba9-4cd8-b95d-f649afcc45be"
  }
}
```
2. Response payload
```json
{
  "status": 200,
  "body": {
    "passenger_name": "WF2 Patient 1",
    "passenger_phone": "+1555505001",
    "pickup_address": "501 Seed St",
    "dropoff_address": "601 Seed Ave",
    "service_type": "medical_transport",
    "notes": null,
    "id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
    "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc51543e",
    "provider_id": "6e0c86e1-fce3-4ac6-ba56-b55717e84cb2",
    "driver_id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993",
    "vehicle_id": null,
    "status": "completed",
    "lifecycle_state": "completed",
    "estimated_distance_miles": null,
    "estimated_duration_minutes": null,
    "priority_score": null,
    "priority_tag": null,
    "is_emergency": false,
    "appointment_time": null,
    "recurring_trip_pattern": null,
    "recurring_schedule_id": null,
    "recurring_instance_date": null,
    "ai_dispatch_context": null,
    "requested_at": "2026-06-09T05:29:42.436957",
    "assigned_at": "2026-06-09T05:29:43.052850",
    "enroute_at": null,
    "arrived_at": "2026-06-09T05:29:43.228032",
    "picked_up_at": "2026-06-09T05:29:43.272406",
    "transporting_at": "2026-06-09T05:29:43.275111",
    "accepted_at": "2026-06-09T05:29:43.052856",
    "completed_at": "2026-06-09T05:29:43.336942"
  }
}
```
3. Database record created
```json
{
  "id": "824036b4-cba9-4cd8-b95d-f649afcc45be",
  "status": "completed",
  "lifecycle_state": "completed",
  "driver_id": "0c15dbd0-06f4-4c5c-8f76-24ee091ff993",
  "requested_at": "2026-06-09 05:29:42.436957",
  "accepted_at": "2026-06-09 05:29:43.052856",
  "picked_up_at": "2026-06-09 05:29:43.272406",
  "transporting_at": "2026-06-09 05:29:43.275111",
  "completed_at": "2026-06-09 05:29:43.336942",
  "updated_at": "2026-06-09 05:29:43.336930"
}
```
4. Screenshot
- scripts/evidence_screens/complete_trip.png

## Launch Readiness Checks
- [x] Patient can be created
- [x] Driver can be created
- [x] Ride can be created
- [x] Ride appears in dispatch board
- [x] Driver can be assigned
- [x] Driver can be dispatched
- [x] Trip can be completed
- [x] Data persists after refresh