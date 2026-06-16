import json
import sqlite3
import sys
import urllib.error
import urllib.request
from urllib.parse import quote
import uuid
from pathlib import Path
from typing import Any

BASE = "http://127.0.0.1:8011"
DB = Path(r"C:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild\backend\data\chat.db")
SEED_PASSWORD = "Amicor123!"
EMAILS = {
    "rider": "rider@amicor.local",
    "dispatcher": "dispatcher@amicor.local",
    "driver_user": "driver@amicor.local",
    "admin": "admin@amicor.local",
}

OUTPUT_PATH = Path(r"C:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild\backend\scripts\lifecycle_phase2_output.json")


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


def one_row(cur: sqlite3.Cursor, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    cur.execute(query, params)
    row = cur.fetchone()
    return dict(row) if row else None


def many_rows(cur: sqlite3.Cursor, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    cur.execute(query, params)
    return [dict(r) for r in cur.fetchall()]


def capture_db_snapshot(cur: sqlite3.Cursor, *, rider_phone: str, request_id: str | None, ride_id: str | None, driver_id: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}

    snapshot["customer_request_for_phone"] = many_rows(
        cur,
        """
        SELECT id, ride_id, rider_phone, dispatch_status, pending_at, accepted_at, assigned_at, in_progress_at, completed_at, updated_at
        FROM health_isf_customer_ride_requests
        WHERE rider_phone = ?
        ORDER BY created_at DESC
        LIMIT 3
        """,
        (rider_phone,),
    )

    if request_id:
        snapshot["customer_request"] = one_row(
            cur,
            """
            SELECT id, ride_id, rider_phone, dispatch_status, pending_at, accepted_at, assigned_at, in_progress_at, completed_at, updated_at
            FROM health_isf_customer_ride_requests
            WHERE id = ?
            """,
            (request_id,),
        )

    if ride_id:
        snapshot["ride"] = one_row(
            cur,
            """
            SELECT id, organization_id, passenger_phone, status, lifecycle_state, driver_id, requested_at, accepted_at, picked_up_at, transporting_at, completed_at, updated_at
            FROM health_isf_rides
            WHERE id = ?
            """,
            (ride_id,),
        )

        snapshot["assignments"] = many_rows(
            cur,
            """
            SELECT id, ride_id, driver_id, assignment_state, attempt_index, offered_at, assigned_at, accepted_at, pickup_complete_at, dropoff_complete_at, updated_at
            FROM health_isf_dispatch_assignments
            WHERE ride_id = ?
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (ride_id,),
        )

        snapshot["dispatch_logs_tail"] = many_rows(
            cur,
            """
            SELECT id, ride_id, action, emitted_event_name, lifecycle_state, assignment_id, created_at
            FROM health_isf_dispatch_logs
            WHERE ride_id = ?
            ORDER BY created_at DESC
            LIMIT 8
            """,
            (ride_id,),
        )

        snapshot["status_history_tail"] = many_rows(
            cur,
            """
            SELECT id, ride_id, from_status, to_status, note, created_at
            FROM health_isf_ride_status_history
            WHERE ride_id = ?
            ORDER BY created_at DESC
            LIMIT 8
            """,
            (ride_id,),
        )

    snapshot["driver"] = one_row(
        cur,
        """
        SELECT id, status, availability_state, is_online, total_trips, updated_at
        FROM health_isf_drivers
        WHERE id = ?
        """,
        (driver_id,),
    )

    return snapshot


def finalize(report: dict[str, Any], failed_step: str | None, fail_reason: str | None):
    report["failed_step"] = failed_step
    report["fail_reason"] = fail_reason

    completed = [s["name"] for s in report["steps"] if s.get("outcome") == "passed"]
    failed = [s["name"] for s in report["steps"] if s.get("outcome") == "failed"]

    missing_screens: list[str] = []
    missing_apis: list[str] = []
    missing_db_fields: list[str] = []

    if failed_step:
        failing = next((s for s in report["steps"] if s["name"] == failed_step), None)
        if failing:
            if not failing.get("screen_url"):
                missing_screens.append(failing["name"])
            if not failing.get("api"):
                missing_apis.append(failing["name"])

    report["readiness_report"] = {
        "completed_steps": completed,
        "failed_steps": failed,
        "missing_screens": missing_screens,
        "missing_apis": missing_apis,
        "missing_database_fields": missing_db_fields,
        "estimated_work_remaining_before_pilot_deployment": (
            "No blocking work identified" if not failed else f"1 blocking component: {failed[0]}"
        ),
    }

    OUTPUT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"failed_step": failed_step, "fail_reason": fail_reason, "output_path": str(OUTPUT_PATH)}, indent=2))
    sys.exit(0)


def execute_step(
    report: dict[str, Any],
    cur: sqlite3.Cursor,
    *,
    name: str,
    screen_url: str,
    api_method: str,
    api_path: str,
    token: str,
    rider_phone: str,
    driver_id: str,
    request_id: str | None,
    ride_id: str | None,
    request_payload: dict[str, Any] | None = None,
    success_check=None,
    failure_message: str,
):
    db_before = capture_db_snapshot(cur, rider_phone=rider_phone, request_id=request_id, ride_id=ride_id, driver_id=driver_id)
    status, response_payload = req(api_method, api_path, request_payload, token)
    db_after = capture_db_snapshot(cur, rider_phone=rider_phone, request_id=request_id, ride_id=ride_id, driver_id=driver_id)

    step = {
        "name": name,
        "screen_url": screen_url,
        "api": {
            "method": api_method,
            "endpoint": api_path,
            "request_payload": request_payload,
            "response_status": status,
            "response_payload": response_payload,
        },
        "database_status_before": db_before,
        "database_status_after": db_after,
    }

    passed = status < 400
    if passed and success_check is not None:
        try:
            passed = bool(success_check(status, response_payload))
        except Exception:
            passed = False

    step["outcome"] = "passed" if passed else "failed"
    report["steps"].append(step)

    if not passed:
        finalize(report, name, failure_message)

    return status, response_payload


def main():
    report: dict[str, Any] = {
        "title": "RIDE LIFECYCLE READINESS REPORT",
        "base_url": BASE,
        "db_path": str(DB),
        "steps": [],
    }

    tokens: dict[str, str] = {}
    for role, email in EMAILS.items():
        status, payload = req("POST", "/api/auth/login", {"email": email, "password": SEED_PASSWORD})
        report[f"{role}_login"] = {"status": status, "response": payload}
        if status != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
            finalize(report, "login", f"Login failed for role {role}")
        tokens[role] = payload["access_token"]

    me_status, me_payload = req("GET", "/api/auth/me", token=tokens["dispatcher"])
    report["dispatcher_me"] = {"status": me_status, "response": me_payload}
    if me_status != 200 or not isinstance(me_payload, dict) or not me_payload.get("organization_id"):
        finalize(report, "organization_lookup", "Unable to resolve organization context from dispatcher token")
    org_id = me_payload["organization_id"]

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    driver_id = str(uuid.uuid4())
    driver_name = f"Phase2 Driver {driver_id[:8]}"
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
            "P2-" + driver_id[:6].upper(),
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

    # 1) Create ride
    create_payload = {
        "rider_name": "Phase2 Rider",
        "rider_phone": rider_phone,
        "pickup_address": "101 Phase2 Way",
        "dropoff_address": "202 Phase2 Ave",
        "ride_type": "healthcare",
        "notes": "Phase 2 lifecycle validation",
    }
    _, create_resp = execute_step(
        report,
        cur,
        name="1_create_ride",
        screen_url=f"{BASE}/app/riders",
        api_method="POST",
        api_path="/api/health-isf/customer-requests",
        token=tokens["rider"],
        rider_phone=rider_phone,
        driver_id=driver_id,
        request_id=None,
        ride_id=None,
        request_payload=create_payload,
        success_check=lambda s, p: s == 201 and isinstance(p, dict) and bool(p.get("id")) and bool(p.get("ride_id")),
        failure_message="Ride creation failed",
    )

    request_id = create_resp["id"]
    ride_id = create_resp["ride_id"]

    # 2) Verify dispatcher queue visibility
    execute_step(
        report,
        cur,
        name="2_verify_dispatcher_queue_visibility",
        screen_url=f"{BASE}/app/dispatch",
        api_method="GET",
        api_path="/api/health-isf/dispatch/queue?limit=100",
        token=tokens["dispatcher"],
        rider_phone=rider_phone,
        driver_id=driver_id,
        request_id=request_id,
        ride_id=ride_id,
        success_check=lambda s, p: s == 200 and isinstance(p, list) and any(item.get("ride_id") == ride_id for item in p),
        failure_message="Newly created ride is not visible in dispatcher queue",
    )

    # Approve prerequisite for assignment
    approve_status, approve_resp = req(
        "POST",
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        token=tokens["dispatcher"],
    )
    report["assignment_prerequisite_approve"] = {
        "method": "POST",
        "endpoint": f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        "status": approve_status,
        "response": approve_resp,
    }
    if approve_status != 200:
        finalize(report, "3_assign_driver", "Approve prerequisite failed before assignment")

    # 3) Assign driver
    execute_step(
        report,
        cur,
        name="3_assign_driver",
        screen_url=f"{BASE}/app/dispatch",
        api_method="POST",
        api_path=f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        token=tokens["dispatcher"],
        rider_phone=rider_phone,
        driver_id=driver_id,
        request_id=request_id,
        ride_id=ride_id,
        request_payload={"driver_id": driver_id},
        success_check=lambda s, p: s == 200,
        failure_message="Driver assignment failed",
    )

    # 4) Verify driver assignment visibility
    offer_status, offer_resp = execute_step(
        report,
        cur,
        name="4_verify_driver_assignment_visibility",
        screen_url=f"{BASE}/app/drivers",
        api_method="GET",
        api_path=f"/api/health-isf/drivers/{driver_id}/active-offer",
        token=tokens["dispatcher"],
        rider_phone=rider_phone,
        driver_id=driver_id,
        request_id=request_id,
        ride_id=ride_id,
        success_check=lambda s, p: s == 200 and isinstance(p, dict) and isinstance(p.get("offer"), dict) and p["offer"].get("ride_id") == ride_id,
        failure_message="Assigned ride not visible in driver assignment/offer view",
    )

    offer_payload = offer_resp["offer"] if isinstance(offer_resp, dict) else None
    offer_id = None
    if isinstance(offer_payload, dict):
        offer_id = offer_payload.get("id") or offer_payload.get("offer_id")
    if not offer_id:
        finalize(report, "5_accept_assignment", "Offer id missing after driver assignment visibility check")

    # 5) Accept assignment
    execute_step(
        report,
        cur,
        name="5_accept_assignment",
        screen_url=f"{BASE}/app/drivers",
        api_method="POST",
        api_path=f"/api/health-isf/dispatch/offers/{offer_id}/accept",
        token=tokens["dispatcher"],
        rider_phone=rider_phone,
        driver_id=driver_id,
        request_id=request_id,
        ride_id=ride_id,
        success_check=lambda s, p: s == 200,
        failure_message="Assignment accept failed",
    )

    # 6) Start trip
    execute_step(
        report,
        cur,
        name="6_start_trip",
        screen_url=f"{BASE}/app/drivers",
        api_method="POST",
        api_path=f"/api/health-isf/drivers/{driver_id}/arrived-pickup",
        token=tokens["dispatcher"],
        rider_phone=rider_phone,
        driver_id=driver_id,
        request_id=request_id,
        ride_id=ride_id,
        request_payload={"ride_id": ride_id},
        success_check=lambda s, p: s == 200,
        failure_message="Driver arrival before pickup failed",
    )

    execute_step(
        report,
        cur,
        name="6_start_trip",
        screen_url=f"{BASE}/app/drivers",
        api_method="POST",
        api_path=f"/api/health-isf/drivers/{driver_id}/pickup-complete",
        token=tokens["dispatcher"],
        rider_phone=rider_phone,
        driver_id=driver_id,
        request_id=request_id,
        ride_id=ride_id,
        request_payload={"ride_id": ride_id},
        success_check=lambda s, p: s == 200,
        failure_message="Trip start/pickup complete failed",
    )

    # 7) Complete trip (progress then complete)
    progress_status, progress_resp = req(
        "POST",
        "/api/ops/workspace/action?role_view=driver",
        {
            "action_type": "driver.update_route_progress",
            "payload": {"trip_id": ride_id, "driver_id": driver_id, "route_progress_percent": 100},
        },
        tokens["driver_user"],
    )
    report["completion_prerequisite_progress"] = {
        "method": "POST",
        "endpoint": "/api/ops/workspace/action?role_view=driver",
        "request_payload": {
            "action_type": "driver.update_route_progress",
            "payload": {"trip_id": ride_id, "driver_id": driver_id, "route_progress_percent": 100},
        },
        "status": progress_status,
        "response": progress_resp,
    }
    if progress_status != 200:
        finalize(report, "7_complete_trip", "Driver progress prerequisite failed before completion")

    execute_step(
        report,
        cur,
        name="7_complete_trip",
        screen_url=f"{BASE}/app/drivers",
        api_method="POST",
        api_path="/api/ops/workspace/action?role_view=driver",
        token=tokens["driver_user"],
        rider_phone=rider_phone,
        driver_id=driver_id,
        request_id=request_id,
        ride_id=ride_id,
        request_payload={
            "action_type": "driver.complete_trip",
            "payload": {"trip_id": ride_id, "driver_id": driver_id},
        },
        success_check=lambda s, p: s == 200,
        failure_message="Trip completion failed",
    )

    # 8) Verify rider history
    execute_step(
        report,
        cur,
        name="8_verify_rider_history",
        screen_url=f"{BASE}/app/riders",
        api_method="GET",
        api_path=f"/api/health-isf/customers/workspace/history?rider_phone={quote(rider_phone, safe='')}&limit=25",
        token=tokens["rider"],
        rider_phone=rider_phone,
        driver_id=driver_id,
        request_id=request_id,
        ride_id=ride_id,
        success_check=lambda s, p: s == 200 and isinstance(p, dict) and isinstance(p.get("history"), list) and any(item.get("ride_id") == ride_id for item in p.get("history", [])),
        failure_message="Rider history does not contain completed ride",
    )

    # 9) Verify driver history
    execute_step(
        report,
        cur,
        name="9_verify_driver_history",
        screen_url=f"{BASE}/app/drivers",
        api_method="GET",
        api_path=f"/api/health-isf/drivers/{driver_id}/assigned-rides",
        token=tokens["driver_user"],
        rider_phone=rider_phone,
        driver_id=driver_id,
        request_id=request_id,
        ride_id=ride_id,
        success_check=lambda s, p: s == 200 and isinstance(p, list) and any(item.get("id") == ride_id for item in p),
        failure_message="Driver history does not contain completed ride",
    )

    # 10) Verify admin history
    execute_step(
        report,
        cur,
        name="10_verify_admin_history",
        screen_url=f"{BASE}/app/dispatch",
        api_method="GET",
        api_path="/api/health-isf/activity-feed?limit=200",
        token=tokens["admin"],
        rider_phone=rider_phone,
        driver_id=driver_id,
        request_id=request_id,
        ride_id=ride_id,
        success_check=lambda s, p: s == 200 and isinstance(p, dict) and any(item.get("ride_id") == ride_id for item in (p.get("items") or p.get("activities") or [])),
        failure_message="Admin history/activity feed does not contain completed ride",
    )

    conn.close()
    finalize(report, None, None)


if __name__ == "__main__":
    main()
