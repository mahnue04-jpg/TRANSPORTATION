import os
import httpx

BASE = "http://127.0.0.1:8010"
EMAIL = "dispatcher@amicor.local"
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")

login = httpx.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=60)
token = login.json()["access_token"]
org = login.json().get("organization_id")
headers = {
    "Authorization": f"Bearer {token}",
    "X-Idempotency-Key": "ride:browser-probe:1",
    "X-Client-Action-Id": "probe-create",
}
payload = {
    "passenger_name": "Browser Payload Probe",
    "passenger_phone": "646-555-9900",
    "pickup_address": "100 Browser Test Ave, New York, NY 10001",
    "dropoff_address": "200 Clinic Rd, New York, NY 10002",
    "service_type": "medical_transport",
    "provider_id": "6e0c86e1-fce3-4ac6-ba56-b55717e84cb2",
    "estimated_distance_miles": 12,
    "estimated_duration_minutes": 29,
    "priority_tag": "normal",
    "is_emergency": False,
    "appointment_time": None,
    "recurring_trip_pattern": None,
    "ai_dispatch_context": None,
    "notes": None,
}
r = httpx.post(
    f"{BASE}/api/health-isf/rides",
    headers=headers,
    json=payload,
    params={"organization_id": org},
    timeout=60,
)
print("create", r.status_code, r.text[:2500])
