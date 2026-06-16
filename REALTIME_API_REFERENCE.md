# Real-Time Dispatch Operations - API Reference

## WebSocket Endpoint

### Connect to Live Updates
```
WS /api/health-isf/ws/live/{organization_id}/{user_id}?role={role}
```

**Parameters:**
- `organization_id` (path): Organization identifier (UUID)
- `user_id` (path): User identifier (UUID)
- `role` (query): User role - `dispatcher`, `driver`, or `admin`

**Example:**
```
ws://localhost:8000/api/health-isf/ws/live/org_a1b2c3d4/user_e5f6g7h8?role=dispatcher
```

**Response on Connect:**
```json
{
  "type": "connected",
  "connection_id": "conn_uuid",
  "timestamp": "2026-05-17T20:30:00Z"
}
```

### Subscribe to Events

**Send:**
```json
{
  "type": "subscribe",
  "subscription_type": "dispatcher_board"
}
```

**Response:**
```json
{
  "type": "subscribed",
  "subscription_type": "dispatcher_board",
  "timestamp": "2026-05-17T20:30:01Z"
}
```

**Subscription Types:**
- `dispatcher_board` - Dispatcher visibility (rides, assignments, driver status)
- `driver_dashboard` - Driver personal (my rides, my assignments)
- `ride_updates` - Detailed ride lifecycle
- `driver_availability` - Driver fleet status

### Unsubscribe from Events

**Send:**
```json
{
  "type": "unsubscribe",
  "subscription_type": "dispatcher_board"
}
```

**Response:**
```json
{
  "type": "unsubscribed",
  "subscription_type": "dispatcher_board",
  "timestamp": "2026-05-17T20:30:02Z"
}
```

### Receive Events

**Event Message:**
```json
{
  "type": "event",
  "event_type": "ride_assigned",
  "payload": {
    "ride_id": "ride_123",
    "driver_id": "driver_456",
    "driver_name": "John Smith",
    "from_status": "pending",
    "to_status": "assigned"
  },
  "timestamp": "2026-05-17T20:30:05Z"
}
```

### Heartbeat (Ping/Pong)

**Send Ping:**
```json
{
  "type": "ping"
}
```

**Receive Pong:**
```json
{
  "type": "pong",
  "timestamp": "2026-05-17T20:30:10Z"
}
```

**Note:** Send ping every 30 seconds to keep connection alive. Connections timeout after 300 seconds of inactivity.

### Connection Errors

**Malformed Message:**
```json
{
  "type": "error",
  "code": "INVALID_MESSAGE",
  "detail": "Message must contain 'type' field",
  "timestamp": "2026-05-17T20:30:15Z"
}
```

**Invalid Subscription:**
```json
{
  "type": "error",
  "code": "INVALID_SUBSCRIPTION",
  "detail": "Unknown subscription_type: invalid_type",
  "timestamp": "2026-05-17T20:30:15Z"
}
```

---

## REST Endpoints

### Activity Feed

#### Get Dispatcher Activity Feed
```
GET /api/health-isf/activity-feed
```

**Query Parameters:**
- `skip` (optional, default=0): Number of records to skip
- `limit` (optional, default=50, max=500): Number of records to return

**Example:**
```bash
GET /api/health-isf/activity-feed?skip=0&limit=10
```

**Response (200 OK):**
```json
{
  "activities": [
    {
      "id": "activity_123",
      "organization_id": "org_456",
      "action": "ride_assigned",
      "ride_id": "ride_789",
      "driver_id": "driver_012",
      "description": "Ride assigned to John Smith",
      "details": {
        "driver_name": "John Smith",
        "passenger_name": "Mary Johnson"
      },
      "actor_user_id": "dispatcher_345",
      "created_at": "2026-05-17T20:30:00+00:00"
    },
    {
      "id": "activity_124",
      "organization_id": "org_456",
      "action": "ride_completed",
      "ride_id": "ride_788",
      "driver_id": "driver_011",
      "description": "Ride completed",
      "details": {
        "distance_miles": 5.2,
        "duration_minutes": 15,
        "fare_amount": 18.50
      },
      "actor_user_id": "driver_011",
      "created_at": "2026-05-17T20:29:45+00:00"
    }
  ],
  "total": 1250,
  "skip": 0,
  "limit": 10
}
```

**Error (401 Unauthorized):**
```json
{
  "detail": "Not authenticated"
}
```

**Error (400 Bad Request):**
```json
{
  "detail": "limit must be <= 500"
}
```

---

## Enhanced Existing Endpoints

### Assign Driver to Ride (Enhanced)

#### Request
```
PATCH /api/health-isf/rides/{ride_id}/assign-driver
Content-Type: application/json

{
  "driver_id": "driver_123"
}
```

**Parameters:**
- `ride_id` (path): Ride identifier (UUID)
- `driver_id` (body): Driver identifier (UUID)

#### Response (200 OK)
```json
{
  "id": "ride_789",
  "status": "assigned",
  "driver_id": "driver_123",
  "driver_name": "John Smith",
  "passenger_name": "Mary Johnson",
  "pickup_address": "123 Main St",
  "dropoff_address": "456 Oak Ave",
  "assigned_at": "2026-05-17T20:30:00+00:00"
}
```

**Events Emitted:**
- `RIDE_ASSIGNED` - to dispatcher_board subscribers
- `RIDE_STATUS_CHANGED` - to ride_updates subscribers

**Activity Logged:**
- Action: `RIDE_ASSIGNED`
- Description: "Ride assigned to {driver_name}"

**Error (404 Not Found):**
```json
{
  "detail": "Ride not found"
}
```

**Error (409 Conflict - Concurrent Lock):**
```json
{
  "detail": "Ride is currently being assigned by another dispatcher",
  "error_code": "CONCURRENT_ASSIGNMENT",
  "ride_id": "ride_789"
}
```

**Error (400 Bad Request - Invalid Status):**
```json
{
  "detail": "Cannot assign driver to ride in status 'completed'"
}
```

---

### Update Ride Status (Enhanced)

#### Request
```
PATCH /api/health-isf/rides/{ride_id}/status
Content-Type: application/json

{
  "status": "completed"
}
```

**Parameters:**
- `ride_id` (path): Ride identifier (UUID)
- `status` (body): New status - `pending`, `accepted`, `in_transit`, `completed`, or `cancelled`

#### Response (200 OK)
```json
{
  "id": "ride_789",
  "status": "completed",
  "driver_id": "driver_123",
  "driver_name": "John Smith",
  "passenger_name": "Mary Johnson",
  "completed_at": "2026-05-17T20:45:00+00:00"
}
```

**Events Emitted:**
- `RIDE_STATUS_CHANGED` - to dispatcher_board, ride_updates subscribers
- `RIDE_COMPLETED` - to driver_dashboard subscribers (if status=completed)

**Activity Logged:**
- Action: `RIDE_COMPLETED` (if status=completed) or `RIDE_CANCELLED` (if status=cancelled)
- Description: Appropriate message based on new status

---

### Set Driver Status (Enhanced)

#### Request
```
POST /api/health-isf/drivers/{driver_id}/set-status
Content-Type: application/json

{
  "status": "available"
}
```

**Parameters:**
- `driver_id` (path): Driver identifier (UUID)
- `status` (body): New status - `available`, `assigned`, `offline`, or `on_break`

#### Response (200 OK)
```json
{
  "id": "driver_123",
  "name": "John Smith",
  "status": "available",
  "phone": "555-0123",
  "updated_at": "2026-05-17T20:30:00+00:00"
}
```

**Events Emitted:**
- `DRIVER_STATUS_CHANGED` - to dispatcher_board, driver_availability subscribers

**Activity Logged:**
- Action: `DRIVER_STATUS_CHANGED`
- Description: "Driver changed status to {status}"

---

## Event Payload Types

### RIDE_STATUS_CHANGED
```json
{
  "event_type": "ride_status_changed",
  "payload": {
    "ride_id": "ride_123",
    "from_status": "pending",
    "to_status": "assigned",
    "driver_id": "driver_456",
    "driver_name": "John Smith"
  }
}
```

### DRIVER_STATUS_CHANGED
```json
{
  "event_type": "driver_status_changed",
  "payload": {
    "driver_id": "driver_123",
    "from_status": "available",
    "to_status": "assigned",
    "driver_name": "John Smith"
  }
}
```

### RIDE_ASSIGNED
```json
{
  "event_type": "ride_assigned",
  "payload": {
    "ride_id": "ride_789",
    "driver_id": "driver_123",
    "driver_name": "John Smith",
    "passenger_name": "Mary Johnson",
    "pickup_address": "123 Main St"
  }
}
```

### RIDE_COMPLETED
```json
{
  "event_type": "ride_completed",
  "payload": {
    "ride_id": "ride_789",
    "driver_id": "driver_123",
    "distance_miles": 5.2,
    "duration_minutes": 15,
    "fare_amount": 18.50
  }
}
```

### ASSIGNMENT_REJECTED
```json
{
  "event_type": "assignment_rejected",
  "payload": {
    "ride_id": "ride_789",
    "driver_id": "driver_123",
    "driver_name": "John Smith",
    "reason": "Too far away"
  }
}
```

### RIDE_CANCELLED
```json
{
  "event_type": "ride_cancelled",
  "payload": {
    "ride_id": "ride_789",
    "reason": "Passenger cancelled",
    "cancelled_by": "passenger"
  }
}
```

---

## Status Codes

### Success
- `200 OK` - Request successful, response body contains result
- `201 Created` - Resource created successfully
- `204 No Content` - Request successful, no response body

### Client Errors
- `400 Bad Request` - Invalid request format or parameters
- `401 Unauthorized` - Authentication required
- `403 Forbidden` - User lacks required permissions
- `404 Not Found` - Resource not found
- `409 Conflict` - Concurrent assignment lock active, retry after delay
- `422 Unprocessable Entity` - Validation error in request body

### Server Errors
- `500 Internal Server Error` - Server error (rare in normal operation)
- `503 Service Unavailable` - Database or real-time service temporarily unavailable

---

## Rate Limiting

- WebSocket connections: 1,000 per organization (soft limit)
- Activity feed requests: 100 per minute per user
- Event broadcasts: No limit (internal)

---

## Authentication

All endpoints require `Authorization: Bearer <token>` header.

**Example:**
```bash
curl -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  https://api.amicor.com/api/health-isf/activity-feed
```

---

## CORS

WebSocket connections from browser require CORS configuration:
```
Access-Control-Allow-Origin: https://dispatcher.amicor.com
Access-Control-Allow-Methods: GET, POST, PATCH, DELETE
Access-Control-Allow-Headers: Authorization, Content-Type
```

---

## Changelog

### Version 2.0 (May 17, 2026)
- Added WebSocket endpoint for real-time updates
- Added activity feed with pagination
- Enhanced assign-driver endpoint with concurrent protection
- Enhanced status update endpoints with event emission
- Added real-time event logging
- Added concurrent assignment lock mechanism

### Version 1.0 (Earlier)
- Basic ride management
- Basic driver management
- Activity logging (non-real-time)

---

**API Reference Version**: 2.0  
**Last Updated**: May 17, 2026  
**Status**: Production Ready ✓
