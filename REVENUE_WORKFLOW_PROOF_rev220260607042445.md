# Revenue Workflow Proof (Run rev220260607042445)

## Definition of Done
A dispatcher can create a ride and collect revenue from it.

Status: PROVEN in this run.

## Run Metadata
- run_id: rev220260607042445
- organization_id: ca8d0c7c-1fff-4465-99d7-75a1fc51543e
- driver_id: 23379af1-2460-4926-88ab-914c7f9de653
- patient_request_id: 2a9a7adc-01d5-4059-81ea-f30e45d07fe4
- ride_id: 8e7e4189-3737-4895-aa3e-5110c9d80700
- invoice_reference: INV-rev220260607042445
- payment_id: eab78dff-5952-48bb-94a3-f5ed77a0d56f

## 12-Step Operational Proof Matrix
| Step | API Proof | DB Proof | Result |
|---|---|---|---|
| 1 Create driver | POST /api/health-isf/drivers -> 201 | health_isf_drivers row exists for driver_id | PASS |
| 2 Driver visible to dispatcher | POST /drivers/{id}/set-status -> 200; GET /drivers/available includes driver_id | driver status=available | PASS |
| 3 Create patient request | POST /api/health-isf/customer-requests -> 201 | health_isf_customer_ride_requests row exists | PASS |
| 4 Patient visible to dispatcher | GET /customer-requests -> 200 and contains patient_request_id | request dispatch_status=pending | PASS |
| 5 Create ride | POST /api/health-isf/rides -> 201 | health_isf_rides row exists (queued/pending) | PASS |
| 6 Ride visible in dispatcher board | GET /api/health-isf/rides -> 200 and contains ride_id | ride row present with null driver before assignment | PASS |
| 7 Assign driver | PATCH /rides/{ride_id}/assign-driver -> 200 | ride.driver_id set, assigned_at populated | PASS |
| 8 Dispatch ride | POST /operations/lifecycle-action?action=accept_assignment -> 200 | lifecycle_state=driver_en_route, enroute_at set | PASS |
| 9 Complete ride | driver_arrived + rider_picked_up + ride_in_progress + ride_completed all -> 200 | ride status=completed, completed_at set | PASS |
| 10 Generate trip record | Derived from completed ride workflow | health_isf_trips row exists for ride_id | PASS |
| 11 Generate invoice / payment intent | POST /payments/intents -> 200 | health_isf_payment_transactions row exists (requires_capture) | PASS |
| 12 Capture + settle payment | POST /payments/capture -> 200; POST /payments/settle -> 200; GET /payments/rides/{ride_id} -> count 1 | settlement ledger has driver+provider processed rows | PASS |

## Revenue Evidence
- Captured amount (payment transaction amount_usd): 159.0
- Ledger split:
  - driver: 95.4 (processed)
  - provider: 63.6 (processed)

## UI Evidence
- Dispatch UI snapshot contained this completed ride row text:
  - ride_id: 8e7e4189-3737-4895-aa3e-5110c9d80700
  - passenger: Revenue Passenger rev220260607042445
  - status: completed
  - assigned driver_id: 23379af1-2460-4926-88ab-914c7f9de653
- A sidebar screenshot was captured during the same authenticated dispatcher session.

## Source Artifact
Full raw evidence for this run is in:
- REVENUE_WORKFLOW_rev220260607042445.json
