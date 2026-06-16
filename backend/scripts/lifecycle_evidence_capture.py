import json
import sqlite3
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8011"
DB = Path(r"C:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild\backend\data\chat.db")
SEED_PASSWORD = "Amicor123!"
EMAILS = {
    "rider": "rider@amicor.local",
    "dispatcher": "dispatcher@amicor.local",
    "driver_user": "driver@amicor.local",
    "admin": "admin@amicor.local",
}


def req(method: str, path: str, data=None, token: str | None = None):
    url = BASE + path
    body = None
    headers = {"Accept": "application/json"}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, json.loads(text) if text else None
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            payload = json.loads(text)
        except Exception:
            payload = {"raw": text}
        return exc.code, payload


def finish(failed_step: str | None, result: dict, message: str | None = None):
    payload = {"failed_step": failed_step, "message": message, "result": result}
    output_path = Path(r"C:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild\backend\scripts\lifecycle_evidence_output.json")
    output_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"failed_step": failed_step, "message": message, "output_path": str(output_path)}, indent=2))
    sys.exit(0)


def main():
    result = {"base_url": BASE, "db_path": str(DB), "api_calls": [], "db": {}}

    for role, email in EMAILS.items():
        status, payload = req("POST", "/api/auth/login", {"email": email, "password": SEED_PASSWORD})
        result[f"{role}_login"] = {"status": status, "response": payload}
        if status != 200:
            finish("login", result)

    tokens = {k: result[f"{k}_login"]["response"]["access_token"] for k in EMAILS}

    status, me = req("GET", "/api/auth/me", token=tokens["dispatcher"])
    result["api_calls"].append(
        {
            "step": "dispatcher_me",
            "method": "GET",
            "path": "/api/auth/me",
            "status": status,
            "response": me,
        }
    )
    org_id = me.get("organization_id") if isinstance(me, dict) else None
    if not org_id:
        finish("organization_lookup", result)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    driver_id = str(uuid.uuid4())
    driver_name = f"Evidence Driver {driver_id[:8]}"
    driver_phone = "917555" + "".join(ch for ch in driver_id if ch.isdigit())[:4]
    cur.execute(
        """
        INSERT INTO health_isf_drivers
        (id, organization_id, name, phone, vehicle_type, vehicle_plate, status, is_active, total_trips, rating, auth_state, availability_state, is_online, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (
            driver_id,
            org_id,
            driver_name,
            driver_phone,
            "sedan",
            "EVD-" + driver_id[:6].upper(),
            "available",
            1,
            0,
            5.0,
            "active",
            "available",
            1,
        ),
    )
    conn.commit()

    rider_phone = "+1555" + "".join(ch for ch in str(uuid.uuid4()) if ch.isdigit())[:7]
    create_payload = {
        "rider_name": "Evidence Rider",
        "rider_phone": rider_phone,
        "pickup_address": "101 Evidence Way",
        "dropoff_address": "202 Evidence Ave",
        "ride_type": "healthcare",
        "notes": "Lifecycle evidence run",
    }
    status, payload = req("POST", "/api/health-isf/customer-requests", create_payload, tokens["rider"])
    result["api_calls"].append(
        {
            "step": "ride_creation",
            "method": "POST",
            "path": "/api/health-isf/customer-requests",
            "request": create_payload,
            "status": status,
            "response": payload,
        }
    )
    if status != 201:
        finish("ride_creation", result)

    request_id = payload["id"]
    ride_id = payload["ride_id"]

    status, queue = req("GET", "/api/health-isf/dispatch/queue?limit=100", token=tokens["dispatcher"])
    queue_count = len(queue) if isinstance(queue, list) else None
    queue_hit = None
    if status == 200 and isinstance(queue, list):
        for item in queue:
            if item.get("ride_id") == ride_id:
                queue_hit = item
                break
    if queue_hit is None:
        result["api_calls"].append(
            {
                "step": "dispatcher_queue_after_create",
                "method": "GET",
                "path": "/api/health-isf/dispatch/queue?limit=100",
                "status": status,
                "response": {"queue_count": queue_count, "matching_item": None},
            }
        )
        cur.execute(
            "SELECT id, ride_id, rider_name, rider_phone, dispatch_status, pending_at, accepted_at, assigned_at, in_progress_at, completed_at, created_at, updated_at FROM health_isf_customer_ride_requests WHERE id = ?",
            (request_id,),
        )
        result["db"]["customer_request"] = dict(cur.fetchone() or {})
        cur.execute(
            "SELECT id, organization_id, passenger_name, passenger_phone, status, lifecycle_state, driver_id, provider_id, requested_at, created_at, updated_at FROM health_isf_rides WHERE id = ?",
            (ride_id,),
        )
        result["db"]["ride"] = dict(cur.fetchone() or {})
        finish(
            "dispatcher_queue_visibility",
            result,
            "New ride request did not appear in /api/health-isf/dispatch/queue after creation.",
        )
    result["api_calls"].append(
        {
            "step": "dispatcher_queue_after_create",
            "method": "GET",
            "path": "/api/health-isf/dispatch/queue?limit=100",
            "status": status,
            "response": {"queue_count": queue_count, "matching_item": queue_hit},
        }
    )

    status, payload = req(
        "POST",
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        token=tokens["dispatcher"],
    )
    result["api_calls"].append(
        {
            "step": "approve_request",
            "method": "POST",
            "path": f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
            "status": status,
            "response": payload,
        }
    )
    if status != 200:
        finish("approve_request", result)

    assign_body = {"driver_id": driver_id}
    status, payload = req(
        "POST",
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        assign_body,
        tokens["dispatcher"],
    )
    result["api_calls"].append(
        {
            "step": "assign_driver",
            "method": "POST",
            "path": f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            "request": assign_body,
            "status": status,
            "response": payload,
        }
    )
    if status != 200:
        finish("assign_driver", result)

    status, offer_payload = req(
        "GET",
        f"/api/health-isf/drivers/{driver_id}/active-offer",
        token=tokens["dispatcher"],
    )
    result["api_calls"].append(
        {
            "step": "driver_active_offer",
            "method": "GET",
            "path": f"/api/health-isf/drivers/{driver_id}/active-offer",
            "status": status,
            "response": offer_payload,
        }
    )
    if status != 200 or not offer_payload.get("offer"):
        finish("driver_offer_lookup", result)

    offer_id = offer_payload["offer"]["id"]

    status, payload = req(
        "POST",
        f"/api/health-isf/dispatch/offers/{offer_id}/accept",
        token=tokens["dispatcher"],
    )
    result["api_calls"].append(
        {
            "step": "driver_accepts_offer",
            "method": "POST",
            "path": f"/api/health-isf/dispatch/offers/{offer_id}/accept",
            "status": status,
            "response": payload,
        }
    )
    if status != 200:
        finish("driver_accept", result)

    status, payload = req(
        "POST",
        f"/api/health-isf/drivers/{driver_id}/pickup-complete",
        {"ride_id": ride_id},
        tokens["dispatcher"],
    )
    result["api_calls"].append(
        {
            "step": "driver_pickup_complete",
            "method": "POST",
            "path": f"/api/health-isf/drivers/{driver_id}/pickup-complete",
            "request": {"ride_id": ride_id},
            "status": status,
            "response": payload,
        }
    )
    if status != 200:
        finish("driver_start_trip", result)

    status, payload = req(
        "POST",
        "/api/ops/workspace/action?role_view=driver",
        {
            "action_type": "driver.update_route_progress",
            "payload": {"trip_id": ride_id, "driver_id": driver_id, "route_progress_percent": 90},
        },
        tokens["driver_user"],
    )
    result["api_calls"].append(
        {
            "step": "driver_progress_trip",
            "method": "POST",
            "path": "/api/ops/workspace/action?role_view=driver",
            "request": {
                "action_type": "driver.update_route_progress",
                "payload": {"trip_id": ride_id, "driver_id": driver_id, "route_progress_percent": 90},
            },
            "status": status,
            "response": payload,
        }
    )
    if status != 200:
        finish("ride_in_progress", result)

    status, payload = req(
        "POST",
        "/api/ops/workspace/action?role_view=driver",
        {
            "action_type": "driver.complete_trip",
            "payload": {"trip_id": ride_id, "driver_id": driver_id},
        },
        tokens["driver_user"],
    )
    result["api_calls"].append(
        {
            "step": "driver_complete_trip",
            "method": "POST",
            "path": "/api/ops/workspace/action?role_view=driver",
            "request": {
                "action_type": "driver.complete_trip",
                "payload": {"trip_id": ride_id, "driver_id": driver_id},
            },
            "status": status,
            "response": payload,
        }
    )
    if status != 200:
        finish("driver_complete_trip", result)

    status, payload = req("GET", "/api/health-isf/dispatcher/queues", token=tokens["dispatcher"])
    completed_match = None
    if status == 200 and isinstance(payload, dict):
        completed = payload.get("queues", {}).get("completed", [])
        if isinstance(completed, list):
            completed_match = next((item for item in completed if item.get("id") == ride_id), None)
    result["api_calls"].append(
        {
            "step": "completed_queue",
            "method": "GET",
            "path": "/api/health-isf/dispatcher/queues",
            "status": status,
            "response_sample": {"completed_match": completed_match},
        }
    )

    cur.execute(
        "SELECT id, ride_id, rider_name, rider_phone, dispatch_status, pending_at, accepted_at, assigned_at, in_progress_at, completed_at, created_at, updated_at FROM health_isf_customer_ride_requests WHERE id = ?",
        (request_id,),
    )
    result["db"]["customer_request"] = dict(cur.fetchone() or {})

    cur.execute(
        "SELECT id, organization_id, passenger_name, passenger_phone, status, lifecycle_state, driver_id, provider_id, requested_at, accepted_at, picked_up_at, transporting_at, completed_at, created_at, updated_at FROM health_isf_rides WHERE id = ?",
        (ride_id,),
    )
    result["db"]["ride"] = dict(cur.fetchone() or {})

    cur.execute(
        "SELECT id, ride_id, driver_id, assignment_state, attempt_index, offered_at, assigned_at, accepted_at, pickup_complete_at, dropoff_complete_at, created_at, updated_at FROM health_isf_dispatch_assignments WHERE ride_id = ? ORDER BY created_at DESC LIMIT 3",
        (ride_id,),
    )
    result["db"]["assignments"] = [dict(r) for r in cur.fetchall()]

    cur.execute(
        "SELECT id, ride_id, action, note, assignment_id, lifecycle_state, transition_reason, emitted_event_name, assignment_transition_source, acted_by_user_id, created_at FROM health_isf_dispatch_logs WHERE ride_id = ? ORDER BY created_at ASC",
        (ride_id,),
    )
    result["db"]["dispatch_logs"] = [dict(r) for r in cur.fetchall()]

    cur.execute(
        "SELECT id, ride_id, from_status, to_status, note, changed_by_user_id, created_at FROM health_isf_ride_status_history WHERE ride_id = ? ORDER BY created_at ASC",
        (ride_id,),
    )
    result["db"]["status_history"] = [dict(r) for r in cur.fetchall()]

    conn.close()
    finish(None, result)


if __name__ == "__main__":
    main()
