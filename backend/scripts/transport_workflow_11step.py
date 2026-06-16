import json
import sqlite3
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:8010"
DB_PATH = Path(r"C:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild\backend\data\chat.db")
SEED_PASSWORD = "Amicor123!"
OUT_DIR = Path(r"C:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild\evidence\workflow_11step")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def req(method, path, data=None, token=None):
    headers = {"Accept": "application/json"}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
            payload = json.loads(text) if text else None
            return response.status, payload
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            payload = json.loads(text)
        except Exception:
            payload = {"raw": text}
        return exc.code, payload


def summarize_payload(payload):
    if payload is None:
        return None
    if isinstance(payload, dict):
        keys = [
            "id",
            "ride_id",
            "driver_id",
            "status",
            "lifecycle_state",
            "dispatch_status",
            "assignment_state",
            "offer",
            "request",
            "ride",
            "message",
            "detail",
        ]
        out = {}
        for k in keys:
            if k in payload:
                out[k] = payload[k]
        return out if out else payload
    if isinstance(payload, list):
        return {"count": len(payload), "sample": payload[:2]}
    return payload


def db_snapshot(request_id=None, ride_id=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    out = {}

    if request_id:
        cur.execute(
            """
            SELECT id, ride_id, dispatch_status, pending_at, accepted_at, assigned_at, in_progress_at, completed_at, updated_at
            FROM health_isf_customer_ride_requests
            WHERE id = ?
            """,
            (request_id,),
        )
        row = cur.fetchone()
        out["customer_request"] = dict(row) if row else None

    if ride_id:
        cur.execute(
            """
            SELECT id, status, lifecycle_state, driver_id, provider_id, accepted_at, picked_up_at, transporting_at, completed_at, updated_at
            FROM health_isf_rides
            WHERE id = ?
            """,
            (ride_id,),
        )
        row = cur.fetchone()
        out["ride"] = dict(row) if row else None

        cur.execute(
            """
            SELECT id, ride_id, driver_id, assignment_state, offered_at, assigned_at, accepted_at, pickup_complete_at, dropoff_complete_at, updated_at
            FROM health_isf_dispatch_assignments
            WHERE ride_id = ?
            ORDER BY created_at DESC
            LIMIT 3
            """,
            (ride_id,),
        )
        out["assignments"] = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT from_status, to_status, note, created_at
            FROM health_isf_ride_status_history
            WHERE ride_id = ?
            ORDER BY created_at ASC
            """,
            (ride_id,),
        )
        out["status_history"] = [dict(r) for r in cur.fetchall()]

    conn.close()
    return out


def add_step(steps, index, name, method, path, status, payload, db_data, passed, note=None):
    steps.append(
        {
            "step": index,
            "name": name,
            "timestamp": now_iso(),
            "api": {
                "method": method,
                "path": path,
                "status": status,
                "response": summarize_payload(payload),
            },
            "db": db_data,
            "passed": bool(passed),
            "note": note,
            "screenshot": f"evidence/workflow_11step/step_{index:02d}.png",
        }
    )


def login(email):
    status, payload = req("POST", "/api/auth/login", {"email": email, "password": SEED_PASSWORD})
    if status != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
        raise RuntimeError(f"Login failed for {email}: {status} {payload}")
    return payload["access_token"]


def main():
    tokens = {
        "provider": login("provider@amicor.local"),
        "dispatcher": login("dispatcher@amicor.local"),
        "driver_user": login("driver@amicor.local"),
    }

    status_me, me = req("GET", "/api/auth/me", token=tokens["dispatcher"])
    if status_me != 200 or not isinstance(me, dict):
        raise RuntimeError(f"Dispatcher /me failed: {status_me} {me}")
    org_id = me.get("organization_id")
    if not org_id:
        raise RuntimeError("Missing organization_id for dispatcher")

    status_drivers, drivers_payload = req("GET", "/api/health-isf/drivers", token=tokens["dispatcher"])
    if status_drivers != 200 or not isinstance(drivers_payload, list):
        raise RuntimeError(f"Could not list drivers: {status_drivers} {drivers_payload}")

    active_driver = None
    for row in drivers_payload:
        state = str((row or {}).get("status") or "").lower()
        if state in {"available", "offline", "paused", "assigned"}:
            active_driver = row
            break

    if not active_driver:
        create_driver_body = {
            "name": f"WF11 Driver {str(uuid.uuid4())[:8]}",
            "phone": "+1555" + "".join(ch for ch in str(uuid.uuid4()) if ch.isdigit())[:7],
            "vehicle_type": "sedan",
            "vehicle_plate": "WF11" + str(uuid.uuid4()).replace("-", "")[:4].upper(),
        }
        status_new_driver, new_driver = req("POST", "/api/health-isf/drivers", create_driver_body, tokens["dispatcher"])
        if status_new_driver != 201:
            raise RuntimeError(f"Could not create driver: {status_new_driver} {new_driver}")
        active_driver = new_driver

    driver_id = active_driver["id"]
    req("POST", f"/api/health-isf/drivers/{driver_id}/set-status", {"status": "available"}, tokens["dispatcher"])

    steps = []

    step1_payload = {
        "rider_name": "Provider Requested Rider",
        "rider_phone": "+1555" + "".join(ch for ch in str(uuid.uuid4()) if ch.isdigit())[:7],
        "pickup_address": "111 Provider Clinic Way",
        "dropoff_address": "222 Care Center Ave",
        "ride_type": "healthcare",
        "notes": "Step1 provider request",
    }
    s1, p1 = req("POST", "/api/health-isf/customer-requests", step1_payload, tokens["provider"])
    request_id = p1.get("id") if isinstance(p1, dict) else None
    ride_id = p1.get("ride_id") if isinstance(p1, dict) else None
    db1 = db_snapshot(request_id, ride_id)
    add_step(steps, 1, "Provider requests ride", "POST", "/api/health-isf/customer-requests", s1, p1, db1, s1 == 201 and bool(request_id) and bool(ride_id))

    s2, p2 = req("GET", "/api/health-isf/dispatch/queue?limit=100", token=tokens["dispatcher"])
    queue_match = None
    if isinstance(p2, list) and ride_id:
        queue_match = next((r for r in p2 if r.get("ride_id") == ride_id), None)
    db2 = db_snapshot(request_id, ride_id)
    add_step(steps, 2, "Ride appears in dispatch queue", "GET", "/api/health-isf/dispatch/queue?limit=100", s2, {"queue_match": queue_match, "count": len(p2) if isinstance(p2, list) else None}, db2, s2 == 200 and queue_match is not None)

    s3a, p3a = req("POST", f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve", token=tokens["dispatcher"])
    s3, p3 = req("POST", f"/api/health-isf/dispatcher/rides/{ride_id}/auto-assign", token=tokens["dispatcher"])
    selected_driver = p3.get("driver_id") if isinstance(p3, dict) else None
    if not selected_driver and isinstance(p3, dict):
        selected_driver = p3.get("selected_driver_id")
    if selected_driver:
        driver_id = selected_driver
    db3 = db_snapshot(request_id, ride_id)
    add_step(
        steps,
        3,
        "Automatic driver assignment executes",
        "POST",
        f"/api/health-isf/dispatcher/rides/{ride_id}/auto-assign",
        s3,
        {"approve_status": s3a, "approve_response": summarize_payload(p3a), "auto_assign_response": summarize_payload(p3)},
        db3,
        s3a == 200 and s3 == 200,
    )

    s4, p4 = req("GET", f"/api/health-isf/drivers/{driver_id}/active-offer", token=tokens["dispatcher"])
    offer = p4.get("offer") if isinstance(p4, dict) else None
    db4 = db_snapshot(request_id, ride_id)
    add_step(steps, 4, "Driver sees ride", "GET", f"/api/health-isf/drivers/{driver_id}/active-offer", s4, p4, db4, s4 == 200 and isinstance(offer, dict))

    offer_id = offer.get("id") if isinstance(offer, dict) else None
    s5, p5 = req("POST", f"/api/health-isf/dispatch/offers/{offer_id}/accept", token=tokens["dispatcher"])
    db5 = db_snapshot(request_id, ride_id)
    add_step(steps, 5, "Driver accepts ride", "POST", f"/api/health-isf/dispatch/offers/{offer_id}/accept", s5, p5, db5, s5 == 200)

    s6, p6 = req("GET", "/api/health-isf/dispatch/active-assignments?limit=100", token=tokens["dispatcher"])
    accepted_match = None
    if isinstance(p6, list):
        accepted_match = next((r for r in p6 if r.get("ride_id") == ride_id), None)
    db6 = db_snapshot(request_id, ride_id)
    add_step(steps, 6, "Dispatcher sees accepted ride", "GET", "/api/health-isf/dispatch/active-assignments?limit=100", s6, {"match": accepted_match}, db6, s6 == 200 and accepted_match is not None)

    s7, p7 = req("POST", f"/api/health-isf/drivers/{driver_id}/accept-ride", {"ride_id": ride_id}, tokens["driver_user"])
    db7 = db_snapshot(request_id, ride_id)
    ride_state_7 = (db7.get("ride") or {}).get("lifecycle_state")
    add_step(steps, 7, "Driver marks en route", "POST", f"/api/health-isf/drivers/{driver_id}/accept-ride", s7, p7, db7, s7 == 200 and str(ride_state_7).lower() in {"driver_en_route", "accepted", "en_route"})

    s8, p8 = req("POST", f"/api/health-isf/drivers/{driver_id}/arrived-pickup", {"ride_id": ride_id}, tokens["driver_user"])
    db8 = db_snapshot(request_id, ride_id)
    ride_state_8 = (db8.get("ride") or {}).get("lifecycle_state")
    add_step(steps, 8, "Driver marks arrived", "POST", f"/api/health-isf/drivers/{driver_id}/arrived-pickup", s8, p8, db8, s8 == 200 and str(ride_state_8).lower() == "arrived")

    s9, p9 = req("POST", f"/api/health-isf/drivers/{driver_id}/pickup-complete", {"ride_id": ride_id}, tokens["driver_user"])
    db9 = db_snapshot(request_id, ride_id)
    ride_state_9 = (db9.get("ride") or {}).get("lifecycle_state")
    add_step(steps, 9, "Driver marks pickup complete", "POST", f"/api/health-isf/drivers/{driver_id}/pickup-complete", s9, p9, db9, s9 == 200 and str(ride_state_9).lower() in {"in_progress", "rider_onboard"})

    s10, p10 = req("POST", f"/api/health-isf/drivers/{driver_id}/dropoff-complete", {"ride_id": ride_id}, tokens["driver_user"])
    db10 = db_snapshot(request_id, ride_id)
    ride_state_10 = (db10.get("ride") or {}).get("lifecycle_state")
    add_step(steps, 10, "Driver marks dropoff complete", "POST", f"/api/health-isf/drivers/{driver_id}/dropoff-complete", s10, p10, db10, s10 == 200 and str(ride_state_10).lower() == "completed")

    s11, p11 = req("GET", f"/api/health-isf/rides/{ride_id}", token=tokens["dispatcher"])
    s11q, p11q = req("GET", "/api/health-isf/dispatcher/queues", token=tokens["dispatcher"])
    completed_match = None
    if isinstance(p11q, dict):
        completed = (p11q.get("queues") or {}).get("completed") or []
        if isinstance(completed, list):
            completed_match = next((r for r in completed if r.get("id") == ride_id), None)
    db11 = db_snapshot(request_id, ride_id)
    ride_status_11 = None
    if isinstance(p11, dict):
        ride_status_11 = p11.get("lifecycle_state") or p11.get("status")
    add_step(
        steps,
        11,
        "Ride status becomes completed",
        "GET",
        f"/api/health-isf/rides/{ride_id}",
        s11,
        {"ride": summarize_payload(p11), "dispatcher_completed_match": completed_match, "dispatcher_queue_status": s11q},
        db11,
        s11 == 200 and str(ride_status_11).lower() == "completed",
    )

    passed_steps = sum(1 for s in steps if s["passed"])
    summary = {
        "generated_at": now_iso(),
        "base_url": BASE,
        "db_path": str(DB_PATH),
        "request_id": request_id,
        "ride_id": ride_id,
        "driver_id": driver_id,
        "passed_steps": passed_steps,
        "total_steps": len(steps),
        "all_passed": passed_steps == len(steps),
        "steps": steps,
    }

    out_json = OUT_DIR / "workflow_11step_results.json"
    out_json.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"results_file": str(out_json), "all_passed": summary["all_passed"], "passed_steps": passed_steps, "total_steps": len(steps), "ride_id": ride_id, "request_id": request_id, "driver_id": driver_id}, indent=2))


if __name__ == "__main__":
    main()
