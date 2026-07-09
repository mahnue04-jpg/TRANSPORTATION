import os
import httpx

BASE = "http://127.0.0.1:8765"
EMAIL = "dispatcher@amicor.local"
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")

login = httpx.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=60)
print("login", login.status_code)
token = login.json()["access_token"]
org = login.json().get("organization_id")
headers = {"Authorization": f"Bearer {token}"}
providers = httpx.get(f"{BASE}/api/health-isf/providers", headers=headers, params={"organization_id": org}, timeout=60).json()
provider_id = providers[0]["id"]
payload = {
    "passenger_name": "API Probe Rider",
    "passenger_phone": "646-555-9901",
    "pickup_address": "100 Browser Test Ave, New York, NY 10001",
    "dropoff_address": "200 Clinic Rd, New York, NY 10002",
    "service_type": "medical_transport",
    "provider_id": provider_id,
    "estimated_distance_miles": 3.5,
    "priority_tag": "normal",
}
r = httpx.post(f"{BASE}/api/health-isf/rides", headers=headers, json=payload, timeout=60)
print("create", r.status_code, r.text[:2000])
