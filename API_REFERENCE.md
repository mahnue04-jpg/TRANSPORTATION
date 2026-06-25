# Amicor Nova — Health ISF API Reference

Base path: `/api/health-isf`  
Auth: `Authorization: Bearer <JWT>` on all endpoints unless noted.

Interactive docs: `/docs` when the server is running.

## Authentication

```http
POST /api/auth/login
Content-Type: application/json

{"email": "dispatcher@amicor.local", "password": "Amicor123!"}
```

## Driver workflow

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/drivers/{id}/live-workspace` | Driver's active ride and assignment state |
| GET | `/drivers/{id}/active-offer` | Pending dispatch offer |
| POST | `/drivers/{id}/route-progress` | Unified trip progression |
| POST | `/drivers/{id}/accept-ride` | Accept assigned ride |
| POST | `/drivers/{id}/arrived-pickup` | Mark arrived at pickup |
| POST | `/drivers/{id}/pickup-complete` | Rider onboard |
| POST | `/drivers/{id}/dropoff-complete` | Complete dropoff |
| POST | `/drivers/{id}/no-show` | Report rider no-show |
| POST | `/drivers/{id}/contact-rider` | SMS/call rider notification |

### Route progress states

```json
POST /api/health-isf/drivers/{driver_id}/route-progress
{"ride_id": "<uuid>", "target_state": "en_route_pickup"}
```

Valid `target_state` values: `en_route_pickup`, `arrived_pickup`, `rider_loaded`, `trip_in_progress`, `completed`

### Contact rider

```json
POST /api/health-isf/drivers/{driver_id}/contact-rider
{"ride_id": "<uuid>", "channel": "sms", "message": "Optional custom text"}
```

Channels: `sms` (default), `call` (returns dial target)

## Rider / patient booking

```json
POST /api/health-isf/customer-requests
{
  "rider_name": "Jane Doe",
  "rider_phone": "646-555-0100",
  "pickup_address": "100 Main St, NY",
  "dropoff_address": "200 Clinic Ave, NY",
  "ride_type": "healthcare",
  "scheduled_time": "2026-06-15T10:00:00Z",
  "notes": "Wheelchair assist",
  "recurring": false
}
```

Auto-dispatch (dispatcher):

```http
POST /api/health-isf/dispatcher/customer-requests/{request_id}/auto-dispatch
```

## Dispatch

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/rides` | List rides |
| POST | `/dispatch/offers/{offer_id}/accept` | Driver accepts offer |
| POST | `/dispatch/offers/{offer_id}/reject` | Driver rejects offer |
| POST | `/dispatcher/customer-requests/{id}/assign-driver` | Manual assignment |

## Payments & billing

```json
POST /api/health-isf/payments/intents
{
  "ride_id": "<uuid>",
  "currency": "USD",
  "capture_immediately": false
}
```

Fare is calculated from ride distance when `amount_usd` is omitted.

Revenue dashboard:

```http
GET /api/health-isf/operations/revenue-workflow?window_hours=24
```

## Operations & seed data

```http
POST /api/health-isf/ops/seed-production-demo
POST /api/health-isf/ops/seed-production-demo?force=true
POST /api/health-isf/ops/seed-phase43
```

## WebSocket (live updates)

```
WS /api/health-isf/ws/live/{organization_id}/{user_id}
```

## Health

```http
GET /api/health
```

Returns platform readiness, database connectivity, and version metadata.
