import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8010"
API = f"{BASE}/api/health-isf"
AUTH = f"{BASE}/api/auth/login"
OUT_DIR = Path("evidence/state_propagation")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def req(method, path, token, body=None, timeout=20):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    url = f"{BASE}{path}"
    response = requests.request(method, url, headers=headers, json=body, timeout=timeout)
    payload = None
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text[:4000]}
    return response.status_code, payload


def login(email, password):
    response = requests.post(AUTH, json={"email": email, "password": password}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError(f"No access token for {email}")
    return token


def slim(obj):
    if isinstance(obj, dict):
        keep = {}
        for key in [
            "id",
            "ride_id",
            "driver_id",
            "organization_id",
            "status",
            "lifecycle_state",
            "dispatch_status",
            "offer",
            "active_ride",
            "active_assignment",
            "queues",
            "detail",
            "message",
        ]:
            if key in obj:
                keep[key] = obj[key]
        return keep if keep else obj
    if isinstance(obj, list):
        return {"count": len(obj), "sample": obj[:2]}
    return obj


def find_ride_in_requests(requests_payload, ride_id):
    if isinstance(requests_payload, list):
        for row in requests_payload:
            if isinstance(row, dict) and str(row.get("ride_id") or "") == ride_id:
                return row
    return None


def find_ride_in_queues(queues_payload, ride_id):
    if not isinstance(queues_payload, dict):
        return None
    queues = queues_payload.get("queues") or {}
    if not isinstance(queues, dict):
        return None
    for queue_name, rows in queues.items():
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and str(row.get("id") or row.get("ride_id") or "") == ride_id:
                    return {"queue": queue_name, "row": row}
    return None


def verify_views(token, ride_id, driver_id, organization_id):
    status_riders, riders_payload = req("GET", f"/api/health-isf/customer-requests?organization_id={organization_id}&limit=200", token)
    status_drivers, drivers_payload = req("GET", f"/api/health-isf/drivers/{driver_id}/live-workspace?organization_id={organization_id}", token)
    status_dispatch, dispatch_payload = req("GET", f"/api/health-isf/dispatcher/queues?organization_id={organization_id}", token)
    status_ride, ride_payload = req("GET", f"/api/health-isf/rides/{ride_id}", token)

    rider_match = find_ride_in_requests(riders_payload, ride_id)
    driver_match = None
    if isinstance(drivers_payload, dict):
        active_ride = drivers_payload.get("active_ride")
        if isinstance(active_ride, dict) and str(active_ride.get("id") or "") == ride_id:
            driver_match = active_ride
    dispatch_match = find_ride_in_queues(dispatch_payload, ride_id)

    return {
        "riders": {
            "status": status_riders,
            "match": rider_match,
            "payload": slim(riders_payload),
        },
        "drivers": {
            "status": status_drivers,
            "match": driver_match,
            "payload": slim(drivers_payload),
        },
        "dispatch": {
            "status": status_dispatch,
            "match": dispatch_match,
            "payload": slim(dispatch_payload),
        },
        "ride": {
            "status": status_ride,
            "payload": slim(ride_payload),
        },
    }


def record_step(report, name, transition_call, verify):
    report["steps"].append({
        "state": name,
        "timestamp": now_iso(),
        "transition_api": transition_call,
        "view_verification": verify,
    })


def main():
    dispatcher_token = login("dispatcher@amicor.local", "Amicor123!")

    me_status, me = req("GET", "/api/auth/me", dispatcher_token)
    if me_status != 200 or not isinstance(me, dict):
        raise RuntimeError(f"/api/auth/me failed: {me_status} {me}")
    organization_id = str(me.get("organization_id") or "").strip()
    if not organization_id:
        raise RuntimeError("No organization_id in /api/auth/me response")

    report = {
        "generated_at": now_iso(),
        "base_url": BASE,
        "organization_id": organization_id,
        "steps": [],
    }

    rider_phone = "+1555" + "".join(ch for ch in str(uuid.uuid4()) if ch.isdigit())[:7]
    rider_name = f"State Rider {str(uuid.uuid4())[:8]}"

    create_rider_body = {
        "rider_name": rider_name,
        "rider_phone": rider_phone,
        "pickup_address": "100 Clinic Way",
        "dropoff_address": "200 Recovery Ave",
        "ride_type": "healthcare",
        "notes": "state propagation run",
    }
    s_rider, p_rider = req("POST", "/api/health-isf/customer-requests", dispatcher_token, create_rider_body)
    if s_rider != 201 or not isinstance(p_rider, dict):
        raise RuntimeError(f"Create rider/request failed: {s_rider} {p_rider}")

    request_id = str(p_rider.get("id") or "")
    ride_id = str(p_rider.get("ride_id") or "")
    if not request_id or not ride_id:
        raise RuntimeError(f"Missing request_id/ride_id in create response: {p_rider}")

    report["rider_created"] = {"status": s_rider, "request": p_rider}
    report["ride_created"] = {"ride_id": ride_id, "source": "customer-request auto-create"}

    create_driver_body = {
        "name": f"State Driver {str(uuid.uuid4())[:8]}",
        "phone": "+1555" + "".join(ch for ch in str(uuid.uuid4()) if ch.isdigit())[:7],
        "vehicle_type": "sedan",
        "vehicle_plate": "ST" + str(uuid.uuid4()).replace("-", "")[:6].upper(),
    }
    s_driver, p_driver = req("POST", "/api/health-isf/drivers", dispatcher_token, create_driver_body)
    if s_driver != 201 or not isinstance(p_driver, dict):
        raise RuntimeError(f"Create driver failed: {s_driver} {p_driver}")

    driver_id = str(p_driver.get("id") or "")
    if not driver_id:
        raise RuntimeError(f"Missing driver_id in create driver response: {p_driver}")

    report["driver_created"] = {"status": s_driver, "driver": p_driver}

    req("POST", f"/api/health-isf/drivers/{driver_id}/set-status", dispatcher_token, {"status": "available"})

    # Requested
    verify_requested = verify_views(dispatcher_token, ride_id, driver_id, organization_id)
    record_step(
        report,
        "Requested",
        {"method": "POST", "path": "/api/health-isf/customer-requests", "status": s_rider, "response": slim(p_rider)},
        verify_requested,
    )

    # Assign driver
    s_approve, p_approve = req("POST", f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve?organization_id={organization_id}", dispatcher_token)
    s_assign, p_assign = req(
        "POST",
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver?organization_id={organization_id}",
        dispatcher_token,
        {"driver_id": driver_id},
    )

    # Accepted (offer accept)
    s_offer, p_offer = req("GET", f"/api/health-isf/drivers/{driver_id}/active-offer?organization_id={organization_id}", dispatcher_token)
    offer_id = None
    if isinstance(p_offer, dict) and isinstance(p_offer.get("offer"), dict):
        offer_id = p_offer["offer"].get("id")
    if not offer_id:
        raise RuntimeError(f"No active offer after assignment: {s_offer} {p_offer}")

    s_accept, p_accept = req("POST", f"/api/health-isf/dispatch/offers/{offer_id}/accept", dispatcher_token)
    verify_accepted = verify_views(dispatcher_token, ride_id, driver_id, organization_id)
    record_step(
        report,
        "Accepted",
        {
            "method": "POST",
            "path": f"/api/health-isf/dispatch/offers/{offer_id}/accept",
            "status": s_accept,
            "response": slim(p_accept),
            "assign": {"approve_status": s_approve, "assign_status": s_assign, "assign_response": slim(p_assign)},
        },
        verify_accepted,
    )

    transitions = [
        ("En Route", "en_route_pickup"),
        ("Arrived", "arrived_pickup"),
        ("Loaded", "rider_loaded"),
        ("Transporting", "trip_in_progress"),
        ("Completed", "completed"),
    ]

    for state_name, target_state in transitions:
        s_t, p_t = req(
            "POST",
            f"/api/health-isf/drivers/{driver_id}/route-progress?organization_id={organization_id}",
            dispatcher_token,
            {"ride_id": ride_id, "target_state": target_state},
        )
        if s_t not in {200, 201}:
            raise RuntimeError(f"Transition {state_name} failed: {s_t} {p_t}")
        time.sleep(0.4)
        verify = verify_views(dispatcher_token, ride_id, driver_id, organization_id)
        record_step(
            report,
            state_name,
            {
                "method": "POST",
                "path": f"/api/health-isf/drivers/{driver_id}/route-progress",
                "body": {"ride_id": ride_id, "target_state": target_state},
                "status": s_t,
                "response": slim(p_t),
            },
            verify,
        )

    report["ids"] = {"ride_id": ride_id, "request_id": request_id, "driver_id": driver_id, "offer_id": offer_id}

    out_file = OUT_DIR / f"state_propagation_{ride_id}.json"
    out_file.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(json.dumps({
        "report_file": str(out_file),
        "ride_id": ride_id,
        "request_id": request_id,
        "driver_id": driver_id,
        "offer_id": offer_id,
        "states": [s["state"] for s in report["steps"]],
    }, indent=2))


if __name__ == "__main__":
    main()
