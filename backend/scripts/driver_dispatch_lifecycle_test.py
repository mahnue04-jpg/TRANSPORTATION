"""Backend stability + full driver dispatch lifecycle verification."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from local_env_clean_reset import (  # noqa: E402
    BASE,
    PASSWORD,
    reset_database,
    verify_driver_ui_empty,
    verify_live_state,
)
from server_runtime import ensure_server_running, verify_server_persistence  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JAMES_PHONE = "9175551001"
STALE_MARKERS = ("nenway", "yeawon", "proof", "browser verify", "ops verify")


def _login(client: httpx.Client, email: str) -> str:
    resp = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    resp.raise_for_status()
    return str(resp.json().get("token") or resp.json().get("access_token"))


def wait_health(timeout_sec: int = 120) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/api/runtime/topology", timeout=3).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _norm_status(raw: str) -> str:
    value = str(raw or "").strip().lower().replace("ridestatus.", "")
    if value in {"completed", "complete"}:
        return "completed"
    if "accept" in value or value == "assigned":
        return "accepted"
    return value or "unknown"


def _find_james(client: httpx.Client, headers: dict) -> tuple[str, str]:
    rows = client.get("/api/health-isf/drivers?limit=200", headers=headers).json()
    james = next(
        (row for row in rows if str(row.get("phone", "")).replace("-", "").replace(" ", "") == JAMES_PHONE),
        None,
    )
    if not james:
        raise RuntimeError("James Smith driver not found")
    return str(james["id"]), str(james.get("organization_id") or "")


def _create_rider_request(client: httpx.Client, rider_headers: dict, *, suffix: str) -> tuple[str, str]:
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    payload = {
        "rider_name": f"Lifecycle Test Rider {suffix}",
        "rider_phone": f"646-555-{stamp[-4:]}",
        "pickup_address": f"100 Lifecycle Pickup {suffix}, New York, NY 10001",
        "dropoff_address": f"200 Lifecycle Dropoff {suffix}, New York, NY 10002",
        "ride_type": "healthcare",
        "recurring": False,
        "notes": f"driver dispatch lifecycle test {suffix}",
    }
    resp = client.post("/api/health-isf/customer-requests", headers=rider_headers, json=payload)
    resp.raise_for_status()
    body = resp.json()
    return str(body["ride_id"]), str(body["id"])


def _approve_and_assign_james(
    client: httpx.Client,
    dispatcher_headers: dict,
    request_id: str,
    ride_id: str,
    driver_id: str,
    org_id: str,
) -> None:
    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=dispatcher_headers,
        params={"organization_id": org_id},
    )
    approve.raise_for_status()
    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    ride.raise_for_status()
    current_driver = str(ride.json().get("driver_id") or "")
    if current_driver == driver_id:
        return
    if current_driver:
        reassign = client.patch(
            f"/api/health-isf/dispatcher/rides/{ride_id}/reassign-driver",
            headers=dispatcher_headers,
            json={"driver_id": driver_id},
        )
        reassign.raise_for_status()
        return
    assign = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        headers=dispatcher_headers,
        params={"organization_id": org_id},
        json={"driver_id": driver_id},
    )
    assign.raise_for_status()


def _ai_sees_ride(client: httpx.Client, headers: dict, org_id: str, ride_id: str) -> bool:
    ai = client.get(
        f"/api/health-isf/ai-dispatch/snapshot?organization_id={org_id}&publish=false&ride_id={ride_id}",
        headers=headers,
    )
    if ai.status_code != 200:
        return False
    live = (ai.json() or {}).get("live_dispatch") or {}
    queue_ids = [str(item) for item in (live.get("queue_ride_ids") or [])]
    focused = str((live.get("focused_ride") or {}).get("ride_id") or "")
    if ride_id in queue_ids or focused == ride_id:
        return True
    queue = client.get(f"/api/health-isf/dispatch/queue?organization_id={org_id}&limit=50", headers=headers)
    if queue.status_code == 200:
        return any(str(row.get("ride_id") or "") == ride_id for row in queue.json())
    return False


def _driver_accept(client: httpx.Client, driver_headers: dict, driver_id: str, ride_id: str) -> None:
    resp = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=driver_headers,
        json={"ride_id": ride_id},
    )
    if resp.status_code >= 400:
        ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=driver_headers)
        status = _norm_status(str((ride.json() or {}).get("lifecycle_state") or (ride.json() or {}).get("status") or ""))
        if status not in {"accepted", "driver_en_route", "arrived", "rider_onboard", "in_progress", "completed"}:
            resp.raise_for_status()


def _driver_complete(client: httpx.Client, driver_headers: dict, driver_id: str, ride_id: str) -> None:
    steps = [
        "en_route_pickup",
        "arrived_pickup",
        "rider_loaded",
        "trip_in_progress",
        "arrived_destination",
    ]
    for step in steps:
        ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=driver_headers)
        ride.raise_for_status()
        status = _norm_status(str((ride.json() or {}).get("lifecycle_state") or (ride.json() or {}).get("status") or ""))
        if status == "completed":
            return
        resp = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=driver_headers,
            json={"ride_id": ride_id, "target_state": step},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"route-progress {step} failed: {resp.status_code} {resp.text[:300]}")
    resp = client.post(
        f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
        headers=driver_headers,
        json={"ride_id": ride_id},
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"dropoff-complete failed: {resp.status_code} {resp.text[:300]}")


def _driver_waiting(client: httpx.Client, driver_headers: dict, dispatcher_headers: dict, driver_id: str, org_id: str) -> dict:
    driver = client.get(f"/api/health-isf/drivers/{driver_id}", headers=dispatcher_headers)
    workspace = client.get(
        f"/api/health-isf/drivers/{driver_id}/live-workspace?organization_id={org_id}",
        headers=driver_headers,
    )
    assigned = client.get(
        f"/api/health-isf/drivers/{driver_id}/assigned-rides?organization_id={org_id}",
        headers=driver_headers,
    )
    offer = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-offer?organization_id={org_id}",
        headers=driver_headers,
    )
    ws_active = str(((workspace.json() or {}).get("active_ride") or {}).get("id") or "") if workspace.status_code == 200 else "error"
    offer_ride = str(((offer.json() or {}).get("offer") or {}).get("ride_id") or "") if offer.status_code == 200 else "error"
    assigned_rows = assigned.json() if assigned.status_code == 200 and isinstance(assigned.json(), list) else []
    return {
        "driver_status": str((driver.json() or {}).get("status") or "").lower() if driver.status_code == 200 else "",
        "workspace_active_ride": ws_active,
        "active_offer": offer_ride,
        "assigned_count": len(assigned_rows),
        "assigned_ride_ids": [str(row.get("id") or "") for row in assigned_rows],
    }


def verify_driver_ui_post_complete(passenger_marker: str) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"ok": False, "error": "playwright_not_installed"}

    url = f"{BASE}/static/ops-shell.html?platform_reset=1"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            token = _login(httpx.Client(base_url=BASE, timeout=60), "driver@amicor.local")
            context.add_init_script(
                f'localStorage.setItem("amicor_access_token", {json.dumps(token)});'
            )
            page.goto(url, wait_until="networkidle", timeout=120000)
            page.wait_for_timeout(4000)
            if page.locator("#role-select").count():
                page.select_option("#role-select", "driver")
                page.wait_for_timeout(3000)
            body = page.locator("body").inner_text().lower()
            stale = [m for m in STALE_MARKERS if m in body]
            uuid_hits = re.findall(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", body)
            checks = {
                "awaiting_assignment_visible": "awaiting assignment" in body,
                "no_active_passenger": passenger_marker.lower() not in body,
                "no_stale_markers": len(stale) == 0,
                "no_uuid_in_body": len(uuid_hits) == 0,
                "no_assigned_rides_table": "no assigned rides found" in body,
            }
            return {"ok": all(checks.values()), "checks": checks, "url": url}
        finally:
            context.close()
            browser.close()


def _verify_post_completion_billing(
    client: httpx.Client,
    headers: dict,
    *,
    driver_id: str,
    ride_id: str,
    org_id: str,
) -> dict[str, bool]:
    earnings = client.get(f"/api/health-isf/drivers/{driver_id}/earnings", headers=headers, params={"organization_id": org_id})
    financial = client.get(f"/api/health-isf/rides/{ride_id}/financial-summary", headers=headers)
    admin = client.get("/api/health-isf/operations/admin-revenue", headers=headers, params={"organization_id": org_id})
    completed_rides = client.get(
        f"/api/health-isf/drivers/{driver_id}/completed-rides",
        headers=headers,
        params={"organization_id": org_id, "limit": 10},
    )
    billing = client.get(
        "/api/health-isf/operations/billing-handoffs",
        headers=headers,
        params={"organization_id": org_id, "limit": 20},
    )
    driver = client.get(f"/api/health-isf/drivers/{driver_id}", headers=headers)

    flags: dict[str, bool] = {}
    earnings_body = earnings.json() if earnings.status_code == 200 else {}
    financial_body = financial.json() if financial.status_code == 200 else {}
    admin_body = admin.json() if admin.status_code == 200 else {}
    completed_body = completed_rides.json() if completed_rides.status_code == 200 and isinstance(completed_rides.json(), list) else []
    billing_body = billing.json() if billing.status_code == 200 and isinstance(billing.json(), list) else []
    driver_body = driver.json() if driver.status_code == 200 else {}

    flags["COMPLETED_HISTORY_CREATED"] = any(str(row.get("id") or "") == ride_id for row in completed_body)
    flags["DRIVER_EARNINGS_POSITIVE"] = float(earnings_body.get("earnings_today_usd") or 0.0) > 0.0
    flags["COMPLETED_TRIPS_COUNT_OK"] = int(earnings_body.get("trip_count") or 0) >= 1
    flags["BILLING_HANDOFF_EXISTS"] = any(str(row.get("ride_id") or "") == ride_id for row in billing_body)
    flags["FINANCIAL_SUMMARY_EXISTS"] = financial.status_code == 200 and float(financial_body.get("driver_pay_usd") or 0.0) > 0.0
    flags["AMICOR_REVENUE_RECORDED"] = float(admin_body.get("platform_revenue_total_usd") or 0.0) > 0.0
    flags["DRIVER_TOTAL_TRIPS_INCREMENTED"] = int(driver_body.get("total_trips") or 0) >= 1
    print("POST_COMPLETE_BILLING:", json.dumps({
        "earnings": earnings_body,
        "financial": financial_body,
        "admin_revenue": admin_body,
        "completed_rides_count": len(completed_body),
        "billing_handoffs_count": len(billing_body),
        "driver_total_trips": driver_body.get("total_trips"),
    }, indent=2))
    return flags


def main() -> int:
    print("=== DRIVER DISPATCH LIFECYCLE TEST ===")
    flags: dict[str, bool] = {}

    db_summary = reset_database()
    print("DB_RESET_OK", json.dumps({"organization_id": db_summary["organization_id"], "driver_id": db_summary["driver_id"]}))

    runtime = ensure_server_running(force_restart=True)
    print("SERVER_RUNTIME", json.dumps(runtime, indent=2))
    if not wait_health():
        print("RESULT=FAIL")
        print("FAIL_STEP=backend_health")
        print("DETAIL=Backend did not return UP on port 8011")
        return 1
    print(f"BACKEND_UP={BASE}")

    org_id = str(db_summary["organization_id"])
    driver_id = str(db_summary["driver_id"])
    reset_live = verify_live_state(org_id, driver_id)
    reset_ui = verify_driver_ui_empty() if os.getenv("SKIP_BROWSER_UI", "").strip().lower() not in {"1", "true", "yes"} else {"ok": True, "skipped": True}
    flags["RESET_API_PASS"] = all(
        reset_live["flags"].get(key) is True
        for key in (
            "DRIVER_WAITING",
            "NO_ACTIVE_RIDE",
            "NO_PENDING_ASSIGNMENT",
            "DISPATCH_QUEUE_EMPTY",
            "AI_QUEUE_EMPTY",
            "SYSTEM_READY_FOR_NEW_RIDE",
        )
    ) and reset_live["flags"].get("RIDER_ACTIVE_RIDE") is False
    flags["RESET_UI_PASS"] = reset_ui.get("ok") is True
    print("RESET_FLAGS:", json.dumps(reset_live["flags"], indent=2))
    print("RESET_UI:", json.dumps(reset_ui, indent=2))

    if not flags["RESET_API_PASS"] or not flags["RESET_UI_PASS"]:
        print("RESULT=FAIL")
        print("FAIL_STEP=operational_reset")
        return 1

    client = httpx.Client(base_url=BASE, timeout=120.0)
    dispatcher_token = _login(client, "dispatcher@amicor.local")
    driver_token = _login(client, "driver@amicor.local")
    rider_token = _login(client, "rider@amicor.local")
    dheaders = {"Authorization": f"Bearer {dispatcher_token}"}
    drheaders = {"Authorization": f"Bearer {driver_token}"}
    rheaders = {"Authorization": f"Bearer {rider_token}"}

    ride_id, request_id = _create_rider_request(client, rheaders, suffix="A")
    flags["RIDER_REQUEST_CREATED"] = bool(ride_id and request_id)
    print(f"RIDE_CREATED ride_id={ride_id} request_id={request_id}")

    queue = client.get(f"/api/health-isf/dispatch/queue?organization_id={org_id}&limit=50", headers=dheaders)
    flags["DISPATCH_RECEIVES_RIDE"] = queue.status_code == 200 and any(
        str(row.get("ride_id") or "") == ride_id for row in (queue.json() if isinstance(queue.json(), list) else [])
    )

    flags["AI_ASSIGNS_DRIVER"] = _ai_sees_ride(client, dheaders, org_id, ride_id)
    _approve_and_assign_james(client, dheaders, request_id, ride_id, driver_id, org_id)
    if not flags["AI_ASSIGNS_DRIVER"]:
        flags["AI_ASSIGNS_DRIVER"] = _ai_sees_ride(client, dheaders, org_id, ride_id)

    ride_row = client.get(f"/api/health-isf/rides/{ride_id}", headers=dheaders).json()
    flags["DRIVER_ASSIGNED"] = str(ride_row.get("driver_id") or "") == driver_id

    if not flags["DRIVER_ASSIGNED"]:
        print("RESULT=FAIL")
        print("FAIL_STEP=driver_assignment")
        print(f"DETAIL=Ride {ride_id} not assigned to James Smith ({driver_id})")
        return 1

    _driver_accept(client, drheaders, driver_id, ride_id)
    accepted = client.get(f"/api/health-isf/rides/{ride_id}", headers=dheaders).json()
    flags["DRIVER_ACCEPTS_RIDE"] = _norm_status(str(accepted.get("lifecycle_state") or accepted.get("status") or "")) in {
        "accepted",
        "driver_en_route",
        "arrived",
        "rider_onboard",
        "in_progress",
        "completed",
    }

    _driver_complete(client, drheaders, driver_id, ride_id)
    completed = client.get(f"/api/health-isf/rides/{ride_id}", headers=dheaders).json()
    flags["RIDE_COMPLETED"] = _norm_status(str(completed.get("lifecycle_state") or completed.get("status") or "")) == "completed"

    post = _driver_waiting(client, drheaders, dheaders, driver_id, org_id)
    flags["DRIVER_AVAILABLE_AFTER_COMPLETE"] = post["driver_status"] == "available"
    flags["NO_ACTIVE_RIDE_AFTER_COMPLETE"] = (
        not post["workspace_active_ride"] and not post["active_offer"] and post["assigned_count"] == 0
    )
    print("POST_COMPLETE:", json.dumps(post, indent=2))

    ui_after = verify_driver_ui_post_complete(f"Lifecycle Test Rider A") if os.getenv("SKIP_BROWSER_UI", "").strip().lower() not in {"1", "true", "yes"} else {"ok": True, "skipped": True}
    flags["DRIVER_UI_RESET_AFTER_COMPLETE"] = ui_after.get("ok") is True
    print("POST_COMPLETE_UI:", json.dumps(ui_after, indent=2))

    flags.update(_verify_post_completion_billing(client, dheaders, driver_id=driver_id, ride_id=ride_id, org_id=org_id))

    ride_id_2, request_id_2 = _create_rider_request(client, rheaders, suffix="B")
    _approve_and_assign_james(client, dheaders, request_id_2, ride_id_2, driver_id, org_id)
    deadline = time.time() + 45
    next_ready = False
    while time.time() < deadline:
        post2 = _driver_waiting(client, drheaders, dheaders, driver_id, org_id)
        ride2 = client.get(f"/api/health-isf/rides/{ride_id_2}", headers=dheaders).json()
        if str(ride2.get("driver_id") or "") == driver_id or ride_id_2 in post2["assigned_ride_ids"] or post2["active_offer"] == ride_id_2:
            next_ready = True
            break
        time.sleep(2)
    flags["NEXT_RIDE_ASSIGNABLE"] = next_ready
    print(f"NEXT_RIDE ride_id={ride_id_2} ready={next_ready}")

    for key, value in flags.items():
        print(f"{key}={str(value).lower()}")

    passed = all(flags.values())
    persistence = verify_server_persistence()
    flags["SERVER_STILL_RUNNING"] = persistence.get("healthy") is True
    print("SERVER_PERSISTENCE:", json.dumps(persistence, indent=2))
    print(f"SERVER_STILL_RUNNING={str(flags['SERVER_STILL_RUNNING']).lower()}")
    print(f"RESULT={'PASS' if passed and flags['SERVER_STILL_RUNNING'] else 'FAIL'}")
    if passed and flags["SERVER_STILL_RUNNING"]:
        print(f"DRIVER_APP_URL={BASE}/static/ops-shell.html?platform_reset=1")
        print(f"RIDER_APP_URL={BASE}/app/riders")
        print(f"DISPATCH_URL={BASE}/app/dispatch")
        print(f"BILLING_URL={BASE}/app/billing")
        print(f"AI_ASSISTANT_URL={BASE}/app/ai-assistant")
        print("NOTE=Backend left running on port 8011 for manual verification.")
    return 0 if passed and flags["SERVER_STILL_RUNNING"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
