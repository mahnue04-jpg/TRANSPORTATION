# Health ISF Module - MVP Skeleton

## Overview

Health ISF (Integrated Services for Health) is the **first MVP module** for the Amicor Health platform. It provides a modular, safe foundation for managing healthcare transportation and logistics without breaking the existing Amicor app.

**Status:** MVP Skeleton - Minimal, functional, ready for iteration.

---

## What This Module Does (MVP Scope)

The Health ISF module manages:

### 1. **Ride Requests**
   - Patient/user requests for medical transport, dialysis, appointments, etc.
   - Lifecycle: Pending → Accepted → In Transit → Completed/Cancelled
   - Includes pickup/dropoff addresses, passenger info, service type

### 2. **Drivers**
   - Transportation provider profiles
   - Status tracking: Available, Busy, Offline
   - Basic metrics: total trips, rating
   - Vehicle info: type and license plate

### 3. **Providers** (Healthcare Facilities)
   - Clinics, hospitals, dialysis centers, etc.
   - Contact info and service type classification
   - Associated with ride requests

### 4. **Dispatch Tracking**
   - Trip execution records (MVP: basic status tracking only)
   - Distance and duration estimation
   - Start/end timestamps

### 5. **Trip Status**
   - Lifecycle: Created → Dispatched → In Progress → Completed/Failed
   - No real-time location tracking in MVP

### 6. **Payout Tracking (Placeholder)**
   - Records payment amounts per driver per trip
   - Status: pending, processed, failed
   - **No real payment processing in MVP** (placeholder only)

### 7. **Admin Dashboard**
   - KPI metrics: active rides, available drivers, providers
   - Aggregated payout data
   - Trip completion stats

---

## MVP API Routes

| Method | Endpoint                      | Description                              |
|--------|-------------------------------|------------------------------------------|
| GET    | `/api/health-isf/status`      | Module health check                      |
| GET    | `/api/health-isf/rides`       | List all rides (paginated)               |
| POST   | `/api/health-isf/rides`       | Create a new ride request                |
| GET    | `/api/health-isf/rides/{id}`  | Get specific ride by ID                  |
| GET    | `/api/health-isf/drivers`     | List all active drivers                  |
| GET    | `/api/health-isf/drivers/available` | List available drivers             |
| GET    | `/api/health-isf/drivers/{id}`| Get specific driver by ID                |
| GET    | `/api/health-isf/providers`   | List all providers                       |
| GET    | `/api/health-isf/providers/{id}` | Get specific provider by ID          |
| GET    | `/api/health-isf/dashboard`   | Dashboard metrics and KPIs               |

---

## Sample Data

The module is initialized with MVP sample data:

### Providers (3)
- Lincoln Medical Center (Brooklyn clinic)
- Queens Dialysis Facility (Queens facility)
- Manhattan Health Hub (Manhattan clinic)

### Drivers (3)
- James Smith (Sedan, Available, 4.8★)
- Maria Garcia (Van, Busy, 4.9★)
- David Chen (Sedan, Offline, 4.7★)

### Rides (3 samples)
- Patricia Johnson: COMPLETED dialysis transport (8.5 mi, ~25 min)
- Robert Williams: ACCEPTED medical appointment (3.2 mi, ~12 min)
- Jennifer Brown: PENDING medical transport (10.1 mi, ~30 min)

---

## What Is **Intentionally Excluded** (NOT in MVP)

❌ **Advanced AI Dispatch**  
- MVP uses simple data retrieval, no ML/AI route optimization
- Future: implement smart driver-to-ride matching

❌ **Real Payment Processing**  
- Payouts are tracked as records only
- Future: integrate Stripe/PayPal for actual disbursement

❌ **Real External APIs**  
- No actual Google Maps distance/duration calculations
- No SMS/Twilio notifications
- No third-party integrations yet

❌ **Real-time Location Tracking**  
- No GPS tracking or live driver location
- Future: add real-time driver updates

❌ **Advanced Authentication**  
- Uses existing Amicor auth, no RBAC for drivers/admins yet
- Future: role-based access (driver, admin, dispatcher)

❌ **Compliance/Regulatory**  
- No background check verification
- No insurance validation
- No accessibility certification checks
- Future: compliance module

❌ **Multi-language Support**  
- MVP is English-only
- Future: i18n support

---

## Database Schema

All Health ISF tables are prefixed with `health_isf_`:

- `health_isf_providers` - Healthcare facilities
- `health_isf_drivers` - Transportation providers
- `health_isf_rides` - Ride requests
- `health_isf_trips` - Trip execution tracking
- `health_isf_payouts` - Payment/payout records

Tables use SQLAlchemy ORM with SQLite (dev) or PostgreSQL (prod).

---

## Isolation & Safety

✅ **No breaking changes to existing app:**
- New routes are isolated under `/api/health-isf/`
- New database tables have `health_isf_` prefix
- Separate module directory: `app/modules/health_isf/`
- Existing chat, auth, and ecosystem routes untouched

✅ **Modular design:**
- Can be enabled/disabled via router registration
- Independent service layer
- Clear separation of models, schemas, routes

---

## Future Upgrade Path

### Phase 2: Enhanced Dispatch
- Smart driver-to-ride matching algorithm
- Distance/duration estimation from Maps API
- Predictive ETA

### Phase 3: Real-time & Communications
- Driver GPS tracking
- SMS notifications (Twilio)
- Live ride updates to passengers

### Phase 4: Payments & Compliance
- Stripe/PayPal integration for payouts
- Background check integration
- Insurance validation
- Accessibility compliance checks

### Phase 5: Advanced Features
- Ride pricing algorithm
- Surge pricing
- Multi-stop rides
- Advance scheduling
- Rating & review system
- Analytics & reporting

---

## Running the MVP

### 1. Initialize Database Tables
```bash
# Tables are auto-created on app startup via SQLAlchemy
python -m backend.app.main
```

### 2. Access Sample Data
```bash
curl http://localhost:8000/api/health-isf/status
curl http://localhost:8000/api/health-isf/rides
curl http://localhost:8000/api/health-isf/drivers
curl http://localhost:8000/api/health-isf/dashboard
```

### 3. Create a New Ride
```bash
curl -X POST http://localhost:8000/api/health-isf/rides \
  -H "Content-Type: application/json" \
  -d '{
    "passenger_name": "John Doe",
    "passenger_phone": "555-0123",
    "pickup_address": "123 Main St, NYC",
    "dropoff_address": "456 Health Ave, NYC",
    "service_type": "medical_appointment",
    "provider_id": null,
    "notes": "Wheelchair accessible required"
  }'
```

---

## Module Structure

```
app/modules/health_isf/
├── __init__.py          # Module entry point
├── models.py            # SQLAlchemy ORM models
├── schemas.py           # Pydantic request/response schemas
├── routes.py            # FastAPI route handlers
├── service.py           # Business logic & sample data
└── README.md            # This file
```

---

## Configuration

MVP uses environment defaults (no special config needed):
- Database: SQLite `chat.db` (or PostgreSQL if `DATABASE_URL` set)
- Logging: Standard Python logging

---

## Testing the MVP

See [LIVE_RUNTIME_VALIDATION.md](../../LIVE_RUNTIME_VALIDATION.md) for full test scenarios.

Quick smoke test:
```bash
# 1. Server health
GET /api/health-isf/status → 200 OK

# 2. List data
GET /api/health-isf/rides → 3 sample rides
GET /api/health-isf/drivers → 3 sample drivers
GET /api/health-isf/providers → 3 sample providers

# 3. Create new ride
POST /api/health-isf/rides → 201 Created

# 4. Dashboard
GET /api/health-isf/dashboard → metrics

# 5. Existing app still works
GET /app → static files served
GET /api/auth/status → existing auth endpoint
```

---

## Support & Questions

- **Module Owner:** Amicor Platform Team
- **Status:** MVP - Ready for feedback
- **Next Milestone:** Phase 2 dispatch optimization
- **Estimated Scope Growth:** 3-4 additional modules before Phase 2

---

## Changelog

### v0.1.0 (MVP Release)
- ✅ Basic CRUD for rides, drivers, providers
- ✅ Trip tracking scaffold
- ✅ Payout placeholder
- ✅ Dashboard metrics
- ✅ Sample data initialization
- ✅ API documentation

---

**This is a safe, minimal foundation. Ready to build Phase 2 on top.**
