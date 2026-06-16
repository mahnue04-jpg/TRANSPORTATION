# Quick Start Guide - Dispatcher Command Center

## 🎯 What's Built

A complete enterprise dispatcher dashboard with:
- ✅ 10 REST API endpoints with real-time audit logging
- ✅ Real-time WebSocket synchronization
- ✅ Complete React UI with 1000+ lines of styling
- ✅ Tenant isolation & RBAC enforcement
- ✅ Concurrent assignment protection
- ✅ Operational intelligence metrics

---

## 🚀 Quick Start

### 1. Backend Setup (Python)

```bash
cd backend

# Ensure dependencies are installed
pip install fastapi uvicorn sqlalchemy alembic

# Start development server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Frontend Setup (React/TypeScript)

```bash
cd frontend

# Install dependencies (if not already done)
npm install

# The dispatcher components are ready to use:
# - No additional dependencies required (uses React hooks)
# - All styling included
# - TypeScript types provided
```

### 3. Test Backend Dispatcher Endpoints

```bash
# 1. Get auth token (adjust to your auth endpoint)
AUTH_TOKEN="your_jwt_token_here"
ORG_ID="your_organization_id"
RIDE_ID="existing_ride_id"
DRIVER_ID="existing_driver_id"

# 2. Fetch dispatcher board
curl -X GET "http://localhost:8000/api/health-isf/dispatcher/board" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json"

# 3. Get dispatcher queues
curl -X GET "http://localhost:8000/api/health-isf/dispatcher/queues?status=pending&status=accepted" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json"

# 4. Get activity log
curl -X GET "http://localhost:8000/api/health-isf/dispatcher/audit-log" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json"

# 5. Reassign a driver
curl -X PATCH "http://localhost:8000/api/health-isf/dispatcher/rides/$RIDE_ID/reassign-driver" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"driver_id\": \"$DRIVER_ID\"}"

# 6. Escalate an issue
curl -X POST "http://localhost:8000/api/health-isf/dispatcher/rides/$RIDE_ID/escalate" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"issue_type": "safety_concern", "description": "Driver reported issue"}'

# 7. Cancel a ride
curl -X PATCH "http://localhost:8000/api/health-isf/dispatcher/rides/$RIDE_ID/cancel" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Passenger not ready"}'
```

### 4. Test Frontend Components

```tsx
// In your React app (e.g., in a page component):

import { DispatcherCommandCenter } from '@/modules/health_isf';
import { useAuth } from '@/hooks/useAuth'; // Your auth hook

export function DispatcherPage() {
  const { user } = useAuth();
  
  if (!user?.organization_id) {
    return <div>Loading...</div>;
  }

  return (
    <DispatcherCommandCenter
      organizationId={user.organization_id}
      userId={user.id}
    />
  );
}
```

### 5. Test WebSocket Connection

```javascript
// In browser console or Node.js:

const orgId = 'your_org_id';
const userId = 'your_user_id';
const token = 'your_jwt_token';

const ws = new WebSocket(
  `wss://localhost:8000/api/health-isf/ws/live/${orgId}/${userId}?role=dispatcher&token=${encodeURIComponent(token)}`
);

ws.onopen = () => {
  console.log('Connected to dispatcher WebSocket');
  
  // Subscribe to dispatcher board updates
  ws.send(JSON.stringify({
    type: 'subscribe',
    subscription_type: 'dispatcher_board'
  }));
};

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('Received event:', message);
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};

ws.onclose = () => {
  console.log('Disconnected from WebSocket');
};
```

---

## 📂 File Structure

```
backend/app/modules/health_isf/
├── routes.py                 # Dispatcher endpoints (lines 1650+)
├── realtime.py               # WebSocket event broadcasting
├── realtime_service.py       # Services (ActivityLogService, etc.)
└── models.py                 # Database models

frontend/modules/health_isf/
├── DispatcherCommandCenter.tsx    # Main UI component
├── DispatcherCommandCenter.css    # Styles
├── dispatcherTypes.ts             # TypeScript types
├── dispatcherHooks.ts             # React hooks
├── webSocketManager.ts            # WebSocket client
├── index.ts                       # Public API exports
└── components/
    ├── DispatcherRideCard.tsx
    ├── DispatcherFiltersBar.tsx
    ├── RideActionModal.tsx
    ├── AuditLogPanel.tsx
    └── [CSS files for each]
```

---

## 🔧 Configuration

### Backend Environment Variables
```bash
# .env or docker-compose environment
DATABASE_URL=postgresql://user:pass@localhost:5432/amicor
JWT_SECRET=your_secret_key
ENVIRONMENT=development
LOG_LEVEL=INFO
```

### Frontend Configuration
```tsx
// Update API_BASE if needed
const API_BASE = '/api/health-isf';

// WebSocket URL is auto-constructed from window.location
// Change protocol if needed (ws: vs wss:)
```

---

## 🧪 Testing Commands

### Python Backend Syntax Check
```bash
python -m py_compile backend/app/modules/health_isf/routes.py
python -m py_compile backend/app/modules/health_isf/realtime.py
python -m py_compile backend/app/modules/health_isf/realtime_service.py
```

### TypeScript Type Check (if using tsc)
```bash
npx tsc --noEmit frontend/modules/health_isf/*.ts
```

---

## 📋 API Response Examples

### GET /dispatcher/board
```json
{
  "organization_id": "org_123",
  "active_rides": [
    {
      "id": "ride_456",
      "passenger_name": "John Doe",
      "status": "in_transit",
      "driver_name": "Jane Smith",
      "pickup_address": "123 Main St",
      "dropoff_address": "456 Oak Ave",
      "estimated_duration_minutes": 25,
      "is_emergency": false
    }
  ],
  "pending_rides": [...],
  "available_drivers": [...],
  "dispatch_load": 65,
  "operational_alerts": [],
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### PATCH /dispatcher/rides/{id}/reassign-driver (Success)
```json
{
  "id": "ride_456",
  "status": "accepted",
  "driver_id": "driver_789",
  "driver_name": "Bob Wilson",
  "message": "Ride reassigned successfully"
}
```

### GET /dispatcher/audit-log
```json
{
  "data": [
    {
      "id": "log_999",
      "action": "driver_reassigned",
      "description": "Driver reassigned from Jane Smith to Bob Wilson",
      "ride_id": "ride_456",
      "driver_id": "driver_789",
      "actor_user_id": "dispatcher_001",
      "actor_user_name": "Sarah Johnson",
      "created_at": "2024-01-15T10:25:00Z"
    }
  ],
  "total": 1
}
```

---

## 🐛 Troubleshooting

### Backend Issues

**Issue**: Import errors on `RideStatus`, `DriverStatus`
```
Solution: Verify imports are added to routes.py:
from app.modules.health_isf.models import RideStatus, DriverStatus
```

**Issue**: `ActivityLogService.get_activity_feed()` parameter error
```
Solution: Verify realtime_service.py has been updated with ride_id parameter
```

**Issue**: WebSocket connection refused
```
Solution: Ensure FastAPI WebSocket route is enabled in routes.py
Check that WebSocket path matches client expectations
```

### Frontend Issues

**Issue**: Rides not updating in real-time
```
Solution: Verify connection status in top-right corner
Check browser console for WebSocket errors
Ensure auth token is valid and includes dispatcher role
```

**Issue**: API responses return 401 Unauthorized
```
Solution: Verify JWT token is valid
Check token includes required ROLE_DISPATCHER role
Ensure token is passed in Authorization header
```

**Issue**: Modal not closing after action
```
Solution: Check console for errors in onClose callback
Verify action promise resolved successfully
```

---

## 🔐 Security Verification

Checklist before production:

- [ ] All dispatcher endpoints require authentication token
- [ ] All endpoints check for `ROLE_DISPATCHER` or admin roles
- [ ] Organization ID is validated for tenant isolation
- [ ] All database queries use parameterized statements
- [ ] WebSocket connections verify organization membership
- [ ] Activity logs capture actor user ID
- [ ] Sensitive operations (escalate, cancel) are logged
- [ ] No passwords/PII in logs or responses
- [ ] HTTPS/WSS used in production
- [ ] Rate limiting enabled on endpoints

---

## 📊 Metrics & Monitoring

Add monitoring for:
- Dispatcher action response times (target: <100ms)
- WebSocket connection count (monitor spikes)
- Failed concurrent assignments (should be 0)
- Audit log entry volume (trending)
- API error rates by endpoint
- Queue sizes over time

---

## 📞 Support

For issues or questions:
1. Check the DISPATCHER_COMMAND_CENTER_IMPLEMENTATION.md for detailed specs
2. Review error logs in the console
3. Verify all dependencies are installed
4. Check that database tables exist (run migrations if needed)
5. Ensure authentication tokens have required roles

---

## ✅ Verification Checklist

After deployment, verify:

- [ ] Backend endpoints respond to HTTP requests
- [ ] WebSocket connections successfully connect
- [ ] Real-time events broadcast to subscribers
- [ ] Activity logs are recorded for all actions
- [ ] Tenant isolation prevents cross-org access
- [ ] UI components render without errors
- [ ] Filters work correctly
- [ ] Action modals submit successfully
- [ ] Audit log displays activities
- [ ] Mobile responsive layout works

---

**Status**: Ready for testing and deployment! 🚀
