# Trip Type Schema Design
## Phase 1C Task 5: Trip Type Classification

### Objective
Introduce a structured `trip_type` field to the Create Ride form that allows dispatchers to classify rides by their transportation pattern, enabling better routing decisions, ETA predictions, and operational intelligence.

---

## 1. Proposed Trip Type Enum

```typescript
enum TripType {
  ONE_WAY = "one_way",              // Single pickup → dropoff
  ROUND_TRIP = "round_trip",        // Pickup → dropoff → return to origin
  RECURRING = "recurring",          // Multi-instance recurring pattern (weekly dialysis)
  DISCHARGE = "discharge",          // Hospital discharge (one-way with post-transport notes)
}
```

### Category Rationale

| Trip Type | Use Case | ETA Calculation | Notes |
|-----------|----------|-----------------|-------|
| **ONE_WAY** | Standard transport between two locations | Direct A→B | Most common (85% of rides) |
| **ROUND_TRIP** | Appointment + return (e.g., dialysis patient drops off at clinic, picked up 4 hours later) | A→B + B→A timed separately | Requires return_time_estimate or patient callback |
| **RECURRING** | Weekly/daily standing orders (e.g., Tuesday & Thursday dialysis) | Based on historical pattern + day-of-week adjustments | Linked to recurring_schedule_id |
| **DISCHARGE** | Hospital discharge transport with discharge notes/restrictions | A→B + post-discharge medical notes | Highest priority, medical clearance required |

---

## 2. Frontend UX Flow

### Form Element: Trip Type Selector

```html
<label class="health-field-group">
  <span class="health-field-label">Trip Type <span class="health-required">*</span></span>
  <div class="health-trip-type-selector">
    <label class="health-trip-type-option">
      <input type="radio" name="trip_type" value="one_way" required />
      <span class="health-trip-type-label">One-Way</span>
      <small class="health-trip-type-desc">Single pickup to dropoff</small>
    </label>
    <label class="health-trip-type-option">
      <input type="radio" name="trip_type" value="round_trip" />
      <span class="health-trip-type-label">Round Trip</span>
      <small class="health-trip-type-desc">Pickup → dropoff → return to origin</small>
    </label>
    <label class="health-trip-type-option">
      <input type="radio" name="trip_type" value="recurring" />
      <span class="health-trip-type-label">Recurring</span>
      <small class="health-trip-type-desc">Repeating pattern (linked to recurring schedule)</small>
    </label>
    <label class="health-trip-type-option">
      <input type="radio" name="trip_type" value="discharge" />
      <span class="health-trip-type-label">Hospital Discharge</span>
      <small class="health-trip-type-desc">Post-discharge medical transport</small>
    </label>
  </div>
  <small class="health-field-error" data-field-error="trip_type"></small>
</label>
```

### Conditional Form Fields (By Trip Type)

#### ONE_WAY (Default)
- **Pickup Address** (required)
- **Dropoff Address** (required)
- **Appointment Time** (optional) — used for scheduling
- **Priority Tag** (optional) — normal, high, urgent, emergency

#### ROUND_TRIP
- All ONE_WAY fields
- **+ Return Time Estimate** (required) — datetime when patient is ready for pickup
  ```html
  <label class="health-field-group" id="health-return-time-group" hidden>
    <span class="health-field-label">Return Pickup Time <span class="health-required">*</span></span>
    <input name="return_pickup_time" type="datetime-local" required />
    <small class="health-field-error" data-field-error="return_pickup_time"></small>
  </label>
  ```
- **+ Return Address** (optional, defaults to pickup address)
  ```html
  <label class="health-field-group" id="health-return-address-group" hidden>
    <span class="health-field-label">Return Dropoff (defaults to pickup location)</span>
    <input name="return_address" placeholder="Leave blank to return to pickup location" />
    <small class="health-field-error" data-field-error="return_address"></small>
  </label>
  ```

#### RECURRING
- All ONE_WAY fields
- **+ Recurring Frequency** (required) — daily, weekly, monthly, custom
- **+ Recurrence Days** (conditional) — checkboxes for Mon–Sun (for weekly/monthly)
- **+ Link to Recurring Schedule** (optional) — dropdown of existing recurring schedules, or "Create new"

#### DISCHARGE
- All ONE_WAY fields
- **+ Discharge Medical Notes** (optional)
  ```html
  <label class="health-field-group" id="health-discharge-notes-group" hidden>
    <span class="health-field-label">Post-Discharge Instructions</span>
    <textarea name="discharge_medical_notes" 
              placeholder="Mobility restrictions, oxygen, dietary, follow-up appointments, etc."></textarea>
  </label>
  ```
- **+ Required Accommodations** (checkboxes)
  ```html
  <div id="health-discharge-accommodations-group" hidden style="margin-top:0.5em;">
    <label style="display:flex; align-items:center; font-weight:normal;">
      <input type="checkbox" name="discharge_accommodations" value="wheelchair" /> Wheelchair
    </label>
    <label style="display:flex; align-items:center; font-weight:normal;">
      <input type="checkbox" name="discharge_accommodations" value="oxygen" /> Oxygen Equipment
    </label>
    <label style="display:flex; align-items:center; font-weight:normal;">
      <input type="checkbox" name="discharge_accommodations" value="gurney" /> Gurney/Stretcher
    </label>
    <label style="display:flex; align-items:center; font-weight:normal;">
      <input type="checkbox" name="discharge_accommodations" value="medical_attendant" /> Medical Attendant
    </label>
  </div>
  ```

---

## 3. Pydantic Schema Extension

### Backend Request Model Update

```python
from enum import Enum

class TripType(str, Enum):
    ONE_WAY = "one_way"
    ROUND_TRIP = "round_trip"
    RECURRING = "recurring"
    DISCHARGE = "discharge"

class RideCreate(RideBase):
    # Existing fields...
    trip_type: TripType = TripType.ONE_WAY
    
    # ROUND_TRIP fields
    return_pickup_time: Optional[datetime] = None
    return_address: Optional[str] = None
    
    # RECURRING fields (replaces recurring_trip_pattern)
    recurring_frequency: Optional[str] = None  # daily, weekly, monthly, custom
    recurring_days: Optional[List[str]] = None  # [mon, tue, ...]
    recurring_schedule_id: Optional[str] = None
    
    # DISCHARGE fields
    discharge_medical_notes: Optional[str] = None
    discharge_accommodations: Optional[List[str]] = None  # [wheelchair, oxygen, ...]
    
    @field_validator("trip_type")
    @classmethod
    def validate_trip_type(cls, value: TripType) -> TripType:
        return value
    
    @field_validator("return_pickup_time")
    @classmethod
    def validate_return_pickup_time(cls, value: Optional[datetime], info: ValidationInfo) -> Optional[datetime]:
        trip_type = info.data.get("trip_type")
        if trip_type == TripType.ROUND_TRIP and not value:
            raise ValueError("return_pickup_time is required for round trip rides")
        return value
    
    @field_validator("recurring_frequency")
    @classmethod
    def validate_recurring_frequency(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        trip_type = info.data.get("trip_type")
        if trip_type == TripType.RECURRING:
            if not value or value not in {"daily", "weekly", "monthly", "custom"}:
                raise ValueError("recurring_frequency must be one of: daily, weekly, monthly, custom")
        return value
```

### Backend Response Model Update

```python
class RideResponse(RideBase):
    # Existing fields...
    trip_type: TripType
    return_pickup_time: Optional[datetime] = None
    return_address: Optional[str] = None
    recurring_frequency: Optional[str] = None
    recurring_days: Optional[List[str]] = None
    recurring_schedule_id: Optional[str] = None
    discharge_medical_notes: Optional[str] = None
    discharge_accommodations: Optional[List[str]] = None
```

---

## 4. JavaScript Form Handling

### Build Trip Type Payload

```javascript
function buildTripTypePayload(formData) {
  const tripType = sanitizeInput(formData.get("trip_type")) || "one_way";
  const payload = { trip_type: tripType };
  
  if (tripType === "round_trip") {
    const returnTime = sanitizeInput(formData.get("return_pickup_time"));
    payload.return_pickup_time = returnTime ? new Date(returnTime).toISOString() : null;
    const returnAddr = sanitizeInput(formData.get("return_address"));
    payload.return_address = returnAddr || null;
  }
  
  if (tripType === "recurring") {
    const freq = sanitizeInput(formData.get("recurring_frequency"));
    payload.recurring_frequency = freq;
    const days = Array.from(els.form.querySelectorAll('input[name="recurring_days"]:checked'))
      .map(el => el.value);
    payload.recurring_days = days.length > 0 ? days : null;
  }
  
  if (tripType === "discharge") {
    const notes = sanitizeInput(formData.get("discharge_medical_notes"));
    payload.discharge_medical_notes = notes || null;
    const accommodations = Array.from(els.form.querySelectorAll('input[name="discharge_accommodations"]:checked'))
      .map(el => el.value);
    payload.discharge_accommodations = accommodations.length > 0 ? accommodations : null;
  }
  
  return payload;
}
```

### Show/Hide Conditional Fields

```javascript
function attachTripTypeListeners() {
  const tripTypeRadios = document.querySelectorAll('input[name="trip_type"]');
  const returnTimeGroup = document.querySelector('#health-return-time-group');
  const returnAddressGroup = document.querySelector('#health-return-address-group');
  const recurringFreqGroup = document.querySelector('#health-recurring-frequency-group');
  const recurringDaysGroup = document.querySelector('#health-recurring-days-group');
  const dischargeNotesGroup = document.querySelector('#health-discharge-notes-group');
  const dischargeAccommodationsGroup = document.querySelector('#health-discharge-accommodations-group');
  
  function updateTripTypeUI() {
    const selected = document.querySelector('input[name="trip_type"]:checked')?.value || "one_way";
    
    returnTimeGroup.hidden = selected !== "round_trip";
    returnAddressGroup.hidden = selected !== "round_trip";
    recurringFreqGroup.hidden = selected !== "recurring";
    recurringDaysGroup.hidden = selected !== "recurring";
    dischargeNotesGroup.hidden = selected !== "discharge";
    dischargeAccommodationsGroup.hidden = selected !== "discharge";
  }
  
  tripTypeRadios.forEach(radio => {
    radio.addEventListener("change", updateTripTypeUI);
  });
  
  updateTripTypeUI(); // Initial state
}
```

---

## 5. Backend ETA & Routing Intelligence

### Distance/Duration Calculation by Trip Type

```python
def calculate_trip_metrics(trip_type: TripType, distance_miles: float, return_distance_miles: Optional[float] = None) -> tuple[float, int]:
    """Calculate total distance and ETA based on trip type."""
    
    if trip_type == TripType.ONE_WAY:
        total_distance = distance_miles
        eta_minutes = int(round((total_distance / 25.0) * 60))  # 25 mph average
    
    elif trip_type == TripType.ROUND_TRIP:
        # Both forward and return legs count for ETA
        return_dist = return_distance_miles or distance_miles
        total_distance = distance_miles + return_dist
        # Add 30 min buffer for patient stay
        eta_minutes = int(round((total_distance / 25.0) * 60)) + 30
    
    elif trip_type == TripType.RECURRING:
        # Single leg distance; recurring pattern implies multiple instances
        total_distance = distance_miles
        eta_minutes = int(round((total_distance / 25.0) * 60))
    
    elif trip_type == TripType.DISCHARGE:
        # Discharge rides are often slower due to patient condition
        # Add 50% time buffer
        total_distance = distance_miles
        base_eta = int(round((total_distance / 25.0) * 60))
        eta_minutes = int(base_eta * 1.5)  # 50% slower
    
    return total_distance, eta_minutes
```

---

## 6. Data Migration Path

### Existing recurring_trip_pattern → New recurring_* Fields

For rides that already have `recurring_trip_pattern` data:

```python
def migrate_recurring_pattern(ride_orm) -> None:
    """
    Migrate legacy recurring_trip_pattern to new recurring_frequency/days fields.
    Runs on first trip type introduction.
    """
    if not ride_orm.recurring_trip_pattern:
        ride_orm.trip_type = TripType.ONE_WAY
        return
    
    pattern = ride_orm.recurring_trip_pattern
    ride_orm.trip_type = TripType.RECURRING
    ride_orm.recurring_frequency = pattern.get("frequency", "weekly")
    ride_orm.recurring_days = pattern.get("days", [])
    ride_orm.recurring_trip_pattern = None  # Deprecated
```

---

## 7. UI/UX Mockup (ASCII)

```
┌─ Create Ride Request ────────────────────────────────────────────────┐
│                                                                        │
│  Passenger Name: [________________]   Passenger Phone: [______________] │
│  Pickup Address: [__________________________________________________]   │
│  Dropoff Address: [_________________________________________________]   │
│  Service Type: [Dialysis ▼]  Provider: [Amicor Health ▼]             │
│                                                                        │
│  ┌─ Trip Type (SELECT ONE) ────────────────────────────────────────┐ │
│  │ ◉ One-Way: Single pickup to dropoff                            │ │
│  │ ○ Round Trip: Pickup → dropoff → return to origin              │ │
│  │ ○ Recurring: Repeating pattern (linked to recurring schedule)  │ │
│  │ ○ Hospital Discharge: Post-discharge medical transport         │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  Estimated Distance (miles): [1.0 ]  (Auto-calculated)               │
│  Estimated Duration (minutes): [__]                                  │
│  Priority: [Normal ▼]                                                │
│  Appointment Time: [________________]                                │
│  □ Mark as emergency intake                                          │
│                                                                        │
│  Trip Recurrence: [No (One-time) ▼]                                  │
│                                                                        │
│  [Create Ride]  [Cancel]                                             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Implementation Timeline

### Phase 1C-S1 (Immediate): MVP Trip Type
- [ ] Add trip_type enum to backend schemas
- [ ] Add trip_type radio buttons to frontend form
- [ ] Build trip_type payload in form submission
- [ ] Update RideCreate validator
- [ ] Test: Create one-way, round-trip rides via API

### Phase 1D (Next Sprint): Advanced Features
- [ ] Implement DISCHARGE trip type with accommodations
- [ ] Implement ROUND_TRIP return time scheduling
- [ ] Link RECURRING trips to recurring_schedule_id
- [ ] Geo-fence discharge rides to medical facilities
- [ ] Implement discharge checklist pre-flight

### Phase 1E (Future): Intelligence
- [ ] Learn ETA adjustments per trip type from historical data
- [ ] Route optimization based on trip type
- [ ] Dispatch scoring favors discharge rides (highest priority)
- [ ] Predictive recurring ride fulfillment

---

## 9. Validation Rules

| Field | Trip Type | Required | Validation |
|-------|-----------|----------|-----------|
| `trip_type` | All | ✅ Yes | Must be one of enum values |
| `return_pickup_time` | ROUND_TRIP | ✅ Yes | Must be after `appointment_time` |
| `return_address` | ROUND_TRIP | ❌ No | Defaults to `pickup_address` |
| `recurring_frequency` | RECURRING | ✅ Yes | {daily, weekly, monthly, custom} |
| `recurring_days` | RECURRING (weekly/monthly) | ✅ Yes | Minimum 1 day selected |
| `recurring_schedule_id` | RECURRING | ❌ No | Links to existing schedule or null |
| `discharge_medical_notes` | DISCHARGE | ❌ No | Free text, max 500 chars |
| `discharge_accommodations` | DISCHARGE | ❌ No | Subset of {wheelchair, oxygen, gurney, medical_attendant} |

---

## 10. Error Handling

### Client-Side
- Trip type changes clear conditional field validation errors
- Missing required conditional fields prevent form submission
- User receives clear error: "Return pickup time is required for round trip rides"

### Server-Side
- 400 Bad Request if required trip-type-specific fields missing
- 400 Bad Request if invalid enum value provided
- 409 Conflict if attempting RECURRING without recurring_schedule_id (future phases)

---

## Success Criteria

✅ Dispatcher can select trip type from 4 options  
✅ Conditional fields appear/disappear based on trip type  
✅ Form submission includes trip type in payload  
✅ Backend validates trip type and required fields  
✅ RideResponse includes trip type in response  
✅ ETA calculation reflects trip type (discharge = +50% buffer)  
✅ One-way trips work end-to-end (MVP)  
✅ No regressions in existing ride creation flow
