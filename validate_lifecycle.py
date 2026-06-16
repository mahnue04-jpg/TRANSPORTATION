"""
End-to-end lifecycle validation script.
Tests the full ride workflow: Request → Assign → Accept → Arrived → Pickup → Complete
"""
import sys, json, time
sys.path.insert(0, "backend")

import requests

BASE = "http://127.0.0.1:8010/api/health-isf"
AUTH = "http://127.0.0.1:8010/api/auth/login"

def get_token():
    r = requests.post(AUTH, json={"email": "admin@amicor.local", "password": "Amicor123!"}, timeout=10)
    if r.status_code != 200:
        print(f"AUTH FAILED {r.status_code}: {r.text[:200]}")
        sys.exit(1)
    token = r.json().get("access_token", "")
    print(f"[1] AUTH OK")
    return token

def get_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def check(label, r, expected=(200, 201)):
    codes = expected if isinstance(expected, tuple) else (expected,)
    ok = r.status_code in codes
    symbol = "PASS" if ok else "FAIL"
    print(f"  [{symbol}] {label}: HTTP {r.status_code}")
    if not ok:
        print(f"         BODY: {r.text[:300]}")
    return ok

def main():
    token = get_token()
    h = get_headers(token)

    # Get available drivers - or force one to available
    r = requests.get(f"{BASE}/drivers?limit=30", headers=h, timeout=10)
    check("GET /drivers", r)
    drivers_data = r.json()
    if isinstance(drivers_data, dict):
        drivers_data = drivers_data.get("items", drivers_data.get("drivers", []))
    avail = [d for d in drivers_data if d.get("status") == "available"]
    if not avail:
        # Reset first driver to available
        first_driver = drivers_data[0] if drivers_data else None
        if not first_driver:
            print("FAIL: No drivers found")
            sys.exit(1)
        r2 = requests.post(
            f"{BASE}/drivers/{first_driver['id']}/set-status",
            json={"status": "available"},
            headers=h,
            timeout=10
        )
        check(f"POST set-status=available for {first_driver['id'][:8]}", r2, (200, 201))
        avail = [first_driver]
    driver = avail[0]
    driver_id = driver["id"]
    print(f"[2] Driver selected: {driver_id[:8]}... name={driver.get('name','-')} status={driver.get('status','-')}")

    # Get providers
    r = requests.get(f"{BASE}/providers?limit=5", headers=h, timeout=10)
    check("GET /providers", r)
    prov_data = r.json()
    if isinstance(prov_data, dict):
        prov_data = prov_data.get("items", prov_data.get("providers", []))
    provider_id = prov_data[0]["id"] if prov_data else None
    print(f"[3] Provider: {str(provider_id)[:8] if provider_id else 'none'}")

    # Create a ride
    ride_payload = {
        "passenger_name": "Test Rider UI Sync",
        "passenger_phone": "+1-555-0199",
        "pickup_address": "123 Main St",
        "dropoff_address": "General Hospital",
        "service_type": "medical_transport",
        "priority_tag": "urgent",
        "is_emergency": False,
        "estimated_distance_miles": 3.5,
    }
    if provider_id:
        ride_payload["provider_id"] = provider_id

    r = requests.post(f"{BASE}/rides", json=ride_payload, headers=h, timeout=10)
    if not check("POST /rides (create)", r, (200, 201)):
        sys.exit(1)
    ride = r.json()
    ride_id = ride["id"]
    print(f"[4] RIDE CREATED: {ride_id[:8]}... status={ride.get('status','-')}")

    # Assign driver
    r = requests.patch(
        f"{BASE}/rides/{ride_id}/assign-driver",
        json={"driver_id": driver_id},
        headers=h,
        timeout=10
    )
    if not check("PATCH /rides/{id}/assign-driver", r):
        sys.exit(1)
    ride = r.json()
    print(f"[5] DRIVER ASSIGNED: ride status={ride.get('status','-')} driver={ride.get('driver_id','?')[:8] if ride.get('driver_id') else '?'}")

    # Driver accept ride
    r = requests.post(
        f"{BASE}/drivers/{driver_id}/accept-ride",
        json={"ride_id": ride_id},
        headers=h,
        timeout=10
    )
    if not check("POST /drivers/{id}/accept-ride", r):
        # Try to continue anyway
        pass
    else:
        ride = r.json()
        print(f"[6] DRIVER ACCEPTED: ride status={ride.get('status','-')}")

    # Verify ride timeline event recorded
    r = requests.get(f"{BASE}/rides/{ride_id}/history", headers=h, timeout=10)
    check("GET /rides/{id}/history", r)
    history = r.json() if r.ok else []
    if isinstance(history, dict):
        history = history.get("items", history.get("events", []))
    print(f"[7] HISTORY EVENTS: {len(history)} recorded")
    for ev in history[-3:]:
        status = ev.get("status", ev.get("event_type", "?"))
        print(f"      - {status}")

    # Driver arrived at pickup
    r = requests.post(
        f"{BASE}/drivers/{driver_id}/arrived-pickup",
        json={"ride_id": ride_id},
        headers=h,
        timeout=10
    )
    if not check("POST /drivers/{id}/arrived-pickup", r):
        pass
    else:
        ride = r.json()
        print(f"[8] DRIVER ARRIVED: ride status={ride.get('status','-')}")

    # Driver pickup complete (rider onboard)
    r = requests.post(
        f"{BASE}/drivers/{driver_id}/pickup-complete",
        json={"ride_id": ride_id},
        headers=h,
        timeout=10
    )
    if not check("POST /drivers/{id}/pickup-complete", r):
        pass
    else:
        ride = r.json()
        print(f"[9] PICKUP COMPLETE: ride status={ride.get('status','-')}")

    # Driver dropoff complete (trip done)
    r = requests.post(
        f"{BASE}/drivers/{driver_id}/dropoff-complete",
        json={"ride_id": ride_id},
        headers=h,
        timeout=10
    )
    if not check("POST /drivers/{id}/dropoff-complete", r):
        pass
    else:
        ride = r.json()
        print(f"[10] TRIP COMPLETE: ride status={ride.get('status','-')}")

    # Final DB record check
    r = requests.get(f"{BASE}/rides/{ride_id}", headers=h, timeout=10)
    check("GET /rides/{id} (final DB record)", r)
    final = r.json()
    print(f"\n=== FINAL RIDE STATE ===")
    print(f"  Ride ID:   {ride_id}")
    print(f"  Status:    {final.get('status','-')}")
    print(f"  Driver ID: {final.get('driver_id','-')}")
    print(f"  Passenger: {final.get('passenger_name','-')}")
    print(f"  Pickup:    {final.get('pickup_address','-')}")
    print(f"  Dropoff:   {final.get('dropoff_address','-')}")
    completed_at = final.get("completed_at") or final.get("updated_at")
    print(f"  Completed: {completed_at}")
    print()
    if final.get("status") == "completed":
        print("PASS: End-to-end lifecycle complete.")
    else:
        print(f"PARTIAL: final status is '{final.get('status','-')}' (expected 'completed')")

if __name__ == "__main__":
    main()
