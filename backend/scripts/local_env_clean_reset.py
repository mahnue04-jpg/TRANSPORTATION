"""Complete operational reset: zero rides/queues across all surfaces."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from app.db.session import SessionLocal
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import (
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFRide,
)
from real_life_ops_verification import reseed_backend

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.getenv("AMICOR_BROWSER_BASE", "http://127.0.0.1:8011").rstrip("/")
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")
TERMINAL_REQUEST_STATUSES = {"completed", "cancelled", "failed", "rejected"}
STALE_PASSENGER_MARKERS = (
    "nenway",
    "yeawon",
    "driver ops verify",
    "lifecycle proof",
    "ai proof",
    "browser verify",
)


def _login(client: httpx.Client, email: str) -> str:
    resp = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    resp.raise_for_status()
    payload = resp.json()
    token = payload.get("token") or payload.get("access_token")
    if not token:
        raise RuntimeError(f"login for {email} returned no token")
    return str(token)


def reset_database() -> dict:
    reseed = reseed_backend()
    db = SessionLocal()
    try:
        org = hs._get_or_create_default_org(db)
        summary = hs.complete_operational_reset(db, organization_id=org.id)
        james = (
            db.query(HealthISFDriver)
            .filter(
                HealthISFDriver.organization_id == org.id,
                HealthISFDriver.name.ilike("James Smith"),
            )
            .first()
        )
        return {
            **summary,
            "reseed": reseed,
            "driver_id": str(james.id) if james else reseed.get("driver_id"),
        }
    finally:
        db.close()


def verify_live_state(org_id: str, driver_id: str) -> dict:
    client = httpx.Client(base_url=BASE, timeout=90.0)
    dispatcher_token = _login(client, "dispatcher@amicor.local")
    driver_token = _login(client, "driver@amicor.local")
    rider_token = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {dispatcher_token}"}
    dheaders = {"Authorization": f"Bearer {driver_token}"}
    rheaders = {"Authorization": f"Bearer {rider_token}"}
    org_q = f"organization_id={org_id}"

    queue = client.get(f"/api/health-isf/dispatch/queue?{org_q}&limit=200", headers=headers)
    dispatch_count = len(queue.json()) if queue.status_code == 200 and isinstance(queue.json(), list) else -1

    ai = client.get(f"/api/health-isf/ai-dispatch/snapshot?{org_q}&publish=false", headers=headers)
    ai_queue = 0
    ai_focus = ""
    if ai.status_code == 200:
        live = ai.json().get("live_dispatch") or {}
        ai_queue = int(live.get("queue_count") or len(live.get("queue_ride_ids") or []))
        ai_focus = str((live.get("focused_ride") or {}).get("ride_id") or "")

    dash = client.get(f"/api/health-isf/dashboard?{org_q}", headers=headers)
    dash_active = -1
    dash_pending = -1
    dash_total = -1
    if dash.status_code == 200:
        payload = dash.json()
        overview = payload.get("dispatch_overview") or {}
        dash_active = int(payload.get("active_rides") or overview.get("active_rides") or 0)
        dash_pending = int(overview.get("pending_rides") or payload.get("pending_rides") or 0)
        dash_total = int(payload.get("total_rides") or 0)

    rides_list = client.get(f"/api/health-isf/rides?{org_q}&limit=200", headers=headers)
    api_ride_count = len(rides_list.json()) if rides_list.status_code == 200 and isinstance(rides_list.json(), list) else -1

    reset_status = client.get(f"/api/health-isf/ops/platform-reset-status?{org_q}", headers=headers)
    platform_epoch = ""
    platform_ready = False
    if reset_status.status_code == 200:
        reset_payload = reset_status.json()
        platform_epoch = str(reset_payload.get("platform_reset_epoch") or "")
        platform_ready = bool(reset_payload.get("system_ready_for_new_ride"))

    cust = client.get(f"/api/health-isf/customer-requests?{org_q}&limit=300", headers=headers)
    rider_active = 0
    if cust.status_code == 200:
        body = cust.json()
        rows = body if isinstance(body, list) else body.get("data") or []
        rider_active = sum(
            1 for row in rows if str(row.get("dispatch_status") or "").lower() not in TERMINAL_REQUEST_STATUSES
        )
    else:
        rider_active = -1

    assigned = client.get(f"/api/health-isf/drivers/{driver_id}/assigned-rides?{org_q}", headers=dheaders)
    assigned_count = len(assigned.json()) if assigned.status_code == 200 and isinstance(assigned.json(), list) else -1

    offer = client.get(f"/api/health-isf/drivers/{driver_id}/active-offer?{org_q}", headers=dheaders)
    offer_ride = str(((offer.json() or {}).get("offer") or {}).get("ride_id") or "") if offer.status_code == 200 else "error"

    workspace = client.get(f"/api/health-isf/drivers/{driver_id}/live-workspace?{org_q}", headers=dheaders)
    ws_active = ""
    driver_status = ""
    if workspace.status_code == 200:
        ws = workspace.json()
        ws_active = str((ws.get("active_ride") or {}).get("id") or "")
    driver = client.get(f"/api/health-isf/drivers/{driver_id}", headers=headers)
    if driver.status_code == 200:
        driver_status = str(driver.json().get("status") or "").lower()

    rider_tracking_active = False
    tracking = client.get("/api/health-isf/customers/workspace/live-tracking?limit=20", headers=rheaders)
    if tracking.status_code == 200:
        active = (tracking.json() or {}).get("active_ride") or {}
        rider_tracking_active = bool(str(active.get("id") or active.get("ride_id") or ""))

    disp_queues = client.get(f"/api/health-isf/dispatcher/queues?{org_q}", headers=headers)
    provider_active = 0
    if disp_queues.status_code == 200:
        queues = disp_queues.json() if isinstance(disp_queues.json(), dict) else {}
        provider_active = len(queues.get("active") or []) + len(queues.get("pending") or [])

    db = SessionLocal()
    try:
        db_rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == org_id).count()
        db_assignments = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.organization_id == org_id,
                HealthISFDispatchAssignment.assignment_state.in_(list(hs.ACTIVE_DISPATCH_ASSIGNMENT_STATES)),
            )
            .count()
        )
    finally:
        db.close()

    flags = {
        "DRIVER_WAITING": driver_status == "available" and not ws_active and not offer_ride and assigned_count == 0,
        "NO_ACTIVE_RIDE": not ws_active and not offer_ride and assigned_count == 0,
        "NO_PENDING_ASSIGNMENT": db_assignments == 0 and not offer_ride,
        "DISPATCH_QUEUE_EMPTY": dispatch_count == 0,
        "AI_QUEUE_EMPTY": ai_queue == 0 and not ai_focus,
        "PROVIDER_QUEUE_EMPTY": provider_active == 0,
        "RIDER_ACTIVE_RIDE": rider_tracking_active,
        "SYSTEM_READY_FOR_NEW_RIDE": (
            dispatch_count == 0
            and ai_queue == 0
            and not ai_focus
            and assigned_count == 0
            and not ws_active
            and not offer_ride
            and rider_active == 0
            and not rider_tracking_active
            and db_rides == 0
            and db_assignments == 0
            and provider_active == 0
            and api_ride_count == 0
            and dash_active == 0
            and dash_total == 0
            and platform_ready
        ),
    }

    return {
        "flags": flags,
        "metrics": {
            "dispatch_queue_count": dispatch_count,
            "ai_queue_count": ai_queue,
            "ai_focused_ride": ai_focus or None,
            "dashboard_active_rides": dash_active,
            "dashboard_pending_rides": dash_pending,
            "dashboard_total_rides": dash_total,
            "api_ride_list_count": api_ride_count,
            "platform_reset_epoch": platform_epoch or None,
            "platform_ready_flag": platform_ready,
            "rider_active_requests": rider_active,
            "driver_assigned_rides": assigned_count,
            "driver_active_offer": offer_ride or None,
            "driver_workspace_active_ride": ws_active or None,
            "driver_status": driver_status,
            "rider_tracking_active_ride": rider_tracking_active,
            "provider_queue_active_pending": provider_active,
            "db_ride_count": db_rides,
            "db_open_assignments": db_assignments,
        },
    }


def verify_driver_ui_empty() -> dict:
    """Open Driver App in a real browser and confirm the waiting screen has no stale ride."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "ok": False,
            "error": "playwright_not_installed",
            "detail": "Install playwright to verify live UI.",
        }

    driver_url = f"{BASE}/static/ops-shell.html?platform_reset=1"
    checks: dict[str, bool | str] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            login = httpx.post(
                f"{BASE}/api/auth/login",
                json={"email": "driver@amicor.local", "password": PASSWORD},
                timeout=60,
            )
            login.raise_for_status()
            token = login.json().get("access_token") or login.json().get("token")
            context.add_init_script(
                f'localStorage.setItem("amicor_access_token", {json.dumps(str(token))});'
            )

            page.goto(driver_url, wait_until="networkidle", timeout=120000)
            page.wait_for_timeout(4000)

            if page.locator("#role-select").count():
                page.select_option("#role-select", "driver")
                page.wait_for_timeout(2500)

            body_text = page.locator("body").inner_text().lower()
            html = page.content().lower()

            checks["awaiting_assignment_visible"] = "awaiting assignment" in body_text
            checks["no_ride_id_visible"] = "ride id" in body_text and "n/a" in body_text
            checks["no_assigned_queue"] = "no pending transport assignments" in body_text
            checks["no_assigned_rides_table"] = "no assigned rides found" in body_text
            checks["no_completed_rides_table"] = "no completed rides found" in body_text

            stale_hits = [marker for marker in STALE_PASSENGER_MARKERS if marker in body_text or marker in html]
            checks["no_stale_passenger_names"] = len(stale_hits) == 0
            if stale_hits:
                checks["stale_markers_found"] = ", ".join(stale_hits)

            ride_id_matches = re.findall(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", body_text)
            checks["no_uuid_ride_ids_in_body"] = len(ride_id_matches) == 0
            if ride_id_matches:
                checks["ride_ids_found"] = ", ".join(ride_id_matches[:5])

            ok = all(
                checks.get(key) is True
                for key in (
                    "awaiting_assignment_visible",
                    "no_assigned_queue",
                    "no_assigned_rides_table",
                    "no_completed_rides_table",
                    "no_stale_passenger_names",
                    "no_uuid_ride_ids_in_body",
                )
            )
            return {"ok": ok, "checks": checks, "url": driver_url}
        finally:
            context.close()
            browser.close()


def restart_server() -> None:
    from server_runtime import ensure_server_running

    summary = ensure_server_running(force_restart=True)
    print(f"SERVER_RUNTIME action={summary.get('action')} pid={summary.get('pid')} log={summary.get('log_file')}")


def main() -> int:
    print("=== COMPLETE OPERATIONAL RESET ===")
    db_summary = reset_database()
    print("DB_RESET:", json.dumps(db_summary, indent=2, default=str))

    restart_server()
    print(f"SERVER_RESTARTED={BASE}")

    org_id = str(db_summary["organization_id"])
    driver_id = str(db_summary["driver_id"])
    live = verify_live_state(org_id, driver_id)
    print("LIVE_METRICS:", json.dumps(live["metrics"], indent=2, default=str))

    for key, value in live["flags"].items():
        if key == "RIDER_ACTIVE_RIDE":
            print(f"{key}={str(value).lower()}")
        else:
            print(f"{key}={str(value).lower()}")

    api_passed = all(
        live["flags"].get(key) is True
        for key in (
            "DRIVER_WAITING",
            "NO_ACTIVE_RIDE",
            "NO_PENDING_ASSIGNMENT",
            "DISPATCH_QUEUE_EMPTY",
            "AI_QUEUE_EMPTY",
            "PROVIDER_QUEUE_EMPTY",
            "SYSTEM_READY_FOR_NEW_RIDE",
        )
    ) and live["flags"].get("RIDER_ACTIVE_RIDE") is False

    ui = verify_driver_ui_empty()
    print("BROWSER_UI:", json.dumps(ui, indent=2, default=str))

    passed = api_passed and ui.get("ok") is True
    print(f"RESULT={'PASS' if passed else 'FAIL'}")
    if passed:
        print(f"DRIVER_APP_URL={BASE}/static/ops-shell.html?platform_reset=1")
        print(f"RIDER_APP_URL={BASE}/app/riders")
        print("NEXT: Open Driver App with platform_reset=1, then create ONE manual ride in Rider App.")
    else:
        if not api_passed:
            print("DETAIL=Live APIs still report residual rides/assignments after reset.")
        if ui.get("ok") is not True:
            print("DETAIL=Driver App UI still shows stale ride content after reset.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
