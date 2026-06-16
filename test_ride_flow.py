import sys
import os
# Add backend directory to path
backend_path = os.path.join(os.getcwd(), "backend")
sys.path.append(backend_path)

from fastapi.testclient import TestClient
from app.main import app
import json

client = TestClient(app)

def test_flow():
    # 1. GET providers and drivers
    print("--- Getting Providers and Drivers ---")
    p_resp = client.get("/api/health-isf/providers")
    providers = p_resp.json()
    provider_id = providers[0]["id"] if providers else None
    
    d_resp = client.get(f"/api/health-isf/drivers?provider_id={provider_id}")
    drivers = d_resp.json()
    
    available_driver = next((d for d in drivers if d["status"] == "available"), None)
    unavailable_driver = next((d for d in drivers if d["status"] != "available"), None)
    
    print(f"Provider ID: {provider_id}")
    print(f"Available Driver: {available_driver['id'] if available_driver else 'None'}")
    print(f"Unavailable Driver: {unavailable_driver['id'] if unavailable_driver else 'None'}")

    if not provider_id or not available_driver:
        print("Required data (provider or available driver) not found. Aborting.")
        return

    # 2. POST /api/health-isf/rides
    print("\n--- Creating Fresh Ride ---")
    ride_data = {
        "passenger_name": "Test Patient",
        "passenger_phone": "555-0199",
        "pickup_address": "Origin A",
        "dropoff_address": "Dest B",
        "provider_id": provider_id,
        "pickup_time": "2023-11-01T10:00:00Z",
        "service_type": "standard"
    }
    r_resp = client.post("/api/health-isf/rides", json=ride_data)
    if r_resp.status_code not in [200, 201]:
        print(f"Failed to create ride: {r_resp.status_code} - {r_resp.text}")
        return
        
    ride = r_resp.json()
    ride_id = ride["id"]
    print(f"Created Ride ID: {ride_id}, Status: {ride['status']}")

    # 3. Negative A: PATCH to completed directly
    print("\n--- Negative A: Direct to Completed ---")
    patch_resp = client.patch(f"/api/health-isf/rides/{ride_id}", json={"status": "completed"})
    print(f"Code: {patch_resp.status_code}, Detail: {patch_resp.json().get('detail')}")

    # 4. Negative B: Assign unavailable driver
    if unavailable_driver:
        print("\n--- Negative B: Assign Unavailable Driver ---")
        patch_resp = client.patch(f"/api/health-isf/rides/{ride_id}", json={"driver_id": unavailable_driver["id"]})
        print(f"Code: {patch_resp.status_code}, Detail: {patch_resp.json().get('detail')}")
    else:
        print("\n--- Negative B skipping (No unavailable driver found) ---")

    # 6a. Dashboard Before
    print("\n--- Dashboard Before Happy Path ---")
    dash_before = client.get("/api/health-isf/dashboard").json()
    print(f"Dashboard: {dash_before}")

    # 5. Happy Path
    print("\n--- Happy Path: Assign -> Accepted -> In Transit -> Completed ---")
    steps = [
        {"driver_id": available_driver["id"]},
        {"status": "accepted"},
        {"status": "in_transit"},
        {"status": "completed"}
    ]
    for step in steps:
        s_resp = client.patch(f"/api/health-isf/rides/{ride_id}", json=step)
        print(f"PATCH {step}: Status {s_resp.status_code}, Ride Status: {s_resp.json().get('status')}")

    # 6b. Dashboard After
    print("\n--- Dashboard After Happy Path ---")
    dash_after = client.get("/api/health-isf/dashboard").json()
    print(f"Dashboard: {dash_after}")

if __name__ == '__main__':
    test_flow()
