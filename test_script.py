import sys
import os
sys.path.append(os.path.join(os.getcwd(), 'backend'))
from fastapi.testclient import TestClient
try:
    from app.main import app
except Exception as e:
    print(f"Import Error: {e}")
    sys.exit(1)

client = TestClient(app)

openapi = app.openapi()
paths = openapi.get("paths", {})
for p in ["/api/health-isf/rides/{ride_id}/status", "/api/health-isf/rides/{ride_id}/assign-driver"]:
    status = "Found" if p in paths and "patch" in paths[p] else "Not Found"
    print(f"{p} PATCH: {status}")

try:
    rides_res = client.get("/api/health-isf/rides")
    rides = rides_res.json() if rides_res.status_code == 200 else []
    ride_id = rides[0]["id"] if rides else None
    
    drivers_res = client.get("/api/health-isf/drivers")
    drivers = drivers_res.json() if drivers_res.status_code == 200 else []
    available_driver = next((d for d in drivers if d.get("status") == "available"), None)
    unavailable_driver = next((d for d in drivers if d.get("status") != "available"), None)
    
    print(f"Ride: {ride_id}, Avail: {available_driver['id'] if available_driver else 'None'}, Unavail: {unavailable_driver['id'] if unavailable_driver else 'None'}")

    if ride_id:
        res = client.patch(f"/api/health-isf/rides/{ride_id}/status", json={"status": "completed"})
        print(f"Neg Status: {res.status_code} - {res.json().get('detail')}")

        if unavailable_driver:
            res = client.patch(f"/api/health-isf/rides/{ride_id}/assign-driver", json={"driver_id": unavailable_driver["id"]})
            print(f"Neg Assign: {res.status_code} - {res.json().get('detail')}")

        if available_driver:
            print("Happy Path:")
            r_assign = client.patch(f"/api/health-isf/rides/{ride_id}/assign-driver", json={"driver_id": available_driver["id"]})
            print(f" Assign: {r_assign.status_code}")
            for s in ["accepted", "in_transit", "completed"]:
                r_status = client.patch(f"/api/health-isf/rides/{ride_id}/status", json={"status": s})
                print(f" Status {s}: {r_status.status_code}")
    else:
        print("No rides found to test")
except Exception as e:
    print(f"Error during test: {e}")
