import json
import requests
import uuid

base = "http://127.0.0.1:8011"
proof = []


def excerpt(data, max_len=320):
    s = json.dumps(data, ensure_ascii=True) if not isinstance(data, str) else data
    return s[:max_len]


def add(step, endpoint, payload, resp, expected=(200, 201), note=""):
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    proof.append(
        {
            "step": step,
            "endpoint": endpoint,
            "payload": payload,
            "status": resp.status_code,
            "pass": resp.status_code in expected,
            "body_excerpt": excerpt(body),
            "note": note,
        }
    )
    return body


# Auth
login_payload = {"email": "dispatcher@amicor.local", "password": "Amicor123!"}
login = requests.post(f"{base}/api/auth/login", json=login_payload, timeout=20)
login_body = add("Auth Dispatcher", "/api/auth/login", login_payload, login, expected=(200,))
if login.status_code != 200:
    print(json.dumps({"error": "dispatcher login failed", "proof": proof}, indent=2))
    raise SystemExit(1)

token = login_body["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 1) Create Request
rider_phone = "+1212555" + str(uuid.uuid4().int % 9000 + 1000)
create_payload = {
    "pickup_address": "100 Clinic Way, New York, NY 10001",
    "dropoff_address": "200 Wellness Ave, New York, NY 10002",
    "rider_name": "Dispatch Proof Rider " + str(uuid.uuid4())[:6],
    "rider_phone": rider_phone,
    "ride_type": "healthcare",
    "recurring": False,
    "notes": "dispatch workflow proof run",
}
create = requests.post(f"{base}/api/health-isf/customer-requests", headers=headers, json=create_payload, timeout=30)
create_body = add("Create Request", "/api/health-isf/customer-requests", create_payload, create, expected=(201,))
if create.status_code != 201:
    print(json.dumps({"error": "create request failed", "proof": proof}, indent=2))
    raise SystemExit(1)
request_id = create_body["id"]
ride_id = create_body.get("ride_id")

# 2) Select Request
queue = requests.get(f"{base}/api/health-isf/customer-requests?limit=50", headers=headers, timeout=30)
queue_body = add("Select Request (Queue Visibility)", "/api/health-isf/customer-requests?limit=50", None, queue, expected=(200,))
if queue.status_code != 200:
    print(json.dumps({"error": "queue read failed", "proof": proof}, indent=2))
    raise SystemExit(1)
found = any((row.get("id") == request_id) for row in (queue_body or [])) if isinstance(queue_body, list) else False
proof.append(
    {
        "step": "Select Request (Match ID)",
        "endpoint": "local-check",
        "payload": {"request_id": request_id},
        "status": 200 if found else 500,
        "pass": found,
        "body_excerpt": f"request_id_found={found}",
        "note": "request selected by ID from queue",
    }
)

approve = requests.post(f"{base}/api/health-isf/dispatcher/customer-requests/{request_id}/approve", headers=headers, timeout=30)
add("Select Request (Approve)", f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve", None, approve, expected=(200,))
if approve.status_code != 200:
    print(json.dumps({"error": "approve failed", "proof": proof}, indent=2))
    raise SystemExit(1)

# 3) Assign Driver
avail = requests.get(f"{base}/api/health-isf/drivers/available", headers=headers, timeout=30)
avail_body = add("Driver Pool Lookup", "/api/health-isf/drivers/available", None, avail, expected=(200,))
if avail.status_code != 200:
    print(json.dumps({"error": "driver lookup failed", "proof": proof}, indent=2))
    raise SystemExit(1)

driver_id = None
if isinstance(avail_body, list) and avail_body:
    driver_id = avail_body[0].get("id")

if not driver_id:
    new_driver_payload = {
        "name": "Proof Driver " + str(uuid.uuid4())[:6],
        "phone": "212-555-" + str(uuid.uuid4()).replace("-", "")[:4],
        "vehicle_type": "sedan",
        "vehicle_plate": "P-" + str(uuid.uuid4())[:5].upper(),
    }
    new_driver = requests.post(f"{base}/api/health-isf/drivers", headers=headers, json=new_driver_payload, timeout=30)
    new_driver_body = add("Driver Create Fallback", "/api/health-isf/drivers", new_driver_payload, new_driver, expected=(200, 201))
    if new_driver.status_code not in (200, 201):
        print(json.dumps({"error": "driver create failed", "proof": proof}, indent=2))
        raise SystemExit(1)
    driver_id = new_driver_body.get("id")

assign_payload = {"action": "assign_driver", "ride_id": ride_id, "driver_id": driver_id}
assign = requests.post(
    f"{base}/api/health-isf/operations/lifecycle-action",
    headers=headers,
    params=assign_payload,
    timeout=30,
)
add(
    "Assign Driver",
    "/api/health-isf/operations/lifecycle-action?action=assign_driver",
    assign_payload,
    assign,
    expected=(200,),
)
if assign.status_code != 200:
    print(json.dumps({"error": "assign failed", "proof": proof}, indent=2))
    raise SystemExit(1)

driver_assign_status_payload = {"status": "assigned"}
driver_assign_status = requests.post(
    f"{base}/api/health-isf/drivers/{driver_id}/set-status",
    headers=headers,
    json=driver_assign_status_payload,
    timeout=30,
)
add(
    "Assign Driver (Driver Status -> assigned)",
    f"/api/health-isf/drivers/{driver_id}/set-status",
    driver_assign_status_payload,
    driver_assign_status,
    expected=(200,),
)

# 4) Accept
accept_payload = {"action": "accept_assignment", "ride_id": ride_id, "driver_id": driver_id}
accept = requests.post(
    f"{base}/api/health-isf/operations/lifecycle-action",
    headers=headers,
    params=accept_payload,
    timeout=30,
)
add(
    "Accept",
    "/api/health-isf/operations/lifecycle-action?action=accept_assignment",
    accept_payload,
    accept,
    expected=(200,),
)

# 5) Start Trip
arrive_payload = {"action": "driver_arrived", "ride_id": ride_id, "driver_id": driver_id}
arrive = requests.post(
    f"{base}/api/health-isf/operations/lifecycle-action",
    headers=headers,
    params=arrive_payload,
    timeout=30,
)
add(
    "Start Trip (Arrived Pickup)",
    "/api/health-isf/operations/lifecycle-action?action=driver_arrived",
    arrive_payload,
    arrive,
    expected=(200,),
)

pickup_payload = {"action": "rider_picked_up", "ride_id": ride_id, "driver_id": driver_id}
start_trip = requests.post(
    f"{base}/api/health-isf/operations/lifecycle-action",
    headers=headers,
    params=pickup_payload,
    timeout=30,
)
add(
    "Start Trip (Pickup Complete)",
    "/api/health-isf/operations/lifecycle-action?action=rider_picked_up",
    pickup_payload,
    start_trip,
    expected=(200,),
)

# 6) Complete Trip
complete_payload = {"action": "ride_completed", "ride_id": ride_id, "driver_id": driver_id}
complete = requests.post(
    f"{base}/api/health-isf/operations/lifecycle-action",
    headers=headers,
    params=complete_payload,
    timeout=30,
)
add(
    "Complete Trip",
    "/api/health-isf/operations/lifecycle-action?action=ride_completed",
    complete_payload,
    complete,
    expected=(200,),
)

# 7) Verify histories update
ride_hist = requests.get(f"{base}/api/health-isf/rides/{ride_id}/history", headers=headers, timeout=30)
add(
    "Verify Histories (Ride History)",
    f"/api/health-isf/rides/{ride_id}/history",
    None,
    ride_hist,
    expected=(200,),
)

phone_encoded = requests.utils.quote(rider_phone)
cust_hist = requests.get(
    f"{base}/api/health-isf/customers/workspace/history?rider_phone={phone_encoded}&limit=20",
    headers=headers,
    timeout=30,
)
cust_hist_body = add(
    "Verify Histories (Customer Workspace History)",
    "/api/health-isf/customers/workspace/history?rider_phone=<encoded>&limit=20",
    {"rider_phone": rider_phone, "limit": 20},
    cust_hist,
    expected=(200,),
)

history_ok = False
if isinstance(cust_hist_body, dict):
    rows = cust_hist_body.get("history") or []
    history_ok = any((row.get("ride_id") == ride_id and row.get("dispatch_status") == "completed") for row in rows)
proof.append(
    {
        "step": "Verify Histories (Completed Entry Present)",
        "endpoint": "local-check",
        "payload": {"ride_id": ride_id, "rider_phone": rider_phone},
        "status": 200 if history_ok else 500,
        "pass": history_ok,
        "body_excerpt": f"completed_history_present={history_ok}",
        "note": "customer history includes completed dispatch for created ride",
    }
)

print(
    json.dumps(
        {
            "request_id": request_id,
            "ride_id": ride_id,
            "driver_id": driver_id,
            "rider_phone": rider_phone,
            "proof": proof,
        },
        indent=2,
    )
)
